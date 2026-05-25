from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from site_agent.core.models import ConceptMapping, DomainTerm, Evidence, UiElement, confidence_band


def normalize_term(value: str) -> str:
    return " ".join(value.replace("_", " ").replace("-", " ").split()).strip().lower()


def slug(value: str) -> str:
    normalized = normalize_term(value)
    import re

    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


@dataclass
class AlignmentSuggestion:
    canonical_name: str
    confidence: float
    evidence_ids: list[str]
    reasoning_summary: str
    aliases: list[str]


@dataclass
class FieldClassification:
    ui_element_id: str
    semantic_type: str
    value_type: str
    confidence: float
    evidence_ids: list[str]
    reasoning_summary: str


@dataclass
class ActionIntent:
    ui_element_id: str
    intent: str
    risk_level: str
    confidence: float
    evidence_ids: list[str]
    reasoning_summary: str


@dataclass
class ConstraintConflict:
    kind: str
    severity: str
    summary: str
    evidence_ids: list[str]


@dataclass
class CrawlPriority:
    target: str
    reason: str
    expected_concepts: list[str]
    priority: float


@dataclass
class FlowGuidance:
    flow_id: str
    usage_summary: str
    confidence: float
    evidence_ids: list[str]
    reasoning_summary: str


@dataclass
class ProductResearchResult:
    product_name: str
    sources: list[dict[str, Any]]
    terms: list[dict[str, Any]]


class AiBackend(Protocol):
    def extract_terms(self, doc_snippets: list[dict[str, str]]) -> list[DomainTerm]:
        ...

    def align_element(
        self,
        element: UiElement,
        ontology: list[DomainTerm],
        evidence: list[Evidence],
    ) -> AlignmentSuggestion | None:
        ...

    def describe_tool(self, mapping: ConceptMapping, evidence: list[Evidence]) -> str | None:
        ...

    def classify_field(self, element: UiElement, evidence: list[Evidence]) -> FieldClassification | None:
        ...

    def normalize_action(self, element: UiElement, evidence: list[Evidence]) -> ActionIntent | None:
        ...

    def detect_conflicts(self, ontology: list[DomainTerm], evidence: list[Evidence]) -> list[ConstraintConflict]:
        ...

    def prioritize_crawl(self, unmapped_elements: list[UiElement], ontology: list[DomainTerm]) -> list[CrawlPriority]:
        ...

    def analyze_interaction_flows(self, flows: list[dict[str, Any]], docs: list[Evidence]) -> list[FlowGuidance]:
        ...

    def research_product_docs(self, product_hint: str, base_url: str | None = None, max_sources: int = 5) -> ProductResearchResult | None:
        ...


class NoopAiBackend:
    def extract_terms(self, doc_snippets: list[dict[str, str]]) -> list[DomainTerm]:
        return []

    def align_element(self, element: UiElement, ontology: list[DomainTerm], evidence: list[Evidence]) -> AlignmentSuggestion | None:
        return None

    def describe_tool(self, mapping: ConceptMapping, evidence: list[Evidence]) -> str | None:
        return None

    def classify_field(self, element: UiElement, evidence: list[Evidence]) -> FieldClassification | None:
        return None

    def normalize_action(self, element: UiElement, evidence: list[Evidence]) -> ActionIntent | None:
        return None

    def detect_conflicts(self, ontology: list[DomainTerm], evidence: list[Evidence]) -> list[ConstraintConflict]:
        return []

    def prioritize_crawl(self, unmapped_elements: list[UiElement], ontology: list[DomainTerm]) -> list[CrawlPriority]:
        return []

    def analyze_interaction_flows(self, flows: list[dict[str, Any]], docs: list[Evidence]) -> list[FlowGuidance]:
        return []

    def research_product_docs(self, product_hint: str, base_url: str | None = None, max_sources: int = 5) -> ProductResearchResult | None:
        return None


class FakeAiBackend(NoopAiBackend):
    """Deterministic test backend that behaves like a structured AI adapter."""

    def extract_terms(self, doc_snippets: list[dict[str, str]]) -> list[DomainTerm]:
        terms: dict[str, DomainTerm] = {}
        for snippet in doc_snippets:
            source = snippet["evidence_id"]
            for line in snippet["text"].splitlines():
                if not line.startswith("#"):
                    continue
                canonical = normalize_term(line.lstrip("#").strip())
                if len(canonical) < 3:
                    continue
                terms[f"term_{slug(canonical)}"] = DomainTerm(
                    id=f"term_{slug(canonical)}",
                    canonical_name=canonical,
                    aliases=[],
                    sources=[source],
                    confidence=0.8,
                )
        return list(terms.values())

    def align_element(self, element: UiElement, ontology: list[DomainTerm], evidence: list[Evidence]) -> AlignmentSuggestion | None:
        label = normalize_term(element.label)
        if label == "wan state":
            for term in ontology:
                if normalize_term(term.canonical_name) == "wan status":
                    doc_ids = [item.id for item in evidence if item.kind == "doc"]
                    return AlignmentSuggestion(
                        canonical_name=term.canonical_name,
                        confidence=0.88,
                        evidence_ids=[*element.evidence_ids, *(doc_ids[:1] or term.sources[:1])],
                        reasoning_summary="AI backend matched WAN state UI language to documented WAN status terminology.",
                        aliases=[element.label],
                    )
        return None

    def describe_tool(self, mapping: ConceptMapping, evidence: list[Evidence]) -> str | None:
        return f"Read {mapping.canonical_name} from the approved evidence-backed schema."

    def classify_field(self, element: UiElement, evidence: list[Evidence]) -> FieldClassification | None:
        label = normalize_term(element.label)
        if "email" in label:
            return FieldClassification(element.id, "email_address", "string", 0.9, element.evidence_ids, "AI classified email-like field from label evidence.")
        if "days" in label or element.control_type == "number":
            return FieldClassification(element.id, "duration_days", "integer", 0.85, element.evidence_ids, "AI classified numeric day field from label/control evidence.")
        return None

    def normalize_action(self, element: UiElement, evidence: list[Evidence]) -> ActionIntent | None:
        label = normalize_term(element.label)
        if element.control_type in {"submit", "button"}:
            risk = "medium" if any(word in label for word in ["save", "send", "apply", "export"]) else "low"
            intent = label.replace(" ", "_") or "activate"
            return ActionIntent(element.id, intent, risk, 0.86, element.evidence_ids, "AI normalized button label to action intent.")
        return None

    def detect_conflicts(self, ontology: list[DomainTerm], evidence: list[Evidence]) -> list[ConstraintConflict]:
        seen: dict[str, DomainTerm] = {}
        conflicts: list[ConstraintConflict] = []
        for term in ontology:
            key = normalize_term(term.canonical_name)
            if key in seen and set(seen[key].constraints) != set(term.constraints):
                conflicts.append(
                    ConstraintConflict(
                        kind="constraint_conflict",
                        severity="warning",
                        summary=f"Conflicting constraints found for {key}.",
                        evidence_ids=[*seen[key].sources, *term.sources],
                    )
                )
            seen[key] = term
        return conflicts

    def prioritize_crawl(self, unmapped_elements: list[UiElement], ontology: list[DomainTerm]) -> list[CrawlPriority]:
        if not unmapped_elements:
            return []
        labels = [element.label for element in unmapped_elements[:5]]
        return [
            CrawlPriority(
                target="review_unmapped_controls",
                reason=f"{len(unmapped_elements)} unmapped controls remain, starting with: {', '.join(labels)}",
                expected_concepts=[term.canonical_name for term in ontology[:5]],
                priority=0.75,
            )
        ]

    def analyze_interaction_flows(self, flows: list[dict[str, Any]], docs: list[Evidence]) -> list[FlowGuidance]:
        return [
            FlowGuidance(
                flow_id=flow.get("id", ""),
                usage_summary=f"Open '{flow.get('trigger_label')}', fill newly visible fields, then cancel/apply according to risk policy.",
                confidence=0.75,
                evidence_ids=flow.get("evidence_ids", []),
                reasoning_summary="Fake backend summarized observed dynamic form flow.",
            )
            for flow in flows
        ]

    def research_product_docs(self, product_hint: str, base_url: str | None = None, max_sources: int = 5) -> ProductResearchResult | None:
        return ProductResearchResult(
            product_name=product_hint,
            sources=[
                {
                    "title": f"{product_hint} user guide",
                    "url": "https://example.com/manual",
                    "source_type": "manual",
                    "summary": "Fake backend manual source for tests.",
                    "confidence": 0.8,
                }
            ][:max_sources],
            terms=[
                {
                    "canonical_name": "wan status",
                    "aliases": ["wan state"],
                    "constraints": [],
                    "units": [],
                    "source_urls": ["https://example.com/manual"],
                    "summary": "WAN status indicates external connectivity.",
                    "confidence": 0.8,
                }
            ],
        )


class OpenAiResponsesBackend(NoopAiBackend):
    def __init__(self, api_key: str, model: str = "gpt-5-mini", base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = float(os.environ.get("SITE_AGENT_AI_TIMEOUT", "30"))
        self.alignment_budget = int(os.environ.get("SITE_AGENT_AI_ALIGNMENT_BUDGET", "8"))
        self._alignment_calls = 0

    def _request_json(self, instructions: str, input_text: str, schema_name: str, schema: dict[str, Any], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": input_text,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI Responses API request failed: {exc.code} {detail}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            raise RuntimeError(f"OpenAI Responses API request failed: {exc}") from exc
        text = raw.get("output_text")
        if not text:
            chunks = []
            for item in raw.get("output", []):
                for content in item.get("content", []):
                    if "text" in content:
                        chunks.append(content["text"])
            text = "".join(chunks)
        return json.loads(text or "{}")

    def extract_terms(self, doc_snippets: list[dict[str, str]]) -> list[DomainTerm]:
        if not doc_snippets:
            return []
        result = self._request_json(
            instructions=(
                "Extract only evidence-supported domain terms. Do not infer target-specific behavior. "
                "Return concise canonical names, aliases, constraints, units, confidence, and evidence IDs."
            ),
            input_text=json.dumps(doc_snippets, sort_keys=True),
            schema_name="ontology_terms",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "terms": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "canonical_name": {"type": "string"},
                                "aliases": {"type": "array", "items": {"type": "string"}},
                                "units": {"type": "array", "items": {"type": "string"}},
                                "constraints": {"type": "array", "items": {"type": "string"}},
                                "confidence": {"type": "number"},
                                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["canonical_name", "aliases", "units", "constraints", "confidence", "evidence_ids"],
                        },
                    }
                },
                "required": ["terms"],
            },
        )
        terms = []
        for item in result.get("terms", []):
            canonical = normalize_term(item["canonical_name"])
            terms.append(
                DomainTerm(
                    id=f"term_{slug(canonical)}",
                    canonical_name=canonical,
                    aliases=item.get("aliases", []),
                    units=item.get("units", []),
                    constraints=item.get("constraints", []),
                    sources=item.get("evidence_ids", []),
                    confidence=float(item.get("confidence", 0.0)),
                )
            )
        return terms

    def align_element(self, element: UiElement, ontology: list[DomainTerm], evidence: list[Evidence]) -> AlignmentSuggestion | None:
        if self._alignment_calls >= self.alignment_budget:
            return None
        self._alignment_calls += 1
        evidence_by_id = {item.id: item for item in evidence}
        relevant = [evidence_by_id[eid] for eid in element.evidence_ids if eid in evidence_by_id]
        if not relevant or not ontology:
            return None
        result = self._request_json(
            instructions=(
                "Map a UI element to a documented ontology term only when evidence supports it. "
                "If confidence is below 0.60, return matched=false."
            ),
            input_text=json.dumps(
                {
                    "ui_element": {"id": element.id, "label": element.label, "control_type": element.control_type, "context": element.context},
                    "ontology": [
                        {"id": term.id, "canonical_name": term.canonical_name, "aliases": term.aliases, "sources": term.sources}
                        for term in ontology
                    ],
                    "evidence": [{"id": item.id, "summary": item.summary, "source": item.source} for item in relevant],
                },
                sort_keys=True,
            ),
            schema_name="concept_mapping",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "matched": {"type": "boolean"},
                    "canonical_name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "reasoning_summary": {"type": "string"},
                },
                "required": ["matched", "canonical_name", "aliases", "confidence", "evidence_ids", "reasoning_summary"],
            },
        )
        if not result.get("matched"):
            return None
        evidence_ids = [eid for eid in result.get("evidence_ids", []) if eid in {item.id for item in evidence}]
        if not evidence_ids:
            return None
        return AlignmentSuggestion(
            canonical_name=normalize_term(result["canonical_name"]),
            confidence=float(result.get("confidence", 0.0)),
            evidence_ids=evidence_ids,
            reasoning_summary=result.get("reasoning_summary", "AI-assisted evidence-backed mapping."),
            aliases=result.get("aliases", [element.label]),
        )

    def describe_tool(self, mapping: ConceptMapping, evidence: list[Evidence]) -> str | None:
        result = self._request_json(
            instructions="Write one concise human-readable MCP tool description grounded only in supplied evidence.",
            input_text=json.dumps(
                {
                    "canonical_name": mapping.canonical_name,
                    "confidence": mapping.confidence,
                    "evidence": [{"id": item.id, "summary": item.summary} for item in evidence if item.id in mapping.evidence_ids],
                },
                sort_keys=True,
            ),
            schema_name="tool_description",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"description": {"type": "string"}},
                "required": ["description"],
            },
        )
        return result.get("description")

    def classify_field(self, element: UiElement, evidence: list[Evidence]) -> FieldClassification | None:
        result = self._request_json(
            instructions="Classify the UI field type using only supplied UI evidence. Return matched=false if evidence is insufficient.",
            input_text=json.dumps(
                {
                    "ui_element": {"id": element.id, "label": element.label, "control_type": element.control_type, "context": element.context},
                    "evidence": [{"id": item.id, "summary": item.summary} for item in evidence if item.id in element.evidence_ids],
                },
                sort_keys=True,
            ),
            schema_name="field_classification",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "matched": {"type": "boolean"},
                    "semantic_type": {"type": "string"},
                    "value_type": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "reasoning_summary": {"type": "string"},
                },
                "required": ["matched", "semantic_type", "value_type", "confidence", "evidence_ids", "reasoning_summary"],
            },
        )
        if not result.get("matched"):
            return None
        evidence_ids = [eid for eid in result.get("evidence_ids", []) if eid in set(element.evidence_ids)]
        if not evidence_ids:
            return None
        return FieldClassification(
            ui_element_id=element.id,
            semantic_type=normalize_term(result["semantic_type"]).replace(" ", "_"),
            value_type=normalize_term(result["value_type"]).replace(" ", "_"),
            confidence=float(result.get("confidence", 0.0)),
            evidence_ids=evidence_ids,
            reasoning_summary=result.get("reasoning_summary", "AI-assisted field classification."),
        )

    def normalize_action(self, element: UiElement, evidence: list[Evidence]) -> ActionIntent | None:
        if element.control_type not in {"submit", "button"}:
            return None
        result = self._request_json(
            instructions=(
                "Normalize a UI action intent from button evidence. Classify risk as low, medium, or high. "
                "High risk means destructive, connectivity-impacting, or hard-to-reverse."
            ),
            input_text=json.dumps(
                {
                    "ui_element": {"id": element.id, "label": element.label, "control_type": element.control_type, "context": element.context},
                    "evidence": [{"id": item.id, "summary": item.summary} for item in evidence if item.id in element.evidence_ids],
                },
                sort_keys=True,
            ),
            schema_name="action_intent",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "matched": {"type": "boolean"},
                    "intent": {"type": "string"},
                    "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                    "confidence": {"type": "number"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "reasoning_summary": {"type": "string"},
                },
                "required": ["matched", "intent", "risk_level", "confidence", "evidence_ids", "reasoning_summary"],
            },
        )
        if not result.get("matched"):
            return None
        evidence_ids = [eid for eid in result.get("evidence_ids", []) if eid in set(element.evidence_ids)]
        if not evidence_ids:
            return None
        return ActionIntent(
            ui_element_id=element.id,
            intent=normalize_term(result["intent"]).replace(" ", "_"),
            risk_level=result["risk_level"],
            confidence=float(result.get("confidence", 0.0)),
            evidence_ids=evidence_ids,
            reasoning_summary=result.get("reasoning_summary", "AI-assisted action normalization."),
        )

    def detect_conflicts(self, ontology: list[DomainTerm], evidence: list[Evidence]) -> list[ConstraintConflict]:
        if not ontology:
            return []
        result = self._request_json(
            instructions="Detect only evidence-backed terminology, unit, or constraint conflicts in the ontology.",
            input_text=json.dumps(
                {
                    "ontology": [
                        {
                            "id": term.id,
                            "canonical_name": term.canonical_name,
                            "aliases": term.aliases,
                            "units": term.units,
                            "constraints": term.constraints,
                            "sources": term.sources,
                        }
                        for term in ontology
                    ],
                    "evidence_ids": [item.id for item in evidence],
                },
                sort_keys=True,
            ),
            schema_name="constraint_conflicts",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "conflicts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "kind": {"type": "string"},
                                "severity": {"type": "string", "enum": ["info", "warning", "error"]},
                                "summary": {"type": "string"},
                                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["kind", "severity", "summary", "evidence_ids"],
                        },
                    }
                },
                "required": ["conflicts"],
            },
        )
        valid_ids = {item.id for item in evidence}
        return [
            ConstraintConflict(
                kind=item["kind"],
                severity=item["severity"],
                summary=item["summary"],
                evidence_ids=[eid for eid in item.get("evidence_ids", []) if eid in valid_ids],
            )
            for item in result.get("conflicts", [])
        ]

    def prioritize_crawl(self, unmapped_elements: list[UiElement], ontology: list[DomainTerm]) -> list[CrawlPriority]:
        if not unmapped_elements:
            return []
        result = self._request_json(
            instructions="Prioritize follow-up crawl or review targets based on unmapped UI elements and missing ontology concepts.",
            input_text=json.dumps(
                {
                    "unmapped_elements": [
                        {"id": element.id, "label": element.label, "control_type": element.control_type, "context": element.context}
                        for element in unmapped_elements[:40]
                    ],
                    "ontology": [term.canonical_name for term in ontology[:80]],
                },
                sort_keys=True,
            ),
            schema_name="crawl_priorities",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "priorities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "target": {"type": "string"},
                                "reason": {"type": "string"},
                                "expected_concepts": {"type": "array", "items": {"type": "string"}},
                                "priority": {"type": "number"},
                            },
                            "required": ["target", "reason", "expected_concepts", "priority"],
                        },
                    }
                },
                "required": ["priorities"],
            },
        )
        return [
            CrawlPriority(
                target=item["target"],
                reason=item["reason"],
                expected_concepts=item.get("expected_concepts", []),
                priority=float(item.get("priority", 0.0)),
            )
            for item in result.get("priorities", [])
        ]

    def research_product_docs(self, product_hint: str, base_url: str | None = None, max_sources: int = 5) -> ProductResearchResult | None:
        result = self._request_json(
            instructions=(
                "Research official or highly trusted product documentation for a web-admin UI target. "
                "Prioritize owner guides, user manuals, admin guides, quick-start guides, and vendor support pages. "
                "Extract jargon-correct domain terms that can help name MCP tools. Do not invent sources."
            ),
            input_text=json.dumps({"product_hint": product_hint, "base_url": base_url, "max_sources": max_sources}, sort_keys=True),
            schema_name="product_doc_research",
            schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "product_name": {"type": "string"},
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                                "source_type": {"type": "string"},
                                "summary": {"type": "string"},
                                "confidence": {"type": "number"},
                            },
                            "required": ["title", "url", "source_type", "summary", "confidence"],
                        },
                    },
                    "terms": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "canonical_name": {"type": "string"},
                                "aliases": {"type": "array", "items": {"type": "string"}},
                                "constraints": {"type": "array", "items": {"type": "string"}},
                                "units": {"type": "array", "items": {"type": "string"}},
                                "source_urls": {"type": "array", "items": {"type": "string"}},
                                "summary": {"type": "string"},
                                "confidence": {"type": "number"},
                            },
                            "required": ["canonical_name", "aliases", "constraints", "units", "source_urls", "summary", "confidence"],
                        },
                    },
                },
                "required": ["product_name", "sources", "terms"],
            },
            tools=[{"type": "web_search"}],
        )
        return ProductResearchResult(
            product_name=result.get("product_name", product_hint),
            sources=result.get("sources", [])[:max_sources],
            terms=result.get("terms", []),
        )


def get_ai_backend() -> AiBackend:
    provider = os.environ.get("SITE_AGENT_AI_PROVIDER", "").strip().lower()
    if provider in {"", "none", "off", "deterministic"}:
        return NoopAiBackend()
    if provider == "fake":
        return FakeAiBackend()
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("SITE_AGENT_AI_PROVIDER=openai requires OPENAI_API_KEY.")
        return OpenAiResponsesBackend(api_key=api_key, model=os.environ.get("SITE_AGENT_AI_MODEL", "gpt-5-mini"))
    raise RuntimeError(f"Unknown SITE_AGENT_AI_PROVIDER: {provider}")
