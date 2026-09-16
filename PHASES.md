# FunnelLens — Build Phases

This file breaks the FunnelLens build into 10 phases. Each phase has a goal, deliverables, acceptance criteria, and a **ready-to-paste prompt** for your coding agent.

## How to use this file

1. Put `README.md`, `PHASES.md` and your Apps Script (`reference/apps_script.gs`) in the project folder before starting.
2. Run **one phase per agent session**, in order. Don't skip phases.
3. Paste the phase's prompt exactly as written. Every prompt starts by making the agent read `README.md`.
4. Before moving on, check the phase's **acceptance criteria** yourself.
5. The agent updates **Project Status** in `README.md` at the end of every phase.
6. If the agent says something conflicts with the README, decide what's right and update the README first. The README is always the source of truth.

**If an agent drifts off track,** paste this:

```
Stop. Re-read README.md, especially Section 6 (Critical Rules) and the phase you are working on in PHASES.md. List what you did that doesn't match, then fix it.
```

---

## Phase 0 — Setup and Logic Discovery

**Goal:** Create the project skeleton, and extract the exact business logic from the production Apps Script into a written spec.

**Deliverables:**
- the folder structure from README §3.3
- `requirements.txt`, `.gitignore` and `.env.example`
- `config/config.yaml` with the real field names
- `config/presets.yaml` (an empty template)
- `docs/LOGIC_SPEC.md`

**Acceptance criteria:**
- [ ] The folder structure matches the README.
- [ ] `docs/LOGIC_SPEC.md` lists every endpoint, request body, field name and report formula found in the Apps Script. Each item cites the Apps Script function it came from.
- [ ] `config.yaml` contains no placeholders, or each remaining one is listed as an open question.
- [ ] No business logic code has been written yet.

**Prompt:**

```
You are building FunnelLens. Before doing anything, read README.md completely. It is the source of truth for this project. Then read PHASES.md and focus only on Phase 0.

Your task for Phase 0: Setup and Logic Discovery.

1. Create the folder and file structure exactly as shown in README.md Section 3.3. Use empty files or minimal stubs with docstrings. Do not implement logic yet.
2. Create requirements.txt using the tech stack in README Section 2. Pin major versions.
3. Create .gitignore so that .env, data/, output/, .venv/, __pycache__/ and *.parquet are excluded.
4. Create .env.example with LSQ_ACCESS_KEY, LSQ_SECRET_KEY and LSQ_API_HOST, using placeholder values.
5. Read reference/apps_script.gs carefully, all of it, and create docs/LOGIC_SPEC.md. It must document:
   a. The API host and every LeadSquared endpoint used: HTTP method, path, request body shape, response shape, and pagination method.
   b. Every LeadSquared field name used, and what it means. This includes Source, Course, Stage (on the Opportunity), Enrolled Date, owner, created and modified dates, and task fields.
   c. For EACH report tab (Lead Funnel, Stage Wise, Source Wise, Course Wise, Reports, Final Count, Source Wise Enrolment, Master Data):
      - which date field filters it
      - how rows and columns are built
      - every column, in order
      - every formula (for example Conversion %, Overdues_Total, Enrolled), written exactly
      - how totals and monthly rollups are calculated
   d. The excluded owners list and how it is applied.
   e. How the stage list and stage order are defined.
   f. How "overdue" is defined (task status, due date comparison, timezone).
   For every item, cite the Apps Script function name it came from. If something is unclear or missing, write it under an "Open Questions" heading. Do not guess.
6. Fill config/config.yaml (format from README Section 4.2) with the real values from the Apps Script.
7. Create config/presets.yaml with an empty presets list and one commented example.
8. Update the "Project Status" table and decision log in README.md, and add any open questions to "Open issues".

Rules: Follow README Section 6 (Critical Rules). Do not write business logic in this phase. Do not invent endpoints or field names. At the end, summarise what you created and list the open questions I need to answer.
```

---

## Phase 1 — LeadSquared API Client

**Goal:** Build one reliable module for all communication with LeadSquared.

**Deliverables:** `funnellens/settings.py`, `funnellens/timeutil.py`, `funnellens/lsq_client.py`, and their tests.

**Acceptance criteria:**
- [ ] IST↔UTC conversion is tested, including day boundaries and month ends.
- [ ] Pagination fetches every page, and raises an error if `max_records` is reached.
- [ ] Retries with back-off work on 429 and 5xx errors (tested with mocks).
- [ ] Keys never appear in logs or error messages.
- [ ] `python cli.py test-connection` succeeds against the real API. A minimal version of `cli.py` is fine for now.

**Prompt:**

```
You are building FunnelLens. Before doing anything, read README.md completely, then docs/LOGIC_SPEC.md, then Phase 1 in PHASES.md. Check the Project Status in README.md to confirm Phase 0 is done.

Your task for Phase 1: LeadSquared API Client.

1. funnellens/settings.py
   - Load secrets from .env using python-dotenv. Also support Streamlit secrets when they are available.
   - Load config/config.yaml.
   - Validate that all required values are present. Fail with a clear message that never prints secret values.

2. funnellens/timeutil.py
   - Use the timezone Asia/Kolkata from config.
   - ist_day_bounds(date) returns (start_utc, end_utc) for 00:00:00 to 23:59:59 IST, converted to UTC.
   - to_lsq_utc_string(dt) formats a datetime as "yyyy-MM-dd HH:mm:ss" in UTC.
   - from_lsq_utc_string(s) parses LSQ UTC strings and returns IST-aware datetimes.
   - day_windows(from_date, to_date) yields one (start_utc, end_utc) pair per IST day.
   - month_bounds(date) returns the start and end of that month.

3. funnellens/lsq_client.py, a class LSQClient:
   - Authenticate with accessKey and secretKey as query parameters, as documented in LOGIC_SPEC.md.
   - Provide a generic request method with timeouts and tenacity retries. Use exponential back-off on HTTP 429, 5xx and connection errors, with retry_attempts from config.
   - Paginate using the exact method documented in LOGIC_SPEC.md. Loop until the last page. If the total reaches api.max_records, raise a RecordLimitError. Never truncate silently.
   - Provide a parallel helper that runs many requests with a ThreadPoolExecutor bounded by api.max_workers, and returns results in input order.
   - Provide one thin method per endpoint listed in LOGIC_SPEC.md. Every date-based method must take BOTH a start and an end (README Critical Rules 1–3).
   - Provide a test_connection() method that makes one cheap, read-only call.
   - Mask secrets in all logging and in exception text.

4. A minimal cli.py with a "test-connection" command.

5. Tests in tests/ using mocked HTTP responses (the responses library or unittest.mock):
   - timezone conversion, including a day boundary, a month end and a leap year
   - pagination across multiple pages, and RecordLimitError
   - retry on 429, followed by success
   - secrets never appear in the text of a raised exception

Rules: Follow README Section 6. Use only the endpoints documented in LOGIC_SPEC.md. FunnelLens is read-only, so no write calls. Run pytest and make sure all tests pass. Update Project Status in README.md. Summarise what you built and how I can run test-connection.
```

---

## Phase 2 — Data Extraction and Cache

**Goal:** Pull all raw data for a date range into clean DataFrames, with a local cache.

**Deliverables:** `funnellens/extract.py`, `funnellens/normalize.py`, `funnellens/cache.py`, and their tests.

**Acceptance criteria:**
- [ ] One function returns a `Dataset` holding leads, opportunities, enrolments, tasks and users as DataFrames.
- [ ] Data is pulled day by day, in parallel.
- [ ] Case variants are merged, for example "ACCA" and "acca ".
- [ ] A second run for the same dates uses the cache and makes no API calls.
- [ ] Record counts for one real day are printed, and look sensible when compared with the Sheet.

**Prompt:**

```
You are building FunnelLens. Before doing anything, read README.md completely, then docs/LOGIC_SPEC.md, then Phase 2 in PHASES.md. Confirm in Project Status that Phases 0–1 are done.

Your task for Phase 2: Data Extraction and Cache.

1. funnellens/extract.py
   - Create a dataclass Dataset holding these DataFrames:
     - leads_created: leads created in the range
     - leads_modified: leads modified in the range
     - opportunities: holds stage, using the field from config
     - enrolments: opportunities by Enrolled Date, from Opportunity Advanced Search, as in LOGIC_SPEC.md
     - tasks: including the fields needed to calculate overdues
     - users: to map owner IDs to counselor names
   - Create fetch_dataset(from_date, to_date, owners=None, progress_callback=None) -> Dataset.
   - Split the range into IST day windows (timeutil.day_windows) and fetch windows in parallel with LSQClient's parallel helper. Report progress through progress_callback so the UI can show a progress bar.
   - Apply server-side filters ONLY for date range, date field and owner (README Section 8.1).
   - Join each lead to its opportunity stage in the same way the Apps Script does.
   - Fetch overdues in full, with no caps (Critical Rule 9).

2. funnellens/normalize.py
   - Rename columns to the internal names in config.yaml "fields".
   - Convert every datetime to IST-aware values, and add an ist_date column.
   - For source, course and stage: trim whitespace, add a normalized key (lowercase, single spaces), and set the display value to the most common original spelling for each key.
   - Put missing source or course values into "(Blank)". Never produce an empty-named value (Critical Rule 11).
   - Map owner IDs to counselor names.
   - Add a boolean column is_excluded_owner using excluded_owners from config.

3. funnellens/cache.py
   - Save raw pulls as parquet files in data/cache/, with one file per (entity, IST date).
   - A day that is at least 2 days old is cache-valid. Today and yesterday are always refetched, because data can still change.
   - Provide a force_refresh option.
   - fetch_dataset uses the cache for each day window where possible.

4. Add "python cli.py pull --from YYYY-MM-DD --to YYYY-MM-DD" to cli.py. It prints row counts per entity per day and the number of API calls made.

5. Tests with fixtures:
   - normalization, including case variants and blanks
   - owner mapping
   - cache hit and cache miss
   - the stage join
   - an error being raised when data exceeds the limit

Rules: Follow README Section 6 strictly, especially rules 1–5, 7, 9 and 11. Run pytest. Update Project Status in README.md. Tell me how to run the pull command for one real day so I can compare its counts with the Google Sheet.
```

---

## Phase 3 — Filtering Engine

**Goal:** Build local, rule-based filtering with presets.

**Deliverables:** `funnellens/filters.py` and its tests.

**Acceptance criteria:**
- [ ] Every operator in README §8.2 works and is tested.
- [ ] Rules on different fields combine with AND; `in` gives OR within a field.
- [ ] Presets load from YAML and are validated.
- [ ] The excluded-owners rule is applied by default and can be switched off.

**Prompt:**

```
You are building FunnelLens. Before doing anything, read README.md completely, especially Section 8 (Filtering), then Phase 3 in PHASES.md. Confirm in Project Status that Phases 0–2 are done.

Your task for Phase 3: Filtering Engine.

1. funnellens/filters.py
   - Define a Rule dataclass with field, op and value, and validate it on creation. An unknown field or operator raises a clear error.
   - Support these operators: equals, not_equals, in, not_in, contains, not_contains, is_empty, not_empty, gt, gte, lt, lte, between.
   - Text comparisons are case-insensitive and trimmed. Where a normalized key column exists, use it.
   - is_empty treats "", NaN, None, "nan", "none" and "(Blank)" as empty.
   - Numeric and date operators convert values safely, without crashing on bad data.
   - apply_filters(df, rules) applies rules one after another (AND between rules).
   - apply_to_dataset(dataset, rules, include_excluded_owners=False) filters every DataFrame in the Dataset consistently. A rule is applied only to DataFrames that have the rule's field. Excluded owners are removed unless include_excluded_owners is True.
   - parse_filter_string("course in ACCA,CMA") -> Rule, for use by the CLI.
   - load_presets() and get_preset(name) read config/presets.yaml, with validation.
   - available_values(dataset, field) returns the sorted display values, for the UI dropdowns.

2. Thorough tests covering:
   - each operator
   - AND/OR combination
   - case and whitespace handling
   - blanks
   - bad input
   - presets
   - the excluded-owners toggle

Rules: Filtering in this phase is local only. Do not add API calls. Follow README Section 6. Run pytest. Update Project Status in README.md.
```

---

## Phase 4 — Report Builders

**Goal:** Build every report so that it matches the Google Sheet logic exactly.

**Deliverables:** `funnellens/reports/*.py`, a report registry, and tests.

**Acceptance criteria:**
- [ ] Every report follows `docs/LOGIC_SPEC.md` exactly: columns, order, formulas and totals.
- [ ] Days are newest first, and a Total row follows each day block.
- [ ] Stage Wise, Source Wise, Course Wise and Lead Funnel all have the same Created total for each day.
- [ ] Final Count has exactly one row per counselor per month.
- [ ] Stage-based reports carry a "Stage as of …" label.

**Prompt:**

```
You are building FunnelLens. Before doing anything, read README.md completely, especially Sections 6 and 7, then read docs/LOGIC_SPEC.md carefully, then Phase 4 in PHASES.md. Confirm in Project Status that Phases 0–3 are done.

Your task for Phase 4: Report Builders.

1. funnellens/reports/__init__.py
   - Create a registry mapping a report key to a builder function and a display name. Keys: lead_funnel, stage, source, course, reports, final, source_enrolment, raw.
   - Every builder has the signature build(dataset, from_date, to_date, context) -> ReportResult.
   - ReportResult holds:
     - a DataFrame
     - metadata: title, date basis, stage-basis label, and which rows are total rows

2. Implement each report in its own file, following LOGIC_SPEC.md EXACTLY:
   - lead_funnel.py: daily and monthly Created, Modified, Tasks and Overdues
   - stage_wise.py: day × stage, using the stage order from config
   - source_wise.py and course_wise.py: day × dynamic columns. Only include values that actually appear, and never blank-named columns. Put "(Blank)" last and Total at the end.
   - reports_tab.py: Lost, Not Reachable and Enrolled, daily and monthly. Enrolled uses the enrolments DataFrame (by Enrolled Date), never modified date.
   - final_count.py: one row per counselor per month, with every column and formula from LOGIC_SPEC.md, including Overdues_Total (uncapped) and Conversion % (exact formula, safe on division by zero). Deduplicate strictly.
   - source_enrolment.py: enrolments and Conversion % by source.
   - raw.py: a flat, traceable table of every lead/opportunity used, with a mask_pii option for phone and email.

3. Layout rules (README Section 9):
   - Days are newest first.
   - A bold Total row follows each day block (mark total rows in the metadata; export will format them).
   - Monthly rollups appear where the Sheet has them.

4. Stage caveat (README Section 7.1): stage-based reports set the label "Stage as of <run date in IST>". Leave a clear hook for Phase 9 snapshots, so that a snapshot's stage is used when one exists for a date.

5. Create funnellens/checks.py with internal consistency checks that return a list of issues:
   - Created totals match across lead_funnel, stage, source and course for each day
   - each Total row equals the sum of its block
   - monthly rollups equal the sum of their daily rows
   - Final Count has no duplicate counselors
   - there are no blank-named columns
   - no value sits exactly at 500, 1000 or 100000

6. Tests built on a small hand-made fixture dataset where you know the correct answers. Test every report and every check.

Rules: If LOGIC_SPEC.md is unclear about something, stop and list the question. Do not guess business logic. Follow README Section 6. Run pytest. Update Project Status in README.md.
```

---

## Phase 5 — Excel Export

**Goal:** Produce a clean, formatted workbook that looks like the Google Sheet.

**Deliverables:** `funnellens/export.py` and its tests.

**Acceptance criteria:**
- [ ] One sheet per selected report, plus `Raw Data` and `Run Info`.
- [ ] Total rows are bold, headers are frozen, percentages are formatted, and columns are auto-sized.
- [ ] The file name follows the README pattern.
- [ ] The workbook can also be returned as bytes, for the Streamlit download button.

**Prompt:**

```
You are building FunnelLens. Before doing anything, read README.md completely, especially Section 9 (Excel Output Format), then Phase 5 in PHASES.md. Confirm in Project Status that Phases 0–4 are done.

Your task for Phase 5: Excel Export.

1. funnellens/export.py
   - write_workbook(results: list[ReportResult], run_info: dict, path=None) -> bytes. It always returns bytes, and also saves the file when a path is given.
   - Create one sheet per report, in registry order. Sheet names are at most 31 characters.
   - Each sheet has a title row, a "Stage as of …" label where relevant, and a bold, frozen header row.
   - Total rows (from the metadata) are bold, with a light fill.
   - Percentage columns use the 0.00% format, and count columns use integer format.
   - Column widths fit the content, within a sensible maximum.
   - Add a Raw Data sheet, with PII masked when requested.
   - Add a Run Info sheet recording:
     - generated-at time (IST) and date range
     - reports and filters/presets used
     - excluded-owners setting
     - row counts and API call count
     - stage-basis labels
     - any issues found by checks.py
   - If checks.py found issues, also add an "Issues" sheet.
   - The default file name is output/FunnelLens_<from>_to_<to>.xlsx.

2. Tests:
   - Open the generated file with openpyxl and assert the sheet names, bold total rows, the percentage number format, the frozen panes and the Run Info contents.

Rules: Follow README Sections 6 and 9. Run pytest. Update Project Status in README.md. Generate one sample file from fixture data and tell me where it is.
```

---

## Phase 6 — Command-Line Interface

**Goal:** Build a complete CLI for scripted and quick runs.

**Deliverables:** the full `cli.py`, plus usage docs.

**Acceptance criteria:**
- [ ] All commands in README §11.2 work: `test-connection`, `pull`, `generate`, `verify` (can be a stub until Phase 8), and `snapshot` (can be a stub until Phase 9).
- [ ] Helpful `--help` text, and clear error messages.
- [ ] A real run for one day produces a correct Excel file.

**Prompt:**

```
You are building FunnelLens. Before doing anything, read README.md completely, especially Section 11, then Phase 6 in PHASES.md. Confirm in Project Status that Phases 0–5 are done.

Your task for Phase 6: Command-Line Interface.

1. Complete cli.py with these commands:
   - test-connection
   - pull --from --to [--force-refresh]
   - generate --reports <keys or "all"> --from --to [--owner ...] [--filter "<rule>" ...] [--preset NAME] [--include-excluded-owners] [--mask-pii] [--force-refresh] [--out PATH]
   - verify --sheet PATH --from --to (a stub that says "available after Phase 8")
   - snapshot (a stub that says "available after Phase 9")
   - list-reports and list-presets

2. The generate command runs the full pipeline:
   fetch_dataset → apply filters → build the selected reports → run checks → write the workbook
   It shows a progress bar and prints the output path and any issues found.

3. Validate input: dates in YYYY-MM-DD format, from <= to, known report keys, and a valid filter syntax. Print friendly errors without Python tracebacks, unless --debug is given.

4. Put the core pipeline in a reusable function, funnellens/pipeline.py: run_pipeline(options, progress_callback) -> (bytes, run_info). Phase 7 will reuse it.

5. Update README Section 11.2 if any commands changed.

Rules: Follow README Section 6. The CLI and the future web app must share the same pipeline code. Run pytest. Update Project Status in README.md. Give me the exact command to generate all reports for yesterday.
```

---

## Phase 7 — Streamlit Web App

**Goal:** Build a friendly web page for the team.

**Deliverables:** `app.py`.

**Acceptance criteria:**
- [ ] A non-technical user can generate and download a report without instructions.
- [ ] Filter dropdowns fill in from the data.
- [ ] Presets and the excluded-owners toggle work.
- [ ] Errors are shown as friendly messages.

**Prompt:**

```
You are building FunnelLens. Before doing anything, read README.md completely, especially Sections 8, 9 and 11.3, then Phase 7 in PHASES.md. Confirm in Project Status that Phases 0–6 are done.

Your task for Phase 7: Streamlit Web App.

1. Build app.py, which uses funnellens/pipeline.py. Do not duplicate business logic.

2. Page layout:
   - Header: "FunnelLens: LeadSquared reports in one click"
   - Sidebar:
     - date range picker (default: yesterday)
     - report checkboxes, plus "Select all"
     - preset picker
     - counselor, source, course and stage multi-selects
     - an "Advanced rules" expander where users add rules with field, operator and value
     - an "Include excluded owners" toggle (default off)
     - a "Mask phone/email" toggle (default on)
     - a "Force refresh" toggle
   - Main area:
     - a Generate button and a progress bar
     - a tab for each report with a preview table
     - an issues panel if checks found problems
     - a Download Excel button

3. Two-step flow, so dropdowns can fill from real data:
   - Step 1, "Load data": fetch the dataset for the date range, and keep it in st.session_state.
   - Step 2: filters and report choices update instantly from the loaded data, with no new API calls (README Section 8.2).
   - If the date range changes, ask the user to reload.

4. Use st.cache_data or session state sensibly. Never show API keys. Show friendly error messages, with technical details inside an expander.

5. Save the current filters as a new preset through a small form that writes to config/presets.yaml. Validate the name and prevent duplicates.

6. Add a simple password gate, using a shared app password from secrets, for when the app is hosted.

Rules: Follow README Sections 6 and 12. Keep the UI simple for non-technical users. Update README Section 11.3 if needed. Update Project Status in README.md. Tell me how to run it and what to check.
```

---

## Phase 8 — Verification Against Google Sheet

**Goal:** Automatically check FunnelLens numbers against the Google Sheet. This is the data check that replaces manual work.

**Deliverables:** `funnellens/verify.py`, a working `cli.py verify` command, and a Verify page in the app.

**Acceptance criteria:**
- [ ] Reads an exported copy of the Google Sheet (.xlsx) and matches it by tab, date and column.
- [ ] Applies the rules in README §10: exact matches, tolerances, "Late change" labels, cap and structure flags.
- [ ] Produces a colour-coded `Verification` sheet and a summary: X passed, Y late changes, Z errors.
- [ ] A real month is verified, and any mismatches are explained.

**Prompt:**

```
You are building FunnelLens. Before doing anything, read README.md completely, especially Section 10 (Verification), then docs/LOGIC_SPEC.md, then Phase 8 in PHASES.md. Confirm in Project Status that Phases 0–7 are done.

Your task for Phase 8: Verification Against the Google Sheet.

1. funnellens/verify.py
   - load_sheet_export(path) reads the exported Google Sheet .xlsx and parses each tab, using the tab and column layout described in LOGIC_SPEC.md. Handle day blocks, Total rows, monthly rollups and dynamic columns. Tolerate small differences in case and whitespace in header names.
   - compare(sheet_data, funnellens_results, from_date, to_date) -> DataFrame with columns: check, tab, date, key (for example a stage, source or counselor), sheet_value, funnellens_value, difference, status.
   - Status rules from README Section 10:
     - EXACT for Created, Source Wise, Course Wise and Enrolled-by-date. A mismatch is ERROR.
     - TOLERANCE for Modified and stage-based counts. Put the tolerance in config.yaml under verify.tolerance_pct, with a default of 2. A mismatch within tolerance is LATE_CHANGE; beyond tolerance it is ERROR.
     - Values at exactly 500, 1000 or 100000 are flagged POSSIBLE_CAP.
     - Duplicate counselors, blank columns and case-duplicate columns are flagged STRUCTURE.
     - Keys present in only one side are flagged MISSING, with a note saying which side.
   - Write a Verification sheet with colour-coded statuses (green, amber, red) and a summary block at the top.

2. Replace the verify stub in cli.py. It prints the summary and writes output/FunnelLens_Verify_<from>_to_<to>.xlsx.

3. Add a "Verify" page to app.py: upload the Sheet export, pick dates, run, then view and download the results.

4. Tests with a small fake Sheet export that includes planted mismatches of each type.

5. Run verify on one real recent month, if I provide the export. List every ERROR and what probably caused it. Do not change report logic to force a match without asking me first.

Rules: Follow README Section 6. Update Project Status and Open issues in README.md.
```

---

## Phase 9 — Stage Snapshots, Deployment and Handover

**Goal:** Fix the stage history caveat for the future, deploy for the team, and document everything.

**Deliverables:** `funnellens/snapshot.py`, `docs/SETUP_GUIDE.md`, deployment config, and a final README update.

**Acceptance criteria:**
- [ ] `python cli.py snapshot` saves today's stages; scheduling instructions are provided.
- [ ] Stage-based reports use a snapshot when one exists, and label it correctly.
- [ ] The app runs in the chosen hosting option, with secrets set up securely.
- [ ] A teammate can set up and use FunnelLens by following `SETUP_GUIDE.md`.

**Prompt:**

```
You are building FunnelLens. Before doing anything, read README.md completely, especially Sections 7.1, 11.4 and 12, then Phase 9 in PHASES.md. Confirm in Project Status that Phases 0–8 are done.

Your task for Phase 9: Stage Snapshots, Deployment and Handover.

1. funnellens/snapshot.py
   - take_snapshot(date=today IST) saves every open lead's current stage (lead_id, owner, stage, source, course, captured_at) to data/snapshots/stages_<date>.parquet.
   - load_snapshot(date) returns the snapshot, or None if there isn't one.
   - Connect this to the Phase 4 hook: for each date in a stage-based report, use that date's snapshot when available, and label it "Stage as of <that date>". Otherwise fall back to current stages and label them "Stage as of <run date>". The Run Info sheet lists which dates used snapshots.
   - Replace the snapshot stub in cli.py.
   - Write scheduling instructions for Windows Task Scheduler and for cron, to run daily at 23:55 IST.

2. Deployment:
   - Add .streamlit/config.toml and a secrets.toml.example (never the real secrets).
   - Write deployment steps for:
     (a) running locally on the office network
     (b) Streamlit Community Cloud, with secrets and viewer email restrictions
     (c) a company server or VM, running as a service
   - Point out that on Streamlit Cloud, local files (cache, snapshots) are not permanent, and suggest options for storing them.

3. docs/SETUP_GUIDE.md: a step-by-step guide for a non-technical teammate, covering:
   - installing Python
   - getting the code
   - setting up .env
   - running the app
   - generating a report
   - running verification
   - common errors and their fixes

4. Final README.md update:
   - make sure every section matches what was actually built
   - mark all phases done in Project Status
   - complete the decision log
   - list remaining open issues and future ideas (for example rebuilding stage history from activity data, scheduled email reports)

5. Final check: run the full test suite, run generate and verify for one real day, and report the results.

Rules: Follow README Sections 6 and 12. Never commit secrets. Summarise what I need to do to go live.
```

---

## Quick Reference

| Phase | Builds | Depends on |
|---|---|---|
| 0 | Skeleton + LOGIC_SPEC.md | Apps Script file |
| 1 | API client | 0 |
| 2 | Data extraction + cache | 1 |
| 3 | Filtering engine | 2 |
| 4 | Reports + consistency checks | 2, 3 |
| 5 | Excel export | 4 |
| 6 | CLI + shared pipeline | 5 |
| 7 | Streamlit app | 6 |
| 8 | Verification vs Google Sheet | 7 |
| 9 | Snapshots, deployment, docs | 8 |
