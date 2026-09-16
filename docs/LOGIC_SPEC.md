# FunnelLens — Logic Specification

> Extracted from `reference/apps_script.gs` (the production Google Apps Script) during Phase 0. This is the authority for report logic (README §7). Every item below cites the Apps Script function(s) it came from. Nothing here is guessed — anything unclear or missing is listed under **Open Questions** at the end instead.

---

## 1. API Host and Endpoints

**Host:** `api-in21.leadsquared.com` (constant `CONFIG.API_HOST`, top of file, comment: "Confirmed from Settings > API in LeadSquared"). Every request builds its URL as `https://${CONFIG.API_HOST}/...`.

**Auth:** `accessKey` and `secretKey` query parameters on every request, read from `PropertiesService.getScriptProperties()` (`ACCESS_KEY`, `SECRET_KEY`). Confirmed throughout — every endpoint function below repeats this pattern.

### 1.1 `Users.Get` — get active counselors
- **Method / path:** `GET /v2/UserManagement.svc/Users.Get?accessKey=...&secretKey=...`
- **Cited in:** `getActiveCounselors()`
- **Request body:** none (GET, no payload)
- **Response shape:** JSON array of user objects, each with at least `ID`, `FirstName`, `LastName`, `StatusCode` (0 = active, 1 = inactive/deactivated per comment), `Role`.
- **Pagination:** none — single call returns the full user list.

### 1.2 `Task.svc/Retrieve` — pending tasks for one owner (live overdue snapshot)
- **Method / path:** `POST /v2/Task.svc/Retrieve?accessKey=...&secretKey=...`
- **Cited in:** `getOverdueTaskCounts(ownerId)`, `getOverdueTaskCountsBatch(ownerIds)`
- **Request body:**
  ```json
  {
    "Parameter": { "LookupName": "OwnerId", "LookupValue": "<ownerId>", "StatusCode": 0 },
    "Columns": { "Exclude_CSV": "Description" },
    "Sorting": { "ColumnName": "DueDate", "Direction": "0" },
    "Paging": { "Offset": 0, "RowCount": 500 }
  }
  ```
  `StatusCode: 0` = incomplete/pending (comment on line 586).
- **Response shape:** `{ "List": [ { "DueDate": "...", ... } ] }`
- **Pagination:** **NONE beyond the first page.** `Offset` is always `0`, `RowCount` is always `500`. There is no loop that increases `Offset` if a counselor has more than 500 pending tasks. See Open Questions — this is the exact shape of bug README Critical Rule #9 warns about ("the old Overdues_Total bug capped silently at 500").

### 1.3 `LeadManagement.svc/RetrieveTaskByLeadId` — tasks for one lead
- **Method / path:** `GET /v2/LeadManagement.svc/RetrieveTaskByLeadId?accessKey=...&secretKey=...&leadId=<id>`
- **Cited in:** `getTasksForLead(leadId)`, `getTasksForLeadsBatch(leadIds)`
- **Request body:** none (GET)
- **Response shape:** `{ "RecordCount": N, "TaskList": [ { "DueDate": "...", "Status": "Pending"/"Completed", ... } ] }` (comment on line 657-658 states this is "Confirmed response shape from LeadSquared docs")
- **Pagination:** none documented; called once per lead (or batched in parallel, one request per lead, via `batchUrlFetch`).

### 1.4 `LeadManagement.svc/Leads.Get` — lead search/retrieval
- **Method / path:** `POST /v2/LeadManagement.svc/Leads.Get?accessKey=...&secretKey=...`
- **Cited in:** `lsqSearch(...)` (used by `lsqSearchAllPages`, which is used for created/modified-date lead pulls), `getLeadSourcesBatch(leadIds)`
- **Request body:**
  ```json
  {
    "Parameter": { "LookupName": "<CreatedOn|ModifiedOn|ProspectID>", "LookupValue": "<value>", "SqlOperator": "<>=|=>" },
    "Columns": { "Include_CSV": "<comma list>" },
    "Sorting": { "ColumnName": "CreatedOn", "Direction": "1" },
    "Paging": { "PageIndex": 1, "PageSize": 1000 }
  }
  ```
- **Response shape:** ambiguous — `getLeadSourcesBatch` handles it as `Array.isArray(data) ? data : (data.List || [])`, implying the response is sometimes a bare JSON array of lead objects and sometimes `{ List: [...] }`. `lsqSearch` itself just returns `JSON.parse(res.getContentText())` directly and callers treat it as an array (`page.length`, `.concat`).
- **Pagination:** `lsqSearchAllPages(lookupName, lookupValue, sqlOperator, includeCsv, maxPages)` loops `PageIndex` from 1 upward, `PageSize` fixed at 1000, stopping when a page returns fewer than 1000 rows. Default safety cap `maxPages = 100` (i.e. 100,000 records). **On hitting the cap it only logs a warning (`Logger.log('WARNING: ... hit the ${maxPages}-page safety cap ...')`) and returns what it has — it does NOT throw.** This conflicts with README Critical Rule #9 ("no silent caps... raise an error"). See Open Questions.
  - Only a lower bound (`>=`) is used for date queries in production (`CreatedOn`/`ModifiedOn` with `>=` and a UTC lower-bound string); the upper bound is applied **client-side** after fetching, via `.filter(l => parseUtcTimestamp(l.CreatedOn) < nextDayStart)` (see §1.4.1). The API call itself has no upper-bound parameter — `SqlOperator` only supports one condition per call (comment on line 1149-1151).

### 1.5 `OpportunityManagement.svc/Retrieve/BySearchParameter` — Opportunity Advanced Search (the "Enrolled by Enrolled Date" endpoint)
- **Method / path:** `POST /v2/OpportunityManagement.svc/Retrieve/BySearchParameter?accessKey=...&secretKey=...`
- **Cited in:** `searchOpportunitiesByEnrolledDate(dayStart, dayEnd)`
- **Note:** comment describes this as an "Admin-only endpoint" — the calling API key must have admin rights.
- **Request body:**
  ```json
  {
    "OpportunityEventCode": 12000,
    "AdvancedSearch": "<JSON-stringified search object, see below>",
    "Columns": { "Include_CSV": "Owner,Status,mx_Custom_2,P_Source" },
    "Paging": { "PageIndex": 1, "PageSize": 200 },
    "Sorting": { "ColumnName": "CreatedOn", "Direction": 1 }
  }
  ```
  The `AdvancedSearch` value is itself a JSON string (not a nested object) with this shape:
  ```json
  {
    "GrpConOp": "And",
    "QueryTimeZone": "India Standard Time",
    "Conditions": [
      {
        "Type": "Activity", "ConOp": "and",
        "RowCondition": [{ "SubConOp": "And", "LSO": "ActivityEvent", "LSO_Type": "PAEvent", "Operator": "eq", "RSO": "12000" }]
      },
      {
        "Type": "Activity", "ConOp": "and",
        "RowCondition": [{ "SubConOp": "and", "LSO": "mx_Custom_45", "LSO_Type": "DateTime", "Operator": "between", "RSO": "<yyyy-MM-dd hh:mm:ss a> TO <yyyy-MM-dd hh:mm:ss a>" }]
      }
    ]
  }
  ```
  The date range string format is `yyyy-MM-dd hh:mm:ss a TO yyyy-MM-dd hh:mm:ss a` (12-hour clock with AM/PM), in the script's local timezone (`Session.getScriptTimeZone()`), **not UTC** — this is different from the lead-search endpoints, which take UTC. Comment: "Structure confirmed working from the account's own captured browser payload."
- **Response shape:** `{ "List": [ { "Owner": "<GUID>", "Status": "...", "mx_Custom_2": "...", "P_Source": null (confirmed unreliable — see §2), "RelatedProspectId": "<leadId>", ... } ] }`
- **Pagination:** `PageIndex` loop, `PageSize` fixed at 200, stops when a page returns fewer than 200 rows, hard safety cap `pageIndex <= 20` (i.e. 4,000 records). **Silently stops at the cap** (only a `Logger.log` on non-200 HTTP responses, no explicit cap-hit warning and no thrown error). Same README Rule #9 conflict as §1.4.

### 1.6 `OpportunityManagement.svc/GetOpportunitiesOfLead` — stage/status/enrolled-date for one lead
- **Method / path:** `POST /v2/OpportunityManagement.svc/GetOpportunitiesOfLead?accessKey=...&secretKey=...&leadId=<id>`
- **Cited in:** `getOpportunityStage(leadId)`, `getOpportunityStagesBatch(leadIds)`
- **Request body:**
  ```json
  {
    "Columns": { "Include_CSV": "mx_Custom_2,Status,mx_Custom_45" },
    "Paging": { "PageIndex": 1, "PageSize": 5 },
    "Sorting": { "ColumnName": "ModifiedOn", "Direction": "1" }
  }
  ```
  Comment on `Direction: '1'` says "1 = descending = most recent first" — the code always takes `list[0]` as "the" opportunity for a lead, i.e. **the most recently modified opportunity**, not necessarily the only one.
- **Response shape:** `data.List || data` — comment: "response shape varies slightly by account config", i.e. the script defensively handles both `{List:[...]}` and a bare array.
- **Pagination:** none (fixed `PageSize: 5`, only `list[0]` is used).

### 1.7 Endpoint-to-field cross reference
| Endpoint | Used for |
|---|---|
| `Users.Get` | active counselor roster (owner ID → name mapping, exclusion filtering) |
| `Task.svc/Retrieve` | live "as of now" overdue task snapshot per counselor (Final Count, Master Data) |
| `LeadManagement.svc/RetrieveTaskByLeadId` | tasks for leads created on a specific day (Lead Funnel Task/Overdues/No Task) |
| `LeadManagement.svc/Leads.Get` | lead search by CreatedOn/ModifiedOn (all created/modified-date report rows); lead lookup by ProspectID (Source Wise Enrolment's per-lead Source lookup) |
| `OpportunityManagement.svc/Retrieve/BySearchParameter` | Opportunity Advanced Search by Enrolled Date — true daily/monthly enrollment counts (Reports "Enrolled Today/This Month", Final Count "Enrolled", Source Wise Enrolment) |
| `OpportunityManagement.svc/GetOpportunitiesOfLead` | per-lead Stage + Status + Enrolled Date (Stage Wise, Master Data, Reports' Lost/NR, enrollment reconciliation) |

---

## 2. Field Names

| Field (schema name) | Where it lives | Meaning | Cited in |
|---|---|---|---|
| `ProspectID` | Lead | Lead's unique ID | throughout, e.g. `lsqSearch`, `getTasksForLead` |
| `FirstName` | Lead | Lead's first name | diagnostics only (`testFieldNames`, `countLeadsForDate`) |
| `OwnerId` | Lead | Owner's GUID — cannot be searched by counselor name directly | comment on `CONFIG.OWNER_FIELD` (lines 24-29) |
| `OwnerIdName` (`CONFIG.OWNER_FIELD`) | Lead | Owner's display name (e.g. "Anuj Thakur"), included in lead API responses even though not in official field metadata; used for all counselor grouping/filtering | `CONFIG.OWNER_FIELD`, `runSyncForDate` |
| `Source` (`CONFIG.LEAD_SOURCE_FIELD`) | Lead | Lead source | `CONFIG.LEAD_SOURCE_FIELD`, Source Wise pivot, Source Wise Enrolment |
| `mx_Enquired_Course` (`CONFIG.PROGRAM_FIELD`) | Lead | Course/program of interest ("Program", mapped to "Enquired Course" per owner confirmation) | `CONFIG.PROGRAM_FIELD`, Course Wise pivot |
| `CreatedOn` | Lead | Creation timestamp, UTC, `yyyy-MM-dd HH:mm:ss` | throughout |
| `ModifiedOn` | Lead | Last-modified timestamp, UTC | throughout |
| `LeadConversionDate` | Lead | Alternate "created" timestamp — "Prospect Creation Date", when an anonymous visitor became a qualified Lead — diagnostic only, not used in production sync | `diagnoseCreatedOnField`, `countLeadsForDate` comment block (lines 1176-1182) |
| `mx_Custom_2` (`CONFIG.OPPORTUNITY_STAGE_FIELD`) | **Opportunity**, not Lead | Pipeline Stage (Cold/Warm/Hot/Enrolled/etc.) — confirmed via a webhook sample showing this field change on stage update | `CONFIG.OPPORTUNITY_STAGE_FIELD` comment (lines 31-34) |
| `Status` (`CONFIG.OPPORTUNITY_STATUS_FIELD`) | Opportunity | Opportunity-level Status: Open / Lost / Won | `CONFIG.OPPORTUNITY_STATUS_FIELD` comment (lines 36-38), used for "Lost" in Reports tab |
| `mx_Custom_45` (`CONFIG.ENROLLED_DATE_FIELD`) | Opportunity | Enrolled Date — the date a lead actually converted | `CONFIG.ENROLLED_DATE_FIELD` comment (lines 44-47) |
| `Owner` | Opportunity (search result) | Owner GUID on the opportunity record, mapped to counselor name via active roster | `searchOpportunitiesByEnrolledDate` result handling |
| `RelatedProspectId` | Opportunity (search result) | Links an opportunity back to its Lead — used because `P_Source` on the opportunity search reliably comes back `null` | `refreshSourceEnrollmentTab`, comment lines 712-717 |
| `P_Source` | Opportunity (search result, requested) | Intended to be the linked lead's Source, but **confirmed to always return `null`** despite being requested — so Source is instead looked up separately per lead via `getLeadSourcesBatch` | comment lines 712-717, `testOpportunityAdvancedSearch` diagnostic |
| `DueDate` | Task | UTC timestamp the task is due | `getOverdueTaskCounts`, `computeDayWiseTaskMetrics(FromMap)` |
| `Status` | Task | `'Pending'` / `'Completed'` | `computeDayWiseTaskMetrics(FromMap)` (checked directly); NOT re-checked in `getOverdueTaskCounts` because that call already filters server-side via `StatusCode: 0` |
| `OpportunityEventCode` | constant, `12000` | Required parameter for Opportunity Advanced Search; "confirmed from your captured browser payload" | `CONFIG.OPPORTUNITY_EVENT_CODE` comment (lines 40-42) |

---

## 3. Report Tabs

All day-based tabs use **newest-first** row ordering (`insertDayBlock`), with a bold Total row directly under each day's block, then a blank separator row before the next day's block (`addDaySeparatorsToTab`/`addDaySeparatorsToAllTabs` retroactively fix any missing separators).

### 3.1 Lead Funnel
- **Date field:** Created date (for Created/Task/Overdues/No Task columns) **and** Modified date (for the Modified columns) — both pulled for the same target day window in `runSyncForDate`. Task DueDate is used only to determine overdue status among that day's created leads' tasks.
- **Rows:** one row per active counselor per day.
- **Columns, in order** (`SHEET_HEADERS.leadFunnel`):
  1. `Date`
  2. `Counselor Name`
  3. `Created On_Day wise` = count of leads created that day, owned by this counselor
  4. `Created On (Monthly)` = **formula**, `SUMIFS($C:$C,$B:$B,B<row>,$A:$A,">="&monthStart,$A:$A,"<="&A<row>)` — running total from month start through this row's own date, same counselor (`fillLeadFunnelMonthlyFormulas`)
  5. `Modified On (Daily)` = count of leads modified that day, owned by this counselor
  6. `Modified On (Monthly)` = **formula**, same SUMIFS pattern over column E
  7. `Modified %_Monthly` = **formula**, `IF(D<row>=0,0,ROUND(F<row>/D<row>*100,1))` — Modified Monthly ÷ Created Monthly × 100, rounded to 1 decimal
  8. `Overdues` = count of overdue tasks among tasks belonging to leads created that day (`Status === 'Pending' && parseUtcTimestamp(DueDate) < now`)
  9. `Task` = total task count across leads created that day
  10. `Overdues %` = `IF(Task=0,0,ROUND(Overdues/Task*100,1))`, computed in JS at row-build time (not a sheet formula)
  11. `No Task` = count of leads created that day with zero tasks
  12. `No Task %` = `IF(Created=0,0,ROUND(NoTask/Created*100,1))`, computed in JS
- **Total row:** `['', 'Total', sum(Created), '', sum(Modified), '', '', sum(Overdues), sum(Task), '', sum(NoTask), '']` — only Created, Modified, Overdues, Task, No Task are summed; the Monthly and % columns are left blank on the Total row.
- **Monthly rollup:** per-row `SUMIFS` formulas (columns D, F, G), not a separate monthly block.
- **Cited in:** `SHEET_HEADERS.leadFunnel`, `runSyncForDate` (row building, lines 1563-1581), `fillLeadFunnelMonthlyFormulas`, `computeDayWiseTaskMetricsFromMap`.

### 3.2 Stage Wise (tab literally named `Stage Wise_Modified On_<Month>`)
- **Date field:** Lead **Created** date. Comment on line 1584: "Based on CREATED leads (not modified), so sum(stages) + Not Modified always equals Created On_Day wise for this counselor/day." ⚠️ The tab's own name says "Modified On" but the logic is Created-date-based — see Open Questions.
- **Rows:** one row per counselor per day.
- **Columns, in order** (`SHEET_HEADERS.stageWise`): `Date`, `Counselor Name`, then the 15 `CONFIG.STAGES` values in the exact order listed in §5, then `Not Modified`, `blank`, `Total`, `Disqualified %`, `Enrolled %`.
  - Each stage column = count of that counselor's day's created leads whose Opportunity stage (`oppLookup`, keyed by `ProspectID`) equals that stage name.
  - `Not Modified` = count of that counselor's day's created leads with **no** opportunity stage found at all (no Opportunity record / stage lookup returned null).
  - `blank` = an always-empty spacer column — confirmed by the row-build code (`stageWiseRows.push([target, counselor, ...stageCounts, notModified, '', total, disqualifiedPct, enrolledPct])`), no value is ever written to it.
  - `Total` = sum of the 15 stage counts + `Not Modified`.
  - `Disqualified %` = `IF(Total=0,0,ROUND(stageCounts[Disqualified]/Total*100,1))`
  - `Enrolled %` = `IF(Total=0,0,ROUND(stageCounts[Enrolled]/Total*100,1))`
- **Total row:** `['', 'Total', ...15 stage sums, notModifiedTotal, '', grandTotal, disqualifiedPct, enrolledPct]` (same % formulas applied against the grand totals).
- **Cited in:** `SHEET_HEADERS.stageWise`, `runSyncForDate` (lines 1583-1600), `CONFIG.STAGES`.

### 3.3 Source Wise (dynamic pivot tab, `Source Wise_<Month>`)
- **Date field:** Lead **Created** date (uses `createdByCounselorForPivot`, built from the same created-leads pull as Stage Wise).
- **Rows/Columns:** `Date`, `Counselor Name`, then one dynamically-added column per distinct `Source` value ever seen, appended left-to-right in first-seen order (columns are never reordered once created).
- **Cell value:** count of that counselor's day's created leads whose `Source` (case-insensitively) matches that column.
- **Case handling / canonicalization** (`writePivotDayBlock`, `canonicalize()`): a value is trimmed; empty/whitespace-only becomes `(Blank)`. Matching against an **already-established column header** wins first (keeps that header's existing casing); otherwise matching against another value **already seen earlier the same day** wins (first-seen casing for the day is used); otherwise a brand-new column is created with this value's own casing.
- **Total row:** `['', 'Total', ...perColumnSums]`.
- **Retroactive cleanup (not part of daily sync, menu-triggered):** `mergeDuplicatePivotColumns` / `mergeDuplicateColumnsAllTabs` finds columns whose headers are case-variants of each other (e.g. "ACCA" and "acca"), sums their values row-by-row into the first (canonical) column, and deletes the duplicate.
- **Cited in:** `ensurePivotTab`, `getPivotColumnHeaders`, `ensurePivotColumns`, `writePivotDayBlock(sheet, target, counselorLeadsMap, CONFIG.LEAD_SOURCE_FIELD)`, `mergeDuplicatePivotColumns`.

### 3.4 Course Wise (`Course Wise_<Month>`)
- Identical mechanism to Source Wise (§3.3), same `writePivotDayBlock` function, but `valueField = CONFIG.PROGRAM_FIELD` (`mx_Enquired_Course`) instead of `CONFIG.LEAD_SOURCE_FIELD`.
- **Cited in:** `runSyncForDate` line 1654: `writePivotDayBlock(tabs.courseWise, target, createdByCounselorForPivot, CONFIG.PROGRAM_FIELD)`.

### 3.5 Reports (`Reports_<Month>`)
- **Date field:** mixed.
  - `New Today` = same target-day **Created**-date pull as Lead Funnel/Stage Wise.
  - `Lost Today` / `NR Today` = same target-day **Modified**-date pull, filtered by Opportunity `Status`/`Stage`.
  - `Enrolled Today` / `Enrolled This Month` = Opportunity Advanced Search by **Enrolled Date** (`searchOpportunitiesByEnrolledDate`).
  - `Yesterday` and `This Month` columns are **formulas** referencing the tab's own historical rows by date (`fillReportsRollupFormulas`), order-independent of physical row position.
- **Rows:** one row per counselor per day.
- **Columns, in order** (`SHEET_HEADERS.reports`), with sheet-column letters as used in the formulas:
  - A `Date`
  - B `Counselor Name`
  - C `New Today` = `createdForCounselor.length`
  - D `Total Yesterday` = formula `SUMIFS($C:$C,$B:$B,B<row>,$A:$A,A<row>-1)`
  - E `Lost Yesterday` = formula `SUMIFS($G:$G,$B:$B,B<row>,$A:$A,A<row>-1)`
  - F `Lost Yesterday %` = formula `IF(D=0,0,ROUND(E/D*100,1))`
  - G `Lost Today` = count of that day's modified-leads for this counselor whose Opportunity `Status === 'Lost'`
  - H `Lost Today %` = `IF(ModifiedCount=0,0,ROUND(LostToday/ModifiedCount*100,1))`, computed in JS
  - I `NR Yesterday` = formula `SUMIFS($K:$K,$B:$B,B<row>,$A:$A,A<row>-1)`
  - J `NR Yesterday %` = formula `IF(D=0,0,ROUND(I/D*100,1))` — ⚠️ denominator is `D` (Total Yesterday), **not** a NR-specific "Total NR Yesterday" — coded exactly this way, see Open Questions.
  - K `NR Today` = count of that day's modified leads for this counselor whose Opportunity `Stage === 'Not Reachable'`
  - L `NR Today %` = `IF(ModifiedCount=0,0,ROUND(NrToday/ModifiedCount*100,1))`, computed in JS
  - M `Total This Month` = formula `SUMIFS($C:$C,$B:$B,B<row>,$A:$A,">="&monthStart,$A:$A,"<="&A<row>)`
  - N `Lost This Month` = formula, same window, over column G
  - O `Lost This Month %` = `IF(M=0,0,ROUND(N/M*100,1))`
  - P `NR This Month` = formula, same window, over column K
  - Q `NR This Month %` = `IF(M=0,0,ROUND(P/M*100,1))`
  - R `Enrolled Today` = `enrolledCountByOwnerId[counselorId]` from `searchOpportunitiesByEnrolledDate` for the target day, keyed by the Opportunity's `Owner` GUID resolved through the active counselor roster
  - S `Enrolled This Month` = formula `SUMIFS($R:$R,$B:$B,B<row>,$A:$A,">="&monthStart,$A:$A,"<="&A<row>)`
- **Total row:** `['', 'Total', sum(NewToday), '', '', '', sum(LostToday), '', '', '', sum(NrToday), '', '', '', '', '', '', sum(EnrolledToday), '']` — only C, G, K, R are summed; every formula column is left blank on the Total row.
- **Separate reconciliation pass (menu-triggered, not part of daily sync):** `reconcileEnrollments()` widens the search to leads **modified** in the last 45 days, re-derives each one's true Enrolled Date via `getOpportunityStage`, and directly overwrites column **R** ("Enrolled Today", `sheet.getRange(row, 18)` — confirmed R = column 18 by position) on the matching historical row, to catch leads that enrolled on day X but were touched again (and thus re-indexed) on a later day Y.
- **Cited in:** `SHEET_HEADERS.reports`, `runSyncForDate` (lines 1602-1627), `fillReportsRollupFormulas`, `reconcileEnrollments`.

### 3.6 Final Count (`Final Count_<Month>`)
- **Date field:** the whole tab is scoped to "this month" (the month tab itself is the date boundary); rebuilt in full for **every** counselor row on every single-day sync (`refreshFinalCount` is called once per `runSyncForDate` and always rewrites all rows).
- **Rows:** one row per active counselor.
- **Columns, in order** (`SHEET_HEADERS.finalCount`):
  1. `Till Date` — ⚠️ **never assigned a value** anywhere in `refreshFinalCount`; the code only clears column 1 (`finalSheet.getRange(3,1,counselors.length,1).setValues(counselors.map(() => ['']))`) and never writes to it again. Always blank. See Open Questions.
  2. `Counselor Name` = literal value
  3. `Created On` = formula `SUMIF('<LeadFunnel tab>'!B:B, B<row>, '<LeadFunnel tab>'!C:C)` — sums Lead Funnel's "Created On_Day wise" across the **whole month tab**
  4. `Modified On` = formula `SUMIF('<LeadFunnel tab>'!B:B, B<row>, '<LeadFunnel tab>'!E:E)`
  5. `Overdues_Monthly` = **plain value** (not a formula) = `overdue.thisMonth` from `getOverdueTaskCountsBatch` — a **live snapshot as of this sync run**, overdue tasks whose DueDate falls in the current calendar month
  6. `Overdues_Total` = **plain value** = `overdue.total` — live snapshot, **all** overdue pending tasks regardless of month. ⚠️ Sourced from `Task.svc/Retrieve` which is capped at 500 rows with no further pagination (§1.2) — a counselor with >500 pending tasks would silently undercount here. This is the exact shape of the historical "Overdues_Total capped at 500" bug README Rule #9 references.
  7. `No Task_Monthly` = formula `SUMIFS('<LeadFunnel>'!K:K, '<LeadFunnel>'!B:B, B<row>, '<LeadFunnel>'!A:A, ">="&monthStart)` — month-to-date sum of Lead Funnel's daily "No Task" column
  8. `No Task_Total` = formula `SUMIF('<LeadFunnel>'!B:B, B<row>, '<LeadFunnel>'!K:K)` — sum across the whole month tab (same "Total" scope as columns 3-4, i.e. "this month", not all-time)
  9. `Enrolled` = formula `SUMIF('<Reports>'!B:B, B<row>, '<Reports>'!R:R)` — sum of Reports' "Enrolled Today" (true Enrolled-Date-based count) across the month. Comment explicitly states this is **not** the Stage Wise creation-date-based snapshot.
  10. `Conversion %` = formula `IF(C<row>=0,0,ROUND(I<row>/C<row>*100,1))` — `Enrolled (col I) ÷ Created On (col C) × 100`, rounded to 1 decimal
  11. `Referral (This Month)` = formula `SUMIF('<SourceWise>'!B:B, B<row>, '<SourceWise>'!<col>:<col>)` where `<col>` is whichever Source Wise column currently has header exactly `"Referrals"` (case-insensitive lookup via `findPivotColumnByHeader`); if no such column exists yet this month, the cell is set to the plain value `0` instead.
  12. `Direct Walk In (This Month)` = same pattern, header `"Direct Walk In"`.
- **No Total row** is built for Final Count anywhere in `refreshFinalCount`.
- **Cited in:** `SHEET_HEADERS.finalCount`, `refreshFinalCount`, `findPivotColumnByHeader`, `getColumnLetter`.

### 3.7 Source Wise Enrolment (`Source Wise Enrolment_<Month>`)
- **Date field:** Enrolled Date, for the **whole month** (`searchOpportunitiesByEnrolledDate(monthStart, monthEnd)`, not just the target day) — this tab is fully rebuilt on every sync, not incrementally updated. Created counts (for the % denominator) come from Source Wise, which is Created-date-based.
- **Rows:** one row per active counselor.
- **Columns:** `Date`, `Counselor Name`, then for **every source currently present in this month's Source Wise tab** (in Source Wise's own column order): `"{Source} Enrolled"`, `"{Source} Conversion %"`. The header row and all data rows are cleared and rewritten fresh every sync, because the source list can grow month to month.
  - `{Source} Enrolled` = count of enrolled opportunities this month for this counselor whose linked lead's Source (looked up via `RelatedProspectId` → `getLeadSourcesBatch`, since the search's own `P_Source` is unreliable — see §2) equals that source, trimmed, blank → `(Blank)`. Opportunities whose `Owner` GUID doesn't resolve to a **currently tracked** counselor are silently dropped (`if (!counselor) return;`).
  - `{Source} Conversion %` = formula `IF(createdFormula=0,0,ROUND(EnrolledCell/(createdFormula)*100,1))` where `createdFormula = SUMIF('<SourceWise>'!B:B, B<row>, '<SourceWise>'!<sourceCol>:<sourceCol>)` — this month's Created count for that exact source, from Source Wise.
- **No Total row.**
- **Cited in:** `refreshSourceEnrollmentTab`, `getLeadSourcesBatch`, `searchOpportunitiesByEnrolledDate`.

### 3.8 Master Data (single continuous tab across all months, `MASTER_TAB_NAME = 'Master Data'`)
- **Date field:** Lead **Created** date (same target-day pull as Stage Wise / Lead Funnel's created side).
- **Rows:** one row per counselor per day, inserted/replaced via `insertDayBlock` with **no Total row** (`insertDayBlock(masterTab, masterRows, null, target)`).
- **Columns** (`MASTER_HEADERS`): `Date`, `Counselor`, `Created`, `Modified`, `Modified %`, `Overdues`, `Overdues %`, then the 15 `CONFIG.STAGES` columns, `Stage Total`, `Lost Today`, `Lost Today %`, `NR Today`, `NR Today %`.
  - `Created` = `createdForCounselor.length`
  - `Modified` = `modifiedForCounselor.length`
  - `Modified %` = `IF(Created=0,0,ROUND(Modified/Created*100,1))` — a **daily** modified %, distinct from Lead Funnel's `Modified %_Monthly`
  - `Overdues` = `overdue.total` — the **same live snapshot** used for Final Count's `Overdues_Total`, not a daily count
  - `Overdues %` = `IF(overdue.totalPending=0,0,ROUND(overdue.total/overdue.totalPending*100,1))` — denominator is total pending tasks fetched (up to 500, see §1.2), different from both Lead Funnel's Overdues % (denominator = that day's new-lead task count) and Final Count (which has no % column at all)
  - Stage columns = same `stageCounts` values/order as Stage Wise (§3.2), Created-date-based
  - `Stage Total` = same as Stage Wise's `Total`
  - `Lost Today`, `Lost Today %`, `NR Today`, `NR Today %` = identical values to Reports' G/H/K/L columns for this counselor/day
- **No `Not Modified` or `blank` column** here (unlike Stage Wise), and no Disqualified/Enrolled % — only `Stage Total`.
- **Cited in:** `MASTER_HEADERS`, `ensureMasterTab`, `migrateMasterTabIfNeeded`, `runSyncForDate` (lines 1629-1637).

---

## 4. Excluded Owners

Defined as two separate constants and applied entirely inside `getActiveCounselors()`:
- `CONFIG.COUNSELOR_EXCLUDE_ROLES = ['Administrator', 'Marketing_User']`
- `CONFIG.COUNSELOR_EXCLUDE_NAMES = ['Prabhjeet Nanda', 'Tarun Sharma', 'BDM edZeb']`

**Application order** (`getActiveCounselors`, lines 532-554):
1. Fetch all users via `Users.Get`.
2. Keep only `StatusCode === 0` (active).
3. Drop any user whose `Role` is in `COUNSELOR_EXCLUDE_ROLES`.
4. Build display name as `` `${FirstName}${LastName ? ' ' + LastName : ''}`.trim() `` — this must match the format `OwnerIdName` returns on leads.
5. Drop any user whose resulting name is in `COUNSELOR_EXCLUDE_NAMES`.

The resulting roster (`getActiveCounselors()`'s return value) is the **single source of truth** for every counselor-row report, every Task/Overdue lookup, and Enrolled-by-owner-GUID mapping. It is re-fetched fresh on **every sync run**, using TODAY's active/role state — so a counselor who leaves (or changes role) makes **their past leads retroactively invisible across the whole sheet**, confirmed explicitly by the diagnostic `diagnoseUntrackedOwners()`'s own comment (lines 825-830): "catches ... anyone who left the company mid-month (their earlier leads would be invisible to the whole sheet, since we always use TODAY's roster, not a point-in-time one)."

**Cited in:** `getActiveCounselors`, `logActiveCounselors`, `diagnoseUntrackedOwners`, `diagnoseCourseGap`.

---

## 5. Stage List and Order

```
CONFIG.STAGES = [
  'Budget Issue', 'Cold', 'Connected', 'Disqualified', 'Enrolled',
  'Future Prospect', 'Hot', 'Interested', 'Language Barrier',
  'Lost to Competitor', 'New', 'Not Reachable',
  'Offline in another city', 'Reachable', 'Warm'
]
```
15 stages, hardcoded as hand-typed strings at the top of the script (`CONFIG.STAGES`), **not derived from the API at runtime**. This exact array order is the column order for Stage Wise and Master Data. It is not pipeline order (Cold→Warm→Hot→Enrolled) — it's closer to alphabetical, with some non-alphabetical placement (e.g. `New` and `Reachable` appear late in the list, not at the top). "Lost" is **not** a value in this list — it is not a Stage at all; it is tracked separately via the Opportunity `Status` field (`CONFIG.OPPORTUNITY_STATUS_FIELD`, §2). **Cited in:** `CONFIG.STAGES` declaration (lines 56-59).

---

## 6. Overdue Definition

Two **different** overdue calculations exist, for two different purposes — they must not be conflated:

### 6.1 "Live snapshot" overdue (Final Count `Overdues_Monthly`/`Overdues_Total`, Master Data `Overdues`/`Overdues %`)
- **Source:** `getOverdueTaskCounts(ownerId)` / `getOverdueTaskCountsBatch(ownerIds)`, via `Task.svc/Retrieve` (§1.2).
- **Query-side filter:** `StatusCode: 0` (server confirms "incomplete/pending").
- **Client-side filter:** `parseUtcTimestamp(t.DueDate) < now`, where `now = new Date()` at the moment the sync executes.
- **Timezone handling:** `DueDate` is a naive UTC string from the API (no timezone marker, e.g. `"2026-08-03 05:30:00.000"`); `parseUtcTimestamp()` forces correct UTC parsing by appending `'Z'` before constructing the `Date` (comment lines 1027-1036 explains plain `new Date(str)` would otherwise be misread as local time by most JS engines). `now` itself is evaluated in whatever timezone the script's JS runtime uses internally (a `Date` instant is timezone-agnostic; the comparison `parseUtcTimestamp(...) < now` is a plain instant comparison, correct regardless of timezone).
- **"This month" boundary:** `monthStart = new Date(now.getFullYear(), now.getMonth(), 1)` — constructed using the Apps Script **project's configured timezone** (`Session.getScriptTimeZone()`, used elsewhere for date formatting, though this particular line uses the JS `Date` constructor directly with local-timezone semantics of the Apps Script runtime).
- **`totalPending`** = every pending task fetched (up to the 500-row cap, §1.2) — used as the denominator for Master Data's `Overdues %`.

### 6.2 "Day-wise" overdue (Lead Funnel `Overdues`/`Overdues %`)
- **Source:** `computeDayWiseTaskMetrics(leadsCreatedToday)` (sequential) / `computeDayWiseTaskMetricsFromMap(leadsCreatedToday, tasksByLeadId)` (batched) — tasks come from `RetrieveTaskByLeadId` (§1.3), scoped to **only the leads created that specific day** (not the counselor's whole pipeline).
- **Filter:** `t.Status === 'Pending' && parseUtcTimestamp(t.DueDate) < now` — same UTC-parse-then-compare-to-now logic as §6.1, but here `Status` (the string field) is checked directly on the task object, because `RetrieveTaskByLeadId` is not pre-filtered server-side by status (unlike `Task.svc/Retrieve`, which used `StatusCode: 0` in the request itself).

### 6.3 Shared caveat
Both definitions use `now` = **the moment the sync executes**, not the target day's own end-of-day boundary. Re-running a sync later in the day (or resyncing a past day via `resyncOneDay`/backfill) re-evaluates overdue status against the **current** moment, not the moment that historical day represents. This means Lead Funnel's `Overdues`/`Overdues %` for a resynced past day reflect overdue status **as of the resync time**, not as of that historical day. See Open Questions.

**Cited in:** `getOverdueTaskCounts`, `getOverdueTaskCountsBatch`, `computeDayWiseTaskMetrics`, `computeDayWiseTaskMetricsFromMap`, `parseUtcTimestamp`.

---

## 7. Day Window / Timezone Mechanics (supporting detail for §3 and §6)

From `runSyncForDate` (lines 1470-1481): a day's window is `target + 1 minute` (`queryStart`, i.e. `12:01:00 AM`) through `target + 24 hours` (`nextDayStart`, i.e. the next calendar day's true midnight — comment: "the window does not spill into the next calendar day"). The lower bound sent to the API is `Utilities.formatDate(queryStart, 'Etc/UTC', 'yyyy-MM-dd HH:mm:ss')` — i.e. converted to its correct UTC wall-clock string, explicitly to avoid the bug described in the comment: "Sending local-time digits labeled as UTC — the old bug — shifts every query by your UTC offset (e.g. 5:30 for IST), causing under/overcounts." The upper bound (`nextDayStart`) is applied **client-side** as a filter after fetching (`.filter(l => parseUtcTimestamp(l.CreatedOn) < nextDayStart)`), since the search API itself only accepts one bound per call (§1.4).

Opportunity Advanced Search (§1.5) instead sends **both** bounds in one call, formatted in **local time** (`yyyy-MM-dd hh:mm:ss a`, 12-hour clock) with an explicit `QueryTimeZone: 'India Standard Time'` parameter in the request body — a different mechanism from the lead-search endpoints.

**Cited in:** `runSyncForDate` (lines 1470-1481), `searchOpportunitiesByEnrolledDate` (lines 774-794).

---

## Resolved Decisions

The following were raised as Open Questions after the initial Phase 0 pass and have since been answered by the project owner (2026-09-16). Each decision is reflected in `config.yaml`, `.env.example`, and/or this spec where applicable.

1. **`LSQ_API_HOST` format:** decided bare host (e.g. `api-in21.leadsquared.com`) during Phase 0, but the project's real `.env` (created independently by the owner) already holds the full `https://` URL. Rather than force an edit to a working secret file, `LSQClient.__init__` (Phase 1, `funnellens/lsq_client.py`) accepts either form: it prepends `https://` only if the value doesn't already start with `http://`/`https://`. `.env.example` documents both are accepted.

2. **`Task.svc/Retrieve`'s 500-row cap (no further pagination):** known and accepted for now — no counselor currently has anywhere near 500 pending tasks. FunnelLens replicates the Apps Script's single 500-row fetch as-is for Phase 1. (Revisit if task volume grows.)

3. **`lsqSearchAllPages` (100,000-record cap) / `searchOpportunitiesByEnrolledDate` (4,000-record cap):** both caps confirmed correct. FunnelLens keeps both values but — per README Critical Rule #9 — **raises an error** when a cap is hit, instead of the Apps Script's silent truncation-with-log-warning.

4. **Final Count's `Till Date` column:** left blank, matching the Apps Script exactly (no FunnelLens-side value is invented for it).

5. **Final Count's Overdues columns:** FunnelLens replicates the live-as-of-generation-time snapshot behavior (not an as-of-date historical figure), to stay comparable with the Sheet.

6. **`"Referrals"` / `"Direct Walk In"` Source value spelling:** confirmed correct as literally coded — kept as-is in `config.yaml`/logic.

7. **Stage Wise tab naming ("...Modified On..." despite Created-date logic):** confirmed as legacy naming from the Apps Script; FunnelLens's Created-date logic is correct and its own report name does not need to carry the misleading suffix.

8. **Stage column order:** FunnelLens matches the Apps Script's `CONFIG.STAGES` order exactly (§5), not pipeline order, so output is directly comparable to the Sheet.

9. **"Lost" as Opportunity Status, not a Stage value:** confirmed correct. `config.yaml`'s `opportunity_status` field and corrected `stages` list (§5) stand as written.

10. **Apps Script project timezone:** confirmed `Asia/Kolkata` (IST) — matches README's assumption throughout; `config.yaml`'s `timezone: Asia/Kolkata` is correct as written.

11. **LeadSquared `Direction` (0/1) sort convention:** FunnelLens trusts the Apps Script's own comments/usage as-is rather than re-deriving the convention independently.

12. **`GetOpportunitiesOfLead` response shape:** FunnelLens's client handles both possible shapes (`{List:[...]}` or a bare array) defensively, same as the Apps Script — no assumption of one specific shape.

13. **`OpportunityEventCode: 12000`:** treated as stable and kept as a hardcoded constant, same as the Apps Script.

14. **Total rows for Final Count / Source Wise Enrolment:** FunnelLens matches the Apps Script exactly — **no** Total row added to either report.

15. **Reports column J ("NR Yesterday %") denominator:** FunnelLens replicates the Apps Script's formula exactly (divides by "Total Yesterday", not an NR-specific total), to stay directly comparable with the Sheet for verification purposes.
