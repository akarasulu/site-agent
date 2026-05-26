from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4


RiskLevel = Literal["low", "medium", "high"]
ConfidenceBand = Literal["stable", "experimental", "internal"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {k: to_jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    return value


def confidence_band(confidence: float) -> ConfidenceBand:
    if confidence >= 0.85:
        return "stable"
    if confidence >= 0.60:
        return "experimental"
    return "internal"


@dataclass
class Evidence:
    id: str
    kind: Literal["ui", "doc", "review", "system"]
    source: str
    summary: str
    locator: str | None = None
    created_at: str = field(default_factory=utc_now)


@dataclass
class DomainTerm:
    id: str
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    units: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class UiElement:
    id: str
    page_id: str
    selector_fingerprint: str
    label: str
    control_type: str
    context: dict[str, Any] = field(default_factory=dict)
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class Page:
    id: str
    url: str
    title: str = ""
    headings: list[str] = field(default_factory=list)


@dataclass
class Form:
    id: str
    page_id: str
    label: str
    action: str | None = None
    method: str | None = None
    field_ids: list[str] = field(default_factory=list)


@dataclass
class Transition:
    source_page_id: str
    target_url: str
    trigger_label: str
    risk_level: RiskLevel = "low"


@dataclass
class InteractionFlow:
    id: str
    page_id: str
    trigger_label: str
    flow_type: str
    discovered_field_ids: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    cancel_supported: bool = False
    requires_open_before_submit: bool = False
    evidence_ids: list[str] = field(default_factory=list)
    reasoning_summary: str = ""


@dataclass
class CrawlSnapshot:
    timestamp: str
    profile_id: str
    run_id: str
    pages: list[Page] = field(default_factory=list)
    forms: list[Form] = field(default_factory=list)
    elements: list[UiElement] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    interaction_flows: list[InteractionFlow] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class ConceptMapping:
    ui_element_id: str
    domain_term_id: str | None
    canonical_name: str
    aliases_seen: list[str]
    confidence: float
    evidence_ids: list[str]
    status: Literal["ready", "review", "internal"]
    reasoning_summary: str


@dataclass
class MappedSchema:
    profile_id: str
    run_id: str
    generated_at: str
    ontology: list[DomainTerm]
    mappings: list[ConceptMapping]
    evidence: list[Evidence]


@dataclass
class ToolSpec:
    name: str
    description: str
    args: dict[str, Any]
    return_schema: dict[str, Any]
    risk_level: RiskLevel
    evidence_ids: list[str]
    confidence: float
    version: str = "0.1.0"
    requires_confirmation: bool = False
    dry_run_supported: bool = True
    exposure_level: Literal["ready_public", "review_required", "internal_disabled"] = "ready_public"
    source_type: Literal["canonical_concept", "ui_page", "ui_form", "ui_flow"] = "canonical_concept"
    reasoning_summary: str = ""
    compatibility_aliases: list[str] = field(default_factory=list)


@dataclass
class AdapterBinding:
    tool_name: str
    profile_id: str
    version: str
    selector_action_bindings: dict[str, Any]


@dataclass
class PythonApiMethod:
    name: str
    description: str
    args: dict[str, Any]
    return_schema: dict[str, Any]
    risk_level: RiskLevel
    dry_run_supported: bool
    evidence_ids: list[str]
    backing_tool: str


@dataclass
class PythonApiSpec:
    package_name: str
    version: str
    methods: list[PythonApiMethod]
    evidence_ids: list[str]
    adapter_version: str = "0.1.0"


@dataclass
class AnsibleModuleSpec:
    name: str
    description: str
    options: dict[str, Any]
    supports_check_mode: bool
    idempotence_level: Literal["full", "partial", "none"]
    risk_level: RiskLevel
    evidence_ids: list[str]
    backing_python_method: str


@dataclass
class AnsibleCollectionSpec:
    namespace: str
    name: str
    version: str
    modules: list[AnsibleModuleSpec]
    evidence_ids: list[str]
    python_api_dependency: str


@dataclass
class DriftFinding:
    kind: str
    severity: Literal["info", "warning", "error"]
    summary: str
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class DriftReport:
    profile_id: str
    run_id: str
    generated_at: str
    findings: list[DriftFinding]
