# UNILOG 50-Row Live Retrieval & Delivery Benchmark Evaluation

**Execution Mode**: `LIVE_GEMINI`  
**Sample Size**: 5 products  
**Delivery Schema Columns**: 252/252 matching  

---

## Executive Summary

| Metric Area | Metric Name | Measured Value | Trust / Status |
| :--- | :--- | :--- | :--- |
| **Identity** | Manufacturer Resolved Rate | **100.0%** (5/5) | Measured (Normalized value) |
| **Identity** | Brand Resolved Rate | **100.0%** (5/5) | Measured |
| **Identity** | MPN Integrity Rate | **100.0%** (Exact: 5, Norm: 0, Diff: 0) | Measured (No substring collision) |
| **Taxonomy** | Classpath Generated Rate | **0.0%** (Avg Depth: 0.0) | Structural Depth |
| **Retrieval** | Verified Domain Resolution Rate | **20.0%** (1/5) | Verified Allowlist Only |
| **Retrieval** | Authoritative Source Discovery | **20.0%** (1/5) | Verified Domain + SourcePolicy |
| **Retrieval** | Exact Product Verification | **0.0%** (0/5) | ProductIdentityMatcher |
| **Evidence** | Products with Valid Evidence | **0.0%** (0/5) | Authoritative Graph Only |
| **Evidence** | Total Evidence Items Extracted | **0** (Avg: 0.0/enriched) | Quoted & Source-backed |
| **Enrichment**| Attributes Populated in CSV | **33** (Avg: 6.6/product) | Delivery Triplets |
| **Delivery** | Overall Delivery Completeness | **10.4%** (Avg: 26.2/252 fields) | Non-empty Delivery Fields |

---

## Multi-Dimensional Delivery Completeness

| Section | Completeness (%) | Description |
| :--- | :--- | :--- |
| **Core Identity** | **66.67%** | PART_NUMBER, Mfg_Part_Num, MANUFACTURER_NAME, BRAND_NAME, Product Name |
| **Taxonomy** | **0.0%** | Dept, Class, Fine, Classpath, UNSPSC |
| **Descriptions** | **0.0%** | SHORT_DESC, LONG_DESC1, MOBILE_DESC, INVOICE_DESC, etc. |
| **Features** | **0.0%** | ITEM_FEATURES_1 through ITEM_FEATURES_20 |
| **Attributes** | **9.07%** | ATTRIBUTE_LABEL 1..50, ATTRIBUTE_VALUE 1..50, ATTRIBUTE_UOM 1..50 |
| **URLs** | **3.33%** | MFR URL, Ref URL 1..5 |
| **Assets & Documents** | **0.0%** | Specification Sheet, Manuals, SDS, Images, CAD drawings |
| **Commercial & Packaging** | **24.71%** | SKU, Packaging, Dimensions, Weights, Volumes |
| **Overall Average** | **10.4%** | Average across all 252 observed delivery columns |

---

## Pipeline Status Distribution

- **ENRICHED**: 1 (20.0%)
- **REVIEW_REQUIRED**: 4 (80.0%)
- **BLOCKED**: 0
- **ERRORS**: 0

### Failure Root Cause Breakdown

- `SOURCE_NOT_FOUND`: 4 products (80.0%)

---

## Ground Truth Availability Notice

- Ground Truth Reference Records in File: **2**
- Ground Truth Matches in 50-Row Sample: **0**
> [!NOTE]
> When ground truth reference rows are not available for a given product row, accuracy metrics are reported as `null`/uncalculated rather than fabricated.
