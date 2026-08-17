from __future__ import annotations

import json

from unilog_product_intelligence.agents.cli import _emit_inspection, _parse_row_id
from unilog_product_intelligence.agents.inspection import (
    build_inspection,
    render_inspection_markdown,
)
from unilog_product_intelligence.agents.orchestration import ProductOrchestrator
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.domain.truth import Source, SourceAuthority, SourceType
from unilog_product_intelligence.providers.base import LLMProvider, LLMRequest, LLMResponse


class InspectionFakeProvider(LLMProvider):
    def generate(self, request: LLMRequest) -> LLMResponse:
        outputs = {
            "product_understanding": (
                '{"product_type":"sanding belt","product_family":null,'
                '"semantic_features":[],"evidence":[],"uncertain_items":[]}'
            ),
            "classification": (
                '{"candidates":[],"selected_candidate":null,'
                '"unresolved_reason":"taxonomy unavailable"}'
            ),
            "attribute_extraction": (
                '{"attributes":['
                '{"attribute":"quantity","raw_value":"6pc","normalized_candidate":"6",'
                '"unit":"pcs","evidence":{"field_name":"Part_Desc","quoted_text":"6pc",'
                '"kind":"directly_present"},"status":"directly_present"},'
                '{"attribute":"grit","raw_value":"80","normalized_candidate":"80",'
                '"unit":null,"evidence":{"field_name":"Part_Desc","quoted_text":"",'
                '"kind":"unknown"},"status":"unknown"},'
                '{"attribute":"dimensions","raw_value":"1/2 x 18","normalized_candidate":'
                '"1/2 in x 18 in","unit":"in","evidence":{"field_name":"Part_Desc",'
                '"quoted_text":"1/2 x 18","kind":"directly_present"},'
                '"status":"inferred"}'
                '],"missing_attributes":[]}'
            ),
        }
        return LLMResponse(
            output_text=outputs[request.task],
            model="test-model",
            request_id=f"request-{request.task}",
            latency_ms=12,
            input_tokens=10,
            output_tokens=8,
            total_tokens=18,
            retry_count=0,
        )


def _inspection():
    source = Source(
        source_id="input-row-2",
        source_type=SourceType.SUPPLIED_INPUT,
        authority=SourceAuthority.HIGH,
    )
    product = ProductTruthService().create_from_raw_input(
        "row-2",
        {
            "Mfg_Part_Num": "DCB518ASTS06G",
            "Part_Desc": "DCB518ASTS06G Diablo 1/2 x 18 - Sanding Belt 6pc",
        },
        source,
    )
    return build_inspection(*ProductOrchestrator(InspectionFakeProvider()).run(product))


def test_inspection_preserves_returned_attributes_and_raw_values() -> None:
    result = _inspection()
    by_name = {item.attribute: item for item in result.attributes}

    assert set(by_name) == {"quantity", "grit", "dimensions"}
    assert by_name["quantity"].raw_value == "6pc"
    assert by_name["quantity"].normalized_value == "6"
    assert by_name["dimensions"].status == "INFERRED"
    assert by_name["dimensions"].correctness == "INFERRED"
    assert by_name["grit"].status == "UNSUPPORTED"
    assert by_name["grit"].evidence_ids == []
    assert by_name["grit"].evidence_status == "NOT_AVAILABLE"
    assert by_name["grit"].unsupported_fact is True


def test_input_is_not_manufacturer_evidence() -> None:
    result = _inspection()

    assert result.sources[0].authority == "NON_AUTHORITATIVE"
    assert result.scorecard.manufacturer_verified_attributes == 0
    assert result.scorecard.input_only_attributes == 1
    assert all(item.origin == "INPUT_DATA" for item in result.evidence)
    assert result.scorecard.validated == 0
    assert all(
        item.origin == "INPUT_DATA" for item in result.attributes if item.status == "CANDIDATE"
    )
    assert all(
        "not manufacturer verification" in item.candidate_reason
        for item in result.attributes
        if item.status == "CANDIDATE"
    )


def test_validation_and_telemetry_are_structured_without_secrets() -> None:
    result = _inspection()
    payload = result.model_dump(mode="json")
    serialized = json.dumps(payload)

    dimensions = next(item for item in result.attributes if item.attribute == "dimensions")
    statuses = {
        item.validation_id.rsplit("-", 1)[-1]: item.status for item in dimensions.validations
    }
    assert statuses["uom"] == "PASS"
    assert statuses["lov"] == "UNAVAILABLE"
    assert statuses["normalization"] == "NOT_ASSESSED"
    assert result.telemetry.agent_calls == 3
    assert result.agents[0].request_id is not None
    assert "authorization" not in serialized.casefold()
    assert "api_key" not in serialized.casefold()


def test_markdown_render_contains_review_sections() -> None:
    markdown = render_inspection_markdown(_inspection())

    for heading in (
        "## 1. Input",
        "## 4. Extracted attributes",
        "## 5. Evidence",
        "## 8. Telemetry",
        "## 11. Limitations",
    ):
        assert heading in markdown


def test_cli_json_and_human_output(tmp_path, monkeypatch, capsys) -> None:
    assert _parse_row_id("row-2") == 2
    assert _parse_row_id("2") == 2

    result = _inspection()
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "inspection.json"

    assert _emit_inspection(result, str(output), True) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["product_id"] == "row-2"
    assert payload["attributes"]
    assert capsys.readouterr().out.lstrip().startswith("{")

    assert _emit_inspection(result, None, False) == 0
    human = capsys.readouterr().out
    assert "# Row-2 Live Inspection" in human
    assert "## 8. Telemetry" in human
