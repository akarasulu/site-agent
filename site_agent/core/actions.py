from __future__ import annotations

import re

from site_agent.core.models import CrawlSnapshot, Form, UiElement, utc_now


HIGH_RISK_WORDS = {"reset", "reboot", "restart", "restore", "factory", "delete", "remove", "upgrade", "firmware", "format"}
MEDIUM_RISK_WORDS = {"save", "apply", "submit", "send", "create", "update", "enable", "disable", "connect", "disconnect", "upload"}
LOW_RISK_WORDS = {"search", "filter", "refresh", "export", "download", "diagnose", "test", "ping"}


def normalize(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def classify_action_risk(label: str, field_labels: list[str]) -> tuple[str, str]:
    text = normalize(" ".join([label, *field_labels]))
    tokens = set(text.split())
    if tokens & HIGH_RISK_WORDS:
        return "high", "Action wording indicates destructive, firmware, reset, or restart behavior."
    if tokens & MEDIUM_RISK_WORDS:
        return "medium", "Action appears to change configuration or connectivity state."
    if tokens & LOW_RISK_WORDS:
        return "low", "Action appears diagnostic, export, search, or refresh oriented."
    return "medium", "Form submission has side effects unless proven read-only."


def form_action_inventory(snapshot: CrawlSnapshot) -> list[dict]:
    element_by_id = {element.id: element for element in snapshot.elements}
    inventory = []
    for form in snapshot.forms:
        fields = [element_by_id[field_id] for field_id in form.field_ids if field_id in element_by_id]
        buttons = [field for field in fields if field.control_type in {"submit", "button"}]
        label = next((button.label for button in buttons if button.label), form.label)
        editable = [field for field in fields if field.control_type not in {"submit", "button", "hidden"}]
        risk, reason = classify_action_risk(label, [field.label for field in fields])
        inventory.append(
            {
                "form_id": form.id,
                "label": form.label,
                "action_label": label,
                "method": form.method,
                "action": form.action,
                "risk_level": risk,
                "requires_confirmation": risk in {"medium", "high"},
                "dry_run_required": True,
                "reason": reason,
                "field_count": len(editable),
                "fields": [
                    {
                        "ui_element_id": field.id,
                        "label": field.label,
                        "control_type": field.control_type,
                        "evidence_ids": field.evidence_ids,
                    }
                    for field in editable
                ],
                "evidence_ids": [eid for field in fields for eid in field.evidence_ids],
            }
        )
    return inventory


def build_action_report(snapshot: CrawlSnapshot) -> dict:
    inventory = form_action_inventory(snapshot)
    counts = {"low": 0, "medium": 0, "high": 0}
    for item in inventory:
        counts[item["risk_level"]] += 1
    return {
        "run_id": snapshot.run_id,
        "profile_id": snapshot.profile_id,
        "generated_at": utc_now(),
        "summary": {"forms": len(inventory), "risk_counts": counts},
        "actions": inventory,
    }
