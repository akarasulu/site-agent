from __future__ import annotations

from pathlib import Path
import hashlib
import re
import time
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from site_agent.core.ai.backends import AiBackend, NoopAiBackend
from site_agent.core.extract.html import extract_interactions
from site_agent.core.ingest.docs import normalize_term
from site_agent.core.models import CrawlSnapshot, DomainTerm, Evidence, Form, InteractionFlow, Transition, UiElement, new_id, utc_now
from site_agent.core.profiles import Profile, profile_root


class CrawlError(RuntimeError):
    pass


CrawlProgress = Callable[[dict[str, Any]], None]


DEFAULT_CLICK_DENY_PATTERNS = [
    r"\blog\s*out\b",
    r"\blogout\b",
    r"\breboot\b",
    r"\brestart\b",
    r"\breset\b",
    r"\brestore\b",
    r"\bfactory\b",
    r"\bdelete\b",
    r"\bremove\b",
    r"\bapply\b",
    r"\bsave\b",
    r"\bsubmit\b",
    r"\bsend\b",
    r"\bupgrade\b",
    r"\bupdate\b",
    r"\bupload\b",
    r"\bdisconnect\b",
    r"\bconnect\b",
    r"\benable\b",
    r"\bdisable\b",
    r"\bstart\b",
    r"\bstop\b",
]


CLICKABLE_SELECTOR = (
    "a, [role=tab], [role=menuitem], [role=treeitem], [onclick], "
    ".AEleMenu3, .AEleMenu3Selected"
)
FORM_FLOW_TRIGGER_SELECTOR = (
    "button, input[type=button], input[type=submit], a, [role=button], [onclick], "
    ".AEleMenu3, .AEleMenu3Selected, .collapBarWithDataTrans"
)
FORM_FLOW_TRIGGER_RE = re.compile(r"\b(add|create|new|new item|add item|create new)\b", re.IGNORECASE)
FORM_FLOW_CANCEL_RE = re.compile(r"\b(cancel|close|discard)\b", re.IGNORECASE)
OVERLAY_DISMISS_RE = re.compile(r"\b(cancel|close|no)\b", re.IGNORECASE)


def validate_url_allowed(profile: Profile, url: str) -> None:
    host = urlparse(url).netloc
    allowed = set(profile.host_allowlist)
    if host not in allowed:
        raise CrawlError(f"URL host '{host}' is not in profile allowlist: {', '.join(sorted(allowed))}")


def state_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "state"


def append_state_url(url: str, label: str) -> str:
    return f"{url.split('#', 1)[0]}#state={state_slug(label)}"


def append_state_path_url(url: str, path: tuple[str, ...]) -> str:
    return f"{url.split('#', 1)[0]}#state={'/'.join(state_slug(label) for label in path)}"


def state_text_hash(text: str) -> str:
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def safe_click_patterns(profile: Profile) -> list[re.Pattern[str]]:
    configured = profile.crawl.click_deny_patterns or []
    return [re.compile(pattern, re.IGNORECASE) for pattern in [*DEFAULT_CLICK_DENY_PATTERNS, *configured]]


def is_safe_navigation_label(label: str, deny_patterns: list[re.Pattern[str]] | None = None) -> bool:
    clean = " ".join(label.split()).strip()
    if len(clean) < 2 or len(clean) > 80:
        return False
    if "?" in clean or len(clean.split()) > 6:
        return False
    if re.fullmatch(r"[\W_]+", clean):
        return False
    lowered = clean.lower()
    if lowered in {"ok", "cancel", "yes", "no", "close", "back", "next", "previous", "refresh"}:
        return False
    return not any(pattern.search(clean) for pattern in (deny_patterns or []))


def term_tokens(ontology: list[DomainTerm]) -> set[str]:
    tokens: set[str] = set()
    for term in ontology:
        for value in [term.canonical_name, *term.aliases]:
            tokens.update(part for part in normalize_term(value).split() if len(part) > 2)
    return tokens


def score_candidate_label(label: str, ontology_tokens: set[str], ai_scores: dict[str, float]) -> float:
    normalized = normalize_term(label)
    label_tokens = {part for part in normalized.split() if len(part) > 2}
    ontology_score = len(label_tokens & ontology_tokens) / max(len(label_tokens), 1)
    seed_score = 0.15 if label_tokens else 0.0
    return seed_score + ontology_score + ai_scores.get(normalized, 0.0)


def ai_navigation_scores(labels: list[str], ontology: list[DomainTerm], ai_backend: AiBackend, budget: int) -> dict[str, float]:
    if not labels or budget <= 0 or not ontology:
        return {}
    synthetic = [
        UiElement(
            id=f"nav_{hashlib.sha256(label.encode('utf-8')).hexdigest()[:10]}",
            page_id="candidate_navigation",
            selector_fingerprint=f"candidate|{label}",
            label=label,
            control_type="navigation_candidate",
            context={"candidate_label": label},
            evidence_ids=[],
        )
        for label in labels[:80]
    ]
    try:
        priorities = ai_backend.prioritize_crawl(synthetic, ontology)
    except Exception:
        return {}
    scores: dict[str, float] = {}
    label_lookup = {normalize_term(label): label for label in labels}
    for priority in priorities[:budget]:
        target = normalize_term(priority.target)
        matched = label_lookup.get(target)
        if not matched:
            target_tokens = set(target.split())
            for normalized, original in label_lookup.items():
                if target_tokens and target_tokens <= set(normalized.split()):
                    matched = original
                    break
        if matched:
            scores[normalize_term(matched)] = max(scores.get(normalize_term(matched), 0.0), float(priority.priority))
        for concept in priority.expected_concepts:
            concept_tokens = set(normalize_term(concept).split())
            for normalized, original in label_lookup.items():
                if concept_tokens & set(normalized.split()):
                    scores[normalize_term(original)] = max(scores.get(normalize_term(original), 0.0), float(priority.priority) * 0.5)
    return scores


def rank_navigation_labels(
    labels: list[str],
    profile: Profile,
    ontology: list[DomainTerm],
    ai_backend: AiBackend,
    ai_calls_remaining: int,
    include_profile_seeds: bool = False,
    planned_labels: list[str] | None = None,
    deprioritized_labels: list[str] | None = None,
) -> tuple[list[str], int]:
    unique = []
    seen = set()
    seed_labels = [*(planned_labels or []), *profile.crawl.js_navigation_texts] if include_profile_seeds else []
    for label in [*seed_labels, *labels]:
        clean = " ".join(label.split()).strip()
        key = normalize_term(clean)
        if clean and key not in seen:
            unique.append(clean)
            seen.add(key)
    ai_scores: dict[str, float] = {}
    if profile.crawl.ai_navigation_planning and ai_calls_remaining > 0:
        ai_scores = ai_navigation_scores(unique, ontology, ai_backend, profile.crawl.ai_navigation_budget)
        ai_calls_remaining -= 1
    ontology_tokens = term_tokens(ontology)
    deprioritized = {normalize_term(label) for label in deprioritized_labels or []}
    ranked = sorted(
        unique,
        key=lambda label: (
            score_candidate_label(label, ontology_tokens, ai_scores) - (0.5 if normalize_term(label) in deprioritized else 0.0),
            -len(label),
            label.lower(),
        ),
        reverse=True,
    )
    return ranked, ai_calls_remaining


def record_html_state(snapshot: CrawlSnapshot, html: str, url: str):
    title_page, forms, elements, transitions, evidence = extract_interactions(html, url)
    snapshot.pages.append(title_page)
    snapshot.forms.extend(forms)
    snapshot.elements.extend(elements)
    snapshot.evidence.extend(evidence)
    return title_page.id, transitions


def emit_progress(
    progress: CrawlProgress | None,
    snapshot: CrawlSnapshot,
    *,
    phase: str,
    current: str,
    scanned: int,
    total: int | None = None,
) -> None:
    if not progress:
        return
    progress(
        {
            "phase": phase,
            "current": current,
            "scanned": scanned,
            "total": total,
            "pages": len(snapshot.pages),
            "forms": len(snapshot.forms),
            "elements": len(snapshot.elements),
            "transitions": len(snapshot.transitions),
            "interaction_flows": len(snapshot.interaction_flows),
        }
    )


def fact_fingerprint(label: str, url: str) -> str:
    return hashlib.sha256(f"fact|{url}|{label}".encode("utf-8")).hexdigest()[:16]


def add_fact(snapshot: CrawlSnapshot, page_id: str, url: str, label: str, value: str, context: dict) -> None:
    clean_label = " ".join(label.split()).strip(" :-")
    clean_value = " ".join(value.split()).strip()
    if len(clean_label) < 3 or len(clean_label) > 100:
        return
    if clean_label.lower() in {"current time", "logout", "copyright"}:
        return
    fingerprint = fact_fingerprint(clean_label, url)
    if any(element.selector_fingerprint == fingerprint for element in snapshot.elements):
        return
    evidence = Evidence(
        id=new_id("ev"),
        kind="ui",
        source=url,
        summary=f"read-only status labelled '{clean_label}'",
        locator=fingerprint,
    )
    snapshot.evidence.append(evidence)
    snapshot.elements.append(
        UiElement(
            id=new_id("ui"),
            page_id=page_id,
            selector_fingerprint=fingerprint,
            label=clean_label,
            control_type="readonly_status",
            context={**context, "read_value": clean_value},
            evidence_ids=[evidence.id],
        )
    )


def add_ui_cue(snapshot: CrawlSnapshot, page_id: str, url: str, label: str, cue_type: str, context: dict) -> None:
    clean_label = " ".join(label.split()).strip(" :-")
    if len(clean_label) < 3 or len(clean_label) > 120:
        return
    fingerprint = hashlib.sha256(f"cue|{url}|{cue_type}|{clean_label}".encode("utf-8")).hexdigest()[:16]
    if any(element.selector_fingerprint == fingerprint for element in snapshot.elements):
        return
    evidence = Evidence(
        id=new_id("ev"),
        kind="ui",
        source=url,
        summary=f"{cue_type} cue labelled '{clean_label}'",
        locator=fingerprint,
    )
    snapshot.evidence.append(evidence)
    snapshot.elements.append(
        UiElement(
            id=new_id("ui"),
            page_id=page_id,
            selector_fingerprint=fingerprint,
            label=clean_label,
            control_type=cue_type,
            context=context,
            evidence_ids=[evidence.id],
        )
    )


def extract_browser_facts(snapshot: CrawlSnapshot, page, page_id: str, url: str) -> None:
    try:
        headings = page.locator("h1,h2,h3,.pageTitle,.title,[id*=Title],[class*=title]").evaluate_all(
            "els => els.map(el => (el.innerText || el.textContent || '').trim()).filter(Boolean).slice(0, 20)"
        )
    except Exception:
        headings = []
    context = {"page_title": page.title(), "headings": headings}
    for heading in headings:
        add_ui_cue(snapshot, page_id, url, heading, "heading", context)
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        text = ""
    for line in text.splitlines():
        clean = " ".join(line.split()).strip()
        if clean in headings or clean.lower() in {"page information", "port forwarding", "firewall", "filter criteria", "dmz"}:
            add_ui_cue(snapshot, page_id, url, clean, "section_heading", context)
    for line in text.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        if value.strip():
            add_fact(snapshot, page_id, url, label, value, context)
    try:
        row_labels = page.locator("tr").evaluate_all(
            """
            rows => rows.map(row => Array.from(row.querySelectorAll('th,td'))
              .map(cell => (cell.innerText || cell.textContent || '').trim())
              .filter(Boolean))
              .filter(cells => cells.length >= 2)
              .map(cells => ({label: cells[0], value: cells[1]}))
              .slice(0, 120)
            """
        )
    except Exception:
        row_labels = []
    for row in row_labels:
        if isinstance(row, dict):
            add_fact(snapshot, page_id, url, row.get("label", ""), row.get("value", ""), context)


def discover_navigation_labels(page, profile: Profile) -> list[str]:
    return [item["label"] for item in discover_navigation_items(page, profile)]


def discover_navigation_items(page, profile: Profile) -> list[dict[str, Any]]:
    deny_patterns = safe_click_patterns(profile)
    try:
        items = page.locator(CLICKABLE_SELECTOR).evaluate_all(
            """
            els => els
              .filter(el => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                const tag = el.tagName.toLowerCase();
                const type = (el.getAttribute('type') || '').toLowerCase();
                if (style.visibility === 'hidden' || style.display === 'none') return false;
                if (rect.width <= 0 || rect.height <= 0) return false;
                if (el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true') return false;
                if (tag === 'button' || tag === 'input' || type === 'submit' || type === 'button') return false;
                return true;
              })
              .map(el => {
                const rect = el.getBoundingClientRect();
                const label = (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
                return {label, rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}};
              })
              .filter(item => item.label)
              .slice(0, 300)
            """
        )
    except Exception:
        items = []
    clean_items: list[dict[str, Any]] = []
    seen = set()
    for item in items:
        label = str(item.get("label") or "")
        for part in label.splitlines():
            clean = " ".join(part.split()).strip()
            key = normalize_term(clean)
            if key not in seen and is_safe_navigation_label(clean, deny_patterns):
                clean_items.append({"label": clean, "rect": item.get("rect") or {}})
                seen.add(key)
    return clean_items


def discover_primary_navigation_labels(page, profile: Profile) -> list[str]:
    items = discover_navigation_items(page, profile)
    bands: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        rect = item.get("rect") or {}
        try:
            y = float(rect.get("y", 0))
            width = float(rect.get("width", 0))
        except (TypeError, ValueError):
            continue
        if width < 40:
            continue
        bands.setdefault(int(y // 24), []).append(item)
    for band in sorted(bands):
        band_items = sorted(bands[band], key=lambda item: (item.get("rect") or {}).get("x", 0))
        labels = [str(item.get("label") or "").strip() for item in band_items]
        labels = [label for label in labels if label]
        if len(labels) >= 3:
            return labels
    return [item["label"] for item in items]


def discover_navigation_label_groups(items: list[dict[str, Any]]) -> dict[str, set[str]]:
    groups_by_label: dict[str, set[str]] = {}
    x_bands: dict[int, list[dict[str, Any]]] = {}
    y_bands: dict[int, list[dict[str, Any]]] = {}
    for item in items:
        rect = item.get("rect") or {}
        try:
            x = float(rect.get("x", 0))
            y = float(rect.get("y", 0))
            width = float(rect.get("width", 0))
            height = float(rect.get("height", 0))
        except (TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        x_bands.setdefault(int(x // 32), []).append({**item, "x": x, "y": y})
        y_bands.setdefault(int(y // 24), []).append({**item, "x": x, "y": y})

    def add_group(group_id: str, group_items: list[dict[str, Any]]) -> None:
        for grouped_item in group_items:
            label = normalize_term(str(grouped_item.get("label") or ""))
            if label:
                groups_by_label.setdefault(label, set()).add(group_id)

    for band, band_items in x_bands.items():
        if len(band_items) < 3:
            continue
        y_values = [float(item["y"]) for item in band_items]
        if max(y_values) - min(y_values) < 72:
            continue
        add_group(f"x:{band}", band_items)

    for band, band_items in y_bands.items():
        if len(band_items) < 3:
            continue
        x_values = [float(item["x"]) for item in band_items]
        if max(x_values) - min(x_values) < 72:
            continue
        add_group(f"y:{band}", band_items)
    return groups_by_label


def best_navigation_label(label: str, visible_labels: list[str]) -> str:
    label_key = normalize_term(label)
    label_tokens = {part for part in label_key.split() if len(part) > 2}
    best_label = label
    best_score = 0.0
    for visible_label in visible_labels:
        visible_key = normalize_term(visible_label)
        if visible_key == label_key:
            return visible_label
        visible_tokens = {part for part in visible_key.split() if len(part) > 2}
        if not visible_tokens or not label_tokens:
            continue
        shared = label_tokens & visible_tokens
        score = len(shared) / len(visible_tokens)
        if visible_key in label_key or label_key in visible_key:
            score += 0.5
        if score > best_score:
            best_label = visible_label
            best_score = score
    if best_score >= 0.65:
        return best_label
    if best_score >= 0.5 and any(len(token) >= 5 for token in (label_tokens & {part for part in normalize_term(best_label).split() if len(part) > 2})):
        return best_label
    return label


def resolve_visible_navigation_label(page, label: str, profile: Profile) -> str:
    return best_navigation_label(label, discover_navigation_labels(page, profile))


def click_navigation_label(page, label: str) -> bool:
    dismiss_blocking_overlays(page)
    exact_text = re.compile(rf"^\s*{re.escape(label)}\s*$")
    try:
        locator = page.locator(CLICKABLE_SELECTOR).filter(has_text=exact_text, visible=True).first
        locator.click(timeout=1000)
        return True
    except Exception:
        try:
            locator = page.locator(CLICKABLE_SELECTOR).filter(has_text=label, visible=True).first
            locator.click(timeout=1000)
            return True
        except Exception:
            return False


def dismiss_blocking_overlays(page) -> bool:
    try:
        blocked = page.locator("#blackMask, .black_overlay, [role=dialog]").evaluate_all(
            """
            els => els.some(el => {
              const style = window.getComputedStyle(el);
              const rect = el.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            })
            """
        )
    except Exception:
        blocked = False
    if not blocked:
        return False
    for pattern in [OVERLAY_DISMISS_RE, re.compile(r"\bok\b", re.IGNORECASE)]:
        try:
            locator = page.locator("button, input[type=button], input[type=submit], a, [role=button]").filter(has_text=pattern, visible=True).last
            locator.click(timeout=1000, force=True)
            page.wait_for_timeout(500)
            return True
        except Exception:
            try:
                page.locator("button, input[type=button], input[type=submit], a, [role=button]").filter(has_text=pattern).last.evaluate("el => el.click()")
                page.wait_for_timeout(500)
                return True
            except Exception:
                continue
    return False


def visible_control_snapshot(page) -> list[dict]:
    try:
        return page.locator("input, select, textarea, button").evaluate_all(
            """
            els => els.map((el, index) => {
              const rect = el.getBoundingClientRect();
              const style = window.getComputedStyle(el);
              const visible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
              const id = el.getAttribute('id') || '';
              const name = el.getAttribute('name') || '';
              const type = (el.getAttribute('type') || el.tagName.toLowerCase()).toLowerCase();
              const label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || name || id || el.getAttribute('value') || el.textContent || el.tagName.toLowerCase();
              const attrs = {};
              for (const attr of ['minlength', 'maxlength', 'min', 'max', 'pattern', 'required']) {
                if (el.hasAttribute(attr)) attrs[attr] = el.getAttribute(attr) || 'true';
              }
              return {index, id, name, type, label: String(label).trim(), value: el.value || '', visible, attrs, rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}};
            }).filter(item => item.visible)
            """
        )
    except Exception:
        return []


def control_identity(control: dict) -> tuple:
    return (control.get("id") or "", control.get("name") or "", control.get("type") or "", control.get("label") or "")


def discover_form_flow_triggers(page) -> list[dict]:
    try:
        triggers = page.locator(FORM_FLOW_TRIGGER_SELECTOR).evaluate_all(
            """
            els => els.map((el, index) => {
              const rect = el.getBoundingClientRect();
              const style = window.getComputedStyle(el);
              const visible = rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
              const label = (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('value') || '').trim();
              return {index, label, visible};
            }).filter(item => item.visible && item.label)
            """
        )
    except Exception:
        return []
    seen = set()
    result = []
    for trigger in triggers:
        label = " ".join(str(trigger.get("label", "")).split())
        if label and FORM_FLOW_TRIGGER_RE.search(label) and label.lower() not in seen:
            result.append({"label": label, "index": trigger.get("index")})
            seen.add(label.lower())
    return result


def click_form_flow_trigger(page, label: str) -> bool:
    try:
        locator = page.locator(FORM_FLOW_TRIGGER_SELECTOR).filter(has_text=re.compile(re.escape(label), re.IGNORECASE), visible=True).first
        locator.click(timeout=1000)
        return True
    except Exception:
        try:
            locator = page.get_by_role("button", name=re.compile(re.escape(label), re.IGNORECASE)).first
            locator.click(timeout=1000)
            return True
        except Exception:
            return False


def cancel_form_flow(page) -> bool:
    try:
        locator = page.locator(FORM_FLOW_TRIGGER_SELECTOR).filter(has_text=FORM_FLOW_CANCEL_RE, visible=True).last
        locator.click(timeout=1000)
        page.wait_for_timeout(500)
        return True
    except Exception:
        return False


def infer_inline_constraints(page, controls: list[dict]) -> dict[str, dict]:
    try:
        body_text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        body_text = ""
    constraints: dict[str, dict] = {}
    for control in controls:
        label = " ".join(str(control.get("label", "")).replace("_", " ").split()).strip(" :")
        field_constraints = dict(control.get("attrs") or {})
        if label:
            length_match = re.search(rf"{re.escape(label)}\s+Length\s*:\s*(\d+)\s*[~\-]\s*(\d+)", body_text, re.IGNORECASE)
            if length_match:
                field_constraints["minLength"] = int(length_match.group(1))
                field_constraints["maxLength"] = int(length_match.group(2))
            range_match = re.search(rf"{re.escape(label)}.*?Range\s*:\s*(\d+)\s*[~\-]\s*(\d+)", body_text, re.IGNORECASE | re.DOTALL)
            if range_match:
                field_constraints["minimum"] = int(range_match.group(1))
                field_constraints["maximum"] = int(range_match.group(2))
        if field_constraints:
            constraints[str(control_identity(control))] = field_constraints
    return constraints


def selector_fingerprint_for_control(control: dict, url: str) -> str:
    stable = "|".join([url, control.get("id") or "", control.get("name") or "", control.get("type") or "", control.get("label") or ""])
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def browser_form_fingerprint(form: dict, control: dict, url: str) -> str:
    stable = "|".join(
        [
            "browser-form",
            url,
            str(form.get("index", "")),
            str(control.get("index", "")),
            control.get("id") or "",
            control.get("name") or "",
            control.get("type") or "",
            control.get("label") or "",
        ]
    )
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def capture_browser_forms(snapshot: CrawlSnapshot, page, page_id: str, state_url: str) -> None:
    if any(form.page_id == page_id and form.field_ids for form in snapshot.forms):
        return
    try:
        browser_forms = page.locator("form").evaluate_all(
            """
            forms => {
              const clean = value => String(value || '').replace(/\\s+/g, ' ').trim();
              const associatedLabel = el => {
                const id = el.getAttribute('id') || '';
                if (!id) return '';
                for (const label of Array.from(document.querySelectorAll('label'))) {
                  if (label.getAttribute('for') === id) return clean(label.innerText || label.textContent || '');
                }
                return '';
              };
              const tableLabel = el => {
                const cell = el.closest('td,th');
                const row = el.closest('tr');
                if (!cell || !row) return '';
                const cells = Array.from(row.children);
                const index = cells.indexOf(cell);
                for (let i = index - 1; i >= 0; i--) {
                  const text = clean(cells[i].innerText || cells[i].textContent || '');
                  if (text) return text.replace(/\\bLength\\s*:\\s*\\d+\\s*[~-]\\s*\\d+\\b/ig, '').trim();
                }
                return '';
              };
              const fallbackLabel = el => {
                const tag = el.tagName.toLowerCase();
                const type = (el.getAttribute('type') || tag).toLowerCase();
                if (tag === 'button' || type === 'button' || type === 'submit') {
                  return clean(el.innerText || el.textContent || el.getAttribute('value') || el.getAttribute('aria-label') || type);
                }
                return clean(
                  el.getAttribute('aria-label') ||
                  el.getAttribute('placeholder') ||
                  associatedLabel(el) ||
                  tableLabel(el) ||
                  el.getAttribute('name') ||
                  el.getAttribute('id') ||
                  tag
                );
              };
              return forms.map((form, formIndex) => {
                const controls = Array.from(form.querySelectorAll('input,select,textarea,button'))
                  .map((el, controlIndex) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    const tag = el.tagName.toLowerCase();
                    const type = (el.getAttribute('type') || tag).toLowerCase();
                    const visible = type === 'hidden'
                      ? false
                      : rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                    return {
                      index: controlIndex,
                      tag,
                      id: el.getAttribute('id') || '',
                      name: el.getAttribute('name') || '',
                      type,
                      role: el.getAttribute('role') || '',
                      ariaLabel: el.getAttribute('aria-label') || '',
                      label: fallbackLabel(el),
                      value: el.value || el.getAttribute('value') || '',
                      visible,
                      bbox: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
                      style: {
                        display: style.display,
                        visibility: style.visibility,
                        fontSize: style.fontSize,
                        fontWeight: style.fontWeight,
                        color: style.color,
                        backgroundColor: style.backgroundColor,
                      },
                    };
                  })
                  .filter(control => control.visible);
                const textLines = clean(form.innerText || form.textContent || '').split(/\\s{2,}|\\n/).filter(Boolean);
                return {
                  index: formIndex,
                  action: form.getAttribute('action') || null,
                  method: (form.getAttribute('method') || 'get').toLowerCase(),
                  label: clean(form.getAttribute('aria-label') || form.getAttribute('name') || textLines[0] || 'browser form'),
                  controls,
                };
              }).filter(form => form.controls.some(control => !['button', 'submit', 'hidden'].includes(control.type)));
            }
            """
        )
    except Exception:
        return
    context = {"page_title": page.title(), "headings": []}
    for browser_form in browser_forms:
        form = Form(
            id=new_id("form"),
            page_id=page_id,
            label=f"browser form: {browser_form.get('label') or 'form'}",
            action=browser_form.get("action"),
            method=browser_form.get("method") or "get",
        )
        for control in browser_form.get("controls") or []:
            label = " ".join(str(control.get("label") or control.get("name") or control.get("id") or control.get("tag") or "field").split())
            fingerprint = browser_form_fingerprint(browser_form, control, state_url)
            evidence = Evidence(
                id=new_id("ev"),
                kind="ui",
                source=state_url,
                summary=f"browser-visible {control.get('type') or control.get('tag')} control labelled '{label}'",
                locator=fingerprint,
            )
            element = UiElement(
                id=new_id("ui"),
                page_id=page_id,
                selector_fingerprint=fingerprint,
                label=label,
                control_type=control.get("type") or control.get("tag") or "input",
                context={
                    **context,
                    "form_id": form.id,
                    "dom_tag": control.get("tag"),
                    "selector_id": control.get("id"),
                    "selector_name": control.get("name"),
                    "accessibility_role": control.get("role"),
                    "accessibility_name": control.get("ariaLabel") or label,
                    "aria_label": control.get("ariaLabel"),
                    "visible": control.get("visible"),
                    "visual_bbox": control.get("bbox"),
                    "computed_style": control.get("style"),
                    "read_value": control.get("value", ""),
                    "browser_reconciled_form": True,
                },
                evidence_ids=[evidence.id],
            )
            snapshot.evidence.append(evidence)
            snapshot.elements.append(element)
            form.field_ids.append(element.id)
        if form.field_ids:
            snapshot.forms.append(form)


def probe_form_flows(snapshot: CrawlSnapshot, page, profile: Profile, page_id: str, state_url: str) -> None:
    if not profile.crawl.discover_form_flows:
        return
    triggers = discover_form_flow_triggers(page)[: profile.crawl.max_form_flow_probes]
    for trigger in triggers:
        before = {control_identity(control) for control in visible_control_snapshot(page)}
        label = trigger["label"]
        if not click_form_flow_trigger(page, label):
            continue
        page.wait_for_timeout(profile.crawl.navigation_wait_ms)
        after_controls = visible_control_snapshot(page)
        new_controls = [control for control in after_controls if control_identity(control) not in before and control.get("type") not in {"button", "submit"}]
        if not new_controls:
            cancel_form_flow(page)
            continue
        evidence = Evidence(
            id=new_id("ev"),
            kind="ui",
            source=state_url,
            summary=f"'{label}' opens a dynamic form flow with {len(new_controls)} newly visible control(s).",
            locator=f"form-flow:{state_url}:{label}",
        )
        snapshot.evidence.append(evidence)
        field_ids = []
        constraints = infer_inline_constraints(page, new_controls)
        for control in new_controls:
            control_constraints = constraints.get(str(control_identity(control)), {})
            element = UiElement(
                id=new_id("ui"),
                page_id=page_id,
                selector_fingerprint=selector_fingerprint_for_control(control, state_url),
                label=control.get("label") or control.get("name") or control.get("id") or "dynamic field",
                control_type=control.get("type") or "input",
                context={
                    "page_title": page.title(),
                    "form_flow_trigger": label,
                    "dynamic_visibility": "appears_after_trigger",
                    "selector_id": control.get("id"),
                    "selector_name": control.get("name"),
                    "requires_open_before_submit": True,
                    "constraints": control_constraints,
                },
                evidence_ids=[evidence.id],
            )
            snapshot.elements.append(element)
            field_ids.append(element.id)
        canceled = cancel_form_flow(page)
        snapshot.interaction_flows.append(
            InteractionFlow(
                id=new_id("flow"),
                page_id=page_id,
                trigger_label=label,
                flow_type="open_fill_cancel",
                discovered_field_ids=field_ids,
                constraints=constraints,
                cancel_supported=canceled,
                requires_open_before_submit=True,
                evidence_ids=[evidence.id],
                reasoning_summary="Crawler safely opened an add/create/new flow, inspected newly visible controls and constraints, then canceled without applying changes.",
            )
        )


def replay_navigation_path(page, base_url: str, path: tuple[str, ...], profile: Profile) -> bool:
    try:
        page.goto(base_url, wait_until="networkidle")
    except Exception:
        return False
    dismiss_blocking_overlays(page)
    if "Home" in discover_navigation_labels(page, profile):
        click_navigation_label(page, "Home")
        page.wait_for_timeout(profile.crawl.navigation_wait_ms)
    for label in path:
        if not is_safe_navigation_label(label, safe_click_patterns(profile)):
            return False
        resolved = resolve_visible_navigation_label(page, label, profile)
        if not click_navigation_label(page, resolved):
            return False
        page.wait_for_timeout(profile.crawl.navigation_wait_ms)
    return True


def path_revisit_allowed(path: tuple[str, ...], label: str, profile: Profile) -> bool:
    normalized_path = [normalize_term(item) for item in path]
    label_key = normalize_term(label)
    seed_keys = {normalize_term(seed) for seed in profile.crawl.js_navigation_texts}
    if label_key in seed_keys and label_key in normalized_path:
        return False
    return label_key not in normalized_path


def planned_branch_key(path: tuple[str, ...]) -> tuple[str, ...]:
    normalized = [normalize_term(label) for label in path if normalize_term(label)]
    if len(normalized) >= 2:
        return tuple(normalized[:2])
    return tuple(normalized[:1])


def planned_branch_time_budget_seconds(planned_paths: list[list[str]] | None, start_time: float, deadline: float | None) -> float | None:
    if not planned_paths or deadline is None:
        return None
    branch_keys = {
        planned_branch_key(tuple(str(label) for label in path if str(label).strip()))
        for path in planned_paths
    }
    branch_count = max(1, len([key for key in branch_keys if key]))
    remaining = max(0.0, deadline - start_time)
    if remaining <= 0:
        return None
    return max(20.0, min(90.0, remaining / branch_count))


def crawl_js_state_graph(
    snapshot: CrawlSnapshot,
    page,
    profile: Profile,
    base_url: str,
    root_page_id: str,
    seen_state_hashes: set[str],
    ontology: list[DomainTerm],
    ai_backend: AiBackend,
    deadline: float | None = None,
    planned_labels: list[str] | None = None,
    planned_paths: list[list[str]] | None = None,
    deprioritized_labels: list[str] | None = None,
    progress: CrawlProgress | None = None,
    progress_total: int | None = None,
    progress_offset: int = 0,
) -> list:
    transitions = []
    planned_mode = bool(planned_paths)
    started_at = time.monotonic()
    branch_time_budget = planned_branch_time_budget_seconds(planned_paths, started_at, deadline)
    branch_elapsed: dict[tuple[str, ...], float] = {}
    root_labels = discover_primary_navigation_labels(page, profile)
    root_label_keys = {normalize_term(label) for label in root_labels}
    labels, ai_calls_remaining = rank_navigation_labels(
        root_labels,
        profile,
        ontology,
        ai_backend,
        profile.crawl.ai_navigation_budget,
        include_profile_seeds=True,
        planned_labels=planned_labels,
        deprioritized_labels=deprioritized_labels,
    )
    pending: list[tuple[tuple[str, ...], set[str]]] = []
    seen_pending: set[tuple[str, ...]] = set()
    for planned_path in planned_paths or []:
        path = tuple(" ".join(str(label).split()).strip() for label in planned_path if str(label).strip())
        normalized = tuple(normalize_term(label) for label in path)
        if path and normalized not in seen_pending:
            pending.append((path, root_label_keys))
            seen_pending.add(normalized)
    for label in labels[: profile.crawl.max_js_states]:
        path = (label,)
        normalized = tuple(normalize_term(item) for item in path)
        if normalized not in seen_pending:
            pending.append((path, root_label_keys))
            seen_pending.add(normalized)
    visited_paths: set[tuple[str, ...]] = set()
    page_ids_by_path: dict[tuple[str, ...], str] = {(): root_page_id}

    while pending and len(visited_paths) < profile.crawl.max_js_states:
        if deadline and time.monotonic() >= deadline:
            break
        path, parent_label_keys = pending.pop(0)
        normalized_path = tuple(normalize_term(label) for label in path)
        if normalized_path in visited_paths:
            continue
        if not path or any(not is_safe_navigation_label(label, safe_click_patterns(profile)) for label in path):
            continue
        branch_key = planned_branch_key(path)
        if branch_time_budget is not None and branch_key and branch_elapsed.get(branch_key, 0.0) >= branch_time_budget:
            continue
        branch_started_at = time.monotonic()
        if not replay_navigation_path(page, base_url, path, profile):
            if branch_time_budget is not None and branch_key:
                branch_elapsed[branch_key] = branch_elapsed.get(branch_key, 0.0) + (time.monotonic() - branch_started_at)
            continue
        visited_paths.add(normalized_path)
        state_url = append_state_path_url(page.url or base_url, path)
        try:
            body_text = page.locator("body").inner_text(timeout=3000)
        except Exception:
            body_text = page.content()
        state_hash = state_text_hash(f"{page.url}\n{body_text}")
        seen_state_hashes.add(state_hash)
        state_page_id, state_transitions = record_html_state(snapshot, page.content(), state_url)
        page_ids_by_path[path] = state_page_id
        extract_browser_facts(snapshot, page, state_page_id, state_url)
        capture_browser_forms(snapshot, page, state_page_id, state_url)
        probe_form_flows(snapshot, page, profile, state_page_id, state_url)
        emit_progress(
            progress,
            snapshot,
            phase="js-state",
            current=" > ".join(path),
            scanned=progress_offset + len(visited_paths),
            total=progress_total,
        )
        transitions.extend(state_transitions)
        parent_path = path[:-1]
        transitions.append(
            Transition(
                source_page_id=page_ids_by_path.get(parent_path, root_page_id),
                target_url=state_url,
                trigger_label=path[-1],
                risk_level="low",
            )
        )
        if len(path) >= profile.crawl.max_js_depth:
            if branch_time_budget is not None and branch_key:
                branch_elapsed[branch_key] = branch_elapsed.get(branch_key, 0.0) + (time.monotonic() - branch_started_at)
            continue
        if deadline and time.monotonic() >= deadline:
            if branch_time_budget is not None and branch_key:
                branch_elapsed[branch_key] = branch_elapsed.get(branch_key, 0.0) + (time.monotonic() - branch_started_at)
            break
        visible_labels = discover_navigation_labels(page, profile)
        child_visible_labels = [label for label in visible_labels if normalize_term(label) not in parent_label_keys]
        next_labels, ai_calls_remaining = rank_navigation_labels(
            child_visible_labels,
            profile,
            ontology,
            ai_backend,
            ai_calls_remaining,
            include_profile_seeds=False,
            deprioritized_labels=deprioritized_labels,
        )
        front_paths = []
        visible_label_keys = {normalize_term(label) for label in visible_labels}
        for next_label in next_labels:
            if not path_revisit_allowed(path, next_label, profile):
                continue
            next_path = (*path, next_label)
            next_normalized = tuple(normalize_term(label) for label in next_path)
            pending_paths = {item[0] for item in pending}
            if next_normalized not in visited_paths and next_path not in pending_paths and len(pending) + len(visited_paths) < profile.crawl.max_js_states:
                front_paths.append((next_path, visible_label_keys))
        if branch_time_budget is not None and branch_key:
            branch_elapsed[branch_key] = branch_elapsed.get(branch_key, 0.0) + (time.monotonic() - branch_started_at)
        if planned_mode:
            pending.extend(front_paths)
        else:
            pending = front_paths + pending
    return transitions


def crawl_profile(
    workspace: Path,
    profile: Profile,
    start_url: str | None = None,
    ontology: list[DomainTerm] | None = None,
    ai_backend: AiBackend | None = None,
    planned_labels: list[str] | None = None,
    planned_paths: list[list[str]] | None = None,
    deprioritized_labels: list[str] | None = None,
    progress: CrawlProgress | None = None,
    progress_total: int | None = None,
) -> CrawlSnapshot:
    target_url = start_url or profile.base_url
    validate_url_allowed(profile, target_url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CrawlError(
            "Playwright is required for browser crawling. Install it with: "
            "pip install -e '.[crawl]' && playwright install chromium"
        ) from exc

    run_id = new_id("run")
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id=run_id)
    auth_state = profile_root(workspace, profile.name) / profile.auth.storage_state_path
    storage_state = str(auth_state) if auth_state.exists() else None
    ontology = ontology or []
    ai_backend = ai_backend or NoopAiBackend()

    visited: set[str] = set()
    pending = [target_url]
    seen_state_hashes: set[str] = set()
    deadline = time.monotonic() + profile.crawl.max_crawl_seconds if profile.crawl.max_crawl_seconds > 0 else None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context_kwargs = {"ignore_https_errors": profile.crawl.ignore_https_errors}
            if storage_state:
                context_kwargs["storage_state"] = storage_state
            context = browser.new_context(**context_kwargs)
            while pending and len(visited) < profile.crawl.max_pages:
                if deadline and time.monotonic() >= deadline:
                    break
                current_url = pending.pop(0)
                if current_url in visited:
                    continue
                validate_url_allowed(profile, current_url)
                visited.add(current_url)
                page = context.new_page()
                page.goto(current_url, wait_until="networkidle")
                final_url = page.url
                page_id, current_transitions = record_html_state(snapshot, page.content(), final_url)
                extract_browser_facts(snapshot, page, page_id, final_url)
                capture_browser_forms(snapshot, page, page_id, final_url)
                probe_form_flows(snapshot, page, profile, page_id, final_url)
                emit_progress(
                    progress,
                    snapshot,
                    phase="page",
                    current=final_url,
                    scanned=len(visited),
                    total=progress_total,
                )
                try:
                    body_text = page.locator("body").inner_text(timeout=3000)
                except Exception:
                    body_text = page.content()
                seen_state_hashes.add(state_text_hash(f"{final_url}\n{body_text}"))
                if profile.crawl.discover_js_states or profile.crawl.js_navigation_texts:
                    current_transitions.extend(
                        crawl_js_state_graph(
                            snapshot=snapshot,
                            page=page,
                            profile=profile,
                            base_url=final_url,
                            root_page_id=page_id,
                            seen_state_hashes=seen_state_hashes,
                            ontology=ontology,
                            ai_backend=ai_backend,
                            deadline=deadline,
                            planned_labels=planned_labels,
                            planned_paths=planned_paths,
                            deprioritized_labels=deprioritized_labels,
                            progress=progress,
                            progress_total=progress_total,
                            progress_offset=len(visited),
                        )
                    )
                allowed_transitions = [t for t in current_transitions if urlparse(t.target_url).netloc in profile.host_allowlist]
                snapshot.transitions.extend(allowed_transitions)
                for transition in allowed_transitions:
                    if transition.target_url not in visited and transition.target_url not in pending:
                        pending.append(transition.target_url)
                page.close()
            context.close()
            browser.close()
    except Exception as exc:  # Playwright wraps browser/runtime failures in several exception types.
        raise CrawlError(f"Crawl failed for {target_url}. Check authentication, allowlist, and browser install. Details: {exc}") from exc

    return snapshot


def collect_js_state_corpus(
    snapshot: CrawlSnapshot,
    page,
    profile: Profile,
    base_url: str,
    root_page_id: str,
    deadline: float | None = None,
    progress: CrawlProgress | None = None,
    progress_total: int | None = None,
) -> tuple[list[Transition], dict[str, Any]]:
    transitions: list[Transition] = []
    deny_patterns = safe_click_patterns(profile)
    root_labels = discover_primary_navigation_labels(page, profile)
    root_label_keys = {normalize_term(label) for label in root_labels}
    queue: list[tuple[str, ...]] = []
    seen_queued: set[tuple[str, ...]] = set()
    for label in root_labels:
        clean = " ".join(str(label).split()).strip()
        key = (normalize_term(clean),)
        if clean and key not in seen_queued and is_safe_navigation_label(clean, deny_patterns):
            queue.append((clean,))
            seen_queued.add(key)

    visited: set[tuple[str, ...]] = set()
    failed_paths: list[list[str]] = []
    duplicate_paths: list[list[str]] = []
    page_ids_by_path: dict[tuple[str, ...], str] = {(): root_page_id}
    seen_state_hashes: set[str] = set()
    stopped_by_deadline = False
    stopped_by_state_limit = False
    while queue:
        if deadline and time.monotonic() >= deadline:
            stopped_by_deadline = True
            break
        if len(visited) >= profile.crawl.max_js_states:
            stopped_by_state_limit = True
            break
        path = queue.pop(0)
        normalized_path = tuple(normalize_term(item) for item in path)
        if normalized_path in visited:
            continue
        if not replay_navigation_path(page, base_url, path, profile):
            failed_paths.append(list(path))
            continue
        visited.add(normalized_path)
        state_url = append_state_path_url(page.url or base_url, path)
        try:
            body_text = page.locator("body").inner_text(timeout=3000)
        except Exception:
            body_text = page.content()
        state_hash = state_text_hash(f"{page.url}\n{body_text}")
        if state_hash in seen_state_hashes:
            duplicate_paths.append(list(path))
            emit_progress(
                progress,
                snapshot,
                phase="collect-duplicate",
                current=" > ".join(path),
                scanned=len(visited),
                total=progress_total,
            )
        seen_state_hashes.add(state_hash)
        state_page_id, state_transitions = record_html_state(snapshot, page.content(), state_url)
        page_ids_by_path[path] = state_page_id
        extract_browser_facts(snapshot, page, state_page_id, state_url)
        capture_browser_forms(snapshot, page, state_page_id, state_url)
        transitions.extend(state_transitions)
        transitions.append(
            Transition(
                source_page_id=page_ids_by_path.get(path[:-1], root_page_id),
                target_url=state_url,
                trigger_label=path[-1],
                risk_level="low",
            )
        )
        emit_progress(
            progress,
            snapshot,
            phase="collect",
            current=" > ".join(path),
            scanned=len(visited),
            total=progress_total,
        )
        if len(path) >= profile.crawl.max_js_depth:
            continue
        child_paths: list[tuple[str, ...]] = []
        nav_items = discover_navigation_items(page, profile)
        label_groups = discover_navigation_label_groups(nav_items)
        for item in nav_items:
            label = str(item.get("label") or "")
            clean = " ".join(str(label).split()).strip()
            if not clean or not is_safe_navigation_label(clean, deny_patterns):
                continue
            clean_key = normalize_term(clean)
            if clean_key in root_label_keys:
                next_path = (clean,)
            else:
                replacement_index = None
                clean_groups = label_groups.get(clean_key, set())
                if any(group.startswith("x:") for group in clean_groups) and len(path) >= 2:
                    replacement_index = 1
                elif any(group.startswith("y:") for group in clean_groups) and len(path) >= 3:
                    replacement_index = 2
                else:
                    for index in range(len(path) - 1, -1, -1):
                        path_key = normalize_term(path[index])
                        if path_key != clean_key and clean_groups & label_groups.get(path_key, set()):
                            replacement_index = index
                            break
                if replacement_index is not None:
                    next_path = (*path[:replacement_index], clean)
                else:
                    if not path_revisit_allowed(path, clean, profile):
                        continue
                    next_path = (*path, clean)
            next_key = tuple(normalize_term(item) for item in next_path)
            if next_key not in visited and next_key not in seen_queued:
                child_paths.append(next_path)
                seen_queued.add(next_key)
        queue = child_paths + queue
    report = {
        "complete": not queue and not failed_paths and not stopped_by_deadline and not stopped_by_state_limit,
        "visited_paths": [list(path) for path in sorted(visited)],
        "visited_count": len(visited),
        "queued_remaining": [list(path) for path in queue],
        "queued_remaining_count": len(queue),
        "failed_paths": failed_paths,
        "failed_count": len(failed_paths),
        "duplicate_paths": duplicate_paths,
        "duplicate_count": len(duplicate_paths),
        "stopped_by_deadline": stopped_by_deadline,
        "stopped_by_state_limit": stopped_by_state_limit,
        "max_states": profile.crawl.max_js_states,
    }
    return transitions, report


def crawl_collect_profile(
    workspace: Path,
    profile: Profile,
    start_url: str | None = None,
    progress: CrawlProgress | None = None,
    progress_total: int | None = None,
) -> tuple[CrawlSnapshot, dict[str, Any]]:
    target_url = start_url or profile.base_url
    validate_url_allowed(profile, target_url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CrawlError(
            "Playwright is required for browser crawling. Install it with: "
            "pip install -e '.[crawl]' && playwright install chromium"
        ) from exc

    run_id = new_id("run")
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id=run_id)
    auth_state = profile_root(workspace, profile.name) / profile.auth.storage_state_path
    storage_state = str(auth_state) if auth_state.exists() else None
    deadline = time.monotonic() + profile.crawl.max_crawl_seconds if profile.crawl.max_crawl_seconds > 0 else None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context_kwargs = {"ignore_https_errors": profile.crawl.ignore_https_errors}
            if storage_state:
                context_kwargs["storage_state"] = storage_state
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.goto(target_url, wait_until="networkidle")
            page_id, transitions = record_html_state(snapshot, page.content(), page.url)
            extract_browser_facts(snapshot, page, page_id, page.url)
            capture_browser_forms(snapshot, page, page_id, page.url)
            emit_progress(progress, snapshot, phase="collect", current=page.url, scanned=1, total=progress_total)
            collected_transitions, report = collect_js_state_corpus(
                snapshot=snapshot,
                page=page,
                profile=profile,
                base_url=page.url,
                root_page_id=page_id,
                deadline=deadline,
                progress=progress,
                progress_total=progress_total,
            )
            transitions.extend(collected_transitions)
            snapshot.transitions.extend(transitions)
            context.close()
            browser.close()
    except Exception as exc:
        raise CrawlError(f"Fast collection failed for {target_url}. Check authentication, allowlist, and browser install. Details: {exc}") from exc
    report.update(
        {
            "run_id": snapshot.run_id,
            "pages": len(snapshot.pages),
            "forms": len(snapshot.forms),
            "elements": len(snapshot.elements),
            "visual_html_snapshots": sum(1 for page in snapshot.pages if page.html_snapshot),
        }
    )
    return snapshot, report


def sample_landing_page_text(workspace: Path, profile: Profile, start_url: str | None = None, max_chars: int = 12000) -> str:
    target_url = start_url or profile.base_url
    validate_url_allowed(profile, target_url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise CrawlError(
            "Playwright is required for browser crawling. Install it with: "
            "pip install -e '.[crawl]' && playwright install chromium"
        ) from exc

    auth_state = profile_root(workspace, profile.name) / profile.auth.storage_state_path
    storage_state = str(auth_state) if auth_state.exists() else None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context_kwargs = {"ignore_https_errors": profile.crawl.ignore_https_errors}
                if storage_state:
                    context_kwargs["storage_state"] = storage_state
                context = browser.new_context(**context_kwargs)
                try:
                    page = context.new_page()
                    page.goto(target_url, wait_until="networkidle")
                    try:
                        text = page.locator("body").inner_text(timeout=5000)
                    except Exception:
                        text = page.content()
                finally:
                    context.close()
            finally:
                browser.close()
    except Exception as exc:
        raise CrawlError(f"Could not sample landing page text for AI domain discovery at {target_url}. Details: {exc}") from exc
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    return normalized[:max_chars]


def crawl_html_fixture(profile: Profile, html: str, url: str | None = None) -> CrawlSnapshot:
    target_url = url or profile.base_url
    validate_url_allowed(profile, target_url)
    run_id = new_id("run")
    page, forms, elements, transitions, evidence = extract_interactions(html, target_url, include_readonly_facts=True)
    return CrawlSnapshot(
        timestamp=utc_now(),
        profile_id=profile.id,
        run_id=run_id,
        pages=[page],
        forms=forms,
        elements=elements,
        transitions=transitions,
        evidence=evidence,
    )


def crawl_fixture_site(profile: Profile, site_dir: Path, start_path: str = "index.html", progress: CrawlProgress | None = None, progress_total: int | None = None) -> CrawlSnapshot:
    start_file = site_dir / start_path
    if not start_file.exists():
        raise CrawlError(f"Fixture site start file does not exist: {start_file}")

    run_id = new_id("run")
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id=run_id)
    visited: set[Path] = set()
    pending = [start_file]

    while pending and len(visited) < profile.crawl.max_pages:
        current = pending.pop(0).resolve()
        if current in visited:
            continue
        if site_dir.resolve() not in current.parents and current != site_dir.resolve():
            continue
        if not current.exists() or current.suffix.lower() not in {".html", ".htm"}:
            continue
        visited.add(current)
        relative = current.relative_to(site_dir.resolve()).as_posix()
        page_url = urljoin(profile.base_url.rstrip("/") + "/", relative)
        page, forms, elements, transitions, evidence = extract_interactions(current.read_text(encoding="utf-8"), page_url)
        snapshot.pages.append(page)
        snapshot.forms.extend(forms)
        snapshot.elements.extend(elements)
        snapshot.transitions.extend(transitions)
        snapshot.evidence.extend(evidence)
        emit_progress(
            progress,
            snapshot,
            phase="fixture-page",
            current=relative,
            scanned=len(visited),
            total=progress_total,
        )
        for transition in transitions:
            parsed = urlparse(transition.target_url)
            if parsed.netloc and parsed.netloc not in profile.host_allowlist:
                continue
            candidate = (site_dir / parsed.path.lstrip("/")).resolve()
            if candidate.is_dir():
                candidate = candidate / "index.html"
            if candidate.suffix == "":
                candidate = candidate.with_suffix(".html")
            if candidate not in visited and candidate not in pending:
                pending.append(candidate)

    return snapshot
