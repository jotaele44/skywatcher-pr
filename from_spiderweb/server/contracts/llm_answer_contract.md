# LLM Answer Contract

When the Custom LLM responds to a query in PRIIS, it must adhere
to a strict answer format so that downstream systems and analysts
can easily interpret, audit, and act on the output. The structure
enforces separation of findings from evidence and highlights
confidence, contradictions, and gaps.

## Fields

- **finding**: A concise, single-sentence statement summarizing
  what the system believes to be true about the query.
- **evidence**: An array of source identifiers (URIs or IDs)
  supporting the finding. Each entry must be traceable to a
  document or record.
- **source_tiers**: A breakdown of evidence counts by tier (T1–T4),
  reflecting the evidentiary weight.
- **confidence**: A qualitative or numeric indication of certainty
  (e.g., `high`, `medium`, `low` or a 0–1 probability).
- **contradictions**: A list of sources or facts that weaken the
  finding or suggest alternative explanations.
- **missing_data**: Data points that would materially improve
  confidence but are not currently available.
- **recommended_action**: A suggested next step such as
  `query_more`, `issue_FOIA`, `map_check`, or `prepare_brief`.

## Example

```json
{
  "finding": "Two recent contracts awarded to ACME Corp coincide
with increased outages near Site One.",
  "evidence": ["doc:contract:C1", "doc:event:E5"],
  "source_tiers": {"T1": 1, "T2": 1, "T3": 0, "T4": 0},
  "confidence": "medium",
  "contradictions": ["doc:report:R2"],
  "missing_data": ["Recent satellite imagery of Site One"],
  "recommended_action": "query_more"
}
```