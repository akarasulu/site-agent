from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from urllib.parse import urljoin

from site_agent.core.models import Evidence, Form, Page, Transition, UiElement, new_id


FIELD_TAGS = {"input", "select", "textarea", "button"}
HEADING_TAGS = {"h1", "h2", "h3"}


def fingerprint(tag: str, attrs: dict[str, str], label: str) -> str:
    stable = "|".join([tag, attrs.get("name", ""), attrs.get("id", ""), attrs.get("type", ""), label])
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


class InteractionHTMLParser(HTMLParser):
    def __init__(self, url: str):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.title = ""
        self.headings: list[str] = []
        self.forms: list[Form] = []
        self.elements: list[UiElement] = []
        self.transitions: list[Transition] = []
        self.evidence: list[Evidence] = []
        self._tag_stack: list[str] = []
        self._text_stack: list[list[str]] = []
        self._current_form: Form | None = None
        self._page_id = new_id("page")
        self._last_label_text = ""
        self._label_for: dict[str, str] = {}
        self._active_label_for: str | None = None
        self._active_anchor: dict[str, str] | None = None
        self._active_button: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {k: v or "" for k, v in attrs_list}
        self._tag_stack.append(tag)
        self._text_stack.append([])

        if tag == "form":
            self._current_form = Form(
                id=new_id("form"),
                page_id=self._page_id,
                label=attrs.get("aria-label") or attrs.get("name") or "form",
                action=attrs.get("action"),
                method=(attrs.get("method") or "get").lower(),
            )
        elif tag == "a" and attrs.get("href"):
            self._active_anchor = attrs
        elif tag == "label":
            self._active_label_for = attrs.get("for")
        elif tag == "button":
            self._active_button = attrs
        elif tag in FIELD_TAGS:
            self._add_field(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        text = self._pop_text(tag)
        if tag == "title":
            self.title = text
        elif tag in HEADING_TAGS and text:
            self.headings.append(text)
        elif tag == "label" and text:
            self._last_label_text = text
            if self._active_label_for:
                self._label_for[self._active_label_for] = text
            self._active_label_for = None
        elif tag == "a" and self._active_anchor:
            href = self._active_anchor.get("href", "")
            if href and not href.startswith(("#", "javascript:")):
                self.transitions.append(
                    Transition(
                        source_page_id=self._page_id,
                        target_url=urljoin(self.url, href),
                        trigger_label=text or href,
                    )
                )
            self._active_anchor = None
        elif tag == "button" and self._active_button is not None:
            self._add_button(self._active_button, text)
            self._active_button = None
        elif tag == "form" and self._current_form:
            self.forms.append(self._current_form)
            self._current_form = None

    def handle_data(self, data: str) -> None:
        if self._text_stack:
            stripped = " ".join(data.split())
            if stripped:
                self._text_stack[-1].append(stripped)

    def page(self) -> Page:
        return Page(id=self._page_id, url=self.url, title=self.title, headings=self.headings)

    def _pop_text(self, tag: str) -> str:
        text_parts = self._text_stack.pop() if self._text_stack else []
        if self._text_stack and text_parts:
            self._text_stack[-1].extend(text_parts)
        if self._tag_stack:
            self._tag_stack.pop()
        return " ".join(text_parts).strip()

    def _context(self) -> dict[str, object]:
        return {
            "page_title": self.title,
            "headings": list(self.headings[-3:]),
            "form_id": self._current_form.id if self._current_form else None,
        }

    def _add_field(self, tag: str, attrs: dict[str, str]) -> None:
        label = (
            attrs.get("aria-label")
            or self._label_for.get(attrs.get("id", ""))
            or self._last_label_text
            or attrs.get("placeholder")
            or attrs.get("name")
            or attrs.get("id")
            or attrs.get("value")
            or tag
        )
        context = self._context()
        if "value" in attrs:
            context["read_value"] = attrs["value"]
        if tag == "input" and attrs.get("type") in {"checkbox", "radio"} and "checked" in attrs:
            context["read_value"] = "true"
        element = UiElement(
            id=new_id("ui"),
            page_id=self._page_id,
            selector_fingerprint=fingerprint(tag, attrs, label),
            label=label,
            control_type=attrs.get("type") or tag,
            context=context,
        )
        evidence = Evidence(
            id=new_id("ev"),
            kind="ui",
            source=self.url,
            summary=f"{element.control_type} control labelled '{label}'",
            locator=element.selector_fingerprint,
        )
        element.evidence_ids.append(evidence.id)
        self.evidence.append(evidence)
        self.elements.append(element)
        if self._current_form:
            self._current_form.field_ids.append(element.id)

    def _add_button(self, attrs: dict[str, str], text: str) -> None:
        label = text or attrs.get("aria-label") or attrs.get("value") or attrs.get("type") or "button"
        element = UiElement(
            id=new_id("ui"),
            page_id=self._page_id,
            selector_fingerprint=fingerprint("button", attrs, label),
            label=label,
            control_type=attrs.get("type") or "button",
            context=self._context(),
        )
        evidence = Evidence(
            id=new_id("ev"),
            kind="ui",
            source=self.url,
            summary=f"{element.control_type} action labelled '{label}'",
            locator=element.selector_fingerprint,
        )
        element.evidence_ids.append(evidence.id)
        self.evidence.append(evidence)
        self.elements.append(element)
        if self._current_form:
            self._current_form.field_ids.append(element.id)


def extract_interactions(html: str, url: str, include_readonly_facts: bool = False) -> tuple[Page, list[Form], list[UiElement], list[Transition], list[Evidence]]:
    parser = InteractionHTMLParser(url)
    parser.feed(html)
    page = parser.page()
    if include_readonly_facts:
        _add_readonly_facts(parser, html, page.id)
    return page, parser.forms, parser.elements, parser.transitions, parser.evidence


def _add_readonly_facts(parser: InteractionHTMLParser, html: str, page_id: str) -> None:
    for text_node in HTMLTextExtractor.extract_parts(html):
        if ":" not in text_node:
            continue
        label, value = text_node.split(":", 1)
        label = " ".join(label.split()).strip()
        value = " ".join(value.split()).strip()
        if not value:
            continue
        selector = fingerprint("readonly_status", {}, label)
        if any(element.selector_fingerprint == selector for element in parser.elements):
            continue
        evidence = Evidence(
            id=new_id("ev"),
            kind="ui",
            source=parser.url,
            summary=f"read-only status labelled '{label}'",
            locator=selector,
        )
        parser.evidence.append(evidence)
        parser.elements.append(
            UiElement(
                id=new_id("ui"),
                page_id=page_id,
                selector_fingerprint=selector,
                label=label,
                control_type="readonly_status",
                context={"page_title": parser.title, "headings": parser.headings, "read_value": value},
                evidence_ids=[evidence.id],
            )
        )


class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = " ".join(data.split())
        if stripped:
            self.parts.append(stripped)

    @classmethod
    def extract(cls, html: str) -> str:
        parser = cls()
        parser.feed(html)
        return " ".join(parser.parts)

    @classmethod
    def extract_parts(cls, html: str) -> list[str]:
        parser = cls()
        parser.feed(html)
        return parser.parts
