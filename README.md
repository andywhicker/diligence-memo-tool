# Diligence Memo Generator

A command-line tool that reads a long investment document (a 10-K or a CIM) and produces a first-pass diligence memo in the format an investment committee expects. Every fact and every number in the memo carries a page citation. Code checks each citation against the source document before it reaches the memo.

```
python diligence.py docs/AVAV_10-K_FY2026_clean.pdf
```

Output: a styled Word memo, a matching PDF, and a Markdown copy. On AeroVironment's FY2026 10-K (138 pages), a full run takes about 13 minutes and costs about $5.75 in API usage. Re-rendering after a code change is free and takes about 30 seconds.

---

## Why this exists

First-pass diligence on a 10-K or CIM is mostly mechanical: find the numbers, find management's explanations, organize them into a standard memo, and flag what doesn't add up. A language model can do that quickly. The problem is trust. A model will produce a confident memo that includes numbers it misread or invented, and in an IC memo one wrong number discredits the whole document.

So the design rule here is simple: **the model is never trusted to cite. Code checks every citation.** Anything that can't be traced to a specific page is removed before it reaches the memo, and every removal is logged.

---

## What the memo contains

The memo follows [memo_template.md](memo_template.md), section by section:

1. **Executive Summary**: business, scale, key positives and concerns, biggest open question
2. **Business Overview**: segments, revenue model, geography, headcount, M&A history, ownership
3. **Market & Competitive Position**: named competitors, stated advantages, regulatory and budget exposure
4. **Customers, Contracts & Backlog**: concentration, government mix, contract types, funded and unfunded backlog
5. **Financial Summary**: four tables (below), table notes, and commentary
6. **Quality of Earnings Flags**: EBITDA definition and add-backs, impairments, revenue recognition, material weaknesses
7. **LBO Inputs**: cited raw inputs for a separate model (no valuation, no returns)
8. **Key Risks**: company-specific and ranked
9. **Consistency Check**: places where management's narrative and the numbers disagree
10. **Questions for Management**: one question for every item marked "Not disclosed", plus diligence questions
11. **Appendix: Coverage Notes**: pages read, findings rejected, memo lines deleted

**Section 5 tables.** The model only chooses which reported figure goes in each cell. Code converts units and computes every ratio. Calculated figures are labeled `calc.` and cite their input pages.

| Table | Contents |
|---|---|
| Financial summary | Revenue, growth, gross profit and margin, operating income, EBITDA as reported, Adjusted EBITDA as reported, D&A, capex, backlog, largest customer % |
| Cash conversion & earnings quality | Organic growth, operating cash flow, free cash flow, FCF / Adj. EBITDA, GAAP EBITDA, add-backs (total and excluding impairment), DSO, DIO |
| Balance sheet & liquidity | Total debt, cash + short-term investments, net debt, gross and net leverage, liquidity including undrawn revolver |
| Operating metrics | Funded and total backlog coverage, capex / depreciation, revenue per employee, contract-type mix, segment margins |

Each reported figure in the tables is marked **✓** if the same number for the same year was found independently on a second page of the document, or **†** if it was found on one page only and should be checked by hand.

---

## How it works

```
 PDF
  │
  ▼
 1. Read pages ─────────── keep each page's printed page number (detected by position, validated)
  │
  ▼
 2. Chunk ──────────────── ~10 pages per chunk, 1-page overlap, each page tagged <page ref="65">
  │
  ▼
 3. Extract (AI) ───────── per chunk: structured findings = claim, number, unit, period, page, exact quote
  │
  ▼
 4. Verify (code) ──────── reject any finding whose quote isn't on the cited page,
  │                         or whose numbers aren't in the quote
  ▼
 5. Tables (AI + code) ─── AI points to the right number for each cell;
  │                         code checks it, converts units, computes the PE metrics, cross-checks pages
  ▼
 6. Write memo (AI) ────── from verified findings + calculated metrics only; cites finding IDs
  │
  ▼
 7. Enforce (code) ─────── delete any line citing a fake ID, an uncited number, or a number not in
  │                         its cited findings; convert IDs to (p. 65) citations
  ▼
 8. Consistency (AI + code) narrative vs. numbers; kept only if both sides are cited and every
  │                         number traces to a finding or a calculation
  ▼
 9. Render ─────────────── Markdown → styled Word → PDF (exported by Word, so they match)
```

**The division of labor.** The model does what it's good at: reading, classifying, choosing the right figure, and writing. Code does what has to be exact: matching quotes, checking numbers, converting units, and calculating. The model never computes a number. It writes "organic growth was 26.4%" only by citing the code's calculation `[C-ORGANIC_GROWTH-FY2026]`, and the reader sees `(calc.; pp. 81, 116, 118)`.

**Results on the AVAV FY2026 10-K:**
- 951 findings extracted; 874 verified, 24 rejected, 53 duplicates from the page overlap removed.
- 64 metrics calculated by code.
- 258 memo lines kept; 2 deleted by the citation check.
- 40 of 69 table inputs independently confirmed on a second page.
- Calculated metrics match a hand calculation, e.g. FCF of $(140.9)M = OCF $(78.4)M − capex $62.5M, and organic growth of 26.4% vs. 140.9% reported.

---

## Setup (Windows)

Requirements: Python 3.12, an Anthropic API key, and Microsoft Word (for the PDF; without Word you still get the `.docx` and `.md`).

```
# 1. Create a virtual environment (a private package folder for this project) and install packages
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 2. Add your API key: create a file named .env in this folder containing one line
ANTHROPIC_API_KEY=sk-ant-...

# 3. Test the connection (costs under $0.01)
python diligence.py --check
```

`.env` is listed in `.gitignore` and is never committed. API usage is billed per token by Anthropic, separately from any Claude subscription.

**Getting a 10-K as a PDF.** SEC EDGAR publishes filings as HTML. Download the filing's `.htm` file into `docs/`, then convert it with the included script, which uses Microsoft Edge:

```
.\tools\html_to_pdf.ps1 -Html docs\<filing>.htm -Out docs\<name>.pdf
```

The script shrinks the print slightly so each filing page fits on one PDF page, which keeps the printed page numbers aligned. Automated EDGAR downloads must identify themselves with a name and email in the request's User-Agent header; this is SEC policy.

---

## Usage

```
python diligence.py docs/<file>.pdf --dry-run     # read and chunk only: page map, chunk map, token estimate. Free.
python diligence.py docs/<file>.pdf --chunk 8     # extract + verify one chunk, to test a prompt change. ~$0.10-0.50.
python diligence.py docs/<file>.pdf               # full run
python diligence.py docs/<file>.pdf --fresh       # ignore saved extraction results and redo everything
```

**Caching.** Every AI call is saved with a fingerprint of its exact prompt, model and settings. On the next run, any step whose inputs haven't changed reuses its saved answer for free. Edit `prompts/write_memo.md`, and only the memo-writing step re-runs.

**Output files:**

| File | What it is |
|---|---|
| `output/<Company>_Diligence_Memo_<date>.pdf / .docx / .md` | The deliverables |
| `output/<doc>/findings.json` | Every verified finding: claim, number, unit, period, page, exact quote |
| `output/<doc>/rejected.json` | Findings that failed verification, with the reason |
| `output/<doc>/calcs.json` | Every calculated metric with its formula and input pages |
| `output/<doc>/citation_log.md` | Every memo line the citation check deleted, with the reason |
| `output/<doc>/draft_raw.md` | The model's draft before enforcement, for audit |

**Settings** live in [config.py](config.py): the model (one line to change), effort level, chunk size, and prices used for the cost log. The cost log prints after every run.

**Prompts** are plain Markdown files in [prompts/](prompts/) and are meant to be edited:

| Prompt | Controls |
|---|---|
| `extract_findings.md` | What gets pulled from each chunk, and the categories |
| `financial_table.md` | Which reported figures feed the tables |
| `write_memo.md` | Memo tone, priorities, and citation rules |
| `consistency_check.md` | What counts as a narrative-vs-numbers problem |

---

## Project structure

```
diligence.py            command-line entry point and pipeline order
config.py               model, effort, chunk size, prices
memo_template.md        the memo's required structure
prompts/                the four prompts sent to the model
src/
  pdf_pages.py          PDF -> pages with printed page numbers
  chunker.py            pages -> overlapping, page-tagged chunks
  extract.py            chunk -> structured findings (AI, JSON schema enforced)
  verify.py             findings -> verified / rejected (code only)
  pipeline.py           runs extract + verify over the document, with caching
  fintable.py           table inputs (AI) + unit conversion, PE metrics, cross-checks (code)
  synthesize.py         verified findings + metrics -> memo draft (AI)
  citations.py          citation enforcement on every memo line (code only)
  consistency.py        narrative-vs-numbers check (AI) + two-sided citation check (code)
  render.py             Markdown -> styled Word -> PDF
  llm.py                the only file that calls the API; cost logging and caching
tools/html_to_pdf.ps1   EDGAR HTML -> page-aligned PDF
```

---

## Known limitations

Ranked by how much they matter for trusting the output.

1. **The citation check confirms numbers, not meaning.** A memo line survives if its numbers appear in the findings it cites. A line could still cite a real finding and misstate it in words (e.g. "rose" when the figure fell, or the wrong segment). Sentences with no numbers only need a valid citation. *Fix planned:* a second, cheaper model checks that each line says what its cited finding says.
2. **The consistency check is not repeatable.** Its checks control what gets kept, not what the model finds. On AVAV, one run caught that Item 5 attributes the low FY2026 tax rate partly to the FDII deduction while the tax reconciliation shows no FDII benefit that year (pp. 60, 111); a later run did not. A $443.0M vs. $443.3M SG&A mismatch between MD&A and the income statement has not been caught. *Fix planned:* run it twice and merge, and add code-only checks for the same metric reported with different values on different pages.
3. **Narrative extraction is thin.** Only 26 of 874 AVAV findings are management's explanations of why a metric moved. That's the raw material for the consistency check.
4. **Year and unit checks are strongest in the tables.** Table inputs are cross-checked against a second page (✓/†). Numbers in the memo text are checked against a finding, but a finding with the wrong year attached would pass. Extraction captures unit labels ("$ thousands") from the page, but nothing confirms them independently.
5. **The model can miss table inputs.** On AVAV it did not pick up the FY2025 goodwill impairment ($18.4M), so one FY2025 metric shows n/a. A gap shows as "Not disclosed" or "n/a", never as an invented number, but some gaps are misses rather than true non-disclosure.
6. **Some correct findings are rejected.** Product names containing numbers (e.g. "Puma 3", "VAPOR 55") can trip the number check. About 4 of the 24 AVAV rejections are this kind of false positive.
7. **Document scope.** Tested on one EDGAR 10-K. Not yet tested on a CIM. Scanned or image-only PDFs aren't supported. Printed page numbers are detected from page footers; documents without them are cited by PDF page ("PDF 12"). PDF text extraction flattens tables into rows of numbers, so column alignment has to be inferred.
8. **Data handling.** Document text is sent to Anthropic's API. Don't run confidential documents (e.g. a CIM under NDA) without authorization from whoever controls them.

**Out of scope for v1:** web interface, database, multi-document comparison, valuation and returns. Valuation is v2: an Excel LBO built from the Section 5 tables and the Section 7 inputs, with your assumptions as toggles.

---

## Cost reference (AVAV FY2026 10-K, Claude Opus 5.5, effort "high")

| Step | API calls | Cost |
|---|---|---|
| Extraction (16 chunks) | 16 | $3.96 |
| Table inputs | 1 | $0.34 |
| Memo draft | 1 | $0.87 |
| Consistency check | 1 | $0.55 |
| **Full run** | **19** | **~$5.75** |
| Re-render with unchanged inputs | 0 | $0 |

Switching `MODEL` in `config.py` to `claude-sonnet-5-5` roughly halves the cost. Accuracy at the cheaper setting hasn't been measured yet.
