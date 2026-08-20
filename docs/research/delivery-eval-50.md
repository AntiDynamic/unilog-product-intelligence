# UNILOG 50-Row Live Retrieval & Delivery Benchmark Evaluation

**Execution Mode**: `LIVE_DETERMINISTIC`  
**Sample Size**: 50 products  
**Delivery Schema Columns**: 252/252 matching  

---

## Executive Summary

| Metric Area | Metric Name | Measured Value | Trust / Status |
| :--- | :--- | :--- | :--- |
| **Truth & Safety** | Unsupported Published Claims | **0** (0.0%) | **0.0% Hard Invariant** |
| **Truth & Safety** | Truth Audit Pass Rate | **100.0%** (1 audited) | Grounded Provenance Gate |
| **Identity** | Manufacturer Resolved Rate | **100.0%** (50/50) | Measured (Normalized value) |
| **Identity** | Brand Resolved Rate | **100.0%** (50/50) | Measured |
| **Identity** | MPN Integrity Rate | **100.0%** (Exact: 50, Norm: 0, Diff: 0) | Measured (No substring collision) |
| **Taxonomy** | Classpath Generated Rate | **100.0%** (Avg Depth: 3.0) | Structural Depth |
| **Retrieval** | Verified Domain Resolution Rate | **88.0%** (44/50) | Verified Allowlist Only |
| **Retrieval** | Authoritative Source Discovery | **2.0%** (1/50) | Verified Domain + SourcePolicy |
| **Retrieval** | Exact Product Verification | **0.0%** (0/50) | ProductIdentityMatcher |
| **Evidence** | Products with Valid Evidence | **0.0%** (0/50) | Authoritative Graph Only |
| **Evidence** | Total Evidence Items Extracted | **0** (Avg: 0.0/enriched) | Quoted & Source-backed |
| **Enrichment**| Attributes Populated in CSV | **15** (Avg: 0.3/product) | Delivery Triplets |
| **Delivery** | Overall Delivery Completeness | **8.79%** (Avg: 22.14/252 fields) | Non-empty Delivery Fields |

---

## Multi-Dimensional Delivery Completeness

| Section | Completeness (%) | Description |
| :--- | :--- | :--- |
| **Core Identity** | **67.0%** | PART_NUMBER, Mfg_Part_Num, MANUFACTURER_NAME, BRAND_NAME, Product Name |
| **Taxonomy** | **80.0%** | Dept, Class, Fine, Classpath, UNSPSC |
| **Descriptions** | **100.0%** | SHORT_DESC, LONG_DESC1, MOBILE_DESC, INVOICE_DESC, etc. |
| **Features** | **2.0%** | ITEM_FEATURES_1 through ITEM_FEATURES_20 |
| **Attributes** | **0.41%** | ATTRIBUTE_LABEL 1..50, ATTRIBUTE_VALUE 1..50, ATTRIBUTE_UOM 1..50 |
| **URLs** | **0.33%** | MFR URL, Ref URL 1..5 |
| **Assets & Documents** | **0.08%** | Specification Sheet, Manuals, SDS, Images, CAD drawings |
| **Commercial & Packaging** | **20.76%** | SKU, Packaging, Dimensions, Weights, Volumes |
| **Overall Average** | **8.79%** | Average across all 252 observed delivery columns |

---

## Pipeline Status Distribution

- **ENRICHED**: 1 (2.0%)
- **REVIEW_REQUIRED**: 49 (98.0%)
- **BLOCKED**: 0
- **ERRORS**: 0

### Failure Root Cause Breakdown

- `SOURCE_NOT_FOUND`: 49 products (98.0%)

---

## Ground Truth Availability Notice

- Ground Truth Reference Records in File: **2**
- Ground Truth Matches in 50-Row Sample: **0**
> [!NOTE]
> When ground truth reference rows are not available for a given product row, accuracy metrics are reported as `null`/uncalculated rather than fabricated.
