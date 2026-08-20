"""
Trace a single product through every stage of the pipeline.

Usage:
    python scripts/trace_product.py WDTS7024RZ
    python scripts/trace_product.py PDSH4816AF
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

import argparse

from unilog_product_intelligence.agents.orchestration import ProductOrchestrator
from unilog_product_intelligence.application.brand_resolver import BrandManufacturerResolver
from unilog_product_intelligence.application.product_truth import ProductTruthService
from unilog_product_intelligence.delivery.adapter import (
    DeliverySchemaContract,
    Phase65ResultDeliveryAdapter,
)
from unilog_product_intelligence.domain.truth import (
    Source,
    SourceAuthority,
    SourceType,
)
from unilog_product_intelligence.enrichment.agent import EvidenceGroundedEnrichmentAgent
from unilog_product_intelligence.enrichment.planner import AttributePlanner
from unilog_product_intelligence.enrichment.service import EnrichmentService
from unilog_product_intelligence.enrichment.validation import ValidationPipeline
from unilog_product_intelligence.providers.factory import ExecutionMode, build_provider
from unilog_product_intelligence.retrieval.agents import (
    DiscoveryResult,
    ManufacturerDiscoveryAgent,
)
from unilog_product_intelligence.retrieval.core import (
    AsyncSourceFetcher,
    DomainCircuitBreaker,
    DomainResolver,
    EvidenceExtractor,
    ManufacturerProfile,
    SourceDecision,
    SourceFetcher,
    SourceKind,
    SourceRecord,
    SourceVerifier,
    _host,
    _same_or_subdomain,
)
from unilog_product_intelligence.retrieval.service import ManufacturerIntelligenceService
from unilog_product_intelligence.retrieval.source_discovery import ProductSourceDiscoveryService

_DEFAULT_INPUT = _ROOT / "Unihack_ Sample Dataset - Input.csv"
_DEFAULT_SCHEMA = _ROOT / "docs" / "research" / "delivery-schema.json"


def sep(title: str) -> None:
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")


def main(mpn: str) -> None:
    print(f"\n{'*' * 80}")
    print(f"  FULL PIPELINE TRACE FOR MPN: {mpn}")
    print(f"{'*' * 80}\n")

    # ── Stage 0: Load input row ─────────────────────────────────────────────────
    sep("STAGE 0: INPUT ROW")
    with open(_DEFAULT_INPUT, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    row = next((r for r in rows if (r.get("Mfg_Part_Num") or "").strip() == mpn), None)
    if not row:
        print(f"  ERROR: MPN '{mpn}' not found in input CSV.")
        sys.exit(1)
    for k, v in row.items():
        if v:
            print(f"  {k}: {v!r}")

    # ── Stage 0.5: Wire services exactly as _build_pipeline does ───────────────
    sep("STAGE 0.5: PIPELINE WIRING (LIVE_DETERMINISTIC)")
    provider = build_provider(ExecutionMode.LIVE_DETERMINISTIC)
    print(f"  Provider:                   {type(provider).__name__}")
    print(
        f"  supports_unified_pre_enr:   {getattr(provider, 'supports_unified_pre_enrichment', False)}"
    )

    truth_service = ProductTruthService()
    source_obj = Source(
        source_id="raw_input",
        source_type=SourceType.SUPPLIED_INPUT,
        authority=SourceAuthority.HIGH,
    )
    product = truth_service.create_from_raw_input(
        product_id=f"trace-{mpn}",
        raw_values=dict(row),
        source=source_obj,
    )

    # Mirror _build_pipeline exactly
    domain_resolver = DomainResolver()
    circuit_breaker = DomainCircuitBreaker()
    fetcher = SourceFetcher()
    async_fetcher = AsyncSourceFetcher(circuit_breaker=circuit_breaker)
    extractor = EvidenceExtractor(provider=provider)
    source_disc = ProductSourceDiscoveryService(
        fetcher=fetcher,
        circuit_breaker=circuit_breaker,
    )
    disc_agent = ManufacturerDiscoveryAgent(provider=provider, resolver=domain_resolver)
    mfg_service = ManufacturerIntelligenceService(fetcher=fetcher, extractor=extractor)
    planner = AttributePlanner()
    enrichment_service = EnrichmentService(
        planner=planner,
        agent=EvidenceGroundedEnrichmentAgent(provider=provider),
        validator=ValidationPipeline(),
        truth_service=truth_service,
    )

    # ── Stage 1: Phase 4 ────────────────────────────────────────────────────────
    sep("STAGE 1: PHASE 4 — Understanding + Classification + Attributes")
    orchestrator = ProductOrchestrator(provider=provider, service=truth_service)
    product, phase4_job = orchestrator.run(product)
    print(f"  Phase 4 job state:          {phase4_job.state}")
    cls = product.classification
    print("\n  CLASSIFICATION:")
    print(f"    Dept:      {cls.department if cls else 'None'}")
    print(f"    Class:     {cls.class_name if cls else 'None'}")
    print(f"    Fine:      {cls.fine if cls else 'None'}")
    print(f"    Classpath: {' > '.join(cls.classpath) if cls and cls.classpath else 'None'}")
    print(f"\n  ATTRIBUTES FROM PHASE 4 ({len(product.attributes)}):")
    for attr in product.attributes:
        best = next(iter(attr.candidates), None)
        val = (best.normalized_value or best.raw_value) if best else "—"
        print(f"    {attr.canonical_name:<30} = {val!r}")
    if not product.attributes:
        print(
            "    -> NONE (DeterministicEvaluationProvider: no Gemini calls, no attribute extraction from raw text)"
        )

    # ── Stage 2: Brand Resolution ───────────────────────────────────────────────
    sep("STAGE 2: BRAND/MANUFACTURER RESOLUTION")
    resolver = BrandManufacturerResolver()
    raw_manuf = str(product.raw_value("Part_Manuf") or "")
    raw_desc = str(product.raw_value("Part_Desc") or "")
    resolved = resolver.resolve(raw_manuf, raw_desc, mpn=mpn)
    print(f"  raw Part_Manuf:             {raw_manuf!r}")
    print(f"  resolved.manufacturer:      {resolved.manufacturer!r}")
    print(f"  resolved.brand:             {resolved.brand!r}")
    print(f"  resolved.is_distributor:    {resolved.is_distributor}")

    # ── Stage 3: Phase 5 Discovery ──────────────────────────────────────────────
    sep("STAGE 3: PHASE 5 — Source Discovery")
    manufacturer_name = resolved.manufacturer or raw_manuf
    brand = resolved.brand
    print(f"  manufacturer_name:          {manufacturer_name!r}")
    print(f"  brand:                      {brand!r}")
    disc_result: DiscoveryResult | None = None
    try:
        disc_result = disc_agent.discover(
            manufacturer_id=manufacturer_name,
            manufacturer_name=manufacturer_name,
            mpn=mpn,
            description=raw_desc,
            brand=brand,
        )
        print(f"\n  Candidates:                 {len(disc_result.candidates)}")
        print(f"  Search requested:           {disc_result.search_requested}")
        print(f"  Unresolved reason:          {disc_result.unresolved_reason!r}")
        for i, c in enumerate(disc_result.candidates, 1):
            print(f"    [{i}] domain={c.domain!r}  status={c.status!r}")
    except Exception as e:
        print(f"  Discovery FAILED: {type(e).__name__}: {e}")

    # ── Stage 4: Source Binding ─────────────────────────────────────────────────
    sep("STAGE 4: SOURCE BINDING")
    verified_source: SourceRecord | None = None
    prof: ManufacturerProfile | None = None
    manufacturer_job = None

    if disc_result and disc_result.candidates:
        verified_candidates = tuple(
            c
            for c in disc_result.candidates
            if c.status == SourceDecision.VERIFIED_MANUFACTURER_SOURCE
        )
        candidate_candidates = tuple(
            c
            for c in disc_result.candidates
            if c.status == SourceDecision.CANDIDATE_MANUFACTURER_SOURCE
        )
        print(f"  Verified domain candidates: {len(verified_candidates)}")
        print(f"  Candidate domain candidates:{len(candidate_candidates)}")

        if verified_candidates or candidate_candidates:
            mfg_id = manufacturer_name or "unknown"
            prof = ManufacturerProfile(
                manufacturer_id=mfg_id,
                canonical_name=mfg_id,
                verified_domains=tuple(c.domain for c in verified_candidates),
                candidate_domains=tuple(c.domain for c in candidate_candidates),
            )
            source_candidates = source_disc.discover(
                product, prof, candidate_urls=disc_result.search_result_urls
            )
            print(f"\n  source_disc.discover() returned {len(source_candidates)} page candidates:")
            for sc in source_candidates[:5]:
                print(f"    {sc.url!r}  kind={sc.source_kind!r}")

            if source_candidates:
                best = source_candidates[0]
                best_domain = _host(best.url)
                is_secondary = (
                    best.source_kind == SourceKind.DISTRIBUTOR_PRODUCT_PAGE
                    or not prof.verified_domains
                    or not any(_same_or_subdomain(best_domain, d) for d in prof.verified_domains)
                )
                cand_rec = SourceRecord(
                    canonical_url=best.url,
                    original_url=best.url,
                    source_kind=SourceKind.DISTRIBUTOR_PRODUCT_PAGE
                    if is_secondary
                    else best.source_kind,
                    decision=SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE
                    if is_secondary
                    else SourceDecision.CANDIDATE_MANUFACTURER_SOURCE,
                    manufacturer_id=prof.manufacturer_id,
                    manufacturer_domain=best_domain,
                    verified_domains=prof.verified_domains if not is_secondary else (),
                    product_id=product.product_id,
                )
                if is_secondary:
                    vs = SourceVerifier().verify_secondary_source(cand_rec, prof)
                    if vs.decision == SourceDecision.SECONDARY_DISTRIBUTOR_SOURCE:
                        verified_source = vs
                else:
                    vs = SourceVerifier().verify_source(cand_rec, prof)
                    if vs.decision == SourceDecision.VERIFIED_MANUFACTURER_SOURCE:
                        verified_source = vs

                print(f"\n  is_secondary:               {is_secondary}")
                print(f"  Binding succeeded:          {verified_source is not None}")
                if verified_source:
                    print(f"  canonical_url:              {verified_source.canonical_url!r}")
                    print(f"  decision:                   {verified_source.decision!r}")
            else:
                print("  -> source_disc.discover() found 0 page candidates. Binding fails here.")

        if verified_source and prof:
            print("\n  Running ManufacturerIntelligenceService.process()...")
            product, manufacturer_job = mfg_service.process(product, verified_source, prof)
            print(f"  ManufacturerJob state:      {manufacturer_job.state}")
            print(f"  ManufacturerJob error:      {manufacturer_job.error!r}")
            vsc = manufacturer_job.verified_source_context
            print("\n  VerifiedProductSourceContext:")
            if vsc is None:
                print("    -> None (fetch failed or product MPN not found on page)")
            else:
                print(f"    canonical_product_url:    {vsc.canonical_product_url!r}")
                print(f"    page_title:               {vsc.page_title!r}")
                print(f"    page_description:         {vsc.page_description!r}")
                print(f"    page_text length:         {len(vsc.page_text or '')} chars")
                print(f"    source_authority:         {vsc.source_authority!r}")
                print(f"    document_urls ({len(vsc.document_urls or [])}):")
                for u in (vsc.document_urls or [])[:5]:
                    print(f"      {u!r}")
                print(f"    image_urls ({len(vsc.image_urls or [])}):")
                for u in (vsc.image_urls or [])[:3]:
                    print(f"      {u!r}")
                print(f"    structured_facts ({len(vsc.structured_facts or [])} rows):")
                for fact in (vsc.structured_facts or [])[:20]:
                    print(f"      {fact.get('attribute')}: {fact.get('raw_value')!r}")
                print(f"    evidence_references ({len(vsc.evidence_references or [])}):")
                for er in (vsc.evidence_references or [])[:5]:
                    print(
                        f"      [{er.evidence_id}] url={er.source_url!r} text={str(er.evidence_text)[:80]!r}"
                    )
    else:
        print("  No candidates from discovery. Binding skipped.")

    # ── Stage 5: Phase 6 Enrichment ────────────────────────────────────────────
    sep("STAGE 5: PHASE 6 — Enrichment")
    source_ctx = manufacturer_job.verified_source_context if manufacturer_job else None
    print(f"  VerifiedSourceContext passed:{source_ctx is not None}")
    enrichment_result = enrichment_service.enrich(product, source_context=source_ctx)
    print(f"  Enrichment status:          {enrichment_result.status}")
    print(f"  Planned attributes:         {enrichment_result.metrics.planned_attributes}")
    print(f"  Enriched attributes:        {enrichment_result.metrics.enriched_attributes}")
    print(f"  Accepted candidates:        {enrichment_result.metrics.accepted_candidates}")
    pt = enrichment_result.product_truth
    print(f"\n  Attributes in ProductTruth ({len(pt.attributes)}):")
    for attr in pt.attributes:
        best = next(iter(attr.candidates), None)
        val = (best.normalized_value or best.raw_value) if best else "—"
        print(f"    {attr.canonical_name:<30} = {val!r}")
    if not pt.attributes:
        print("    -> NONE")

    # ── Stage 6: Descriptions ───────────────────────────────────────────────────
    sep("STAGE 6: DESCRIPTIONS")
    d = pt.descriptions
    if d:
        print(f"  short:          {d.short!r}")
        print(f"  long (120):     {(d.long or '')[:120]!r}")
        print(f"  mobile:         {d.mobile!r}")
        print(f"  invoice:        {d.invoice!r}")
        print(f"  retail:         {d.retail!r}")
        print(f"  marketing (120):{(d.marketing or '')[:120]!r}")
        print(f"  features ({len(d.features)}):")
        for i, feat in enumerate(d.features, 1):
            print(f"    {i}. {feat!r}")
    else:
        print("  -> None")

    # ── Stage 7: Delivery Adapter ───────────────────────────────────────────────
    sep("STAGE 7: DELIVERY ADAPTER — 252 columns")
    fake_result = SimpleNamespace(
        product_truth=pt,
        phase4_job=phase4_job,
        discovery=disc_result,
        manufacturer_job=manufacturer_job,
        enrichment=enrichment_result,
        resolved_manufacturer=resolved.manufacturer if resolved else None,
        resolved_brand=resolved.brand if resolved else None,
        is_distributor_masked=resolved.is_distributor if resolved else False,
    )
    contract = DeliverySchemaContract.from_json(_DEFAULT_SCHEMA)
    adapter = Phase65ResultDeliveryAdapter(contract)
    record = adapter.to_record(fake_result)
    row_out = dict(zip(record.headers, record.as_row()))
    populated = {k: v for k, v in row_out.items() if v is not None and v != ""}
    print(f"  Populated (non-empty):      {len(populated)} / 252")
    print("\n  All populated delivery fields:")
    for k, v in populated.items():
        print(f"    {k:<35} = {str(v)[:100]!r}")

    # ── Diagnosis ───────────────────────────────────────────────────────────────
    sep("DIAGNOSIS — ROOT CAUSE SUMMARY")
    print(f"  Phase 4 state:              {phase4_job.state}")
    print(f"  Phase 4 attributes found:   {len(product.attributes)}")
    print(f"  Discovery candidates:       {len(disc_result.candidates) if disc_result else 0}")
    print(f"  Source binding:             {verified_source is not None}")
    print(f"  VerifiedSourceContext:      {source_ctx is not None}")
    print(f"  Phase 6 enriched attrs:     {enrichment_result.metrics.enriched_attributes}")
    print(f"  Delivery populated fields:  {len(populated)} / 252")

    if phase4_job.state in ("failed", "FAILED"):
        print("\n  *** PHASE 4 FAILED. DeterministicEvaluationProvider returns no attributes.")
    if not disc_result or not disc_result.candidates:
        print("\n  *** PHASE 5: Domain UNRESOLVED — no known Whirlpool domain in DomainResolver.")
    elif not verified_source:
        print(
            "\n  *** PHASE 5: Domain resolved but no verified source page returned for this MPN URL."
        )
    elif source_ctx is None:
        print(
            "\n  *** PHASE 5: Source bound but VerifiedSourceContext is None (fetch or verification failed)."
        )
    elif enrichment_result.metrics.enriched_attributes == 0:
        print("\n  *** PHASE 6: Source context present but 0 attributes enriched.")
        print(
            "      This means the deterministic spec extractor found no structured table on the page."
        )
        print("      Gemini (live-gemini mode) is needed to extract attributes from HTML prose.")
    print("\n  Solution: run with GEMINI_API_KEY + --mode live-gemini to get full enrichment.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Full pipeline trace for a single MPN.")
    parser.add_argument("mpn", help="MPN to trace (e.g. WDTS7024RZ)")
    args = parser.parse_args()
    main(args.mpn)
