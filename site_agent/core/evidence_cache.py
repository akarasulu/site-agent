from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from site_agent.core.debug import state_path
from site_agent.core.ingest.docs import normalize_term
from site_agent.core.models import CrawlSnapshot, Page, UiElement, utc_now
from site_agent.core.profiles import output_root
from site_agent.core.storage import read_json, write_json


STRUCTURAL_TAGS = {
    "a",
    "article",
    "button",
    "div",
    "fieldset",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "input",
    "label",
    "li",
    "main",
    "nav",
    "option",
    "section",
    "select",
    "table",
    "td",
    "textarea",
    "th",
    "tr",
    "ul",
}
TEXT_SKIP_TAGS = {"script", "style", "noscript", "template"}


@dataclass
class PageEvidenceCacheRecord:
    cache_key: str
    page_id: str
    url: str
    url_family: dict[str, Any]
    state_path: list[str]
    title: str
    headings: list[str]
    html_hash: str | None
    text_hash: str
    template_signature: str
    tag_histogram: dict[str, int]
    form_count: int
    element_count: int
    transition_count: int
    link_labels: list[str]
    control_labels: list[str]
    evidence_ids: list[str]
    evidence_density: dict[str, int]


@dataclass
class EvidenceCache:
    profile_id: str
    run_id: str
    generated_at: str
    records: list[PageEvidenceCacheRecord] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


class _HtmlFeatureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tag_histogram: Counter[str] = Counter()
        self.text_parts: list[str] = []
        self.link_labels: list[str] = []
        self.control_labels: list[str] = []
        self._skip_depth = 0
        self._anchor_depth = 0
        self._button_depth = 0
        self._anchor_text: list[str] = []
        self._button_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self.tag_histogram[tag] += 1
        attrs_by_name = {name.lower(): value or "" for name, value in attrs}
        if tag in TEXT_SKIP_TAGS:
            self._skip_depth += 1
        if tag == "a":
            self._anchor_depth += 1
            self._anchor_text = []
        if tag == "button":
            self._button_depth += 1
            self._button_text = []
        if tag in {"input", "select", "textarea"}:
            label = _first_present(
                attrs_by_name,
                ("aria-label", "placeholder", "title", "name", "id"),
            )
            if label:
                self.control_labels.append(label)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        self.tag_histogram[tag] += 1
        attrs_by_name = {name.lower(): value or "" for name, value in attrs}
        if tag in {"input", "select", "textarea"}:
            label = _first_present(
                attrs_by_name,
                ("aria-label", "placeholder", "title", "name", "id"),
            )
            if label:
                self.control_labels.append(label)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.split()).strip()
        if not text:
            return
        self.text_parts.append(text)
        if self._anchor_depth:
            self._anchor_text.append(text)
        if self._button_depth:
            self._button_text.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in TEXT_SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "a" and self._anchor_depth:
            label = " ".join(self._anchor_text).strip()
            if label:
                self.link_labels.append(label)
            self._anchor_depth -= 1
            self._anchor_text = []
        if tag == "button" and self._button_depth:
            label = " ".join(self._button_text).strip()
            if label:
                self.control_labels.append(label)
            self._button_depth -= 1
            self._button_text = []


def build_evidence_cache(snapshot: CrawlSnapshot) -> EvidenceCache:
    forms_by_page: dict[str, list[Any]] = defaultdict(list)
    elements_by_page: dict[str, list[UiElement]] = defaultdict(list)
    transitions_by_page: dict[str, list[Any]] = defaultdict(list)
    evidence_by_id = {item.id: item for item in snapshot.evidence}

    for form in snapshot.forms:
        forms_by_page[form.page_id].append(form)
    for element in snapshot.elements:
        elements_by_page[element.page_id].append(element)
    page_by_url = {page.url: page.id for page in snapshot.pages}
    for transition in snapshot.transitions:
        page_id = page_by_url.get(transition.target_url) or transition.source_page_id
        transitions_by_page[page_id].append(transition)

    records = [
        _record_for_page(
            snapshot.profile_id,
            page,
            forms_by_page.get(page.id, []),
            elements_by_page.get(page.id, []),
            transitions_by_page.get(page.id, []),
            evidence_by_id,
        )
        for page in sorted(snapshot.pages, key=lambda item: item.id)
    ]
    return EvidenceCache(
        profile_id=snapshot.profile_id,
        run_id=snapshot.run_id,
        generated_at=utc_now(),
        records=records,
        summary=_cache_summary(snapshot, records),
    )


def diff_evidence_caches(previous: EvidenceCache | dict[str, Any], current: EvidenceCache | dict[str, Any]) -> dict[str, Any]:
    previous_records = _records_by_key(previous)
    current_records = _records_by_key(current)
    previous_keys = set(previous_records)
    current_keys = set(current_records)
    common_keys = previous_keys & current_keys

    changed_content = []
    for key in sorted(common_keys):
        old = previous_records[key]
        new = current_records[key]
        if old.get("html_hash") != new.get("html_hash") or old.get("text_hash") != new.get("text_hash"):
            changed_content.append(
                {
                    "cache_key": key,
                    "url": new.get("url"),
                    "old_text_hash": old.get("text_hash"),
                    "new_text_hash": new.get("text_hash"),
                }
            )

    return {
        "previous_run_id": _cache_value(previous, "run_id"),
        "current_run_id": _cache_value(current, "run_id"),
        "added_cache_keys": sorted(current_keys - previous_keys),
        "removed_cache_keys": sorted(previous_keys - current_keys),
        "changed_content": changed_content,
        "unchanged_cache_keys": sorted(common_keys - {item["cache_key"] for item in changed_content}),
    }


def write_evidence_cache(workspace: Path, profile_name: str, cache: EvidenceCache) -> Path:
    path = output_root(workspace, profile_name) / "reports" / f"evidence-cache-{cache.run_id}.json"
    write_json(path, cache)
    return path


def load_evidence_cache(path: Path) -> dict[str, Any]:
    return read_json(path)


def _record_for_page(
    profile_id: str,
    page: Page,
    forms: list[Any],
    elements: list[UiElement],
    transitions: list[Any],
    evidence_by_id: dict[str, Any],
) -> PageEvidenceCacheRecord:
    parser = _HtmlFeatureParser()
    html = page.html_snapshot or ""
    if html:
        parser.feed(html)
    page_text = "\n".join([page.title, *page.headings, *parser.text_parts])
    tag_histogram = {
        tag: parser.tag_histogram[tag]
        for tag in sorted(parser.tag_histogram)
        if tag in STRUCTURAL_TAGS
    }
    structural_payload = {
        "tags": tag_histogram,
        "form_count": len(forms),
        "element_roles": dict(sorted(Counter(_element_family(element) for element in elements).items())),
        "transition_count": len(transitions),
    }
    template_signature = f"tpl_{_digest_json(structural_payload)[:16]}"
    state = state_path(page)
    cache_payload = {
        "profile_id": profile_id,
        "url_family": _url_family(page.url, state),
        "state_path": state,
        "template_signature": template_signature,
    }
    evidence_ids = _ordered_unique(
        evidence_id
        for element in elements
        for evidence_id in element.evidence_ids
    )
    evidence_density = Counter(
        evidence_by_id[evidence_id].kind
        for evidence_id in evidence_ids
        if evidence_id in evidence_by_id
    )

    return PageEvidenceCacheRecord(
        cache_key=f"page_{_digest_json(cache_payload)[:20]}",
        page_id=page.id,
        url=page.url,
        url_family=_url_family(page.url, state),
        state_path=state,
        title=page.title,
        headings=page.headings[:12],
        html_hash=_digest(html) if html else None,
        text_hash=_digest(page_text),
        template_signature=template_signature,
        tag_histogram=tag_histogram,
        form_count=len(forms),
        element_count=len(elements),
        transition_count=len(transitions),
        link_labels=_ordered_unique(parser.link_labels)[:80],
        control_labels=_ordered_unique([element.label for element in elements] + parser.control_labels)[:120],
        evidence_ids=evidence_ids,
        evidence_density=dict(sorted(evidence_density.items())),
    )


def _cache_summary(snapshot: CrawlSnapshot, records: list[PageEvidenceCacheRecord]) -> dict[str, Any]:
    template_groups: dict[str, list[PageEvidenceCacheRecord]] = defaultdict(list)
    for record in records:
        template_groups[record.template_signature].append(record)

    groups = []
    for signature, group_records in sorted(template_groups.items()):
        groups.append(
            {
                "template_signature": signature,
                "pages": len(group_records),
                "examples": [record.url for record in group_records[:3]],
                "max_forms": max((record.form_count for record in group_records), default=0),
                "max_elements": max((record.element_count for record in group_records), default=0),
            }
        )

    return {
        "pages": len(records),
        "forms": len(snapshot.forms),
        "elements": len(snapshot.elements),
        "transitions": len(snapshot.transitions),
        "templates": len(template_groups),
        "repeated_templates": sum(1 for group in template_groups.values() if len(group) > 1),
        "cacheable_pages": sum(1 for record in records if record.html_hash or record.text_hash),
        "template_groups": groups,
    }


def _url_family(url: str, state: list[str]) -> dict[str, Any]:
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme.lower(),
        "host": parsed.netloc.lower(),
        "path": parsed.path or "/",
        "query_keys": sorted({key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}),
        "state_path": state,
    }


def _element_family(element: UiElement) -> str:
    value_state = "with_value" if "read_value" in element.context else "no_value"
    return f"{normalize_term(element.control_type)}:{value_state}"


def _first_present(values: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = " ".join(values.get(key, "").split()).strip()
        if value:
            return value
    return ""


def _ordered_unique(values: list[str] | Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = " ".join(str(value).split()).strip()
        key = normalize_term(clean)
        if clean and key not in seen:
            result.append(clean)
            seen.add(key)
    return result


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_json(value: dict[str, Any]) -> str:
    return _digest(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _records_by_key(cache: EvidenceCache | dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_records = _cache_value(cache, "records") or []
    records = []
    for record in raw_records:
        if isinstance(record, PageEvidenceCacheRecord):
            records.append(record.__dict__)
        else:
            records.append(dict(record))
    return {record["cache_key"]: record for record in records}


def _cache_value(cache: EvidenceCache | dict[str, Any], key: str) -> Any:
    if isinstance(cache, EvidenceCache):
        return getattr(cache, key)
    return cache.get(key)
