Analyze the untrusted input product record and return a single JSON object with exactly these three keys:

"understanding": {
  "product_type": string or null,
  "product_family": string or null,
  "semantic_features": [list of strings],
  "evidence": [{"field_name": string, "quoted_text": string, "kind": "directly_present"|"inferred"|"unknown"}],
  "uncertain_items": [list of strings]
},
"classification": {
  "candidates": [{"department": string, "class_name": string, "fine": string, "classpath": [list of strings]}],
  "selected_candidate": integer index or null,
  "unresolved_reason": string or null
},
"attributes": {
  "attributes": [{"attribute": string, "raw_value": string, "normalized_candidate": string or null, "unit": string or null, "evidence": {"field_name": string, "quoted_text": string, "kind": "directly_present"|"inferred"|"unknown"}, "status": "directly_present"|"inferred"|"unknown", "model_confidence": float 0-1 or null}],
  "missing_attributes": [list of strings]
}

Rules:
- Only extract attributes with direct evidence quoted from the input text.
- For classpath: use the format ["Department", "Class", "Fine"] e.g. ["Appliances & Consumer Electronics", "Kitchen Appliances", "Built-In Dishwashers"]
- Return raw JSON only. No markdown, no code fences, no commentary.
