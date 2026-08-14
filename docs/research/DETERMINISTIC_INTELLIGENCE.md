# Deterministic intelligence boundaries

Deterministic processing precedes model-assisted enrichment. Its job is to preserve source values,
normalize only reversible presentation differences, identify explicit gaps, and collect reviewable
signals. It does not infer product facts.

## Registry contract

Each reference registry accepts traceable `ReferenceRecord` entries with a record ID, canonical
name, aliases, optional code, optional manufacturer context, and source ID. A registry that has not
loaded approved reference material reports `reference_data_unavailable`; it is not treated as empty
reference data.

Resolution tries exact, normalized exact, and punctuation-canonical matches. A unique match may
resolve. Multiple matches are ambiguous. Fuzzy similarity is returned only as an ambiguous review
candidate, with no canonical record selected.

## Identity and values

MPNs are normalized only for Unicode, whitespace, and case. Duplicate assessment uses a normalized
MPN plus manufacturer signal and returns an assessment, never a merge. Mathematical decimal/fraction
conversion is marked `calculated`; it must not be presented as an official UniLog fraction mapping.

The delivery adapter preserves the observed delivery header sequence. It currently projects raw
input fields only where their names already occur in the official template. Semantic mapping and
enrichment fields require approved reference data and evidence.
