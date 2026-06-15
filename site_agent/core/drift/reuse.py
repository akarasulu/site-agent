from __future__ import annotations

from collections import Counter
from typing import Any

from site_agent.core.debug import state_path
from site_agent.core.ingest.docs import normalize_term
from site_agent.core.models import CrawlSnapshot, Page, UiElement
from site_agent.core.page_graph import visual_box


def build_adapter_reuse_report(
    previous: CrawlSnapshot,
    current: CrawlSnapshot,
    bindings: dict[str, Any] | list[dict[str, Any]] | None,
) -> dict[str, Any]:
    previous_elements = {element.id: element for element in previous.elements}
    current_elements = {element.id: element for element in current.elements}
    current_by_selector = {element.selector_fingerprint: element for element in current.elements}
    previous_pages = {page.id: page for page in previous.pages}
    current_pages = {page.id: page for page in current.pages}

    candidates = []
    for binding in _iter_bindings(bindings):
        adapter = _binding_adapter(binding)
        element_ids = _binding_element_ids(adapter)
        field_matches = []
        for element_id in element_ids:
            previous_element = previous_elements.get(element_id)
            if previous_element is None:
                field_matches.append(
                    {
                        "previous_element_id": element_id,
                        "status": "missing_previous_evidence",
                        "score": 0.0,
                    }
                )
                continue
            match = _best_current_match(
                previous_element,
                current_elements,
                current_by_selector,
                previous_pages,
                current_pages,
            )
            field_matches.append(match)
        status = _binding_status(field_matches)
        candidates.append(
            {
                "tool_name": _binding_value(binding, "tool_name"),
                "action": adapter.get("action"),
                "status": status,
                "confidence": _binding_confidence(field_matches),
                "field_matches": field_matches,
            }
        )

    status_counts = Counter(candidate["status"] for candidate in candidates)
    return {
        "previous_run_id": previous.run_id,
        "current_run_id": current.run_id,
        "summary": {
            "bindings": len(candidates),
            "stable": status_counts.get("stable", 0),
            "reuse_candidates": status_counts.get("reuse_candidate", 0),
            "review_required": status_counts.get("review_required", 0),
            "broken": status_counts.get("broken", 0),
        },
        "candidates": candidates,
    }


def _best_current_match(
    previous_element: UiElement,
    current_elements: dict[str, UiElement],
    current_by_selector: dict[str, UiElement],
    previous_pages: dict[str, Page],
    current_pages: dict[str, Page],
) -> dict[str, Any]:
    same_selector = current_by_selector.get(previous_element.selector_fingerprint)
    if same_selector:
        return _match_result(previous_element, same_selector, 1.0, "stable_selector")

    scored = []
    for current_element in current_elements.values():
        score, signals = _semantic_match_score(
            previous_element,
            current_element,
            previous_pages.get(previous_element.page_id),
            current_pages.get(current_element.page_id),
        )
        if score > 0:
            scored.append((score, signals, current_element))
    if not scored:
        return _missing_result(previous_element)
    score, signals, current_element = max(scored, key=lambda item: (item[0], item[2].id))
    status = "reuse_candidate" if score >= 0.75 else "review_required" if score >= 0.50 else "broken"
    return _match_result(previous_element, current_element, score, status, signals)


def _semantic_match_score(
    previous_element: UiElement,
    current_element: UiElement,
    previous_page: Page | None,
    current_page: Page | None,
) -> tuple[float, dict[str, Any]]:
    score = 0.0
    signals: dict[str, Any] = {}
    if normalize_term(previous_element.label) and normalize_term(previous_element.label) == normalize_term(current_element.label):
        score += 0.38
        signals["label"] = "exact"
    elif _tokens(previous_element.label) & _tokens(current_element.label):
        score += 0.18
        signals["label"] = "token_overlap"

    if normalize_term(previous_element.control_type) == normalize_term(current_element.control_type):
        score += 0.22
        signals["control_type"] = "exact"

    previous_state = state_path(previous_page) if previous_page else []
    current_state = state_path(current_page) if current_page else []
    if previous_state and previous_state == current_state:
        score += 0.24
        signals["state_path"] = previous_state
    elif previous_page and current_page and previous_page.url.split("#", 1)[0] == current_page.url.split("#", 1)[0]:
        score += 0.12
        signals["url_family"] = "same_base_url"

    previous_box = visual_box(previous_element.context)
    current_box = visual_box(current_element.context)
    if previous_box and current_box:
        visual_score = _visual_similarity(previous_box, current_box)
        score += visual_score * 0.16
        signals["visual_similarity"] = round(visual_score, 3)

    return round(min(1.0, score), 3), signals


def _visual_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    left_center = (left["x"] + left["width"] / 2, left["y"] + left["height"] / 2)
    right_center = (right["x"] + right["width"] / 2, right["y"] + right["height"] / 2)
    distance = abs(left_center[0] - right_center[0]) + abs(left_center[1] - right_center[1])
    size = max(1.0, left["width"] + left["height"] + right["width"] + right["height"])
    return max(0.0, 1.0 - distance / size)


def _binding_status(field_matches: list[dict[str, Any]]) -> str:
    if not field_matches:
        return "review_required"
    statuses = {match.get("status") for match in field_matches}
    if statuses <= {"stable"}:
        return "stable"
    if "broken" in statuses or "missing_previous_evidence" in statuses:
        return "broken"
    if "review_required" in statuses:
        return "review_required"
    return "reuse_candidate"


def _binding_confidence(field_matches: list[dict[str, Any]]) -> float:
    if not field_matches:
        return 0.0
    return round(sum(float(match.get("score", 0.0)) for match in field_matches) / len(field_matches), 3)


def _match_result(
    previous_element: UiElement,
    current_element: UiElement,
    score: float,
    status: str,
    signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "previous_element_id": previous_element.id,
        "current_element_id": current_element.id,
        "previous_selector": previous_element.selector_fingerprint,
        "current_selector": current_element.selector_fingerprint,
        "label": current_element.label,
        "control_type": current_element.control_type,
        "status": "stable" if status == "stable_selector" else status,
        "score": round(score, 3),
        "signals": signals or {"selector": "unchanged"},
    }


def _missing_result(previous_element: UiElement) -> dict[str, Any]:
    return {
        "previous_element_id": previous_element.id,
        "previous_selector": previous_element.selector_fingerprint,
        "status": "broken",
        "score": 0.0,
        "signals": {"missing": "no semantic candidate found"},
    }


def _binding_element_ids(adapter: dict[str, Any]) -> list[str]:
    element_ids = []
    if adapter.get("ui_element_id"):
        element_ids.append(str(adapter["ui_element_id"]))
    element_ids.extend(str(value) for value in adapter.get("element_ids", []) if value)
    element_ids.extend(str(value) for value in adapter.get("source_field_ids", []) if value)
    for field in adapter.get("fields", []) or []:
        if isinstance(field, dict) and field.get("ui_element_id"):
            element_ids.append(str(field["ui_element_id"]))
    return _ordered_unique(element_ids)


def _iter_bindings(bindings: dict[str, Any] | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not bindings:
        return []
    if isinstance(bindings, dict):
        items = bindings.get("bindings", [])
        return [item for item in items if isinstance(item, dict)]
    return [item for item in bindings if isinstance(item, dict)]


def _binding_adapter(binding: dict[str, Any]) -> dict[str, Any]:
    adapter = _binding_value(binding, "selector_action_bindings", {})
    return adapter if isinstance(adapter, dict) else {}


def _binding_value(binding: dict[str, Any], key: str, default: Any = None) -> Any:
    return binding.get(key, default)


def _tokens(value: str) -> set[str]:
    return {part for part in normalize_term(value).split() if len(part) > 2}


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
