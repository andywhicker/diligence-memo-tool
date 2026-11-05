You are building the financial summary table for a PE diligence memo. You have a list of verified numeric findings extracted from a 10-K or CIM. Your only job is to choose which finding goes in each cell. Code will convert units, compute margins and growth, and check your choices against other pages.

## Rows to fill

- `revenue`: total consolidated revenue
- `gross_profit`: consolidated gross profit (some companies label it "gross margin" in dollars)
- `operating_income`: consolidated income (loss) from operations
- `ebitda_reported`: EBITDA exactly as the company reports it, consolidated. Leave blank if the company does not report it.
- `adjusted_ebitda`: Adjusted EBITDA exactly as the company reports it. If the company reports only a segment-level measure (e.g. "total segment adjusted EBITDA"), you may use the total of that measure, and you must say so in `notes`.
- `d_and_a`: total depreciation and amortization
- `capex`: purchases of property and equipment (capital expenditures) from the cash flow statement if available
- `backlog_total`: total backlog. If the company only reports funded and unfunded backlog separately, leave this blank and describe the components in `notes`.
- `largest_customer_pct`: the largest single customer's share of revenue, as a percentage

## Rules

1. **Columns.** Use the last three fiscal years that appear in the findings, oldest first, labeled like "FY2024", "FY2025", "FY2026". Use the company's own fiscal-year naming (e.g. "fiscal year ended April 30, 2026" = "FY2026").
2. **One finding per cell.** Give the ID of the single finding whose value is that metric for that fiscal year. Prefer the audited financial statements over MD&A when both exist.
3. **Exact match only.** The finding's metric and period must match the row and column exactly. Do not use a segment figure for a consolidated row (except the adjusted EBITDA case above), a quarterly figure for an annual column, or a pro forma figure for a reported column.
4. **Blank means not disclosed.** If no finding matches, use "" as the finding_id. Never pick an approximate match. A blank cell will show "Not disclosed".
5. **Notes.** Add short notes (bullets) a reader needs to interpret the table: the definition behind the EBITDA row you used, acquisitions that make years non-comparable, and backlog components if total backlog is blank. Every note must end with the finding IDs that support it in square brackets, e.g. [F08-056]. Notes may contain only numbers that appear in the findings they cite. Do not calculate.

## Verified numeric findings

Format: [ID] category | page | metric | value unit | period | fact

{{FINDINGS}}
