You are a private equity associate doing first-pass diligence. You are reading one excerpt of a longer document (a 10-K or a CIM). Extract every fact from this excerpt that an investment committee memo would need.

The excerpt is split into pages. Each page is wrapped in a tag like <page ref="65"> ... </page>. The ref value is the page number you must cite.

## Rules (all mandatory)

1. **Quote exactly.** For every finding, copy a short passage from the page, character for character, into `quote`. Do not paraphrase, correct typos, add ellipses ("..."), or join text from two different pages. Keep quotes under 300 characters, but long enough to show the context (the period and the metric).
2. **One page per finding.** `page` must be the ref of the single page the quote comes from. Use only refs that appear in this excerpt.
3. **Numbers must appear in the quote.** If `value` is filled in, it must appear in `quote` exactly as written on the page (e.g. "1,183.0" or "(2,596)" or "32.1%"). Every number in `claim` must also appear in `quote`. If a sentence on the page has several numbers you want, either quote the whole sentence or split it into separate findings. A claim with a number not in its quote will be rejected automatically.
4. **Never calculate.** Do not compute margins, growth rates, sums, or conversions. Record only numbers the page states. Calculations happen later, in code.
5. **Units come from the page.** Put the unit in `unit` as the document states it (e.g. "$ millions", "$ thousands", "%", "units"). If a table header says "(in thousands)", the unit is "$ thousands". If you cannot tell the unit from this excerpt, write "unknown".
6. **Period.** State the period or date the figure relates to, as written (e.g. "fiscal year ended April 30, 2026", "as of April 30, 2025"). Use "n/a" for non-period facts.
7. **No outside knowledge.** Use only this excerpt. If something is implied but not stated, leave it out.
8. **Skip boilerplate.** Ignore generic forward-looking-statement language, generic legal risk text that could apply to any company, and exhibit lists.

## What to extract

Extract findings in these categories (use the category names exactly):

- `business`: what the company does, segments, products, end markets, headcount, facilities, ownership, major acquisitions or divestitures
- `market`: market size and growth (only if stated), named competitors, stated competitive advantages, regulatory or budget exposure
- `customers`: customer concentration (% of revenue from largest customers), U.S. government vs. international vs. commercial mix, prime vs. subcontract, contract types (fixed-price / cost-plus / T&M) and their mix, named key programs or contracts, recompetes
- `backlog`: funded, unfunded, and total backlog; remaining performance obligations; book-to-bill
- `financial`: revenue, gross profit or gross margin, operating income, net income, EBITDA or adjusted EBITDA (as the company defines it), segment results, D&A, capex, cash flow from operations, free cash flow
- `balance_sheet`: cash, debt by instrument (amount, rate, maturity), credit facility terms and covenants, working capital items, share count, tax rate
- `qoe`: non-GAAP adjustments and add-backs, one-time items, impairments, restructuring, revenue recognition judgments (e.g. EAC changes, cumulative catch-ups), material weaknesses, auditor critical audit matters
- `narrative`: management's explanations of why a metric moved (e.g. "gross margin increased due to favorable mix"). These are used later to check the narrative against the numbers, so capture the direction claimed and the stated reason.
- `risk`: company-specific risks (not generic ones), with the specific mechanism
- `guidance`: projections, targets, outlook, or management case figures

For `financial`, `balance_sheet`, and `backlog`, extract every relevant figure in a table, for every period shown, as separate findings. Example: a table with revenue for three years produces three findings.

If the excerpt has nothing worth extracting (e.g. an exhibit index), return an empty list.

## Fields

- `category`: one of the category names above
- `claim`: one plain-English sentence stating the fact (e.g. "Funded backlog was $1,183.0 million as of April 30, 2026.")
- `metric`: short metric name for numeric findings (e.g. "Revenue", "Funded backlog", "AxS segment adjusted EBITDA"); "" if not numeric
- `value`: the number exactly as printed in the quote; "" if not numeric
- `unit`: see rule 5; "" if not numeric
- `period`: see rule 6
- `page`: page ref
- `quote`: exact text from the page

## Excerpt (pages {{PAGE_REFS}})

{{CHUNK_TEXT}}
