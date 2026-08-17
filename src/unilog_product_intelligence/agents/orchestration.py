"""Explicit, bounded orchestration for untrusted structured model output."""

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.truth import (
    AssessmentMetadata,
    AuditEvent,
    CandidateValue,
    Evidence,
    EvidenceType,
    ProductClassification,
    ProductTruth,
    SourceAuthority,
    ValueStatus,
)
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceKind(StrEnum):
    DIRECTLY_PRESENT = "directly_present"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class EvidenceDTO(DTO):
    field_name: str
    quoted_text: str
    kind: EvidenceKind


class ProductUnderstandingResult(DTO):
    product_type: str | None = None
    product_family: str | None = None
    semantic_features: list[str] = Field(default_factory=list)
    evidence: list[EvidenceDTO] = Field(default_factory=list)
    uncertain_items: list[str] = Field(default_factory=list)


class ClassificationCandidate(DTO):
    department: str | None = None
    class_name: str | None = None
    fine: str | None = None
    classpath: list[str] = Field(default_factory=list)


class ClassificationResult(DTO):
    candidates: list[ClassificationCandidate] = Field(default_factory=list)
    selected_candidate: int | None = None
    unresolved_reason: str | None = None


class AttributeDTO(DTO):
    attribute: str
    raw_value: str | None = None
    normalized_candidate: str | None = None
    unit: str | None = None
    evidence: EvidenceDTO
    status: EvidenceKind
    model_confidence: float | None = Field(default=None, ge=0, le=1)


class AttributeExtractionResult(DTO):
    attributes: list[AttributeDTO] = Field(default_factory=list)
    missing_attributes: list[str] = Field(default_factory=list)


class JobState(StrEnum):
    RECEIVED = "received"
    PREPROCESSED = "preprocessed"
    UNDERSTANDING = "understanding"
    UNDERSTOOD = "understood"
    CLASSIFYING = "classifying"
    CLASSIFIED = "classified"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    VALIDATING = "validating"
    CANDIDATES_ACCEPTED = "candidates_accepted"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


class AgentRun(DTO):
    agent: str
    task: str
    prompt_version: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    latency_ms: int | None = None
    retry_count: int = 0
    request_id: str | None = None
    total_tokens: int | None = None
    tool_calls: int = 0
    tool_use_tokens: int | None = None
    provider_attempt_count: int | None = None
    thought_tokens: int | None = None
    error: str | None = None


class ProductJob(DTO):
    job_id: str
    product_id: str
    state: JobState = JobState.RECEIVED
    runs: list[AgentRun] = Field(default_factory=list)
    agent_outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ProductOrchestrator:
    """Runs ordered tasks and maps validated DTOs to ProductTruth candidates."""

    def __init__(self, provider: LLMProvider, service: ProductTruthService | None = None) -> None:
        self._provider = provider
        self._service = service or ProductTruthService()
        self._cache: dict[str, LLMResponse] = {}

    def run(
        self, product: ProductTruth, prompt_version: str = "v1"
    ) -> tuple[ProductTruth, ProductJob]:
        job = ProductJob(
            job_id=str(uuid4()), product_id=product.product_id, state=JobState.PREPROCESSED
        )
        context = {field.field_name: field.raw_value for field in product.raw_inputs}
        try:
            job.state = JobState.UNDERSTANDING
            understanding = self._call(
                "product_understanding", context, ProductUnderstandingResult, job, prompt_version
            )
            job.state = JobState.UNDERSTOOD
            job.state = JobState.CLASSIFYING
            classification = self._call(
                "classification", context, ClassificationResult, job, prompt_version
            )
            product = self._classification(product, cast(ClassificationResult, classification))
            job.state = JobState.CLASSIFIED
            job.state = JobState.EXTRACTING
            attributes = self._call(
                "attribute_extraction", context, AttributeExtractionResult, job, prompt_version
            )
            job.state = JobState.EXTRACTED
            product = self._attributes(product, cast(AttributeExtractionResult, attributes))
            product.audit_events.append(
                _audit(
                    product.product_id,
                    "product_understood",
                    {
                        "product_type": cast(ProductUnderstandingResult, understanding).product_type
                        or "unknown"
                    },
                )
            )
            job.state = JobState.CANDIDATES_ACCEPTED
        except (RuntimeError, ValueError) as error:
            job.state = JobState.FAILED
            product.audit_events.append(
                _audit(product.product_id, "agent_job_failed", {"error": type(error).__name__})
            )
        return product, job

    def _call(
        self, task: str, context: dict[str, object], dto: type[DTO], job: ProductJob, version: str
    ) -> DTO:
        prompt = _prompt(task, version) + "\n\nINPUT (untrusted record text):\n" + str(context)
        key = sha256(f"{task}|{version}|{prompt}".encode()).hexdigest()
        run = AgentRun(
            agent=task,
            task=task,
            prompt_version=version,
            started_at=datetime.now(UTC),
            status="running",
        )
        job.runs.append(run)
        try:
            response = self._cache.get(key)
            if response is None:
                response = self._provider.generate(
                    LLMRequest(
                        task=task, input_text=prompt, response_schema=dto.model_json_schema()
                    )
                )
                self._cache[key] = response
            parsed = dto.model_validate_json(response.output_text)
            run.status, run.model = "succeeded", response.model
            job.agent_outputs[task] = parsed.model_dump(mode="json")
            run.input_tokens, run.output_tokens, run.cached_tokens = (
                response.input_tokens,
                response.output_tokens,
                response.cached_tokens,
            )
            run.total_tokens = response.total_tokens
            run.latency_ms, run.retry_count, run.request_id = (
                response.latency_ms,
                response.retry_count,
                response.request_id,
            )
            run.tool_calls = response.tool_calls
            run.tool_use_tokens = response.tool_use_input_tokens
            return parsed
        except Exception as error:
            run.status, run.error = "failed", str(error)[:200]
            raise RuntimeError("agent execution failed") from error
        finally:
            run.completed_at = datetime.now(UTC)

    def _classification(self, product: ProductTruth, result: ClassificationResult) -> ProductTruth:
        selected = (
            result.candidates[result.selected_candidate]
            if result.selected_candidate is not None
            and result.selected_candidate < len(result.candidates)
            else ClassificationCandidate()
        )
        return self._service.add_classification(
            product,
            ProductClassification(
                department=selected.department,
                class_name=selected.class_name,
                fine=selected.fine,
                classpath=tuple(selected.classpath),
                source_ids=[product.sources[0].source_id],
            ),
        )

    def _attributes(self, product: ProductTruth, result: AttributeExtractionResult) -> ProductTruth:
        source_id = product.sources[0].source_id
        for item in result.attributes:
            if item.status == EvidenceKind.UNKNOWN or not item.evidence.quoted_text:
                continue
            candidate_id = str(uuid4())
            attribute_id = "attribute-" + "-".join(item.attribute.casefold().split())
            candidate = CandidateValue(
                candidate_id=candidate_id,
                raw_value=item.raw_value,
                normalized_value=item.normalized_candidate,
                uom=item.unit,
                status=ValueStatus.CANDIDATE
                if item.status == EvidenceKind.DIRECTLY_PRESENT
                else ValueStatus.INFERRED,
                source_ids=[source_id],
                assessment=AssessmentMetadata(
                    model_confidence=item.model_confidence, source_authority=SourceAuthority.HIGH
                ),
            )
            product = self._service.add_attribute_candidate(
                product, attribute_id, candidate, item.attribute
            )
            product = self._service.attach_evidence(
                product,
                Evidence(
                    evidence_id=str(uuid4()),
                    source_id=source_id,
                    product_id=product.product_id,
                    attribute_id=attribute_id,
                    candidate_id=candidate_id,
                    quoted_text=item.evidence.quoted_text,
                    location={"field": item.evidence.field_name},
                    evidence_type=EvidenceType.DIRECT_TEXT
                    if item.status == EvidenceKind.DIRECTLY_PRESENT
                    else EvidenceType.MODEL_INFERENCE,
                ),
            )
        return product


def _prompt(task: str, version: str) -> str:
    directory = Path(__file__).parent / "prompts" / task / version
    return "\n\n".join(
        (directory / name).read_text(encoding="utf-8").strip() for name in ("system.md", "task.md")
    )


def _audit(product_id: str, event_type: str, details: dict[str, str]) -> AuditEvent:

    return AuditEvent(
        event_id=str(uuid4()),
        product_id=product_id,
        event_type=event_type,
        actor="orchestrator",
        details=details,
        created_at=datetime.now(UTC),
    )
