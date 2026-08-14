"""Minimal PostgreSQL persistence adapter for Phase 6 diagnostics.

The adapter depends only on a DB-API-shaped connection supplied by composition code. It does not
import a driver, open connections implicitly, or expose persistence to agents. A production
application can inject psycopg (or a test double) without changing the enrichment domain.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from .models import EnrichmentResult, ValidationResult


class Cursor(Protocol):
    def execute(self, statement: str, parameters: Sequence[Any] = ()) -> object: ...

    def close(self) -> object: ...


class Connection(Protocol):
    def cursor(self) -> Cursor: ...

    def commit(self) -> object: ...

    def rollback(self) -> object: ...


class EnrichmentPersistence(Protocol):
    """Application persistence port; agents do not receive this interface."""

    def save(self, result: EnrichmentResult) -> None: ...


class PostgresEnrichmentRepository:
    """Persist one result transactionally using the Phase 6 PostgreSQL schema."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def save(self, result: EnrichmentResult) -> None:
        cursor = self.connection.cursor()
        try:
            for plan in result.attribute_plans:
                cursor.execute(
                    """
                    INSERT INTO attribute_plans
                    (id, product_id, attribute_id, attribute_name, applicability, current_status,
                     current_value, evidence_available, enrichment_decision,
                     validation_requirements, allowed_values, allowed_uom,
                     reference_availability, priority, reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (product_id, attribute_id) DO UPDATE SET
                      current_status = EXCLUDED.current_status,
                      current_value = EXCLUDED.current_value,
                      evidence_available = EXCLUDED.evidence_available,
                      enrichment_decision = EXCLUDED.enrichment_decision,
                      validation_requirements = EXCLUDED.validation_requirements,
                      allowed_values = EXCLUDED.allowed_values,
                      allowed_uom = EXCLUDED.allowed_uom,
                      reference_availability = EXCLUDED.reference_availability,
                      priority = EXCLUDED.priority,
                      reason = EXCLUDED.reason
                    """,
                    (
                        f"plan-{result.product_id}-{plan.attribute_id}",
                        result.product_id,
                        plan.attribute_id,
                        plan.attribute_name,
                        plan.applicability.value,
                        plan.current_status.value,
                        _json(plan.current_value),
                        plan.evidence_available,
                        plan.enrichment_required.value,
                        _json(list(plan.validation_requirements)),
                        _json(list(plan.allowed_values)),
                        _json(list(plan.allowed_uom)),
                        plan.reference_availability.value,
                        plan.priority,
                        plan.reason,
                    ),
                )
            for candidate in result.candidates:
                cursor.execute(
                    """
                    INSERT INTO enrichment_candidates
                    (id, product_id, attribute_id, value, raw_value, normalized_value, uom,
                     source_id, evidence_ids, evidence_text, status, validation_state,
                     candidate_reason, model_metadata, cache_key)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      value = EXCLUDED.value,
                      raw_value = EXCLUDED.raw_value,
                      normalized_value = EXCLUDED.normalized_value,
                      uom = EXCLUDED.uom,
                      evidence_ids = EXCLUDED.evidence_ids,
                      evidence_text = EXCLUDED.evidence_text,
                      status = EXCLUDED.status,
                      validation_state = EXCLUDED.validation_state,
                      candidate_reason = EXCLUDED.candidate_reason,
                      model_metadata = EXCLUDED.model_metadata,
                      cache_key = EXCLUDED.cache_key
                    """,
                    (
                        candidate.candidate_id,
                        result.product_id,
                        candidate.attribute_id,
                        _json(candidate.value),
                        _json(candidate.raw_value),
                        candidate.normalized_value,
                        candidate.uom,
                        candidate.source_id,
                        _json(list(candidate.evidence_ids)),
                        candidate.evidence_text,
                        candidate.status.value,
                        candidate.validation_state,
                        candidate.candidate_reason,
                        _json(candidate.model_metadata),
                        candidate.cache_key,
                    ),
                )
            for validation in result.validations:
                cursor.execute(
                    """
                    INSERT INTO enrichment_validation_results
                    (id, product_id, attribute_id, validator, passed, severity, message,
                     evidence_reference, rule_reference, actual_value, expected_condition)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                      passed = EXCLUDED.passed,
                      severity = EXCLUDED.severity,
                      message = EXCLUDED.message,
                      actual_value = EXCLUDED.actual_value,
                      expected_condition = EXCLUDED.expected_condition
                    """,
                    (
                        _validation_id(result.product_id, validation),
                        result.product_id,
                        validation.attribute,
                        validation.validator,
                        validation.passed,
                        validation.severity.value,
                        validation.message,
                        validation.evidence_reference,
                        validation.rule_reference,
                        _json(validation.actual_value),
                        validation.expected_condition,
                    ),
                )
            for index, review in enumerate(result.reviews):
                cursor.execute(
                    """
                    INSERT INTO enrichment_reviews
                    (id, product_id, attribute_id, current_value, candidate_values, source_ids,
                     evidence, validation_failures, recommended_action, reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        f"review-{result.product_id}-{review.attribute}-{index}",
                        result.product_id,
                        review.attribute,
                        _json(review.current_value),
                        _json(list(review.candidate_values)),
                        _json(list(review.sources)),
                        _json([item.model_dump(mode="json") for item in review.evidence]),
                        _json(
                            [item.model_dump(mode="json") for item in review.validation_failures]
                        ),
                        review.recommended_action,
                        review.reason,
                    ),
                )
            cache_keys = {
                candidate.cache_key for candidate in result.candidates if candidate.cache_key
            }
            for cache_key in cache_keys:
                cursor.execute(
                    """
                    INSERT INTO enrichment_cache
                    (cache_key, product_id, source_content_hashes, prompt_version, model_version,
                     schema_version, result)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (cache_key) DO UPDATE SET result = EXCLUDED.result
                    """,
                    (
                        cache_key,
                        result.product_id,
                        _json(
                            [
                                item.source_content_hash
                                for candidate in result.candidates
                                for item in candidate.evidence
                                if item.source_content_hash
                            ]
                        ),
                        "enrichment/v1",
                        _model(result),
                        "phase6-v1",
                        _json(result.model_dump(mode="json")),
                    ),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()


def _validation_id(product_id: str, validation: ValidationResult) -> str:
    payload = validation.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=_json_default).encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    return f"validation-{product_id}-{digest}"


def _model(result: EnrichmentResult) -> str:
    for candidate in result.candidates:
        model = candidate.model_metadata.get("model")
        if model:
            return model
    return "unknown"


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=_json_default, sort_keys=True)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)
