#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY_FILE="${OPENAI_API_KEY_FILE:-$ROOT/site-agent-openai.key}"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  if [[ ! -s "$KEY_FILE" ]]; then
    echo "Set OPENAI_API_KEY or provide a readable key file at $KEY_FILE." >&2
    exit 2
  fi
  export OPENAI_API_KEY="$(tr -d '\r\n' < "$KEY_FILE")"
fi
export SITE_AGENT_AI_PROVIDER=openai
export SITE_AGENT_AI_MODEL="${SITE_AGENT_AI_MODEL:-gpt-5-mini}"
export SITE_AGENT_AI_TIMEOUT="${SITE_AGENT_AI_TIMEOUT:-90}"
export SITE_AGENT_AI_ALIGNMENT_BUDGET="${SITE_AGENT_AI_ALIGNMENT_BUDGET:-2}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

"$ROOT/.venv/bin/python" - <<'PY'
from site_agent.core.ai.backends import get_ai_backend
from site_agent.core.models import ConceptMapping, DomainTerm, Evidence, UiElement

backend = get_ai_backend()
doc_ev = Evidence(id="ev_doc", kind="doc", source="manual.md", summary="WAN status indicates whether the router connection is connected.")
ui_ev = Evidence(id="ev_ui", kind="ui", source="fixture", summary="read-only status labelled 'WAN State'")
terms = backend.extract_terms([
    {
        "evidence_id": doc_ev.id,
        "source": doc_ev.source,
        "text": "# wan status\nWAN status indicates whether the router connection is connected or disconnected.",
    }
])
print({"term_count": len(terms), "terms": [term.canonical_name for term in terms]})
ontology = terms or [DomainTerm(id="term_wan_status", canonical_name="wan status", aliases=["WAN State"], sources=[doc_ev.id], confidence=0.9)]
element = UiElement(
    id="ui_1",
    page_id="page_1",
    selector_fingerprint="abc",
    label="WAN State",
    control_type="readonly_status",
    context={"read_value": "Connected"},
    evidence_ids=[ui_ev.id],
)
suggestion = backend.align_element(element, ontology, [doc_ev, ui_ev])
print({"alignment": None if suggestion is None else {"canonical_name": suggestion.canonical_name, "confidence": suggestion.confidence, "evidence_ids": suggestion.evidence_ids}})
mapping = ConceptMapping(
    ui_element_id=element.id,
    domain_term_id=ontology[0].id,
    canonical_name=ontology[0].canonical_name,
    aliases_seen=[element.label],
    confidence=0.9,
    evidence_ids=[doc_ev.id, ui_ev.id],
    status="ready",
    reasoning_summary="smoke test",
)
description = backend.describe_tool(mapping, [doc_ev, ui_ev])
print({"description": description})
classification = backend.classify_field(
    UiElement("ui_email", "page_1", "email", "Alert email", "email", {}, ["ev_ui"]),
    [ui_ev],
)
print({"classification": None if classification is None else {"semantic_type": classification.semantic_type, "value_type": classification.value_type, "confidence": classification.confidence}})
action = backend.normalize_action(
    UiElement("ui_save", "page_1", "save", "Save settings", "submit", {}, ["ev_ui"]),
    [ui_ev],
)
print({"action": None if action is None else {"intent": action.intent, "risk_level": action.risk_level, "confidence": action.confidence}})
conflicts = backend.detect_conflicts(ontology, [doc_ev, ui_ev])
print({"conflict_count": len(conflicts)})
priorities = backend.prioritize_crawl([element], ontology)
print({"priority_count": len(priorities)})
research = backend.research_product_docs("ZTE H3600 V9 router web UI user guide manual", "https://192.168.1.1", 3)
print({"research": None if research is None else {"product_name": research.product_name, "sources": len(research.sources), "terms": len(research.terms)}})
PY
