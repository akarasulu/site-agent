from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from math import log1p
from typing import Any

from site_agent.core.debug import state_path
from site_agent.core.ingest.docs import normalize_term
from site_agent.core.models import CrawlSnapshot, UiElement


FIELD_TYPES = {"text", "number", "email", "password", "select", "checkbox", "radio", "textarea", "hidden"}
ACTION_TYPES = {"button", "submit"}
CONTENT_TYPES = {"heading", "section_heading"}


def title_label(value: str) -> str:
    return " ".join(part.capitalize() for part in normalize_term(value).split())


def visual_box(context: dict[str, Any]) -> dict[str, float] | None:
    raw = context.get("visual_bbox") or context.get("bbox") or context.get("rect")
    if not isinstance(raw, dict):
        return None
    try:
        return {
            "x": round(float(raw.get("x", 0.0)), 2),
            "y": round(float(raw.get("y", 0.0)), 2),
            "width": round(float(raw.get("width", 0.0)), 2),
            "height": round(float(raw.get("height", 0.0)), 2),
        }
    except (TypeError, ValueError):
        return None


def element_role(element: UiElement) -> str:
    control_type = normalize_term(element.control_type)
    context = element.context
    aria_role = normalize_term(str(context.get("accessibility_role") or context.get("role") or ""))
    if control_type in FIELD_TYPES:
        return "field"
    if control_type in ACTION_TYPES or aria_role == "button":
        return "action"
    if control_type == "readonly_status" or "read_value" in context:
        return "data_value"
    if control_type in CONTENT_TYPES:
        return "content_heading"
    if aria_role in {"tab", "menuitem", "link", "treeitem"} or context.get("candidate_label"):
        return "navigation"
    return "unknown"


def element_features(element: UiElement) -> dict[str, Any]:
    context = element.context
    bbox = visual_box(context)
    return {
        "label": element.label,
        "control_type": element.control_type,
        "semantic_role": element_role(element),
        "text_length": len(element.label or ""),
        "has_current_value": "read_value" in context,
        "visible": context.get("visible"),
        "bbox": bbox,
        "dom": {
            "tag": context.get("dom_tag") or context.get("tag"),
            "id": context.get("selector_id"),
            "name": context.get("selector_name"),
        },
        "accessibility": {
            "role": context.get("accessibility_role") or context.get("role"),
            "name": context.get("accessibility_name") or context.get("aria_label"),
        },
        "style": context.get("computed_style") or {},
        "evidence_ids": list(element.evidence_ids),
    }


def visual_block_groups(snapshot: CrawlSnapshot, vertical_gap: float = 16.0) -> list[dict[str, Any]]:
    elements_by_page = defaultdict(list)
    for element in snapshot.elements:
        elements_by_page[element.page_id].append(element)

    blocks: list[dict[str, Any]] = []
    for page in snapshot.pages:
        candidates = [
            (element, visual_box(element.context))
            for element in elements_by_page.get(page.id, [])
        ]
        visual_elements = [
            (element, box)
            for element, box in candidates
            if box and box["width"] > 0 and box["height"] > 0
        ]
        visual_elements.sort(key=lambda item: (item[1]["y"], item[1]["x"]))  # type: ignore[index]
        rows: list[list[tuple[UiElement, dict[str, float]]]] = []
        current: list[tuple[UiElement, dict[str, float]]] = []
        for element, box in visual_elements:
            if not current:
                current = [(element, box)]
                continue
            current_box = _union_box([item_box for _, item_box in current])
            if _same_visual_band(current_box, box, vertical_gap):
                current.append((element, box))
            else:
                rows.append(current)
                current = [(element, box)]
        if current:
            rows.append(current)

        page_blocks = [_visual_block(page.id, index, row) for index, row in enumerate(rows, start=1)]
        signature_counts = Counter(block["pattern_signature"] for block in page_blocks)
        for block in page_blocks:
            block["repeated_candidate"] = signature_counts[block["pattern_signature"]] > 1
        blocks.extend(page_blocks)
    return blocks


def build_page_graph(snapshot: CrawlSnapshot) -> dict[str, Any]:
    forms_by_page = defaultdict(list)
    for form in snapshot.forms:
        forms_by_page[form.page_id].append(form)
    element_by_id = {element.id: element for element in snapshot.elements}
    elements_by_page = defaultdict(list)
    field_to_form: dict[str, str] = {}
    for form in snapshot.forms:
        for field_id in form.field_ids:
            field_to_form[field_id] = form.id
    for element in snapshot.elements:
        elements_by_page[element.page_id].append(element)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    visual_blocks = visual_block_groups(snapshot)
    block_ids_by_element = defaultdict(list)
    for block in visual_blocks:
        for element_id in block["element_ids"]:
            block_ids_by_element[element_id].append(block["id"])
    role_counts = Counter()
    visual_nodes = 0
    current_value_nodes = 0

    for page in snapshot.pages:
        page_elements = elements_by_page.get(page.id, [])
        nodes.append(
            {
                "id": page.id,
                "kind": "page",
                "label": " > ".join(title_label(part) for part in state_path(page)) or page.title or page.url,
                "features": {
                    "url": page.url,
                    "title": page.title,
                    "headings": page.headings[:8],
                    "state_path": state_path(page),
                    "forms": len(forms_by_page.get(page.id, [])),
                    "elements": len(page_elements),
                },
            }
        )
        for form in forms_by_page.get(page.id, []):
            nodes.append(
                {
                    "id": form.id,
                    "kind": "form",
                    "label": form.label,
                    "page_id": form.page_id,
                    "features": {
                        "action": form.action,
                        "method": form.method,
                        "fields": len(form.field_ids),
                    },
                }
            )
            edges.append({"source": page.id, "target": form.id, "relationship": "page_contains_form"})
        for element in page_elements:
            features = element_features(element)
            features["visual_block_ids"] = block_ids_by_element.get(element.id, [])
            role_counts[features["semantic_role"]] += 1
            visual_nodes += 1 if features["bbox"] else 0
            current_value_nodes += 1 if features["has_current_value"] else 0
            nodes.append(
                {
                    "id": element.id,
                    "kind": "element",
                    "label": element.label,
                    "page_id": element.page_id,
                    "features": features,
                }
            )
            form_id = field_to_form.get(element.id)
            if form_id:
                edges.append({"source": form_id, "target": element.id, "relationship": "form_contains_element"})
            else:
                edges.append({"source": page.id, "target": element.id, "relationship": "page_contains_element"})

        visual_elements = [element for element in page_elements if visual_box(element.context)]
        visual_elements.sort(key=lambda item: (visual_box(item.context)["y"], visual_box(item.context)["x"]))  # type: ignore[index]
        for left, right in zip(visual_elements, visual_elements[1:]):
            edges.append({"source": left.id, "target": right.id, "relationship": "visual_next"})

    return {
        "run_id": snapshot.run_id,
        "profile_id": snapshot.profile_id,
        "summary": {
            "nodes": len(nodes),
            "edges": len(edges),
            "pages": len(snapshot.pages),
            "forms": len(snapshot.forms),
            "elements": len(snapshot.elements),
            "role_counts": dict(role_counts),
            "visual_nodes": visual_nodes,
            "current_value_nodes": current_value_nodes,
            "visual_blocks": len(visual_blocks),
            "repeated_visual_blocks": sum(1 for block in visual_blocks if block["repeated_candidate"]),
        },
        "visual_blocks": visual_blocks,
        "nodes": nodes,
        "edges": edges,
    }


def _visual_block(page_id: str, index: int, row: list[tuple[UiElement, dict[str, float]]]) -> dict[str, Any]:
    sorted_row = sorted(row, key=lambda item: item[1]["x"])
    elements = [element for element, _ in sorted_row]
    boxes = [box for _, box in sorted_row]
    roles = [element_role(element) for element in elements]
    control_families = [_control_family(element) for element in elements]
    dom_tags = [
        normalize_term(str(element.context.get("dom_tag") or element.context.get("tag") or ""))
        for element in elements
    ]
    signature_payload = {
        "roles": roles,
        "control_families": control_families,
        "dom_tags": dom_tags,
    }
    block_box = _union_box(boxes)
    return {
        "id": f"vblock_{page_id}_{index}",
        "page_id": page_id,
        "element_ids": [element.id for element in elements],
        "labels": [element.label for element in elements if element.label],
        "bbox": block_box,
        "semantic_roles": dict(sorted(Counter(roles).items())),
        "pattern_signature": f"vpat_{_digest_json(signature_payload)[:12]}",
        "repeated_candidate": False,
    }


def _same_visual_band(left: dict[str, float], right: dict[str, float], vertical_gap: float) -> bool:
    overlap = _vertical_overlap_ratio(left, right)
    if overlap >= 0.25:
        return True
    left_bottom = left["y"] + left["height"]
    gap = right["y"] - left_bottom
    return gap >= 0 and gap < vertical_gap


def _vertical_overlap_ratio(left: dict[str, float], right: dict[str, float]) -> float:
    top = max(left["y"], right["y"])
    bottom = min(left["y"] + left["height"], right["y"] + right["height"])
    overlap = max(0.0, bottom - top)
    shortest = max(1.0, min(left["height"], right["height"]))
    return overlap / shortest


def _union_box(boxes: list[dict[str, float]]) -> dict[str, float]:
    min_x = min(box["x"] for box in boxes)
    min_y = min(box["y"] for box in boxes)
    max_x = max(box["x"] + box["width"] for box in boxes)
    max_y = max(box["y"] + box["height"] for box in boxes)
    return {
        "x": round(min_x, 2),
        "y": round(min_y, 2),
        "width": round(max_x - min_x, 2),
        "height": round(max_y - min_y, 2),
    }


def _control_family(element: UiElement) -> str:
    role = element_role(element)
    if role in {"field", "action", "data_value", "navigation"}:
        return role
    return normalize_term(element.control_type)


def _digest_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def coverage_preservation_labels(snapshot: CrawlSnapshot, limit: int = 40) -> list[dict[str, Any]]:
    forms_by_page = Counter(form.page_id for form in snapshot.forms)
    elements_by_page = defaultdict(list)
    for element in snapshot.elements:
        elements_by_page[element.page_id].append(element)

    candidates: dict[str, dict[str, Any]] = {}
    for page in snapshot.pages:
        elements = elements_by_page.get(page.id, [])
        path = state_path(page)
        if path:
            labels = [title_label(part) for part in path]
            labels.append(" > ".join(labels))
        else:
            labels = [heading for heading in page.headings[:2] if heading] or [page.title or page.url]
        field_count = sum(1 for element in elements if normalize_term(element.control_type) in FIELD_TYPES)
        value_count = sum(1 for element in elements if "read_value" in element.context)
        action_count = sum(1 for element in elements if normalize_term(element.control_type) in ACTION_TYPES)
        status_count = sum(1 for element in elements if element_role(element) == "data_value")
        score = 0.25
        score += min(0.2, log1p(len(elements)) / 25)
        score += min(0.2, forms_by_page[page.id] * 0.04)
        score += min(0.2, value_count * 0.02)
        score += min(0.1, field_count * 0.01)
        score += min(0.05, action_count * 0.01)
        score += min(0.05, status_count * 0.01)
        score = round(min(0.86, score), 3)
        signals = {
            "forms": forms_by_page[page.id],
            "elements": len(elements),
            "fields": field_count,
            "current_values": value_count,
            "actions": action_count,
            "status_values": status_count,
        }
        for label in labels:
            clean = " ".join(str(label).split()).strip()
            key = normalize_term(clean)
            if not clean or not key:
                continue
            existing = candidates.get(key)
            item = {
                "label": clean,
                "score": score,
                "path": labels[-1] if path else clean,
                "state_path": path,
                "signals": signals,
                "reason": "Preserve a previously discovered high-value UI state while targeting missing concepts.",
            }
            if existing is None or score > existing["score"]:
                candidates[key] = item

    return sorted(candidates.values(), key=lambda item: (-item["score"], item["label"]))[:limit]
