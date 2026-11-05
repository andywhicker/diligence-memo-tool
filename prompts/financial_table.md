You are gathering the inputs for the financial tables in a PE diligence memo. You have a list of verified findings extracted from a 10-K or CIM. Your only job is to point to the right number for each input. Code will convert units, compute every ratio and metric, and check your picks against the source quotes and other pages.

## How to pick

For each input (a "slot") and each fiscal year, give a `pick`: the ID of a finding, and the `number` exactly as it is written in that finding's quote or value (e.g. "290,009" or "75%" or "(78,404)"). A finding may contain several numbers (e.g. three years in one sentence); pick the one for that year.

Code rejects a pick if the number is not in that finding's quote, so copy it exactly.

## Slots

Income statement and cash flow (for each fiscal year):
- `revenue`: total consolidated revenue
- `gross_profit`: consolidated gross profit (some companies call it "gross margin" in dollars)
- `operating_income`: consolidated income (loss) from operations
- `ebitda_reported`: EBITDA exactly as the company reports it, consolidated. Leave empty if not reported.
- `adjusted_ebitda`: Adjusted EBITDA exactly as the company reports it. If the company reports only a segment-level measure (e.g. "total segment adjusted EBITDA"), use the total of that measure and say so in `notes`.
- `d_and_a`: total depreciation and amortization (cash flow statement preferred)
- `depreciation`: depreciation only, excluding amortization of intangibles
- `goodwill_impairment`: goodwill impairment charge recorded in the year (leave empty if none is reported)
- `capex`: purchases of property and equipment from the cash flow statement
- `operating_cash_flow`: net cash provided by (used in) operating activities
- `acquired_revenue`: revenue contributed during the year by businesses acquired during that year, as the company discloses it. This slot may have SEVERAL picks (one per acquisition); code adds them. Leave empty if not disclosed.
- `cost_of_sales`: total cost of sales / cost of revenue
- `ffp_revenue`, `cost_plus_revenue`, `tm_revenue`: revenue by contract type (fixed-price, cost-plus, time-and-materials)
- `largest_customer_pct`: the largest single customer's share of revenue, as a percentage (the U.S. government counts as one customer if the company treats it that way)

Balance sheet and other (as of each fiscal year end):
- `total_debt`: total principal amount of debt outstanding (excluding leases). If there is one instrument, use it; if several, use the total if the document states one.
- `cash`: cash and cash equivalents
- `short_term_investments`: short-term investments / marketable securities (leave empty if none)
- `revolver_available`: undrawn availability under the revolving credit facility
- `accounts_receivable`: billed accounts receivable, net
- `unbilled_receivables`: unbilled receivables / contract assets
- `inventory`: inventories, net
- `funded_backlog`, `unfunded_backlog`, `backlog_total`: as reported (leave `backlog_total` empty if only components are reported)
- `employees`: total employees (full-time, or total if that is what is stated)

Segments (for each fiscal year): for each reportable segment, its revenue and its profit measure (e.g. segment adjusted EBITDA or segment operating income), with `profit_label` naming the measure.

## Rules

1. **Columns.** Use the last three fiscal years that appear in the findings, oldest first, labeled like "FY2024", "FY2025", "FY2026", using the company's own fiscal-year naming ("fiscal year ended April 30, 2026" = "FY2026"). Balance sheet slots use the balance at that fiscal year end.
2. **Exact match only.** The number must be that metric, for that year, on the basis described. No segment figures for consolidated slots (except the adjusted EBITDA case above), no quarterly or pro forma figures for annual reported columns.
3. **Empty means not disclosed.** If nothing matches, give an empty `picks` list. Never pick an approximate match. Never pick a number you would have to calculate.
4. **One pick per slot**, except `acquired_revenue`.
5. **Notes.** Add short notes a reader needs to interpret the tables: the definition behind the EBITDA slot, acquisitions that make years non-comparable, what `total_debt` consists of, backlog components if `backlog_total` is empty. Every note must end with the finding IDs that support it, each in its own brackets, e.g. [F08-056][F10-003]. Notes may contain only numbers that appear in the findings they cite. Do not calculate.

## Verified numeric findings

Format: [ID] category | page | metric | value unit | period | fact

{{FINDINGS}}
