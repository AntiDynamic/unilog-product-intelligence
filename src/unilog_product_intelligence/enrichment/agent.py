"""Evidence-grounded enrichment agent with a narrow, auditable provider contract."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from pydantic import ValidationError

from unilog_product_intelligence.domain.source_context import VerifiedProductSourceContext
from unilog_product_intelligence.domain.truth import (
    ProductTruth,
    SourceAuthority,
    SourceStatus,
    SourceType,
)
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse

from .models import (
    AttributePlan,
    CandidateResponseEnvelope,
    EnrichmentCandidate,
    EvidenceReference,
    FinalAttributeStatus,
    ValidationResult,
)
from .reference import separate_value_and_uom


class EnrichmentAgentError(RuntimeError):
    """A provider or structured-output failure that is safe to report."""


class EnrichmentAgentRun:
    """Observable call metadata; no hidden model reasoning is retained."""

    def __init__(self, response: LLMResponse | None = None, error: str | None = None) -> None:
        self.started_at: datetime = datetime.now(UTC)
        self.completed_at: datetime | None = None
        self.response = response
        self.error = error

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.response is not None


class EvidenceGroundedEnrichmentAgent:
    """Ask a model only about planned fields and supplied evidence chunks."""

    prompt_version = "enrichment/v1"

    def __init__(self, provider: LLMProvider | None = None, max_repair_attempts: int = 1) -> None:
        self.provider = provider
        self.max_repair_attempts = max_repair_attempts
        self.cache: dict[str, tuple[EnrichmentCandidate, ...]] = {}
        self._cache_lock = threading.Lock()
        self._local = threading.local()

    @property
    def last_run(self) -> EnrichmentAgentRun | None:
        return getattr(self._local, "last_run", None)

    @last_run.setter
    def last_run(self, value: EnrichmentAgentRun | None) -> None:
        self._local.last_run = value

    def enrich(
        self,
        product: ProductTruth,
        plans: Iterable[AttributePlan],
        evidence: Iterable[EvidenceReference],
        source_context: VerifiedProductSourceContext | None = None,
        *,
        model_version: str = "gemini-3.5-flash-lite",
        schema_version: str = "phase6-v1",
    ) -> tuple[EnrichmentCandidate, ...]:
        selected = tuple(
            plan
            for plan in plans
            if plan.enrichment_required.value in {"ENRICH", "VERIFY_EXISTING"}
            and plan.applicability.value in {"REQUIRED", "OPTIONAL"}
        )
        evidence_items = tuple(evidence)
        if not selected or not evidence_items:
            self.last_run = EnrichmentAgentRun(error=None)
            self.last_run.completed_at = datetime.now(UTC)
            return ()
        key = self.cache_key(
            product,
            selected,
            evidence_items,
            model_version,
            schema_version,
            source_context=source_context,
        )
        with self._cache_lock:
            cached_result = self.cache.get(key)
        if cached_result is not None:
            self.last_run = EnrichmentAgentRun(
                LLMResponse(output_text="", model=model_version, cached_tokens=1)
            )
            self.last_run.completed_at = datetime.now(UTC)
            return cached_result
        if self.provider is None:
            self.last_run = EnrichmentAgentRun(error="provider_unavailable")
            self.last_run.completed_at = datetime.now(UTC)
            return ()
        prompt = _prompt(product, selected, evidence_items, source_context)
        run = EnrichmentAgentRun()
        self.last_run = run
        try:
            response = self.provider.generate(
                LLMRequest(
                    task="evidence_grounded_enrichment",
                    input_text=prompt,
                    response_schema=CandidateResponseEnvelope.model_json_schema(),
                    metadata={
                        "prompt_version": self.prompt_version,
                        "schema_version": schema_version,
                    },
                )
            )
            run.response = response
            envelope = CandidateResponseEnvelope.model_validate_json(response.output_text)
            by_name = {plan.attribute_name.casefold(): plan for plan in selected}
            by_id = {plan.attribute_id: plan for plan in selected}
            allowed_evidence = {item.evidence_id: item for item in evidence_items}
            candidates: list[EnrichmentCandidate] = []
            for item in envelope.candidates:
                plan = by_id.get(item.attribute) or by_name.get(item.attribute.casefold())
                if plan is None or item.evidence_id not in allowed_evidence:
                    continue
                reference = allowed_evidence[item.evidence_id]
                status = (
                    FinalAttributeStatus.INFERRED
                    if item.status.casefold() in {"inferred", "calculated"}
                    else FinalAttributeStatus.ENRICHED
                )
                raw_val = item.raw_value if item.raw_value is not None else item.value
                cand_val = item.value
                val_clean, parsed_uom = separate_value_and_uom(
                    cand_val, allowed_uoms=plan.allowed_uom
                )
                final_uom = item.uom or parsed_uom
                final_val = val_clean if val_clean is not None else cand_val

                candidates.append(
                    EnrichmentCandidate(
                        candidate_id="enrichment-" + str(uuid4()),
                        product_id=product.product_id,
                        attribute_id=plan.attribute_id,
                        attribute=plan.attribute_name,
                        value=final_val,
                        raw_value=raw_val,
                        normalized_value=item.normalized_value,
                        uom=final_uom,
                        source_id=reference.source_id,
                        evidence_ids=(reference.evidence_id,),
                        evidence_text=item.evidence_text or reference.evidence_text,
                        evidence=(reference,),
                        status=status,
                        candidate_reason=item.reason,
                        model_metadata={
                            "prompt_version": self.prompt_version,
                            "model": response.model,
                            "directness": item.status,
                        },
                        cache_key=key,
                    )
                )
            result = tuple(candidates)
            with self._cache_lock:
                self.cache[key] = result
            run.completed_at = datetime.now(UTC)
            return result
        except (ValidationError, ValueError, TypeError) as error:
            run.error = type(error).__name__
            run.completed_at = datetime.now(UTC)
            raise EnrichmentAgentError("malformed enrichment response") from error
        except Exception as error:
            run.error = type(error).__name__
            run.completed_at = datetime.now(UTC)
            raise EnrichmentAgentError("enrichment provider failed") from error

    def repair(
        self,
        product: ProductTruth,
        plan: AttributePlan,
        candidate: EnrichmentCandidate,
        failures: Iterable[ValidationResult],
        evidence: Iterable[EvidenceReference],
    ) -> EnrichmentCandidate | None:
        """Perform one provider repair; the caller enforces the configured attempt bound."""

        if self.provider is None or self.max_repair_attempts <= 0:
            return None
        evidence_items = tuple(evidence)
        failure_text = "\\n".join(f"{item.validator}: {item.message}" for item in failures)
        prompt = (
            "SYSTEM: Bounded repair only. Use supplied evidence and allowed values/UOM. "
            "If the candidate cannot be repaired without inventing facts, return no candidate. "
            "Output JSON only.\\n"
            f"ATTRIBUTE: {plan.attribute_id} allowed_values={list(plan.allowed_values)} "
            f"allowed_uom={list(plan.allowed_uom)}\\n"
            f"CANDIDATE: {candidate.model_dump(mode='json')}\\n"
            f"VALIDATION_FAILURES: {failure_text}\\n"
            f"EVIDENCE: {[item.model_dump(mode='json') for item in evidence_items]}"
        )
        run = EnrichmentAgentRun()
        self.last_run = run
        try:
            response = self.provider.generate(
                LLMRequest(
                    task="evidence_grounded_enrichment_repair",
                    input_text=prompt,
                    response_schema=CandidateResponseEnvelope.model_json_schema(),
                    metadata={"prompt_version": "repair/v1"},
                )
            )
            run.response = response
            envelope = CandidateResponseEnvelope.model_validate_json(response.output_text)
            item = next(iter(envelope.candidates), None)
            if item is None or item.evidence_id not in {ref.evidence_id for ref in evidence_items}:
                run.completed_at = datetime.now(UTC)
                return None
            reference = next(ref for ref in evidence_items if ref.evidence_id == item.evidence_id)
            repaired = candidate.model_copy(
                update={
                    "value": item.value,
                    "raw_value": item.raw_value if item.raw_value is not None else item.value,
                    "normalized_value": item.normalized_value,
                    "uom": item.uom,
                    "evidence_ids": (reference.evidence_id,),
                    "evidence_text": item.evidence_text or reference.evidence_text,
                    "evidence": (reference,),
                    "candidate_reason": item.reason,
                    "model_metadata": {
                        **candidate.model_metadata,
                        "repair_prompt_version": "repair/v1",
                    },
                }
            )
            run.completed_at = datetime.now(UTC)
            return repaired
        except (ValidationError, ValueError, TypeError):
            run.error = "malformed_repair_response"
            run.completed_at = datetime.now(UTC)
            return None
        except Exception as error:
            run.error = type(error).__name__
            run.completed_at = datetime.now(UTC)
            return None

    @staticmethod
    def cache_key(
        product: ProductTruth,
        plans: Iterable[AttributePlan],
        evidence: Iterable[EvidenceReference],
        model_version: str,
        schema_version: str,
        source_context: VerifiedProductSourceContext | None = None,
    ) -> str:
        payload = {
            "product": product.product_id,
            "plans": [plan.model_dump(mode="json") for plan in plans],
            "evidence": [item.model_dump(mode="json") for item in evidence],
            "model": model_version,
            "schema": schema_version,
            "prompt": EvidenceGroundedEnrichmentAgent.prompt_version,
            "source_context": (
                source_context.model_dump(mode="json") if source_context is not None else None
            ),
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()


def _prompt(
    product: ProductTruth,
    plans: tuple[AttributePlan, ...],
    evidence: tuple[EvidenceReference, ...],
    source_context: VerifiedProductSourceContext | None = None,
) -> str:
    plan_text = "\n".join(
        f"- {plan.attribute_id} ({plan.attribute_name}) applicability={plan.applicability} "
        f"allowed_values={list(plan.allowed_values)} allowed_uom={list(plan.allowed_uom)}"
        for plan in plans
    )
    evidence_text = "\n".join(
        f"- evidence_id={item.evidence_id} source_id={item.source_id} "
        f"source={item.source_url or ''} text={item.evidence_text}"
        for item in evidence
    )
    identity = product.identity.manufacturer_part_number
    mpn = identity.normalized_value if identity else ""
    mfg_id = product.identity.manufacturer
    mfg = (mfg_id.normalized_value if mfg_id else None) or ""
    b_id = product.identity.brand
    brand = (b_id.normalized_value if b_id else None) or ""

    source_ctx_text = (
        source_context.build_prompt_context() if source_context is not None else ""
    )

    prompt_parts = [
        "SYSTEM: Evidence-grounded enrichment v1. Extract ONLY attributes in the supplied plan.",
        "Use ONLY supplied evidence and verified manufacturer source context.",
        "Never use unsupported world knowledge. Return no candidate if unsupported.",
        "Every candidate MUST cite one supplied evidence_id.",
        "Do not alter MPN or manufacturer identity.",
        "Do not invent evidence IDs or LOV values. Separate numeric values and units.",
        "Distinguish direct facts from inference/calculation. Output JSON only.\n",
        f"PRODUCT IDENTITY: id={product.product_id} manufacturer={mfg} brand={brand} mpn={mpn}",
    ]

    if source_ctx_text:
        prompt_parts.append(f"VERIFIED MANUFACTURER SOURCE CONTEXT:\n{source_ctx_text}")

    prompt_parts.append(f"PLANNED ATTRIBUTES:\n{plan_text}")
    prompt_parts.append(f"VERIFIED EVIDENCE:\n{evidence_text}")

    return "\n\n".join(prompt_parts)


def evidence_references(product: ProductTruth) -> tuple[EvidenceReference, ...]:
    """Expose only evidence attached to available authoritative manufacturer/distributor sources."""

    sources = {item.source_id: item for item in product.sources}
    result: list[EvidenceReference] = []
    for item in product.evidence:
        source = sources.get(item.source_id)
        if source is None or source.status != SourceStatus.AVAILABLE:
            continue
        if source.source_type not in {
            SourceType.MANUFACTURER_PAGE,
            SourceType.MANUFACTURER_DOCUMENT,
            SourceType.MANUFACTURER_CATALOG,
            SourceType.AUTHORIZED_DISTRIBUTOR,
        }:
            continue
        if source.authority not in {
            SourceAuthority.AUTHORITATIVE,
            SourceAuthority.HIGH,
            SourceAuthority.SECONDARY,
        }:
            continue
        if not item.quoted_text:
            continue
        result.append(
            EvidenceReference(
                evidence_id=item.evidence_id,
                source_id=item.source_id,
                source_url=source.uri,
                source_type=source.source_type.value,
                source_authority=source.authority.value,
                source_content_hash=source.content_hash,
                evidence_text=item.quoted_text,
                page=item.document_page,
                section=item.location.get("section"),
                retrieved_at=source.retrieved_at,
                document_chunk=item.location.get("chunk"),
            )
        )
    return tuple(result)
