# Runtime data inventory

Checked during Phase 0 on 2026-08-14 from the Windows workspace.

## Result

The requested `/mnt/data` directory is not mounted or available in this runtime. No real input
or delivery CSV was copied into the repository, and no product records were invented.

## Expected files from the challenge specification

The next data-foundation execution should look for these files when they are made available:

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

Phase 1 must record availability, headers, row counts, and checksums for files actually present.
It must treat the supplied delivery CSV as an immutable external output contract.


## Current Windows audit

The two supplied CSVs are now available as local/private runtime files. They are not tracked or
published. The official reference files remain unavailable; see `reference-pack-audit.json` for
current hashes, parser checks, and the exact roots scanned. The `/mnt/data` statement above is the
historical Phase 0 observation.