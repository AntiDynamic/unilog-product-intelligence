# UNILOG 50-Row Live Benchmark Evaluation Report

## 1. Executive Summary

- **Evaluated Rows:** 50 raw challenge products from `Unihack_ Sample Dataset - Input.csv`.
- **Execution Mode:** LIVE internet retrieval against authoritative manufacturer domains (real HTTP sockets).
- **Schema Compliance:** 252/252 columns matching official 252-column schema.
- **ENRICHED Products:** 40 (Row 2 Diablo Sanding Belt).
- **REVIEW_REQUIRED Products:** 10.
- **BLOCKED / Errors:** 0 / 0.

---

## 2. Key Metrics Summary

| Metric Category | Metric | Value |
|---|---|---|
| **Identity** | Manufacturer Accuracy | 32.0% (16/50) |
| **Identity** | Brand Accuracy | 100.0% (50/50) |
| **Identity** | MPN Integrity | 100.0% |
| **Identity** | Taxonomy Classpath | 100.0% |
| **Retrieval** | Domain Resolution Rate | 100.0% (50/50) |
| **Retrieval** | Authoritative Source Discovery | 80.0% (40/50) |
| **Enrichment** | Products with Authoritative Evidence | 40 (80.0%) |
| **Enrichment** | Total Attributes Populated | 93 |
| **Delivery** | Avg Non-Empty Fields / Product | 19.58 / 252 |
| **Delivery** | Avg Output Completeness | 7.77% |

---

## 3. Failure Taxonomy & Root Causes

| Failure Category | Affected Rows | Share of Batch | Root Cause |
|---|---|---|---|
| `SOURCE_NOT_FOUND for 3M (Rows 3-8) & Mirka (Rows 9-12)` | 10 | 20.0% | 3m.com and mirka.com drops or redirects crawler requests without search link resolution. |

---

## 4. Distributor Cases Analysis

| Row | Raw Part_Manuf | Description Brand Token | Resolved Manufacturer | Resolved Brand | Status |
|---|---|---|---|---|---|
| Row 3 | Jam Industrial Supply LLC (JAMIN) | 3M 775L Stikit Film P150 - Cub... | `3m` | `3M` | `REVIEW_REQUIRED` |
| Row 4 | Jam Industrial Supply LLC (JAMIN) | 3M 775L Stikit Film P120 - Cub... | `3m` | `3M` | `REVIEW_REQUIRED` |
| Row 5 | Jam Industrial Supply LLC (JAMIN) | 3M 775L Stikit Film P80 - Cubi... | `3m` | `3M` | `REVIEW_REQUIRED` |
| Row 6 | Jam Industrial Supply LLC (JAMIN) | 3M 775L Stikit Film P180 - Cub... | `3m` | `3M` | `REVIEW_REQUIRED` |
| Row 7 | Jam Industrial Supply LLC (JAMIN) | 3M 775L Stikit Film P220 - Cub... | `3m` | `3M` | `REVIEW_REQUIRED` |
| Row 8 | Jam Industrial Supply LLC (JAMIN) | 3M 775L Stikit Film P320 - Cub... | `3m` | `3M` | `REVIEW_REQUIRED` |
| Row 9 | Mirka Abrasives Inc (MIRUS) | 5B-332-080 HIOLIT 5" P80... | `mirka abrasives` | `Mirka` | `REVIEW_REQUIRED` |
| Row 10 | Mirka Abrasives Inc (MIRUS) | 5B-332-120 HIOLIT 5" P120... | `mirka abrasives` | `Mirka` | `REVIEW_REQUIRED` |
| Row 11 | Mirka Abrasives Inc (MIRUS) | 9A-570-240 Abranet 2.75x30... | `mirka abrasives` | `Mirka` | `REVIEW_REQUIRED` |
| Row 12 | Mirka Abrasives Inc (MIRUS) | 9A-570-320 Abranet 2.75x30... | `mirka abrasives` | `Mirka` | `REVIEW_REQUIRED` |

---

## 5. Row-by-Row Execution Traces (Sample)

| Row | MPN | Input Manufacturer | Resolved Manufacturer | Brand | MFR URL | Populated Attrs | Status |
|---|---|---|---|---|---|---|---|
| 2 | `DCB518ASTS06G` | Freud Inc (2435) | `Freud Inc` | `Diablo` | https://diablotools.com/products... | 15 | `ENRICHED` |
| 3 | `3MABR-7100075678` | Jam Industrial Suppl | `3m` | `3M` | None | 0 | `REVIEW_REQUIRED` |
| 4 | `3MABR-7100045865` | Jam Industrial Suppl | `3m` | `3M` | None | 0 | `REVIEW_REQUIRED` |
| 5 | `3MABR-7100048736` | Jam Industrial Suppl | `3m` | `3M` | None | 0 | `REVIEW_REQUIRED` |
| 6 | `3MABR-7100075690` | Jam Industrial Suppl | `3m` | `3M` | None | 0 | `REVIEW_REQUIRED` |
| 7 | `3MABR-7100075692` | Jam Industrial Suppl | `3m` | `3M` | None | 0 | `REVIEW_REQUIRED` |
| 8 | `3MABR-7100145365` | Jam Industrial Suppl | `3m` | `3M` | None | 0 | `REVIEW_REQUIRED` |
| 9 | `5B-332-080` | Mirka Abrasives Inc  | `mirka abrasives` | `Mirka` | None | 0 | `REVIEW_REQUIRED` |
| 10 | `5B-332-120` | Mirka Abrasives Inc  | `mirka abrasives` | `Mirka` | None | 0 | `REVIEW_REQUIRED` |
| 11 | `9A-570-240` | Mirka Abrasives Inc  | `mirka abrasives` | `Mirka` | None | 0 | `REVIEW_REQUIRED` |
| 12 | `9A-570-320` | Mirka Abrasives Inc  | `mirka abrasives` | `Mirka` | None | 0 | `REVIEW_REQUIRED` |
| 13 | `DBD090094101F` | Freud Inc (2435) | `Freud Inc` | `Diablo` | https://diablotools.com/products... | 2 | `ENRICHED` |
| 14 | `DBDS12125A01F` | Freud Inc (2435) | `Freud Inc` | `Diablo` | https://diablotools.com/products... | 2 | `ENRICHED` |
| 15 | `DBDS12125G01F` | Freud Inc (2435) | `Freud Inc` | `Diablo` | https://diablotools.com/products... | 2 | `ENRICHED` |
| 16 | `DBDS14125A01F` | Freud Inc (2435) | `Freud Inc` | `Diablo` | https://diablotools.com/products... | 2 | `ENRICHED` |
| 17 | `DBDS14125G01F` | Freud Inc (2435) | `Freud Inc` | `Diablo` | https://diablotools.com/products... | 2 | `ENRICHED` |
| 18 | `49-94-0013` | Milwaukee Accessory  | `Milwaukee Accessory` | `Milwaukee` | https://www.milwaukeetool.com/pr... | 2 | `ENRICHED` |
| 19 | `49-94-0029` | Milwaukee Accessory  | `Milwaukee Accessory` | `Milwaukee` | https://www.milwaukeetool.com/pr... | 2 | `ENRICHED` |
| 20 | `49-94-0033` | Milwaukee Accessory  | `Milwaukee Accessory` | `Milwaukee` | https://www.milwaukeetool.com/pr... | 2 | `ENRICHED` |
| 21 | `49-94-0001` | Milwaukee Accessory  | `Milwaukee Accessory` | `Milwaukee` | https://www.milwaukeetool.com/pr... | 2 | `ENRICHED` |

---

## 6. High-Priority Action Item (#1 Bottleneck)

**Bottleneck #1 (34/50 rows = 68% of failures):** `Milwaukee Accessory (4031)` and description abbreviation `Milw` are not recognized as `Milwaukee Tool` (`milwaukeetool.com`).

**Proposed Fix:**
1. In `brand_resolver.py`: add `Milw` brand token regex `r'\bMilw\b'` mapping to `('milwaukee', 'Milwaukee')`.
2. In `core.py`: add `'milwaukee accessory'` and `'milwaukee accessories'` to `_known_manufacturer_domains` pointing to `('milwaukeetool.com',)`. Clean account code suffix `(4031)` in manufacturer key normalization.
3. In `source_discovery.py`: support MPN format with hyphens for Milwaukee (e.g. `49-94-0013` -> `/products/{mpn}` and search patterns).