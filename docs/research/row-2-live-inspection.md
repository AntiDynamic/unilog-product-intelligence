# Row-2 Live Inspection: `row-2`

## 1. Input

```json
{
  "Mfg_Part_Num": "DCB518ASTS06G",
  "Part_Desc": "DCB518ASTS06G Diablo 1/2\"x18\" - Sanding Belt 6pc",
  "E1_Brand": "-- Unbranded --",
  "Unilog_Brand": "-- No Unilog Brand --",
  "DIB_Brand": "-- No DIB Brand --",
  "Part_Manuf": "Freud Inc (2435)"
}
```

State: `candidates_accepted`. This is an inspectability report, not a correctness claim.

## 2. Product understanding

[
  {
    "task": "product_understanding",
    "agent": "product_understanding",
    "model": "gemini-3.5-flash-lite",
    "prompt_version": "v1",
    "request_id": "v1_ChdJN2VBYXN6d0wtN2RnOFVQazltZDRRZxIXSTdlQWFzendMLTdkZzhVUGs5bWQ0UWc",
    "status": "succeeded",
    "latency_ms": 5764,
    "retry_count": 0,
    "provider_attempt_count": null,
    "input_tokens": null,
    "output_tokens": null,
    "cached_tokens": null,
    "thought_tokens": null,
    "tool_use_tokens": null,
    "total_tokens": null,
    "structured_output": {
      "product_type": "Sanding Belt",
      "product_family": "Diablo",
      "semantic_features": [
        "1/2\"x18\"",
        "6pc"
      ],
      "evidence": [
        {
          "field_name": "product_type",
          "quoted_text": "Sanding Belt",
          "kind": "directly_present"
        },
        {
          "field_name": "product_family",
          "quoted_text": "Diablo",
          "kind": "directly_present"
        },
        {
          "field_name": "semantic_features",
          "quoted_text": "1/2\"x18\"",
          "kind": "directly_present"
        },
        {
          "field_name": "semantic_features",
          "quoted_text": "6pc",
          "kind": "directly_present"
        }
      ],
      "uncertain_items": []
    },
    "error": null
  }
]

## 3. Classification

[
  {
    "task": "classification",
    "agent": "classification",
    "model": "gemini-3.5-flash-lite",
    "prompt_version": "v1",
    "request_id": "v1_ChdLYmVBYXZUQUxjR21qdU1QNEphUGlRNBIXS2JlQWF2VEFMY0dtanVNUDRKYVBpUTQ",
    "status": "succeeded",
    "latency_ms": 4055,
    "retry_count": 0,
    "provider_attempt_count": null,
    "input_tokens": null,
    "output_tokens": null,
    "cached_tokens": null,
    "thought_tokens": null,
    "tool_use_tokens": null,
    "total_tokens": null,
    "structured_output": {
      "candidates": [],
      "selected_candidate": null,
      "unresolved_reason": "Taxonomy context is unavailable."
    },
    "error": null
  }
]

```json
{
  "status": "REFERENCE_DATA_UNAVAILABLE",
  "output": {
    "candidates": [],
    "selected_candidate": null,
    "unresolved_reason": "Taxonomy context is unavailable."
  },
  "source_ids": [
    "input-Unihack_ Sample Dataset - Input.csv"
  ],
  "evidence_ids": [],
  "validation_state": "PENDING",
  "note": "Official taxonomy/LOV correctness is not established by this run."
}
```

## 4. Extracted attributes

### 1. Manufacturer Part Number

- Raw: `DCB518ASTS06G`
- Normalized: `DCB518ASTS06G`
- UOM: `None`
- Status: `CANDIDATE`; origin: `INPUT_DATA`; correctness: `DIRECTLY_SUPPORTED_BY_INPUT`
- Evidence: `AVAILABLE`; source IDs: `['input-Unihack_ Sample Dataset - Input.csv']`; evidence IDs: `['ad2853f7-d849-4c30-b6bd-eaf334180cb7']`
- Agent/model/prompt: `attribute_extraction` / `gemini-3.5-flash-lite` / `v1`
- Validation:
```json
[
  {
    "validation_id": "inspection-manufacturer-part-number-evidence",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "Quoted evidence is attached.",
    "rule": "candidate must retain evidence linkage",
    "actual_value": [
      "ad2853f7-d849-4c30-b6bd-eaf334180cb7"
    ],
    "expected_condition": "at least one evidence ID"
  },
  {
    "validation_id": "inspection-manufacturer-part-number-source",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "A source reference is attached; authority is assessed separately.",
    "rule": "candidate must retain source linkage",
    "actual_value": [
      "input-Unihack_ Sample Dataset - Input.csv"
    ],
    "expected_condition": "at least one source ID"
  },
  {
    "validation_id": "inspection-manufacturer-part-number-normalization",
    "validator": "inspection",
    "status": "NOT_APPLIED",
    "severity": "INFO",
    "message": "No distinct normalization was applied.",
    "rule": "only documented deterministic normalization may pass",
    "actual_value": "DCB518ASTS06G",
    "expected_condition": "a documented deterministic normalization rule"
  },
  {
    "validation_id": "inspection-manufacturer-part-number-uom",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No unit of measure was returned.",
    "rule": "attribute unit must be explicit before unit validation",
    "actual_value": null,
    "expected_condition": "a supported unit of measure"
  },
  {
    "validation_id": "inspection-manufacturer-part-number-lov",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No official attribute LOV/reference data was available in this run.",
    "rule": "attribute value must be checked against an official LOV",
    "actual_value": "DCB518ASTS06G",
    "expected_condition": "official LOV/reference data"
  },
  {
    "validation_id": "inspection-manufacturer-part-number-conflict",
    "validator": "inspection",
    "status": "NONE",
    "severity": "INFO",
    "message": "No conflict was recorded for this attribute.",
    "rule": "candidate must not have unresolved source/value conflicts",
    "actual_value": null,
    "expected_condition": "no open conflict"
  },
  {
    "validation_id": "inspection-manufacturer-part-number-manufacturer-source",
    "validator": "inspection",
    "status": "NOT_AVAILABLE",
    "severity": "WARNING",
    "message": "No manufacturer evidence is associated with this candidate.",
    "rule": "input data must not be treated as manufacturer verification",
    "actual_value": null,
    "expected_condition": "verified manufacturer source"
  }
]
```

### 2. Product Description

- Raw: `DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc`
- Normalized: `DCB518ASTS06G Diablo 1/2"x18" - Sanding Belt 6pc`
- UOM: `None`
- Status: `CANDIDATE`; origin: `INPUT_DATA`; correctness: `DIRECTLY_SUPPORTED_BY_INPUT`
- Evidence: `AVAILABLE`; source IDs: `['input-Unihack_ Sample Dataset - Input.csv']`; evidence IDs: `['f340043a-b3e7-4a83-8abb-66dbbb86de35']`
- Agent/model/prompt: `attribute_extraction` / `gemini-3.5-flash-lite` / `v1`
- Validation:
```json
[
  {
    "validation_id": "inspection-product-description-evidence",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "Quoted evidence is attached.",
    "rule": "candidate must retain evidence linkage",
    "actual_value": [
      "f340043a-b3e7-4a83-8abb-66dbbb86de35"
    ],
    "expected_condition": "at least one evidence ID"
  },
  {
    "validation_id": "inspection-product-description-source",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "A source reference is attached; authority is assessed separately.",
    "rule": "candidate must retain source linkage",
    "actual_value": [
      "input-Unihack_ Sample Dataset - Input.csv"
    ],
    "expected_condition": "at least one source ID"
  },
  {
    "validation_id": "inspection-product-description-normalization",
    "validator": "inspection",
    "status": "NOT_APPLIED",
    "severity": "INFO",
    "message": "No distinct normalization was applied.",
    "rule": "only documented deterministic normalization may pass",
    "actual_value": "DCB518ASTS06G Diablo 1/2\"x18\" - Sanding Belt 6pc",
    "expected_condition": "a documented deterministic normalization rule"
  },
  {
    "validation_id": "inspection-product-description-uom",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No unit of measure was returned.",
    "rule": "attribute unit must be explicit before unit validation",
    "actual_value": null,
    "expected_condition": "a supported unit of measure"
  },
  {
    "validation_id": "inspection-product-description-lov",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No official attribute LOV/reference data was available in this run.",
    "rule": "attribute value must be checked against an official LOV",
    "actual_value": "DCB518ASTS06G Diablo 1/2\"x18\" - Sanding Belt 6pc",
    "expected_condition": "official LOV/reference data"
  },
  {
    "validation_id": "inspection-product-description-conflict",
    "validator": "inspection",
    "status": "NONE",
    "severity": "INFO",
    "message": "No conflict was recorded for this attribute.",
    "rule": "candidate must not have unresolved source/value conflicts",
    "actual_value": null,
    "expected_condition": "no open conflict"
  },
  {
    "validation_id": "inspection-product-description-manufacturer-source",
    "validator": "inspection",
    "status": "NOT_AVAILABLE",
    "severity": "WARNING",
    "message": "No manufacturer evidence is associated with this candidate.",
    "rule": "input data must not be treated as manufacturer verification",
    "actual_value": null,
    "expected_condition": "verified manufacturer source"
  }
]
```

### 3. Width

- Raw: `1/2"`
- Normalized: `1/2`
- UOM: `in`
- Status: `CANDIDATE`; origin: `INPUT_DATA`; correctness: `DIRECTLY_SUPPORTED_BY_INPUT`
- Evidence: `AVAILABLE`; source IDs: `['input-Unihack_ Sample Dataset - Input.csv']`; evidence IDs: `['7ff08b00-477a-4c95-894f-4798346bddad']`
- Agent/model/prompt: `attribute_extraction` / `gemini-3.5-flash-lite` / `v1`
- Validation:
```json
[
  {
    "validation_id": "inspection-width-evidence",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "Quoted evidence is attached.",
    "rule": "candidate must retain evidence linkage",
    "actual_value": [
      "7ff08b00-477a-4c95-894f-4798346bddad"
    ],
    "expected_condition": "at least one evidence ID"
  },
  {
    "validation_id": "inspection-width-source",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "A source reference is attached; authority is assessed separately.",
    "rule": "candidate must retain source linkage",
    "actual_value": [
      "input-Unihack_ Sample Dataset - Input.csv"
    ],
    "expected_condition": "at least one source ID"
  },
  {
    "validation_id": "inspection-width-normalization",
    "validator": "inspection",
    "status": "NOT_ASSESSED",
    "severity": "WARNING",
    "message": "A model normalization is shown, but no deterministic rule verified it.",
    "rule": "only documented deterministic normalization may pass",
    "actual_value": "1/2",
    "expected_condition": "a documented deterministic normalization rule"
  },
  {
    "validation_id": "inspection-width-uom",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "A unit of measure is present.",
    "rule": "attribute unit must be explicit before unit validation",
    "actual_value": "in",
    "expected_condition": "a supported unit of measure"
  },
  {
    "validation_id": "inspection-width-lov",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No official attribute LOV/reference data was available in this run.",
    "rule": "attribute value must be checked against an official LOV",
    "actual_value": "1/2",
    "expected_condition": "official LOV/reference data"
  },
  {
    "validation_id": "inspection-width-conflict",
    "validator": "inspection",
    "status": "NONE",
    "severity": "INFO",
    "message": "No conflict was recorded for this attribute.",
    "rule": "candidate must not have unresolved source/value conflicts",
    "actual_value": null,
    "expected_condition": "no open conflict"
  },
  {
    "validation_id": "inspection-width-manufacturer-source",
    "validator": "inspection",
    "status": "NOT_AVAILABLE",
    "severity": "WARNING",
    "message": "No manufacturer evidence is associated with this candidate.",
    "rule": "input data must not be treated as manufacturer verification",
    "actual_value": null,
    "expected_condition": "verified manufacturer source"
  }
]
```

### 4. Length

- Raw: `18"`
- Normalized: `18`
- UOM: `in`
- Status: `CANDIDATE`; origin: `INPUT_DATA`; correctness: `DIRECTLY_SUPPORTED_BY_INPUT`
- Evidence: `AVAILABLE`; source IDs: `['input-Unihack_ Sample Dataset - Input.csv']`; evidence IDs: `['162a334f-dc65-4c0e-9286-a46693f9049e']`
- Agent/model/prompt: `attribute_extraction` / `gemini-3.5-flash-lite` / `v1`
- Validation:
```json
[
  {
    "validation_id": "inspection-length-evidence",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "Quoted evidence is attached.",
    "rule": "candidate must retain evidence linkage",
    "actual_value": [
      "162a334f-dc65-4c0e-9286-a46693f9049e"
    ],
    "expected_condition": "at least one evidence ID"
  },
  {
    "validation_id": "inspection-length-source",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "A source reference is attached; authority is assessed separately.",
    "rule": "candidate must retain source linkage",
    "actual_value": [
      "input-Unihack_ Sample Dataset - Input.csv"
    ],
    "expected_condition": "at least one source ID"
  },
  {
    "validation_id": "inspection-length-normalization",
    "validator": "inspection",
    "status": "NOT_ASSESSED",
    "severity": "WARNING",
    "message": "A model normalization is shown, but no deterministic rule verified it.",
    "rule": "only documented deterministic normalization may pass",
    "actual_value": "18",
    "expected_condition": "a documented deterministic normalization rule"
  },
  {
    "validation_id": "inspection-length-uom",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "A unit of measure is present.",
    "rule": "attribute unit must be explicit before unit validation",
    "actual_value": "in",
    "expected_condition": "a supported unit of measure"
  },
  {
    "validation_id": "inspection-length-lov",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No official attribute LOV/reference data was available in this run.",
    "rule": "attribute value must be checked against an official LOV",
    "actual_value": "18",
    "expected_condition": "official LOV/reference data"
  },
  {
    "validation_id": "inspection-length-conflict",
    "validator": "inspection",
    "status": "NONE",
    "severity": "INFO",
    "message": "No conflict was recorded for this attribute.",
    "rule": "candidate must not have unresolved source/value conflicts",
    "actual_value": null,
    "expected_condition": "no open conflict"
  },
  {
    "validation_id": "inspection-length-manufacturer-source",
    "validator": "inspection",
    "status": "NOT_AVAILABLE",
    "severity": "WARNING",
    "message": "No manufacturer evidence is associated with this candidate.",
    "rule": "input data must not be treated as manufacturer verification",
    "actual_value": null,
    "expected_condition": "verified manufacturer source"
  }
]
```

### 5. Product Type

- Raw: `Sanding Belt`
- Normalized: `Sanding Belt`
- UOM: `None`
- Status: `CANDIDATE`; origin: `INPUT_DATA`; correctness: `DIRECTLY_SUPPORTED_BY_INPUT`
- Evidence: `AVAILABLE`; source IDs: `['input-Unihack_ Sample Dataset - Input.csv']`; evidence IDs: `['9f14f2c3-c9ee-416a-8854-a702e316c335']`
- Agent/model/prompt: `attribute_extraction` / `gemini-3.5-flash-lite` / `v1`
- Validation:
```json
[
  {
    "validation_id": "inspection-product-type-evidence",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "Quoted evidence is attached.",
    "rule": "candidate must retain evidence linkage",
    "actual_value": [
      "9f14f2c3-c9ee-416a-8854-a702e316c335"
    ],
    "expected_condition": "at least one evidence ID"
  },
  {
    "validation_id": "inspection-product-type-source",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "A source reference is attached; authority is assessed separately.",
    "rule": "candidate must retain source linkage",
    "actual_value": [
      "input-Unihack_ Sample Dataset - Input.csv"
    ],
    "expected_condition": "at least one source ID"
  },
  {
    "validation_id": "inspection-product-type-normalization",
    "validator": "inspection",
    "status": "NOT_APPLIED",
    "severity": "INFO",
    "message": "No distinct normalization was applied.",
    "rule": "only documented deterministic normalization may pass",
    "actual_value": "Sanding Belt",
    "expected_condition": "a documented deterministic normalization rule"
  },
  {
    "validation_id": "inspection-product-type-uom",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No unit of measure was returned.",
    "rule": "attribute unit must be explicit before unit validation",
    "actual_value": null,
    "expected_condition": "a supported unit of measure"
  },
  {
    "validation_id": "inspection-product-type-lov",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No official attribute LOV/reference data was available in this run.",
    "rule": "attribute value must be checked against an official LOV",
    "actual_value": "Sanding Belt",
    "expected_condition": "official LOV/reference data"
  },
  {
    "validation_id": "inspection-product-type-conflict",
    "validator": "inspection",
    "status": "NONE",
    "severity": "INFO",
    "message": "No conflict was recorded for this attribute.",
    "rule": "candidate must not have unresolved source/value conflicts",
    "actual_value": null,
    "expected_condition": "no open conflict"
  },
  {
    "validation_id": "inspection-product-type-manufacturer-source",
    "validator": "inspection",
    "status": "NOT_AVAILABLE",
    "severity": "WARNING",
    "message": "No manufacturer evidence is associated with this candidate.",
    "rule": "input data must not be treated as manufacturer verification",
    "actual_value": null,
    "expected_condition": "verified manufacturer source"
  }
]
```

### 6. Package Quantity

- Raw: `6pc`
- Normalized: `6`
- UOM: `pc`
- Status: `CANDIDATE`; origin: `INPUT_DATA`; correctness: `DIRECTLY_SUPPORTED_BY_INPUT`
- Evidence: `AVAILABLE`; source IDs: `['input-Unihack_ Sample Dataset - Input.csv']`; evidence IDs: `['d7057b76-4f13-42cd-adc8-2d11f21100cf']`
- Agent/model/prompt: `attribute_extraction` / `gemini-3.5-flash-lite` / `v1`
- Validation:
```json
[
  {
    "validation_id": "inspection-package-quantity-evidence",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "Quoted evidence is attached.",
    "rule": "candidate must retain evidence linkage",
    "actual_value": [
      "d7057b76-4f13-42cd-adc8-2d11f21100cf"
    ],
    "expected_condition": "at least one evidence ID"
  },
  {
    "validation_id": "inspection-package-quantity-source",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "A source reference is attached; authority is assessed separately.",
    "rule": "candidate must retain source linkage",
    "actual_value": [
      "input-Unihack_ Sample Dataset - Input.csv"
    ],
    "expected_condition": "at least one source ID"
  },
  {
    "validation_id": "inspection-package-quantity-normalization",
    "validator": "inspection",
    "status": "NOT_ASSESSED",
    "severity": "WARNING",
    "message": "A model normalization is shown, but no deterministic rule verified it.",
    "rule": "only documented deterministic normalization may pass",
    "actual_value": "6",
    "expected_condition": "a documented deterministic normalization rule"
  },
  {
    "validation_id": "inspection-package-quantity-uom",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "A unit of measure is present.",
    "rule": "attribute unit must be explicit before unit validation",
    "actual_value": "pc",
    "expected_condition": "a supported unit of measure"
  },
  {
    "validation_id": "inspection-package-quantity-lov",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No official attribute LOV/reference data was available in this run.",
    "rule": "attribute value must be checked against an official LOV",
    "actual_value": "6",
    "expected_condition": "official LOV/reference data"
  },
  {
    "validation_id": "inspection-package-quantity-conflict",
    "validator": "inspection",
    "status": "NONE",
    "severity": "INFO",
    "message": "No conflict was recorded for this attribute.",
    "rule": "candidate must not have unresolved source/value conflicts",
    "actual_value": null,
    "expected_condition": "no open conflict"
  },
  {
    "validation_id": "inspection-package-quantity-manufacturer-source",
    "validator": "inspection",
    "status": "NOT_AVAILABLE",
    "severity": "WARNING",
    "message": "No manufacturer evidence is associated with this candidate.",
    "rule": "input data must not be treated as manufacturer verification",
    "actual_value": null,
    "expected_condition": "verified manufacturer source"
  }
]
```

### 7. Brand Name

- Raw: `Diablo`
- Normalized: `Diablo`
- UOM: `None`
- Status: `CANDIDATE`; origin: `INPUT_DATA`; correctness: `DIRECTLY_SUPPORTED_BY_INPUT`
- Evidence: `AVAILABLE`; source IDs: `['input-Unihack_ Sample Dataset - Input.csv']`; evidence IDs: `['a98c8353-ad0f-49df-96cf-dc1961fb7df4']`
- Agent/model/prompt: `attribute_extraction` / `gemini-3.5-flash-lite` / `v1`
- Validation:
```json
[
  {
    "validation_id": "inspection-brand-name-evidence",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "Quoted evidence is attached.",
    "rule": "candidate must retain evidence linkage",
    "actual_value": [
      "a98c8353-ad0f-49df-96cf-dc1961fb7df4"
    ],
    "expected_condition": "at least one evidence ID"
  },
  {
    "validation_id": "inspection-brand-name-source",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "A source reference is attached; authority is assessed separately.",
    "rule": "candidate must retain source linkage",
    "actual_value": [
      "input-Unihack_ Sample Dataset - Input.csv"
    ],
    "expected_condition": "at least one source ID"
  },
  {
    "validation_id": "inspection-brand-name-normalization",
    "validator": "inspection",
    "status": "NOT_APPLIED",
    "severity": "INFO",
    "message": "No distinct normalization was applied.",
    "rule": "only documented deterministic normalization may pass",
    "actual_value": "Diablo",
    "expected_condition": "a documented deterministic normalization rule"
  },
  {
    "validation_id": "inspection-brand-name-uom",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No unit of measure was returned.",
    "rule": "attribute unit must be explicit before unit validation",
    "actual_value": null,
    "expected_condition": "a supported unit of measure"
  },
  {
    "validation_id": "inspection-brand-name-lov",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No official attribute LOV/reference data was available in this run.",
    "rule": "attribute value must be checked against an official LOV",
    "actual_value": "Diablo",
    "expected_condition": "official LOV/reference data"
  },
  {
    "validation_id": "inspection-brand-name-conflict",
    "validator": "inspection",
    "status": "NONE",
    "severity": "INFO",
    "message": "No conflict was recorded for this attribute.",
    "rule": "candidate must not have unresolved source/value conflicts",
    "actual_value": null,
    "expected_condition": "no open conflict"
  },
  {
    "validation_id": "inspection-brand-name-manufacturer-source",
    "validator": "inspection",
    "status": "NOT_AVAILABLE",
    "severity": "WARNING",
    "message": "No manufacturer evidence is associated with this candidate.",
    "rule": "input data must not be treated as manufacturer verification",
    "actual_value": null,
    "expected_condition": "verified manufacturer source"
  }
]
```

### 8. Manufacturer

- Raw: `Freud Inc (2435)`
- Normalized: `Freud Inc`
- UOM: `None`
- Status: `CANDIDATE`; origin: `INPUT_DATA`; correctness: `DIRECTLY_SUPPORTED_BY_INPUT`
- Evidence: `AVAILABLE`; source IDs: `['input-Unihack_ Sample Dataset - Input.csv']`; evidence IDs: `['3564c53c-471d-46e7-9dd0-8a90e7225981']`
- Agent/model/prompt: `attribute_extraction` / `gemini-3.5-flash-lite` / `v1`
- Validation:
```json
[
  {
    "validation_id": "inspection-manufacturer-evidence",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "Quoted evidence is attached.",
    "rule": "candidate must retain evidence linkage",
    "actual_value": [
      "3564c53c-471d-46e7-9dd0-8a90e7225981"
    ],
    "expected_condition": "at least one evidence ID"
  },
  {
    "validation_id": "inspection-manufacturer-source",
    "validator": "inspection",
    "status": "PASS",
    "severity": "INFO",
    "message": "A source reference is attached; authority is assessed separately.",
    "rule": "candidate must retain source linkage",
    "actual_value": [
      "input-Unihack_ Sample Dataset - Input.csv"
    ],
    "expected_condition": "at least one source ID"
  },
  {
    "validation_id": "inspection-manufacturer-normalization",
    "validator": "inspection",
    "status": "NOT_ASSESSED",
    "severity": "WARNING",
    "message": "A model normalization is shown, but no deterministic rule verified it.",
    "rule": "only documented deterministic normalization may pass",
    "actual_value": "Freud Inc",
    "expected_condition": "a documented deterministic normalization rule"
  },
  {
    "validation_id": "inspection-manufacturer-uom",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No unit of measure was returned.",
    "rule": "attribute unit must be explicit before unit validation",
    "actual_value": null,
    "expected_condition": "a supported unit of measure"
  },
  {
    "validation_id": "inspection-manufacturer-lov",
    "validator": "inspection",
    "status": "UNAVAILABLE",
    "severity": "WARNING",
    "message": "No official attribute LOV/reference data was available in this run.",
    "rule": "attribute value must be checked against an official LOV",
    "actual_value": "Freud Inc",
    "expected_condition": "official LOV/reference data"
  },
  {
    "validation_id": "inspection-manufacturer-conflict",
    "validator": "inspection",
    "status": "NONE",
    "severity": "INFO",
    "message": "No conflict was recorded for this attribute.",
    "rule": "candidate must not have unresolved source/value conflicts",
    "actual_value": null,
    "expected_condition": "no open conflict"
  },
  {
    "validation_id": "inspection-manufacturer-manufacturer-source",
    "validator": "inspection",
    "status": "NOT_AVAILABLE",
    "severity": "WARNING",
    "message": "No manufacturer evidence is associated with this candidate.",
    "rule": "input data must not be treated as manufacturer verification",
    "actual_value": null,
    "expected_condition": "verified manufacturer source"
  }
]
```

## 5. Evidence

```json
[
  {
    "evidence_id": "ad2853f7-d849-4c30-b6bd-eaf334180cb7",
    "source_id": "input-Unihack_ Sample Dataset - Input.csv",
    "evidence_text": "DCB518ASTS06G",
    "evidence_type": "direct_text",
    "origin": "INPUT_DATA",
    "document_id": null,
    "chunk_id": null,
    "page": null,
    "section": "Mfg_Part_Num",
    "content_hash": null,
    "retrieved_at": null,
    "evidence_status": "AVAILABLE"
  },
  {
    "evidence_id": "f340043a-b3e7-4a83-8abb-66dbbb86de35",
    "source_id": "input-Unihack_ Sample Dataset - Input.csv",
    "evidence_text": "DCB518ASTS06G Diablo 1/2\"x18\" - Sanding Belt 6pc",
    "evidence_type": "direct_text",
    "origin": "INPUT_DATA",
    "document_id": null,
    "chunk_id": null,
    "page": null,
    "section": "Part_Desc",
    "content_hash": null,
    "retrieved_at": null,
    "evidence_status": "AVAILABLE"
  },
  {
    "evidence_id": "7ff08b00-477a-4c95-894f-4798346bddad",
    "source_id": "input-Unihack_ Sample Dataset - Input.csv",
    "evidence_text": "1/2\"",
    "evidence_type": "direct_text",
    "origin": "INPUT_DATA",
    "document_id": null,
    "chunk_id": null,
    "page": null,
    "section": "Part_Desc",
    "content_hash": null,
    "retrieved_at": null,
    "evidence_status": "AVAILABLE"
  },
  {
    "evidence_id": "162a334f-dc65-4c0e-9286-a46693f9049e",
    "source_id": "input-Unihack_ Sample Dataset - Input.csv",
    "evidence_text": "18\"",
    "evidence_type": "direct_text",
    "origin": "INPUT_DATA",
    "document_id": null,
    "chunk_id": null,
    "page": null,
    "section": "Part_Desc",
    "content_hash": null,
    "retrieved_at": null,
    "evidence_status": "AVAILABLE"
  },
  {
    "evidence_id": "9f14f2c3-c9ee-416a-8854-a702e316c335",
    "source_id": "input-Unihack_ Sample Dataset - Input.csv",
    "evidence_text": "Sanding Belt",
    "evidence_type": "direct_text",
    "origin": "INPUT_DATA",
    "document_id": null,
    "chunk_id": null,
    "page": null,
    "section": "Part_Desc",
    "content_hash": null,
    "retrieved_at": null,
    "evidence_status": "AVAILABLE"
  },
  {
    "evidence_id": "d7057b76-4f13-42cd-adc8-2d11f21100cf",
    "source_id": "input-Unihack_ Sample Dataset - Input.csv",
    "evidence_text": "6pc",
    "evidence_type": "direct_text",
    "origin": "INPUT_DATA",
    "document_id": null,
    "chunk_id": null,
    "page": null,
    "section": "Part_Desc",
    "content_hash": null,
    "retrieved_at": null,
    "evidence_status": "AVAILABLE"
  },
  {
    "evidence_id": "a98c8353-ad0f-49df-96cf-dc1961fb7df4",
    "source_id": "input-Unihack_ Sample Dataset - Input.csv",
    "evidence_text": "Diablo",
    "evidence_type": "direct_text",
    "origin": "INPUT_DATA",
    "document_id": null,
    "chunk_id": null,
    "page": null,
    "section": "Part_Desc",
    "content_hash": null,
    "retrieved_at": null,
    "evidence_status": "AVAILABLE"
  },
  {
    "evidence_id": "3564c53c-471d-46e7-9dd0-8a90e7225981",
    "source_id": "input-Unihack_ Sample Dataset - Input.csv",
    "evidence_text": "Freud Inc (2435)",
    "evidence_type": "direct_text",
    "origin": "INPUT_DATA",
    "document_id": null,
    "chunk_id": null,
    "page": null,
    "section": "Part_Manuf",
    "content_hash": null,
    "retrieved_at": null,
    "evidence_status": "AVAILABLE"
  }
]
```

## 6. Sources

```json
[
  {
    "source_id": "input-Unihack_ Sample Dataset - Input.csv",
    "source_url": null,
    "source_type": "supplied_input",
    "authority": "NON_AUTHORITATIVE",
    "status": "AVAILABLE",
    "origin": "INPUT_DATA",
    "manufacturer_id": null,
    "retrieved_at": null,
    "content_hash": null,
    "document_id": null
  }
]
```

## 7. Validation

```json
[]
```

## 8. Telemetry

```json
{
  "agent_calls": 3,
  "input_tokens": null,
  "output_tokens": null,
  "cached_tokens": null,
  "thought_tokens": null,
  "tool_use_tokens": null,
  "total_tokens": null,
  "latency_ms": 15549,
  "retries": 0,
  "tool_calls": 0
}
```

## 9. Correctness assessment

```json
[
  {
    "attribute": "Manufacturer Part Number",
    "classification": "DIRECTLY_SUPPORTED_BY_INPUT",
    "rationale": "The quoted evidence appears verbatim in the supplied row.",
    "input_support": "DIRECT",
    "manufacturer_support": "NONE",
    "traceable": true,
    "technically_plausible": "NOT_ASSESSED_WITHOUT_AUTHORITATIVE_REFERENCE",
    "validation_status": "PENDING"
  },
  {
    "attribute": "Product Description",
    "classification": "DIRECTLY_SUPPORTED_BY_INPUT",
    "rationale": "The quoted evidence appears verbatim in the supplied row.",
    "input_support": "DIRECT",
    "manufacturer_support": "NONE",
    "traceable": true,
    "technically_plausible": "NOT_ASSESSED_WITHOUT_AUTHORITATIVE_REFERENCE",
    "validation_status": "PENDING"
  },
  {
    "attribute": "Width",
    "classification": "DIRECTLY_SUPPORTED_BY_INPUT",
    "rationale": "The quoted evidence appears verbatim in the supplied row.",
    "input_support": "DIRECT",
    "manufacturer_support": "NONE",
    "traceable": true,
    "technically_plausible": "NOT_ASSESSED_WITHOUT_AUTHORITATIVE_REFERENCE",
    "validation_status": "PENDING"
  },
  {
    "attribute": "Length",
    "classification": "DIRECTLY_SUPPORTED_BY_INPUT",
    "rationale": "The quoted evidence appears verbatim in the supplied row.",
    "input_support": "DIRECT",
    "manufacturer_support": "NONE",
    "traceable": true,
    "technically_plausible": "NOT_ASSESSED_WITHOUT_AUTHORITATIVE_REFERENCE",
    "validation_status": "PENDING"
  },
  {
    "attribute": "Product Type",
    "classification": "DIRECTLY_SUPPORTED_BY_INPUT",
    "rationale": "The quoted evidence appears verbatim in the supplied row.",
    "input_support": "DIRECT",
    "manufacturer_support": "NONE",
    "traceable": true,
    "technically_plausible": "NOT_ASSESSED_WITHOUT_AUTHORITATIVE_REFERENCE",
    "validation_status": "PENDING"
  },
  {
    "attribute": "Package Quantity",
    "classification": "DIRECTLY_SUPPORTED_BY_INPUT",
    "rationale": "The quoted evidence appears verbatim in the supplied row.",
    "input_support": "DIRECT",
    "manufacturer_support": "NONE",
    "traceable": true,
    "technically_plausible": "NOT_ASSESSED_WITHOUT_AUTHORITATIVE_REFERENCE",
    "validation_status": "PENDING"
  },
  {
    "attribute": "Brand Name",
    "classification": "DIRECTLY_SUPPORTED_BY_INPUT",
    "rationale": "The quoted evidence appears verbatim in the supplied row.",
    "input_support": "DIRECT",
    "manufacturer_support": "NONE",
    "traceable": true,
    "technically_plausible": "NOT_ASSESSED_WITHOUT_AUTHORITATIVE_REFERENCE",
    "validation_status": "PENDING"
  },
  {
    "attribute": "Manufacturer",
    "classification": "DIRECTLY_SUPPORTED_BY_INPUT",
    "rationale": "The quoted evidence appears verbatim in the supplied row.",
    "input_support": "DIRECT",
    "manufacturer_support": "NONE",
    "traceable": true,
    "technically_plausible": "NOT_ASSESSED_WITHOUT_AUTHORITATIVE_REFERENCE",
    "validation_status": "PENDING"
  }
]
```

## 10. Unsupported/inferred values

Scorecard: `{'direct_from_input': 8, 'direct_from_manufacturer': 0, 'normalized': 4, 'calculated': 0, 'inferred': 0, 'unsupported': 0, 'unresolved': 0, 'validated': 0, 'review_required': 8, 'attributes_with_evidence': 8, 'attributes_without_evidence': 0, 'manufacturer_verified_attributes': 0, 'input_only_attributes': 8, 'inferred_attributes': 0}`

## 11. Limitations

- The supplied UniHack row is INPUT_DATA, not authoritative manufacturer evidence.
- No manufacturer source was retrieved in this existing row-2 execution.
- No domain candidate validation event was recorded; candidates remain review-required.
- The inspection does not expose private model reasoning or chain-of-thought.
- Input file: Unihack_ Sample Dataset - Input.csv.
