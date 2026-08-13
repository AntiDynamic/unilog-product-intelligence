# Phase 1 data-foundation findings

Checked on 2026-08-14 in the Windows workspace for
`AntiDynamic/unilog-product-intelligence`.

## Source availability

The challenge specification names the following runtime files, including the input and official
delivery CSVs. None were accessible at `/mnt/data` or in the common local locations searched:

- `Unihack_ Sample Dataset - Input.csv`
- `Unihack_ Expected Output - Delivery Format.csv`
- `Sample-1000_Items.xlsx`
- `Unilog-Sample_200_Items-Input-vs-Output.xlsx`
- `UNILOG_INTERNAL_CONTENT_GUIDELINES.docx`
- `Unilog_Master_UOM_Standards_Abbreviations_and_Terms.xlsx`
- `Decimal_Fraction.xlsx`
- `UniCat_Manufacturer_and_Brand_List.xlsx`
- `Unicat_Lov_v1_0_Updated_With_Remarks.xlsx`
- `FAUCETS_LOV.xlsx`
- `Fittings_LOV.xlsx`
- `Reference_Documents_Summary.xlsx`

This is a runtime availability discrepancy, not a conclusion that the files do not exist
elsewhere. The machine-readable report is `docs/research/data-inventory.json`.

## Implemented inspection behavior

When a file exists, the inventory generator computes metrics from the file itself. CSV uses its
exact first row as the header. XLSX inspection records worksheet names, a detected header row,
leading rows, merged ranges, and row/column counts. It also reports null counts, known-placeholder
counts, unique counts, duplicate row counts, representative values, SHA-256, and inferred value
types.

## Source-truth rules

The readers preserve raw values. The normalization layer maps the official placeholder strings to
`null` only in the normalized view and records `reason: placeholder`. The raw value remains in the
row contract and in the planned `raw_product_inputs` JSONB storage.

The official delivery file is treated as an external contract. Its exact header order must be
extracted from the actual CSV and stored once in a JSON schema definition. No delivery headers are
hard-coded in the application because the actual file is unavailable in this runtime.

