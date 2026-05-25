from __future__ import annotations

from dataclasses import asdict

from site_agent.core.ai.backends import AiBackend
from site_agent.core.models import CrawlSnapshot, MappedSchema


def build_ai_analysis_report(
    snapshot: CrawlSnapshot,
    schema: MappedSchema,
    ai_backend: AiBackend,
    max_elements: int = 40,
) -> dict:
    evidence = schema.evidence
    mapping_by_element = {mapping.ui_element_id: mapping for mapping in schema.mappings}
    unmapped = [element for element in snapshot.elements if mapping_by_element.get(element.id) and mapping_by_element[element.id].status != "ready"]
    candidates = snapshot.elements[:max_elements]

    field_classifications = []
    action_intents = []
    for element in candidates:
        classification = ai_backend.classify_field(element, evidence)
        if classification and classification.evidence_ids:
            field_classifications.append(asdict(classification))
        action = ai_backend.normalize_action(element, evidence)
        if action and action.evidence_ids:
            action_intents.append(asdict(action))

    conflicts = [asdict(item) for item in ai_backend.detect_conflicts(schema.ontology, evidence)]
    priorities = [asdict(item) for item in ai_backend.prioritize_crawl(unmapped[:max_elements], schema.ontology)]
    flow_guidance = [asdict(item) for item in ai_backend.analyze_interaction_flows([asdict(flow) for flow in snapshot.interaction_flows], evidence)]
    return {
        "run_id": schema.run_id,
        "profile_id": schema.profile_id,
        "field_classifications": field_classifications,
        "action_intents": action_intents,
        "conflicts": conflicts,
        "crawl_priorities": priorities,
        "interaction_flow_guidance": flow_guidance,
        "limits": {"max_elements": max_elements},
    }
