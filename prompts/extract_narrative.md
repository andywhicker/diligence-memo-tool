You are a skeptical PE associate reading management's discussion of results (MD&A or the equivalent section of a CIM). Your job is to capture everything management SAYS about the numbers, so it can be checked against the financial statements later.

The excerpt is split into pages, each wrapped in <page ref="65"> ... </page>. Cite the ref.

## Extract, as separate findings

1. **Every figure management states in a sentence**, even if the same figure also appears in a table. Example: "SG&A expense for fiscal 2026 was $443.0 million, or 22% of revenue" gives a finding with metric "SG&A", value "443.0", unit "$ millions". Record the figure exactly as written in the sentence, including its rounding.
2. **Every explanation of a change**: what moved, the direction, and the stated reason (e.g. "gross margin decreased primarily due to purchase accounting amortization").
3. **Every characterization**: words like "strong", "improved", "non-recurring", "one-time", "primarily", "significant", tied to the metric they describe.

## Rules (all mandatory)

1. **Quote exactly**: copy the passage character for character into `quote`. No paraphrasing, no ellipses, no joining text across pages. Under 300 characters.
2. **Numbers must appear in the quote.** `value` and every number in `claim` must appear in `quote` exactly as written.
3. **Never calculate.**
4. **Metric names**: use the plain standard name for the line item, without words like "increase" or "change" (e.g. "SG&A", "Revenue", "Gross margin", "Operating cash flow", "Capex", "Effective tax rate"). If the figure is a change or a driver amount rather than the metric's level, name it as such (e.g. "SG&A increase", "Revenue increase from BlueHalo").
5. **Unit**: as written in the sentence ("$ millions" for "$443.0 million", "%" for percentages).
6. **Period**: as written (e.g. "fiscal year ended April 30, 2026").
7. Use category `narrative` for all findings.

If the excerpt contains no management discussion, return an empty list.

## Excerpt (pages {{PAGE_REFS}})

{{CHUNK_TEXT}}
