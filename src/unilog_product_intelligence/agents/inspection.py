"""Inspectable, evidence-aware projection of one agentic ProductTruth run."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.domain.truth import (
    ProductTruth,
    SourceAuthority,
    SourceStatus,
    SourceType,
    ValueStatus,
)

from .orchestration import AgentRun, ProductJob


class InspectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InspectionSource(InspectionModel):
    source_id: str
    source_url: str | None = None
    source_type: str
    authority: str
    status: str
    origin: str
    manufacturer_id: str | None = None
    retrieved_at: datetime | None = None
    content_hash: str | None = None
    document_id: str | None = None


class InspectionEvidence(InspectionModel):
    evidence_id: str
    source_id: str
    evidence_text: str | None = None
    evidence_type: str
    origin: str
    document_id: str | None = None
    chunk_id: str | None = None
    page: int | None = None
    section: str | None = None
    content_hash: str | None = None
    retrieved_at: datetime | None = None
    evidence_status: str


class InspectionValidation(InspectionModel):
    validation_id: str
    validator: str
    status: str
    severity: str
    message: str
    rule: str
    actual_value: Any = None
    expected_condition: str | None = None


class AttributeInspection(InspectionModel):
    attribute: str
    attribute_id: str
    raw_value: Any = None
    normalized_value: Any = None
    uom: str | None = None
    status: str
    candidate_reason: str
    origin: str
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    validation_ids: list[str] = Field(default_factory=list)
    evidence_status: str
    reported_evidence_text: str | None = None
    reported_evidence_field: str | None = None
    agent: str
    model: str | None = None
    prompt_version: str
    correctness: str
    unsupported_fact: bool = False
    validations: list[InspectionValidation] = Field(default_factory=list)


class AgentInspection(InspectionModel):
    task: str
    agent: str
    model: str | None = None
    prompt_version: str
    request_id: str | None = None
    status: str
    latency_ms: int | None = None
    retry_count: int = 0
    provider_attempt_count: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    thought_tokens: int | None = None
    tool_use_tokens: int | None = None
    total_tokens: int | None = None
    structured_output: dict[str, Any] | None = None
    error: str | None = None


class InspectionTelemetry(InspectionModel):
    agent_calls: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    thought_tokens: int | None = None
    tool_use_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int
    retries: int
    tool_calls: int


class InspectionScorecard(InspectionModel):
    direct_from_input: int
    direct_from_manufacturer: int
    normalized: int
    calculated: int
    inferred: int
    unsupported: int
    unresolved: int
    validated: int
    review_required: int
    attributes_with_evidence: int
    attributes_without_evidence: int
    manufacturer_verified_attributes: int
    input_only_attributes: int
    inferred_attributes: int


class CorrectnessAssessment(InspectionModel):
    attribute: str
    classification: str
    rationale: str
    input_support: str
    manufacturer_support: str
    traceable: bool
    technically_plausible: str
    validation_status: str


class ProductInspectionResult(InspectionModel):
    status: str
    product_id: str
    state: str
    input: dict[str, Any]
    agents: list[AgentInspection]
    classification: dict[str, Any]
    attributes: list[AttributeInspection]
    evidence: list[InspectionEvidence]
    sources: list[InspectionSource]
    validations: list[InspectionValidation]
    telemetry: InspectionTelemetry
    scorecard: InspectionScorecard
    correctness_assessment: list[CorrectnessAssessment]
    limitations: list[str]


def build_inspection(
    product: ProductTruth,
    job: ProductJob,
    *,
    input_filename: str | None = None,
) -> ProductInspectionResult:
    """Build a projection without changing ProductTruth or inventing evidence."""

    source_by_id = {source.source_id: source for source in product.sources}
    raw_input = {field.field_name: field.raw_value for field in product.raw_inputs}
    input_text = " ".join(str(value) for value in raw_input.values() if value is not None)
    run_by_task = {run.task: run for run in job.runs}
    evidence_by_id = {item.evidence_id: item for item in product.evidence}
    domain_validations = {item.event_id: item for item in product.validation_events}

    sources = [_source(item) for item in product.sources]
    evidence = [_evidence(item, source_by_id) for item in product.evidence]
    validations = [
        InspectionValidation(
            validation_id=item.event_id,
            validator="ProductTruthService",
            status=item.validation_state.value.upper(),
            severity="ERROR" if item.validation_state.value == "failed" else "INFO",
            message=item.message,
            rule=item.code,
            actual_value=None,
            expected_condition=None,
        )
        for item in product.validation_events
    ]

    attributes: list[AttributeInspection] = []
    correctness: list[CorrectnessAssessment] = []
    seen_attribute_names: set[str] = set()
    for record in product.attributes:
        seen_attribute_names.add(record.canonical_name.casefold())
        for candidate in record.candidates:
            run = run_by_task.get("attribute_extraction")
            candidate_evidence = [
                evidence_by_id[item] for item in candidate.evidence_ids if item in evidence_by_id
            ]
            candidate_sources = [
                source_by_id[item] for item in candidate.source_ids if item in source_by_id
            ]
            assessment = _correctness(
                record.canonical_name, candidate, candidate_evidence, candidate_sources, input_text
            )
            candidate_validations = [
                item
                for item in validations
                if item.validation_id in domain_validations
                and domain_validations[item.validation_id].candidate_id == candidate.candidate_id
            ]
            inspection_validations = _attribute_validations(
                record.canonical_name,
                candidate.raw_value,
                candidate.normalized_value,
                candidate.uom,
                candidate.evidence_ids,
                candidate.source_ids,
                candidate_validations,
            )
            validation_ids = [item.validation_id for item in inspection_validations]
            origin = _origin(candidate_sources)
            attributes.append(
                AttributeInspection(
                    attribute=record.canonical_name,
                    attribute_id=record.attribute_id,
                    raw_value=candidate.raw_value,
                    normalized_value=candidate.normalized_value,
                    uom=candidate.uom,
                    status=candidate.status.value.upper(),
                    candidate_reason=_candidate_reason(candidate.status, origin),
                    origin=origin,
                    source_ids=list(candidate.source_ids),
                    evidence_ids=list(candidate.evidence_ids),
                    validation_ids=validation_ids,
                    evidence_status="AVAILABLE" if candidate_evidence else "NOT_AVAILABLE",
                    agent=run.agent if run else "attribute_extraction",
                    model=run.model if run else None,
                    prompt_version=run.prompt_version if run else "unknown",
                    correctness=assessment.classification,
                    unsupported_fact=assessment.classification in {"UNSUPPORTED", "UNKNOWN"},
                    validations=inspection_validations,
                )
            )
        correctness.append(assessment)
    reported = job.agent_outputs.get("attribute_extraction", {}).get("attributes", [])
    for item in reported:
        if not isinstance(item, dict):
            continue
        name = str(item.get("attribute") or "unknown attribute")
        if name.casefold() in seen_attribute_names:
            continue
        reported_evidence = item.get("evidence")
        quoted_text = (
            str(reported_evidence.get("quoted_text"))
            if isinstance(reported_evidence, dict)
            and reported_evidence.get("quoted_text") is not None
            else None
        )
        field_name = (
            str(reported_evidence.get("field_name"))
            if isinstance(reported_evidence, dict)
            and reported_evidence.get("field_name") is not None
            else None
        )
        input_supported = bool(quoted_text and quoted_text in input_text)
        model_status = str(item.get("status", "")).casefold()
        status = (
            "INFERRED"
            if model_status == "inferred"
            else ("CANDIDATE" if input_supported else "UNSUPPORTED")
        )
        correctness_class = (
            "INFERRED"
            if model_status == "inferred" and input_supported
            else "DIRECTLY_SUPPORTED_BY_INPUT"
            if input_supported
            else "UNSUPPORTED"
        )
        assessment = CorrectnessAssessment(
            attribute=name,
            classification=correctness_class,
            rationale=(
                "The returned quote appears verbatim in supplied input."
                if input_supported
                else "The returned attribute has no accepted evidence matching supplied input."
            ),
            input_support="DIRECT" if input_supported else "NONE",
            manufacturer_support="NONE",
            traceable=False,
            technically_plausible="NOT_ASSESSED_WITHOUT_AUTHORITATIVE_REFERENCE",
            validation_status="REVIEW_REQUIRED",
        )
        inspection_validations = _attribute_validations(
            name,
            item.get("raw_value"),
            item.get("normalized_candidate"),
            item.get("unit"),
            [],
            [],
            [],
        )
        attributes.append(
            AttributeInspection(
                attribute=name,
                attribute_id="attribute-" + "-".join(name.casefold().split()),
                raw_value=item.get("raw_value"),
                normalized_value=item.get("normalized_candidate"),
                uom=item.get("unit"),
                status=status,
                candidate_reason=(
                    "Model-derived candidate; not verified."
                    if status == "INFERRED"
                    else "Model output was returned without accepted, traceable evidence."
                ),
                origin="INFERRED"
                if status == "INFERRED"
                else ("INPUT_DATA" if input_supported else "UNKNOWN"),
                source_ids=[],
                evidence_ids=[],
                validation_ids=[value.validation_id for value in inspection_validations],
                evidence_status="NOT_AVAILABLE",
                reported_evidence_text=quoted_text,
                reported_evidence_field=field_name,
                agent=run_by_task["attribute_extraction"].agent
                if "attribute_extraction" in run_by_task
                else "attribute_extraction",
                model=run_by_task["attribute_extraction"].model
                if "attribute_extraction" in run_by_task
                else None,
                prompt_version=run_by_task["attribute_extraction"].prompt_version
                if "attribute_extraction" in run_by_task
                else "unknown",
                correctness=assessment.classification,
                unsupported_fact=assessment.classification in {"UNSUPPORTED", "UNKNOWN"},
                validations=inspection_validations,
            )
        )
        correctness.append(assessment)

    agents = [_agent(run, job.agent_outputs.get(run.task)) for run in job.runs]
    telemetry = _telemetry(job.runs)
    scorecard = _scorecard(attributes)
    classification_output = job.agent_outputs.get("classification", {})
    classification = {
        "status": "REFERENCE_DATA_UNAVAILABLE"
        if "unavailable" in str(classification_output).casefold()
        or "unresolved" in str(classification_output).casefold()
        else "CANDIDATE",
        "output": classification_output,
        "source_ids": list(product.classification.source_ids),
        "evidence_ids": list(product.classification.evidence_ids),
        "validation_state": product.classification.validation_state.value.upper(),
        "note": "Official taxonomy/LOV correctness is not established by this run.",
    }
    limitations = [
        "The supplied UniHack row is INPUT_DATA, not authoritative manufacturer evidence.",
        "No manufacturer source was retrieved in this existing row-2 execution.",
        "No domain candidate validation event was recorded; candidates remain review-required.",
        "The inspection does not expose private model reasoning or chain-of-thought.",
    ]
    if input_filename:
        limitations.append(f"Input file: {Path(input_filename).name}.")
    return ProductInspectionResult(
        status="completed",
        product_id=product.product_id,
        state=job.state.value,
        input=raw_input,
        agents=agents,
        classification=classification,
        attributes=attributes,
        evidence=evidence,
        sources=sources,
        validations=validations,
        telemetry=telemetry,
        scorecard=scorecard,
        correctness_assessment=correctness,
        limitations=limitations,
    )


def render_inspection_markdown(result: ProductInspectionResult) -> str:
    """Render a reviewable report; JSON remains the source of truth."""

    lines = [
        f"# Row-2 Live Inspection: `{result.product_id}`",
        "",
        "## 1. Input",
        "",
        "```json",
        _json(result.input),
        "```",
        "",
        f"State: `{result.state}`. This is an inspectability report, not a correctness claim.",
        "",
        "## 2. Product understanding",
        "",
        _agent_section(result, "product_understanding"),
        "",
        "## 3. Classification",
        "",
        _agent_section(result, "classification"),
        "",
        "```json",
        _json(result.classification),
        "```",
        "",
        "## 4. Extracted attributes",
        "",
    ]
    for index, item in enumerate(result.attributes, start=1):
        lines.extend(
            [
                f"### {index}. {item.attribute}",
                "",
                f"- Raw: `{item.raw_value}`",
                f"- Normalized: `{item.normalized_value}`",
                f"- UOM: `{item.uom}`",
                f"- Status: `{item.status}`; origin: `{item.origin}`; correctness: "
                f"`{item.correctness}`",
                f"- Evidence: `{item.evidence_status}`; source IDs: `{item.source_ids}`; "
                f"evidence IDs: `{item.evidence_ids}`",
                f"- Agent/model/prompt: `{item.agent}` / `{item.model}` / `{item.prompt_version}`",
                "- Validation:",
                "```json",
                _json([value.model_dump(mode="json") for value in item.validations]),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            "## 5. Evidence",
            "",
            "```json",
            _json([item.model_dump(mode="json") for item in result.evidence]),
            "```",
            "",
            "## 6. Sources",
            "",
            "```json",
            _json([item.model_dump(mode="json") for item in result.sources]),
            "```",
            "",
            "## 7. Validation",
            "",
            "```json",
            _json([item.model_dump(mode="json") for item in result.validations]),
            "```",
            "",
            "## 8. Telemetry",
            "",
            "```json",
            _json(result.telemetry.model_dump(mode="json")),
            "```",
            "",
            "## 9. Correctness assessment",
            "",
            "```json",
            _json([item.model_dump(mode="json") for item in result.correctness_assessment]),
            "```",
            "",
            "## 10. Unsupported/inferred values",
            "",
            f"Scorecard: `{result.scorecard.model_dump(mode='json')}`",
            "",
            "## 11. Limitations",
            "",
            *[f"- {item}" for item in result.limitations],
            "",
        ]
    )
    return "\n".join(lines)


def _source(source: Any) -> InspectionSource:
    origin = _origin(source)
    return InspectionSource(
        source_id=source.source_id,
        source_url=source.uri
        if source.uri and source.uri.startswith(("http://", "https://"))
        else None,
        source_type=source.source_type.value,
        authority=_inspection_source_authority(source),
        status=source.status.value.upper(),
        origin=origin,
        manufacturer_id=source.manufacturer_id,
        retrieved_at=source.retrieved_at,
        content_hash=source.content_hash,
        document_id=source.metadata.get("document_id"),
    )


def _inspection_source_authority(source: Any) -> str:
    if source.source_type == SourceType.SUPPLIED_INPUT:
        return "NON_AUTHORITATIVE"
    if source.status == SourceStatus.REJECTED:
        return "REJECTED"
    if source.source_type in {
        SourceType.MANUFACTURER_PAGE,
        SourceType.MANUFACTURER_DOCUMENT,
        SourceType.MANUFACTURER_CATALOG,
    }:
        if source.authority == SourceAuthority.AUTHORITATIVE:
            return "VERIFIED_MANUFACTURER"
        if source.authority == SourceAuthority.UNKNOWN:
            return "UNKNOWN"
        return "CANDIDATE"
    if source.authority == SourceAuthority.UNKNOWN:
        return "UNKNOWN"
    return "CANDIDATE"


def _evidence(item: Any, source_by_id: dict[str, Any]) -> InspectionEvidence:
    source = source_by_id.get(item.source_id)
    return InspectionEvidence(
        evidence_id=item.evidence_id,
        source_id=item.source_id,
        evidence_text=item.quoted_text,
        evidence_type=item.evidence_type.value,
        origin=_origin(source) if source else "UNKNOWN",
        document_id=item.location.get("document_id"),
        chunk_id=item.location.get("chunk_id"),
        page=item.document_page,
        section=item.location.get("section") or item.location.get("field"),
        content_hash=source.content_hash if source else None,
        retrieved_at=source.retrieved_at if source else None,
        evidence_status="AVAILABLE" if item.quoted_text else "NOT_AVAILABLE",
    )


def _agent(run: AgentRun, output: dict[str, Any] | None) -> AgentInspection:
    return AgentInspection(
        task=run.task,
        agent=run.agent,
        model=run.model,
        prompt_version=run.prompt_version,
        request_id=run.request_id,
        status=run.status,
        latency_ms=run.latency_ms,
        retry_count=run.retry_count,
        provider_attempt_count=getattr(run, "provider_attempt_count", None),
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cached_tokens=run.cached_tokens,
        thought_tokens=getattr(run, "thought_tokens", None),
        tool_use_tokens=getattr(run, "tool_use_tokens", None),
        total_tokens=run.total_tokens,
        structured_output=output,
        error=run.error,
    )


def _telemetry(runs: list[AgentRun]) -> InspectionTelemetry:
    return InspectionTelemetry(
        agent_calls=len(runs),
        input_tokens=_sum_optional(runs, "input_tokens"),
        output_tokens=_sum_optional(runs, "output_tokens"),
        cached_tokens=_sum_optional(runs, "cached_tokens"),
        thought_tokens=_sum_optional(runs, "thought_tokens"),
        tool_use_tokens=_sum_optional(runs, "tool_use_tokens"),
        total_tokens=_sum_optional(runs, "total_tokens"),
        latency_ms=sum(item.latency_ms or 0 for item in runs),
        retries=sum(item.retry_count for item in runs),
        tool_calls=sum(item.tool_calls for item in runs),
    )


def _sum_optional(runs: list[AgentRun], name: str) -> int | None:
    values = [getattr(item, name, None) for item in runs]
    return (
        sum(value for value in values if isinstance(value, int))
        if any(isinstance(value, int) for value in values)
        else None
    )


def _attribute_validations(
    name: str,
    raw: Any,
    normalized: Any,
    uom: str | None,
    evidence_ids: list[str],
    source_ids: list[str],
    domain: list[InspectionValidation],
) -> list[InspectionValidation]:
    result = list(domain)
    prefix = "inspection-" + "-".join(name.casefold().split())
    result.extend(
        [
            InspectionValidation(
                validation_id=f"{prefix}-evidence",
                validator="inspection",
                status="PASS" if evidence_ids else "NOT_AVAILABLE",
                severity="INFO" if evidence_ids else "WARNING",
                message="Quoted evidence is attached."
                if evidence_ids
                else "No evidence is attached.",
                rule="candidate must retain evidence linkage",
                actual_value=evidence_ids,
                expected_condition="at least one evidence ID",
            ),
            InspectionValidation(
                validation_id=f"{prefix}-source",
                validator="inspection",
                status="PASS" if source_ids else "NOT_AVAILABLE",
                severity="INFO" if source_ids else "WARNING",
                message="A source reference is attached; authority is assessed separately.",
                rule="candidate must retain source linkage",
                actual_value=source_ids,
                expected_condition="at least one source ID",
            ),
            InspectionValidation(
                validation_id=f"{prefix}-normalization",
                validator="inspection",
                status="NOT_ASSESSED"
                if raw is not None and normalized is not None and raw != normalized
                else "NOT_APPLIED",
                severity="WARNING"
                if raw is not None and normalized is not None and raw != normalized
                else "INFO",
                message="A model normalization is shown, but no deterministic rule verified it."
                if raw is not None and normalized is not None and raw != normalized
                else "No distinct normalization was applied.",
                rule="only documented deterministic normalization may pass",
                actual_value=normalized,
                expected_condition="a documented deterministic normalization rule",
            ),
            InspectionValidation(
                validation_id=f"{prefix}-uom",
                validator="inspection",
                status="PASS" if uom else "UNAVAILABLE",
                severity="INFO" if uom else "WARNING",
                message="A unit of measure is present."
                if uom
                else "No unit of measure was returned.",
                rule="attribute unit must be explicit before unit validation",
                actual_value=uom,
                expected_condition="a supported unit of measure",
            ),
            InspectionValidation(
                validation_id=f"{prefix}-lov",
                validator="inspection",
                status="UNAVAILABLE",
                severity="WARNING",
                message="No official attribute LOV/reference data was available in this run.",
                rule="attribute value must be checked against an official LOV",
                actual_value=normalized,
                expected_condition="official LOV/reference data",
            ),
            InspectionValidation(
                validation_id=f"{prefix}-conflict",
                validator="inspection",
                status="NONE",
                severity="INFO",
                message="No conflict was recorded for this attribute.",
                rule="candidate must not have unresolved source/value conflicts",
                actual_value=None,
                expected_condition="no open conflict",
            ),
            InspectionValidation(
                validation_id=f"{prefix}-manufacturer-source",
                validator="inspection",
                status="NOT_AVAILABLE",
                severity="WARNING",
                message="No manufacturer evidence is associated with this candidate.",
                rule="input data must not be treated as manufacturer verification",
                actual_value=None,
                expected_condition="verified manufacturer source",
            ),
        ]
    )
    return result


def _correctness(
    name: str, candidate: Any, evidence: list[Any], sources: list[Any], input_text: str
) -> CorrectnessAssessment:
    quoted = [item.quoted_text or "" for item in evidence]
    input_supported = any(value and value in input_text for value in quoted)
    manufacturer_supported = any(
        source.source_type
        in {
            SourceType.MANUFACTURER_PAGE,
            SourceType.MANUFACTURER_DOCUMENT,
            SourceType.MANUFACTURER_CATALOG,
        }
        and source.authority.value == "authoritative"
        for source in sources
    )
    if manufacturer_supported:
        classification = "DIRECTLY_SUPPORTED_BY_MANUFACTURER"
        rationale = "A non-input source is linked to the candidate."
    elif input_supported and candidate.status == ValueStatus.INFERRED:
        classification = "INFERRED"
        rationale = "The evidence is from supplied input, but the domain status is inferred."
    elif input_supported:
        classification = "DIRECTLY_SUPPORTED_BY_INPUT"
        rationale = "The quoted evidence appears verbatim in the supplied row."
    elif (
        candidate.normalized_value is not None
        and candidate.raw_value is not None
        and candidate.raw_value != candidate.normalized_value
    ):
        classification = "DETERMINISTICALLY_DERIVED"
        rationale = "Raw and normalized forms differ; no manufacturer source is present."
    elif evidence:
        classification = "UNSUPPORTED"
        rationale = "Evidence is attached but cannot be matched to the supplied input."
    else:
        classification = "UNKNOWN"
        rationale = "No traceable evidence is attached."
    return CorrectnessAssessment(
        attribute=name,
        classification=classification,
        rationale=rationale,
        input_support="DIRECT" if input_supported else "NONE",
        manufacturer_support="DIRECT" if manufacturer_supported else "NONE",
        traceable=bool(evidence and sources),
        technically_plausible="NOT_ASSESSED_WITHOUT_AUTHORITATIVE_REFERENCE",
        validation_status=candidate.assessment.validation_state.value.upper(),
    )


def _scorecard(attributes: list[AttributeInspection]) -> InspectionScorecard:
    counts = Counter(item.correctness for item in attributes)
    normalized = sum(
        item.raw_value is not None
        and item.normalized_value is not None
        and item.raw_value != item.normalized_value
        for item in attributes
    )
    validated = sum(item.status == "VERIFIED" for item in attributes)
    return InspectionScorecard(
        direct_from_input=counts["DIRECTLY_SUPPORTED_BY_INPUT"],
        direct_from_manufacturer=counts["DIRECTLY_SUPPORTED_BY_MANUFACTURER"],
        normalized=normalized,
        calculated=counts["DETERMINISTICALLY_DERIVED"],
        inferred=counts["INFERRED"],
        unsupported=counts["UNSUPPORTED"],
        unresolved=counts["UNKNOWN"],
        validated=validated,
        review_required=sum(
            item.status in {"CANDIDATE", "INFERRED", "REVIEW_REQUIRED"} for item in attributes
        ),
        attributes_with_evidence=sum(bool(item.evidence_ids) for item in attributes),
        attributes_without_evidence=sum(not item.evidence_ids for item in attributes),
        manufacturer_verified_attributes=counts["DIRECTLY_SUPPORTED_BY_MANUFACTURER"],
        input_only_attributes=counts["DIRECTLY_SUPPORTED_BY_INPUT"],
        inferred_attributes=counts["INFERRED"],
    )


def _origin(value: Any) -> str:
    if isinstance(value, list):
        origins = [_origin(item) for item in value]
        if "MANUFACTURER_SOURCE" in origins:
            return "MANUFACTURER_SOURCE"
        if "INPUT_DATA" in origins:
            return "INPUT_DATA"
        for origin in origins:
            if origin != "UNKNOWN":
                return origin
    source_type = getattr(value, "source_type", value)
    source_type = source_type.value if hasattr(source_type, "value") else str(source_type)
    return {
        SourceType.SUPPLIED_INPUT.value: "INPUT_DATA",
        SourceType.MANUFACTURER_PAGE.value: "MANUFACTURER_SOURCE",
        SourceType.MANUFACTURER_DOCUMENT.value: "MANUFACTURER_SOURCE",
        SourceType.MANUFACTURER_CATALOG.value: "MANUFACTURER_SOURCE",
        SourceType.UNILOG_RULE.value: "CALCULATED",
        SourceType.MODEL_INFERENCE.value: "INFERRED",
    }.get(source_type, "UNKNOWN")


def _candidate_reason(status: ValueStatus, origin: str) -> str:
    if status == ValueStatus.INFERRED:
        return "Model-derived candidate; not verified."
    if origin == "INPUT_DATA":
        return "Candidate is linked to supplied input; this is not manufacturer verification."
    return "Candidate status is preserved from the domain model."


def _json(value: Any) -> str:
    import json

    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def _agent_section(result: ProductInspectionResult, task: str) -> str:
    values = [item for item in result.agents if item.task == task]
    return _json([item.model_dump(mode="json") for item in values])
