"""Phase 6 CLI for deterministic diagnostics and connected vertical-slice runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from unilog_product_intelligence.agents.orchestration import ProductOrchestrator
from unilog_product_intelligence.application.execution import GeminiExecutionService
from unilog_product_intelligence.application.phase65 import Phase65Pipeline, Phase65Result
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.config import Settings
from unilog_product_intelligence.data.readers import read_tabular_file
from unilog_product_intelligence.domain.truth import (
    ProductTruth,
    Source,
    SourceAuthority,
    SourceType,
)
from unilog_product_intelligence.providers.gemini import GeminiProvider
from unilog_product_intelligence.retrieval import (
    DomainResolver,
    EvidenceExtractor,
    HtmlParser,
    ManufacturerDiscoveryAgent,
    ManufacturerIntelligenceService,
    ManufacturerProfile,
    ProductSourceDiscoveryService,
    SourceFetcher,
    SourceRecord,
    canonicalize_url,
)
from unilog_product_intelligence.retrieval.agents import DiscoveryResult
from unilog_product_intelligence.retrieval.core import SourceDecision, SourceKind

from .agent import EvidenceGroundedEnrichmentAgent
from .models import EnrichmentResult
from .planner import AttributePlanner, ReferencePack
from .service import EnrichmentService


def phase6_main() -> None:
    parser = argparse.ArgumentParser(description="Run evidence-grounded Phase 6 enrichment.")
    parser.add_argument("--input", required=True, help="CSV/XLSX raw UniHack input")
    parser.add_argument("--limit", type=int, default=3, help="Maximum real rows to process")
    parser.add_argument(
        "--row-id", action="append", type=_parse_row_id, help="Specific data row(s)"
    )
    parser.add_argument("--output", help="Optional JSON diagnostics output path")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run the connected Phase 4 -> Phase 5 -> Phase 6 path with Gemini",
    )
    parser.add_argument("--refresh", action="store_true", help="Bypass the Phase 5 source cache")
    parser.add_argument(
        "--reference-root", action="append", default=[], help="Reference search root"
    )
    args = parser.parse_args()
    input_path = Path(args.input)
    tabular = read_tabular_file(input_path)
    selected_rows = (
        [row for row in tabular.rows if row.row_number in args.row_id]
        if args.row_id
        else tabular.rows[: max(0, args.limit)]
    )
    roots = [Path.cwd(), *[Path(value) for value in args.reference_root]]
    reference_pack = ReferencePack.discover(roots)
    settings = Settings()
    provider = GeminiExecutionService(GeminiProvider(settings)) if args.live else None
    service = EnrichmentService(
        planner=AttributePlanner(reference_pack=reference_pack),
        agent=EvidenceGroundedEnrichmentAgent(provider=provider),
    )
    truth_service = ProductTruthService()
    results: list[EnrichmentResult] = []
    vertical_results: list[dict[str, Any]] = []

    if args.row_id and len(selected_rows) != len(args.row_id):
        found = {row.row_number for row in selected_rows}
        missing = sorted(set(args.row_id) - found)
        raise ValueError(f"row-id values not found: {missing}")
    for row in selected_rows:
        product = truth_service.create_from_raw_input(
            product_id=f"unihack-row-{row.row_number}",
            raw_values=row.raw_values,
            source=Source(
                source_id=f"input-{tabular.source_file.sha256 or 'unknown'}",
                source_type=SourceType.SUPPLIED_INPUT,
                authority=SourceAuthority.MEDIUM,
                uri=str(input_path.resolve()),
            ),
        )
        if not args.live:
            results.append(service.enrich(product))
            continue
        assert provider is not None
        fetcher = SourceFetcher()
        source_discovery = ProductSourceDiscoveryService(fetcher)

        def source_binding(
            item: ProductTruth,
            discovery: DiscoveryResult,
            finder: ProductSourceDiscoveryService = source_discovery,
        ) -> tuple[SourceRecord, ManufacturerProfile] | None:
            return _bind_verified_candidate(item, discovery, finder)

        pipeline = Phase65Pipeline(
            orchestrator=ProductOrchestrator(provider),
            discovery=ManufacturerDiscoveryAgent(provider, DomainResolver()),
            manufacturer=ManufacturerIntelligenceService(
                fetcher,
                parser=HtmlParser(),
                extractor=EvidenceExtractor(provider),
            ),
            enrichment=service,
            source_binding=source_binding,
        )
        vertical_results.append(
            _vertical_payload(
                row_number=row.row_number,
                input_path=input_path,
                initial_product=product,
                result=pipeline.run(product, refresh=args.refresh),
            )
        )

    if args.live:
        payload = {
            "phase": "4->5->6",
            "input": str(input_path),
            "reference_availability": reference_pack.availability,
            "reference_files": {name: str(path) for name, path in reference_pack.files.items()},
            "live_requested": True,
            "gemini_key_configured": bool(settings.gemini_api_key),
            "rows_requested": [row.row_number for row in selected_rows],
            "results": vertical_results,
            "summary": _vertical_summary(vertical_results),
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        report_dir = Path("docs/research")
        report_dir.mkdir(parents=True, exist_ok=True)
        if len(vertical_results) == 1 and vertical_results[0]["row_number"] == 2:
            (report_dir / "row-2-vertical-slice.json").write_text(text + "\n", encoding="utf-8")
            (report_dir / "row-2-vertical-slice.md").write_text(
                _vertical_markdown(vertical_results[0]), encoding="utf-8"
            )
        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(text)
        return

    payload = {
        "phase": 6,
        "input": str(input_path),
        "reference_availability": reference_pack.availability,
        "reference_files": {name: str(path) for name, path in reference_pack.files.items()},
        "live_requested": False,
        "gemini_key_configured": bool(settings.gemini_api_key),
        "rows_requested": [row.row_number for row in selected_rows],
        "results": [result.model_dump(mode="json") for result in results],
        "summary": _summary(results),
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)


def _parse_row_id(value: str) -> int:
    text = value.removeprefix("row-")
    try:
        row_id = int(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("row id must be an integer or row-N") from error
    if row_id < 1:
        raise argparse.ArgumentTypeError("row id must be positive")
    return row_id


def _summary(results: list[EnrichmentResult]) -> dict[str, int]:
    return {
        "products": len(results),
        "agent_calls": sum(result.metrics.agent_calls for result in results),
        "ready": sum(result.metrics.ready for result in results),
        "review_required": sum(result.metrics.review_required for result in results),
        "blocked": sum(result.metrics.blocked for result in results),
        "candidates": sum(len(result.candidates) for result in results),
        "conflicts": sum(result.metrics.conflicts for result in results),
    }


def _identity_value(product: ProductTruth, field: str) -> str:
    identity = getattr(product, "identity", None)
    value = getattr(identity, field, None)
    return str(getattr(value, "normalized_value", None) or getattr(value, "raw_value", None) or "")


def _bind_verified_candidate(
    product: ProductTruth,
    discovery: object,
    source_discovery: ProductSourceDiscoveryService | None = None,
) -> tuple[SourceRecord, ManufacturerProfile] | None:
    candidates = tuple(
        item
        for item in getattr(discovery, "candidates", ())
        if item.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
    )
    if not candidates:
        return None
    domains = tuple(dict.fromkeys(str(item.domain) for item in candidates))
    manufacturer_id = _identity_value(product, "manufacturer")
    profile = ManufacturerProfile(
        manufacturer_id=manufacturer_id,
        canonical_name=manufacturer_id,
        verified_domains=domains,
    )
    url = canonicalize_url(domains[0] if "://" in domains[0] else f"https://{domains[0]}/")
    source_kind = SourceKind.MANUFACTURER_PRODUCT_PAGE
    if source_discovery is not None:
        exact_sources = source_discovery.discover(
            product,
            profile,
            candidate_urls=getattr(discovery, "search_result_urls", ()),
        )
        if not exact_sources:
            return None
        exact = exact_sources[0]
        url = exact.url
        source_kind = exact.source_kind
    return (
        SourceRecord(
            canonical_url=url,
            original_url=url,
            source_kind=source_kind,
            decision=SourceDecision.VERIFIED_MANUFACTURER_SOURCE,
            manufacturer_id=manufacturer_id,
            manufacturer_domain=_host(url),
            product_id=product.product_id,
        ),
        profile,
    )


def _host(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").casefold()


def _vertical_payload(
    row_number: int,
    input_path: Path,
    initial_product: ProductTruth,
    result: Phase65Result,
) -> dict[str, Any]:
    product = result.product_truth
    source_identity = initial_product.identity
    values = {
        attribute.canonical_name: attribute.normalized_value or attribute.raw_value
        for attribute in product.attributes
        if attribute.normalized_value is not None or attribute.raw_value is not None
    }
    manufacturer = getattr(source_identity, "manufacturer", None)
    if manufacturer is not None:
        values.setdefault("Manufacturer", manufacturer.normalized_value or manufacturer.raw_value)
    sources = [
        {
            "url": source.uri,
            "type": source.source_type,
            "authority": source.authority,
            "evidence": [
                evidence.quoted_text or ""
                for evidence in product.evidence
                if evidence.source_id == source.source_id
            ],
        }
        for source in product.sources
        if source.uri
    ]
    return {
        "row_number": row_number,
        "product_id": product.product_id,
        "input": str(input_path),
        "product": values,
        "sources": sources,
    }

def _vertical_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "products": len(results),
        "attributes": sum(len(item["product"]) for item in results),
        "sources": sum(len(item["sources"]) for item in results),
        "evidence": sum(
            len(source["evidence"])
            for item in results
            for source in item["sources"]
        ),
    }

def _vertical_markdown(item: dict[str, Any]) -> str:
    sources = item["sources"]
    return "\n".join(
        [
            f"# UniLog row-{item['row_number']} product",
            "",
            f"- Product attributes: {len(item['product'])}",
            f"- Sources: {len(sources)}",
            f"- Evidence excerpts: {sum(len(source['evidence']) for source in sources)}",
            "",
            "The JSON report contains the completed product attributes and source evidence.",
            "",
        ]
    )

if __name__ == "__main__":
    phase6_main()
