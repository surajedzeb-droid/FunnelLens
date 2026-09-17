# FunnelLens

**LeadSquared reports in one click.**

FunnelLens is a Python tool that pulls lead, opportunity and task data from the LeadSquared CRM and turns it into formatted Excel reports: Stage Wise, Course Wise, Source Wise, Final Count and more. It runs as a simple web page for the team (Streamlit) and as a command-line tool.

> **For AI agents and developers:** this README is the single source of truth for the project. Read it fully before starting any phase in `PHASES.md`. If something you are asked to do conflicts with this file, stop and flag it instead of guessing. At the end of every phase, update the **Project Status** section at the bottom of this file.

---

## 1. Purpose

### 1.1 Background

The team used to fill in a manual Excel template (`LSQ_Funnel_August_26.xlsx`) every day from LeadSquared data. This was automated with a **Google Apps Script** inside a Google Sheet. That script syncs daily and writes these tabs, with a fresh set of tabs for each month:

| Tab | What it holds |
|---|---|
| Lead Funnel | Daily/monthly Created and Modified counts, Task and Overdue tracking |
| Stage Wise | Leads by pipeline stage (Cold / Warm / Hot / Enrolled / etc.) |
| Source Wise | Leads by lead source (columns grow as new sources appear) |
| Course Wise | Leads by course of interest (columns grow as new courses appear) |
| Reports | Lost / Not Reachable / Enrolled tracking, daily and monthly rollups |
| Final Count | One row per counselor, monthly summary including Overdues_Total and Conversion % |
| Source Wise Enrolment | Enrolments and Conversion % by source |
| Master Data | Flat data feed for a Looker Studio dashboard |

The Apps Script is in production and works. It is still **the reference implementation** for business logic.

### 1.2 Why FunnelLens exists

- **Lookups on demand.** Anyone on the team can get any report for any date range and any set of filters, without waiting for the daily sync or editing the Sheet.
- **Excel output.** The result is a clean, formatted `.xlsx` file that can be shared.
- **Independent data check.** FunnelLens queries LeadSquared separately from the Google Sheet. If both produce the same numbers for the same day, the data is verified. This replaces tedious manual checking.
- **No Google execution limits.** Large date ranges work without the pause-and-resume logic that Apps Script needs.

### 1.3 Users

The owner and a few teammates. Some may be non-technical, so the web page must be usable without any knowledge of code.

### 1.4 Goals

1. Produce the same numbers as the Google Sheet for the same dates and filters.
2. Generate any combination of reports for any date range in one run.
3. Support flexible filtering (counselor, source, course, stage, and custom rules).
4. Be safe and predictable: no silent caps, no silent data loss, clear errors.

### 1.5 Non-goals (for now)

- Writing data back to LeadSquared. **FunnelLens is read-only.**
- Replacing the Google Sheet or the Looker Studio dashboard.
- Real-time streaming or live dashboards.

---

## 2. Tech Stack

| Area | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | `zoneinfo` built in, modern typing |
| HTTP | `requests` + `tenacity` | Simple calls with retry and back-off |
| Data | `pandas` | Grouping, pivoting, filtering |
| Cache | `pyarrow` (Parquet files) | Fast local cache of raw pulls |
| Excel | `openpyxl` (or `xlsxwriter` via pandas) | Formatting: bold totals, % formats, column widths |
| Web UI | `streamlit` | Quick, friendly web page for the team |
| CLI | `argparse` (or `typer`) | Scripted and scheduled runs |
| Config | `python-dotenv`, `PyYAML` | Secrets in `.env`, settings in YAML |
| Testing | `pytest` | Unit tests with mocked API responses |
| Timezone | `zoneinfo` (`Asia/Kolkata`) | All IST ↔ UTC conversion |

---

## 3. Architecture

### 3.1 Core idea: pull once, compute many

1. **Extract.** For the chosen date range, fetch the raw leads, opportunities and tasks from LeadSquared **once**.
2. **Normalize.** Clean the data into pandas DataFrames with consistent column names, trimmed text and case-normalized values.
3. **Filter.** Apply the user's filter rules locally.
4. **Build reports.** Each report is a function that groups the same filtered data a different way.
5. **Export.** Write one Excel workbook with a sheet for each selected report, plus Raw Data and Run Info sheets.

This has three benefits:

- **Reports agree with each other.** They all come from the same pull.
- **New reports are cheap.** Adding one needs only a new grouping function, with no new API code.
- **Numbers can be traced.** The Raw Data sheet shows exactly which leads make up every count.

### 3.2 Data flow

```
LeadSquared API
      │  (date range, date field, optional owner)   ← Stage 1 filtering (server side)
      ▼
lsq_client.py  →  extract.py  →  cache/ (parquet)
                                      │
                                      ▼
                               normalize.py
                                      │
                                      ▼
                               filters.py              ← Stage 2 filtering (local)
                                      │
                                      ▼
                               reports/*.py
                                      │
                                      ▼
                               export.py  →  FunnelLens_<from>_to_<to>.xlsx
                                      ▲
                     cli.py  /  app.py (Streamlit)  (both call the same core)
```

### 3.3 Project structure

```
funnellens/
├── README.md                 ← this file (source of truth)
├── PHASES.md                 ← build plan with agent prompts
├── requirements.txt
├── .env.example              ← template for secrets (never commit .env)
├── .gitignore
├── config/
│   ├── config.yaml           ← field mapping, excluded owners, stage list, settings
│   └── presets.yaml          ← saved filter combinations
├── reference/
│   └── apps_script.gs        ← copy of the production Google Apps Script (read-only reference)
├── docs/
│   ├── LOGIC_SPEC.md         ← exact report definitions extracted from the Apps Script
│   └── SETUP_GUIDE.md        ← step-by-step setup for teammates
├── funnellens/
│   ├── __init__.py
│   ├── settings.py           ← loads .env and config.yaml
│   ├── timeutil.py           ← IST ↔ UTC helpers, date windows
│   ├── lsq_client.py         ← all HTTP calls, auth, retries, pagination
│   ├── extract.py            ← leads / opportunities / tasks / users pulls
│   ├── cache.py              ← parquet cache read/write
│   ├── normalize.py          ← cleaning and column standardization
│   ├── filters.py            ← filter rules engine and presets
│   ├── reports/
│   │   ├── __init__.py       ← report registry
│   │   ├── lead_funnel.py
│   │   ├── stage_wise.py
│   │   ├── source_wise.py
│   │   ├── course_wise.py
│   │   ├── reports_tab.py
│   │   ├── final_count.py
│   │   └── source_enrolment.py
│   ├── export.py             ← Excel writing and formatting
│   ├── snapshot.py           ← daily stage snapshots (stage history)
│   └── verify.py             ← compare FunnelLens output with the Google Sheet
├── cli.py                    ← command-line entry point
├── app.py                    ← Streamlit web page
├── data/
│   ├── cache/                ← raw pull cache (git-ignored)
│   └── snapshots/            ← daily stage snapshots (git-ignored)
├── output/                   ← generated Excel files (git-ignored)
└── tests/
    ├── fixtures/             ← sample API responses and small datasets
    └── test_*.py
```

---

## 4. Configuration

### 4.1 Secrets (`.env`, never committed)

```
LSQ_ACCESS_KEY=xxxxxxxx
LSQ_SECRET_KEY=xxxxxxxx
LSQ_API_HOST=https://api-in21.leadsquared.com   # confirm the exact region host
```

When the app is deployed on Streamlit Community Cloud, the same values go into Streamlit **Secrets** instead.

### 4.2 Settings (`config/config.yaml`)

All LeadSquared field names live here, never hard-coded in Python. The values below are **placeholders** and must be filled in from the Apps Script during Phase 0.

```yaml
timezone: Asia/Kolkata

fields:                      # LeadSquared schema names (TO BE CONFIRMED)
  lead_id: ProspectID
  owner: OwnerId
  created_on: CreatedOn
  modified_on: ModifiedOn
  source: Source
  course: mx_Course              # placeholder
  stage: <opportunity field>     # Stage lives on the OPPORTUNITY, not the lead
  enrolled_date: <opportunity field>

stages: [Cold, Warm, Hot, Enrolled, Lost, Not Reachable]   # confirm the full list and order

excluded_owners: []          # same exclusion list as the Apps Script

api:
  page_size: 1000            # use the max the endpoint allows (verify)
  max_records: 100000        # hard safety limit; exceeding it is an ERROR, never a silent truncation
  max_workers: 5             # parallel requests
  retry_attempts: 5
```

### 4.3 Presets (`config/presets.yaml`)

```yaml
presets:
  - name: "Team North – ACCA Hot Leads"
    rules:
      - {field: owner, op: in, value: ["Counselor A", "Counselor B"]}
      - {field: course, op: in, value: ["ACCA"]}
      - {field: stage, op: equals, value: "Hot"}
```

---

## 5. LeadSquared API Notes

- **Auth.** `accessKey` and `secretKey` are passed as query parameters on every request.
- **Host.** The host is region-specific, for example `api-in21.leadsquared.com`. Take the exact host from the Apps Script.
- **Datetimes.** The API works in **UTC**, in the format `yyyy-MM-dd HH:mm:ss`. The business works in **IST (UTC+5:30)**.
- **Endpoints.** The exact endpoint paths, request bodies and response shapes must be copied from the production Apps Script (`reference/apps_script.gs`) and checked against the official LeadSquared API docs. Do **not** invent endpoints. Record them in `docs/LOGIC_SPEC.md`. The Apps Script uses endpoints for:
  - lead search / retrieval by created and modified date
  - **Opportunity Advanced Search**, used for stage and for Enrolled-by-Enrolled-Date
  - task retrieval, used for tasks and overdues
  - users / owners, used to map owner IDs to counselor names
- **Rate limits.** Back off and retry on HTTP 429 and 5xx errors. Never hammer the API.

---

## 6. Critical Rules (lessons from the Apps Script build)

Each of these was a real production bug. **Every phase must respect them.**

1. **Timezone.** Convert IST to UTC before sending. Never send an IST time labelled as UTC.
2. **Always bound date queries.** Every query has an explicit start **and** end. A day is `00:00:00 IST` to `23:59:59 IST`, converted to UTC.
3. **Date-windowed pagination.** Large ranges are split into day windows, and each window is paginated fully. Old days must never get buried under newer ones.
4. **Stage comes from the Opportunity**, not from a lead field.
5. **Enrolled is counted by Enrolled Date** through Opportunity Advanced Search. It is never inferred from "modified today", because leads touched again later get missed that way.
6. **Parallel requests.** Batch API calls with a thread pool (bounded by `max_workers`) for speed.
7. **Case-normalize** sources, courses and stages. "ACCA", "acca " and "Acca" are one value. Trim whitespace. Display the most common original spelling.
8. **Excluded owners** are removed by design, using the same list as the Apps Script. The UI has a toggle to include them.
9. **No silent caps.** The pagination limit is 100,000 records. If a result reaches any limit, **raise an error**. Watch for suspicious round numbers (500, 1,000, 100,000). The old Overdues_Total bug capped silently at 500.
10. **No duplicate rows.** Final Count has exactly one row per counselor per month.
11. **No phantom columns.** Dynamic columns (sources and courses) never include blank or empty-name columns. Missing values go into an explicit "(Blank)" column.
12. **Read-only.** FunnelLens never writes to LeadSquared.

---

## 7. Report Definitions

Each report must match the Google Sheet's logic **exactly**. The detailed column lists and formulas are extracted from the Apps Script in Phase 0 into `docs/LOGIC_SPEC.md`. That file becomes the authority for report logic.

| Report | Date basis | Grouped by | Key outputs |
|---|---|---|---|
| Lead Funnel | Created date; Modified date; task due date | Day, month | Created, Modified, Tasks, Overdues |
| Stage Wise | Lead created date | Day × Stage | Count per stage and a Total |
| Source Wise | Lead created date | Day × Source (dynamic) | Count per source and a Total |
| Course Wise | Lead created date | Day × Course (dynamic) | Count per course and a Total |
| Reports | Per the Apps Script | Day, month | Lost, Not Reachable, Enrolled (by Enrolled Date) |
| Final Count | Month | Counselor | Leads, Enrolled, Overdues_Total, Conversion %, and more per the Apps Script |
| Source Wise Enrolment | Enrolled Date | Source | Enrolments, Conversion % |
| Raw Data | All of the above | One row per lead/opportunity | Replaces "Master Data" for tracing numbers |

### 7.1 Stage history caveat

LeadSquared returns a lead's **current** stage, not its stage on a past date. The Google Sheet records the stage on the day it syncs, so for past days FunnelLens Stage Wise can differ from the Sheet.

This is handled in three ways:

- **Now.** Stage-based reports on past dates are clearly labelled **"Stage as of <run date>"**.
- **From Phase 9 on.** A daily snapshot saves every lead's stage. When a snapshot exists for a date, FunnelLens uses it and labels the report **"Stage as of <that date>"**.
- **Future (optional).** Rebuild historical stages from LeadSquared stage-change activity.

Created counts, Source Wise, Course Wise and Enrolled-by-Enrolled-Date are **not** affected by this caveat.

---

## 8. Filtering

### 8.1 Stage 1: server side (what gets downloaded)

Only three filters are sent to LeadSquared:

- the date range (always required)
- the date field chosen by the report
- the owner (only when specific counselors are selected)

### 8.2 Stage 2: local (on the downloaded data)

Every other condition is applied locally with pandas, so changing a filter needs no new API call. Each rule has the shape `{field, op, value}`.

| Operator | Meaning |
|---|---|
| `equals` / `not_equals` | Exact match (case-insensitive, trimmed) |
| `in` / `not_in` | Matches any value in a list, or none of them |
| `contains` / `not_contains` | Substring match |
| `is_empty` / `not_empty` | Blank, null, "nan" or "none" |
| `gt` / `gte` / `lt` / `lte` | Numeric comparison |
| `between` | Numeric or date range, inclusive |

Rules combine like this:

- **Different fields are combined with AND.**
- **Multiple values in one field are combined with OR**, through `in`.

Excluded owners are applied automatically as a permanent rule, which can be switched off with a toggle.

---

## 9. Excel Output Format

- **File name:** `FunnelLens_<YYYY-MM-DD>_to_<YYYY-MM-DD>.xlsx`, saved in `output/`
- **Sheets:**
  - one sheet per selected report
  - `Raw Data`
  - `Run Info`, which records the generated-at time (IST), date range, reports, filters and presets used, excluded-owner setting, record counts, API call count, and stage-basis labels
- **Layout** (same as the Google Sheet):
  - Days appear **newest first**.
  - A **bold Total row** follows each day's block.
  - Monthly rollups appear where the Sheet has them.
- **Formatting:**
  - bold headers with a frozen header row
  - auto column widths
  - percentages formatted as `0.00%`
  - Conversion % computed with the Apps Script's exact formula; division by zero shows `0%` or blank, as the Sheet does
- **Privacy:** `Raw Data` can mask phone numbers and emails. Masking is on by default in the web app.

---

## 10. Verification (the data check)

`verify.py` compares FunnelLens output with an exported copy of the Google Sheet for the same dates. It produces a `Verification` sheet with these columns: check, date, Sheet value, FunnelLens value, difference, status.

| Metric | Rule |
|---|---|
| Created, Source Wise, Course Wise, Enrolled-by-date | Must match **exactly** |
| Modified, Stage-based counts | A small tolerance is allowed. Differences are labelled **"Late change"**, not "Error" |
| Any value at exactly 500 / 1,000 / 100,000 | Flagged as a **possible cap** |
| Duplicate counselor rows, blank columns, case-duplicate columns | Flagged as **structural** |

The same checks power an optional **Audit** mode.

---

## 11. Running FunnelLens

### 11.1 Setup

```bash
git clone <repo> && cd funnellens
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then fill in your keys
python cli.py test-connection
```

### 11.2 Command line

```bash
python cli.py test-connection
python cli.py pull --from 2026-09-01 --to 2026-09-15
python cli.py generate --reports stage course final --from 2026-09-01 --to 2026-09-15
python cli.py generate --reports all --from 2026-09-01 --to 2026-09-15 --preset "Team North – ACCA Hot Leads"
python cli.py generate --reports stage --from 2026-09-10 --to 2026-09-10 --filter "course in ACCA,CMA"
python cli.py verify --sheet exports/LSQ_Sheet_Sep.xlsx --from 2026-09-01 --to 2026-09-15
python cli.py snapshot           # save today's stage snapshot
python cli.py list-reports       # report keys accepted by --reports
python cli.py list-presets       # preset names from config/presets.yaml
```

`generate` also accepts `--owner NAME` (repeatable), `--include-excluded-owners`, `--mask-pii`, `--force-refresh`, and `--out PATH`. Any command accepts `--debug` (before the subcommand) to show a full traceback instead of a one-line error.

### 11.3 Web app

```bash
streamlit run app.py
```

The web page uses a two-step flow (README section 8): **Load data** fetches once and keeps
it in the session; everything after that (filters, report choice, Generate) is local-only,
with no new API calls except Final Count's live Overdues snapshot.

- **Sidebar:**
  - date range picker (default: yesterday IST) and a **Load data** button, with a Force refresh toggle
  - report checkboxes, plus "Select all"
  - preset picker
  - Counselor, Source, Course and Stage multi-selects (options come from the loaded data)
  - an Advanced rules expander (field / operator / value)
  - Include excluded owners toggle (default off) and Mask phone/email toggle (default on)
  - a form to save the current filters as a new preset
- **Main area:**
  - a **Generate** button
  - a progress bar (during Load data)
  - report previews
  - a **Download Excel** button

### 11.4 Hosting options

1. **Local machine.** Run it on the office network. This is the first choice.
2. **Streamlit Community Cloud.** Keys go in Secrets, and access is restricted to specific emails.
3. **Company server or VM.** Use this if IT policy requires it.

---

## 12. Security

- Never commit `.env`, `data/` or `output/`. They are all in `.gitignore`.
- API keys go only in `.env` or Streamlit Secrets, and must never appear in logs.
- CRM data contains personal information. Mask it in shared exports and limit who can access the hosted app.
- FunnelLens is read-only toward LeadSquared.

---

## 13. Inputs Needed from the Owner

- [ ] Production Apps Script, saved as `reference/apps_script.gs`
- [ ] API host (region)
- [ ] Access key and secret key
- [ ] Field schema names for Source, Course, Stage and Enrolled Date
- [ ] Full stage list, in display order
- [ ] Excluded owners list
- [ ] An exported copy of the Google Sheet for one recent month, used for verification
- [ ] The filters the team uses most often

---

## 14. Glossary

| Term | Meaning |
|---|---|
| LSQ | LeadSquared CRM |
| Lead | A prospect record |
| Opportunity | A sales record linked to a lead; holds Stage and Enrolled Date |
| Counselor / Owner | The sales user who owns a lead |
| Stage | Pipeline stage (Cold, Warm, Hot, Enrolled, …) |
| Enrolled Date | The date a lead converted, stored on the opportunity |
| Overdue | A task past its due date and not completed |
| Conversion % | Enrolments relative to leads, using the exact formula in `LOGIC_SPEC.md` |
| IST | India Standard Time, UTC+5:30 |

---

## 15. Project Status

> Agents: update this section at the end of every phase. Record what was done, the decisions made, and any open issues.

| Phase | Status | Notes |
|---|---|---|
| 0. Setup and Logic Discovery | Done | Folder structure, requirements.txt, .gitignore, .env.example, config/config.yaml, config/presets.yaml created. docs/LOGIC_SPEC.md extracted from reference/apps_script.gs (2185 lines), covering every endpoint, field, all 8 report tabs, excluded owners, stage list, and overdue definitions, each cited to its source function. 15 open questions raised — see Open issues below and docs/LOGIC_SPEC.md "Open Questions". |
| 1. LeadSquared API Client | Done | funnellens/settings.py (.env + Streamlit secrets + config.yaml loader), funnellens/timeutil.py (IST/UTC conversion, day windows, month bounds), funnellens/lsq_client.py (LSQClient: auth, retry with back-off, full pagination with RecordLimitError instead of silent truncation, ThreadPoolExecutor parallel helper, one method per LOGIC_SPEC.md endpoint, secret masking) built. Minimal cli.py with test-connection added. 22 tests in tests/ (timeutil, lsq_client, settings) all pass. `python cli.py test-connection` succeeds against the real API. |
| 2. Data Extraction and Cache | Done | funnellens/extract.py (Dataset dataclass; fetch_dataset pulls leads_created/leads_modified/enrolments per IST day window in parallel, then opportunities + tasks per lead, one day at a time to keep total concurrency bounded by max_workers), funnellens/normalize.py (column renaming to config.yaml field names, IST ist_date, case-normalized source/course/stage via canonicalize_column, counselor roster + is_excluded_owner from Users.Get), funnellens/cache.py (parquet cache, one file per entity/IST date, valid once ≥2 days old, force_refresh option) built. `cli.py pull --from --to [--force-refresh]` added, printing row counts per entity per day and the API call count. 39 tests pass. Real-day run (2026-09-15): 88 created, 173 modified, 198 opportunities, 5 enrolments, 107 tasks, 35 users, 287 API calls; a second run for the same day made 1 call (get_users(), which is intentionally uncached). |
| 3. Filtering Engine | Done | funnellens/filters.py: Rule dataclass (validates field against every normalize.py column, and op against README §8.2's 13 operators), apply_filters (AND across rules, `in`/`not_in` give OR within a field, case-insensitive/trimmed text, is_empty/not_empty treat "", NaN, None, "nan", "none", "(Blank)" as empty, gt/gte/lt/lte/between coerce to numeric or datetime and never crash on bad data), apply_to_dataset (per-Dataset-frame filtering, skips a rule where the frame lacks that field, excluded-owners rule on by default via include_excluded_owners), parse_filter_string, load_presets/get_preset (config/presets.yaml, validated), available_values. 31 new tests (70 total) pass. Verified against real Phase 2 data: filtering leads_created by source correctly narrowed 88 rows to 18. |
| 4. Report Builders | Done | funnellens/reports/{__init__,_shared,lead_funnel,stage_wise,source_wise,course_wise,reports_tab,final_count,source_enrolment,raw}.py + funnellens/checks.py built per LOGIC_SPEC.md section 3 exactly. Registry of 8 keys, every builder is build(dataset, from_date, to_date, context) -> ReportResult (DataFrame + an `is_total` column marking Total rows). Days newest-first with a Total row per day block; Monthly/Yesterday columns are pandas SUMIFS-equivalents over whatever calendar days are present in `dataset` (caller must pull enough history -- documented in _shared.py). Stage Wise carries a "Stage as of <run date>" label (Phase 9 hook not yet wired). checks.py implements all 6 Phase 4 consistency checks. 30 new tests (100 total) pass on a hand-built fixture with known-correct answers. Verified against real Phase 2 data (2026-09-15): all 8 reports build without error; checks.py caught a real issue -- see Open issues. |
| 5. Excel Export | Done | funnellens/export.py: write_workbook(results, run_info, path=None) -> bytes, always saving to `path` (or the default `output/FunnelLens_<from>_to_<to>.xlsx`, from run_info's from_date/to_date). One sheet per selected report (given order) + Raw Data (pulled out of `results` by key=="raw") + Run Info (caller's run_info dict, plus stage-basis labels and checks.py's issue count computed here) + an Issues sheet only when checks.py finds any. Bold/frozen headers, bold Total rows with a light fill, `0.00"%"` format for %% columns (values are already 0-100, so the built-in `0.00%` format would double-scale them), integer format for counts, auto-sized columns. 12 new tests (112 total) pass. Real-data sample generated at output/FunnelLens_2026-09-15_to_2026-09-15.xlsx. |
| 6. Command-Line Interface | Done | funnellens/pipeline.py: run_pipeline(options, progress_callback) -> (bytes, run_info), the shared fetch_dataset -> normalize -> filter -> build reports -> checks -> write_workbook pipeline (raises PipelineError for an unknown report key or a reversed date range; always includes the "raw" report so Raw Data appears even if not selected; run_info carries output_path, api_calls, row_counts and the checks.py issue list). cli.py: test-connection, pull, generate (--reports/--from/--to/--owner/--filter/--preset/--include-excluded-owners/--mask-pii/--force-refresh/--out), verify/snapshot stubs, list-reports, list-presets. Error handling is centralized once in main() (SettingsError/LSQError/PipelineError/FilterError/ValueError -> a one-line message and exit 1; --debug re-raises). 17 new tests (129 total) pass. Real run: `python cli.py generate --reports all --from 2026-09-15 --to 2026-09-15` wrote a 10-sheet workbook and correctly surfaced the Overdues_Total==500 issue from Phase 4 on stdout. |
| 7. Streamlit Web App | Done | app.py: two-step flow -- "Load data" (sidebar) calls pipeline.fetch_and_normalize() once and stores the Dataset/Settings/LSQClient in st.session_state; everything else (report checkboxes, preset picker, Counselor/Source/Course/Stage multi-selects populated via filters.available_values(), an Advanced rules expander, excluded-owners/mask-PII/force-refresh toggles, a save-as-preset form) is local-only and calls pipeline.build_report_results() on Generate, with no new API calls except Final Count's live snapshot. Preview tabs per report, a Download Excel button, a friendly-error/technical-details-expander pattern, and an optional shared-password gate (APP_PASSWORD secret/env; no-op if unset). Split pipeline.py further into fetch_and_normalize() + build_report_results() + build_workbook() so app.py and cli.py share the exact same filter/report logic without recomputing reports twice for preview vs. export. 21 new tests (142 total) pass, including 8 headless functional tests using Streamlit's own AppTest harness (load data, filter dropdowns, Generate, error paths) -- no browser needed, since the available Chrome instance wasn't network-reachable from this environment. Verified against real cached data too (2026-09-15): Load Data and Generate both completed with 7 report tabs and a working download button; fixed one real cosmetic bug found this way (Total rows' blank cells confused Streamlit's Arrow table serializer). |
| 8. Verification Against Google Sheet | Not started | |
| 9. Stage Snapshots, Deployment and Handover | Not started | |

### Decision log

| Date | Decision | Reason |
|---|---|---|
| 2026-09 | Name: FunnelLens | Clear view into the LSQ funnel, and it doubles as a data check |
| 2026-09 | Streamlit web UI + CLI sharing one core | The team includes non-technical users |
| 2026-09 | Date logic matches the Google Sheet exactly | Output must be comparable with the Sheet |
| 2026-09 | Pull once, compute all reports locally | Consistency, speed, easy new reports |
| 2026-09 | Stage history: label now, add snapshots later | LSQ only returns the current stage |
| 2026-09-16 | Field schema (Source, Course, Stage, Enrolled Date, owner) filled into config.yaml from reference/apps_script.gs CONFIG constant, not guessed | Script comments explicitly mark these as "confirmed" against the live LeadSquared account |
| 2026-09-16 | config.yaml's stage list corrected to the real 15-value CONFIG.STAGES array; "Lost" removed from stages and modeled as opportunity_status instead | README's original placeholder stage list (Cold/Warm/Hot/Enrolled/Lost/Not Reachable) doesn't match production; Lost is an Opportunity Status value, not a Stage value |
| 2026-09-16 | All 15 Phase 0 open questions resolved by the owner; FunnelLens replicates the Apps Script's behavior/formulas exactly wherever a choice existed (column order, NR Yesterday % denominator, live-snapshot Overdues, no Total rows on Final Count/Source Wise Enrolment, 500-task and 100k/4k record caps) | Verification against the Google Sheet (README goal 1) requires matching its exact output, not a "corrected" version of it; FunnelLens still raises errors instead of silently truncating per Rule 9 |
| 2026-09-16 | LSQClient accepts LSQ_API_HOST as either a bare host or a full https:// URL, instead of enforcing the bare-host decision from Phase 0 | The project's real .env (created independently by the owner) already held the full URL; testing against it found the bare-host assumption would have broken test-connection. Accepting both is a one-line fix with no downside. |
| 2026-09-16 | requirements.txt pins pyarrow, which fails to build from source on Python 3.14 (no prebuilt wheel yet); tzdata added as a Windows-only dependency since zoneinfo has no system tz database there | Discovered while installing Phase 1 dependencies. Doesn't block Phase 1 (pyarrow is only needed starting Phase 2's parquet cache) but the project's Python version may need pinning to <3.14 before Phase 2, or wait for pyarrow wheels to catch up. |
| 2026-09-17 | requirements.txt's pyarrow pin bumped from `>=14.0,<15` to `>=20.0,<26` | pyarrow 20+ ships a cp314 wheel; 14.x-19.x only build from source and that build fails on Python 3.14 (pkg_resources missing). Resolves the open issue logged during Phase 1. |
| 2026-09-17 | LSQClient throttles itself to 18 calls per 5s (a lock + sliding window of call timestamps), shared across every thread it spawns | The real account enforces a hard 20-calls/5s limit. With 5 parallel workers each independently retrying on 429 (tenacity's per-call back-off), a real Phase 2 pull against a day with ~90 leads kept every worker retrying into the same saturated window and never cleared, exhausting all 5 retry attempts. A shared rate limiter that blocks *before* sending fixes the root cause instead of retrying harder. |
| 2026-09-17 | extract.py tags each enrolments day-window with an `ist_date` column at fetch time | The Opportunity Advanced Search response never returns an Enrolled Date field per record (it's only the search's own filter parameter, per LOGIC_SPEC.md 1.5) -- without tagging it, Reports/Final Count/Source Wise Enrolment (Phase 4) couldn't attribute an enrolment to a day or month at all once multiple days' results were concatenated. |
| 2026-09-17 | Final Count's live Overdues snapshot (LOGIC_SPEC.md 6.1) is fetched via a live LSQClient call inside final_count.py at report-build time, not from the Phase 2 cache | Resolved Decision 5 requires this figure to reflect "now" at generation time, not a historically cached pull -- the same live-query behavior the Apps Script itself uses. ReportContext gained an optional `client` field for this one report; every other report builder is a pure function of `dataset`. Owner confirmed this approach over caching a stale per-owner snapshot in Phase 2. |
| 2026-09-17 | Percentage columns in export.py use a custom `0.00"%"` number format instead of Excel's built-in `0.00%` | Report builders' safe_pct() already returns the percentage on a 0-100 scale (e.g. 66.7), matching every ROUND(x/y*100,1) formula in LOGIC_SPEC.md; the built-in `0.00%` format multiplies the cell value by 100 again for display, which would show "6670.00%". The custom format just appends a literal "%" without rescaling. |
| 2026-09-17 | export.py strips tzinfo from any timezone-aware datetime cell before writing (report sheets and Run Info) | openpyxl raises `TypeError: Excel does not support timezones in datetimes` on a tz-aware value -- caught by generating a real sample workbook, since normalize.py's IST-aware datetimes (created_on, enrolled_date, etc.) flow straight into Raw Data, and run_info's generated_at is also tz-aware. |
| 2026-09-17 | Run Info's `generated_at` is converted to IST before being written, not just stripped of tzinfo | README section 9 requires the generated-at time in IST; the tz-stripping fix above preserved whatever zone the datetime happened to be in (UTC, from `datetime.now(timezone.utc)`), which isn't what a reader expects labeled "generated_at" without a zone marker. |
| 2026-09-17 | normalize.py's normalize_opportunities() drops duplicate lead_id rows (keeping the last) | A multi-day `generate` run crashed with "The truth value of a Series is ambiguous": extract.py fetches opportunities per created-day window, so a lead created on one day and modified on another is fetched in both days' windows, and stage_wise.py's `.set_index("lead_id")[...].get(lead_id)` returned a Series instead of a scalar once duplicates existed. Fixed once at the shared source (every report joins opportunities by lead_id) instead of patching stage_wise.py alone -- raw.py had already independently worked around the same issue with its own `drop_duplicates`, since removed as redundant. |
| 2026-09-17 | funnellens/pipeline.py split into fetch_and_normalize() + build_report_results() + build_workbook(), with run_pipeline() as both back to back | Phase 7's two-step web UI (Load data once, then filter/Generate repeatedly with no new API calls) needed the fetch and the filter/report/export stages separately; build_report_results() is factored out further so app.py's preview tabs and its Download button use the exact same computed ReportResults instead of building reports twice. cli.py's `generate` command (run_pipeline) is unaffected. |
| 2026-09-17 | app.py verified via Streamlit's own AppTest harness (headless, no browser) instead of a live browser session | The only connected Chrome browser was on a different machine, not network-reachable from this dev environment's localhost. AppTest actually drives the real widget tree (button clicks, session_state, reruns) rather than mocking the UI layer, so it's a faithful substitute, not a downgrade -- a live-browser check is still worth doing before hosting the app for the team. |

### Open issues

- All 15 Phase 0 open questions were answered by the project owner on 2026-09-16 — see `docs/LOGIC_SPEC.md` → "Resolved Decisions" for the full list, rationale, and citations. Key outcomes: the Apps Script's 500-task pagination cap and 100,000/4,000-record search caps are accepted as-is, but FunnelLens raises an error (never truncates silently) when a cap is hit; Stage Wise/Master Data column order and Reports' "NR Yesterday %" formula are replicated exactly as coded, for verification against the Sheet; no Total rows are added to Final Count or Source Wise Enrolment. Note: `LSQ_API_HOST`'s format decision (bare host) was superseded during Phase 1 — see the decision log below.
- Resolved 2026-09-17: `requirements.txt`'s pyarrow pin was bumped to `>=20.0,<26` (see decision log), which installs cleanly on Python 3.14.
- **New, 2026-09-17:** Final Count's `Overdues_Total` for real counselors (e.g. Manish Anand, Navya Seth, Sakshi Kapoor as of 2026-09-15) came back exactly `500` -- `funnellens/checks.py`'s "no value sits exactly at 500/1000/100000" check caught this live. This is the exact silent-cap shape Resolved Decision 2 accepted "for now" on the assumption that "no counselor currently has anywhere near 500 pending tasks" -- that assumption no longer holds. `Task.svc/Retrieve` (LOGIC_SPEC.md 1.2) never advances its `Offset` beyond 0, so counselors past 500 pending tasks are silently undercounted. Needs an owner decision: confirm whether the endpoint's `Offset`/`RowCount` paging actually works (untested, so FunnelLens shouldn't just start looping it without confirmation) before Final Count's Overdues figures can be trusted for these counselors.
