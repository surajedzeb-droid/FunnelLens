/*******************************************************************
 * LEADSQUARED -> GOOGLE SHEETS DAILY FUNNEL SYNC
 * -----------------------------------------------------------------
 * Replicates: Lead Funnel_Aug 26 / Stage Wise_Modified On / Reports / Final Count
 * Auto-creates a fresh set of 4 tabs every new month (e.g. "..._Sep 26").
 *
 * SETUP STEPS:
 * 1. Extensions > Apps Script in your Google Sheet, paste this file in.
 * 2. Go to Project Settings > Script Properties, add:
 *      ACCESS_KEY   = <your LeadSquared access key>
 *      SECRET_KEY   = <your LeadSquared secret key>
 * 3. Field names are pre-filled from your account. Run `testFieldNames`
 *    first to sanity-check, then check View > Logs.
 * 4. Run `setupDailyTrigger` ONCE manually (it will ask for permissions).
 * 5. Done — dailySync() will now run automatically every morning, and
 *    the counselor list refreshes itself from LeadSquared each run.
 *******************************************************************/

// ============================ CONFIG ============================
const CONFIG = {
  // Confirmed from Settings > API in LeadSquared:
  API_HOST: 'api-in21.leadsquared.com',

  // CONFIRMED from LeadFields.csv export:
  // "Owner" field's schema name is OwnerId, but it stores a GUID, not a
  // name — so we can't search leads by "Anuj" directly. Instead we filter
  // client-side using OwnerIdName, which LeadSquared includes in lead
  // responses even though it isn't in the field metadata list.
  OWNER_FIELD: 'OwnerIdName',

  // Stage field (drives Stage Wise tab) — CORRECTED: this field lives on the
  // OPPORTUNITY record, not the Lead record. Confirmed via your webhook sample
  // (OpportunityStage_Post_Update event showed mx_Custom_2 going New -> Reachable).
  OPPORTUNITY_STAGE_FIELD: 'mx_Custom_2',

  // Opportunity-level Status (Open / Lost / Won) — useful for the Reports tab's
  // Lost tracking. Also confirmed from your sample data.
  OPPORTUNITY_STATUS_FIELD: 'Status',

  // OpportunityEventCode — confirmed from your captured browser payload
  // ("Code":"12000"). Required by the Opportunity Advanced Search API.
  OPPORTUNITY_EVENT_CODE: 12000,

  // Opportunity-level Enrolled Date — confirmed schema name. This lets us
  // count TRUE daily enrollments (a lead created months ago that enrolls
  // today still counts today), instead of inferring it from stage snapshots.
  ENROLLED_DATE_FIELD: 'mx_Custom_45',

  // Lead Source — confirmed schema name:
  LEAD_SOURCE_FIELD: 'Source',

  // Program — mapped to "Enquired Course" per your confirmation:
  PROGRAM_FIELD: 'mx_Enquired_Course',

  // The exact stage values that appear as columns in "Stage Wise_Modified On"
  STAGES: ['Budget Issue','Cold','Connected','Disqualified','Enrolled',
           'Future Prospect','Hot','Interested','Language Barrier',
           'Lost to Competitor','New','Not Reachable',
           'Offline in another city','Reachable','Warm'],

  // CONFIRMED via logActiveCounselors: these roles should NOT be counted
  // as counselors. Everyone else (Sales_User, Sales_Manager, etc.) is kept.
  COUNSELOR_EXCLUDE_ROLES: ['Administrator', 'Marketing_User'],

  // Specific individuals to exclude regardless of role (per explicit request):
  COUNSELOR_EXCLUDE_NAMES: ['Prabhjeet Nanda', 'Tarun Sharma', 'BDM edZeb'],
};

const SHEET_HEADERS = {
  leadFunnel: ['Date','Counselor Name','Created On_Day wise','Created On (Monthly)',
    'Modified On (Daily)','Modified On (Monthly)','Modified %_Monthly',
    'Overdues','Task','Overdues %','No Task','No Task %'],
  stageWise: ['Date','Counselor Name', ...CONFIG.STAGES, 'Not Modified', 'blank','Total',
    'Disqualified %','Enrolled %'],
  reports: ['Date','Counselor Name','New Today','Total Yesterday','Lost Yesterday',
    'Lost Yesterday %','Lost Today','Lost Today %','NR Yesterday',
    'NR Yesterday %','NR Today','NR Today %','Total This Month','Lost This Month',
    'Lost This Month %','NR This Month','NR This Month %','Enrolled Today','Enrolled This Month'],
  finalCount: ['Till Date','Counselor Name','Created On','Modified On',
    'Overdues_Monthly','Overdues_Total','No Task_Monthly','No Task_Total',
    'Enrolled','Conversion %','Referral (This Month)','Direct Walk In (This Month)'],
};

// Single, never-rotating tab that accumulates every day across all months —
// this is what Looker Studio (or any BI tool) should connect to, instead of
// the per-month tabs above (which stay purely for manual drill-down).
const MASTER_TAB_NAME = 'Master Data';
const MASTER_HEADERS = ['Date', 'Counselor', 'Created', 'Modified', 'Modified %',
  'Overdues', 'Overdues %', ...CONFIG.STAGES, 'Stage Total',
  'Lost Today', 'Lost Today %', 'NR Today', 'NR Today %'];


// ======================= MONTH TAB HELPERS =======================
function getMonthSuffix(date) {
  // e.g. "Sep 26"
  const mon = Utilities.formatDate(date, Session.getScriptTimeZone(), 'MMM');
  const yy = Utilities.formatDate(date, Session.getScriptTimeZone(), 'yy');
  return `${mon} ${yy}`;
}

function getMonthTabNames(date) {
  const suf = getMonthSuffix(date);
  return {
    leadFunnel: `Lead Funnel_${suf}`,
    stageWise: `Stage Wise_Modified On_${suf}`,
    reports: `Reports_${suf}`,
    finalCount: `Final Count_${suf}`,
    sourceWise: `Source Wise_${suf}`,
    courseWise: `Course Wise_${suf}`,
    sourceEnrollment: `Source Wise Enrolment_${suf}`,
  };
}

function ensureTab(ss, name, headers) {
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.getRange(2, 1, 1, headers.length).setValues([headers]); // row 2, matches your template's header row
    setTabTitle(sheet);
    applySheetFormatting(sheet, 2);
  } else {
    // Existing tab — if the header definition has grown since this tab
    // was first created (e.g. new columns added to Final Count later in
    // the month), extend the header row and re-apply formatting so the
    // new columns are labeled and styled, not just silently written with
    // data and no header.
    const currentHeaderCount = sheet.getLastColumn();
    if (headers.length > currentHeaderCount) {
      const newHeaders = headers.slice(currentHeaderCount);
      sheet.getRange(2, currentHeaderCount + 1, 1, newHeaders.length).setValues([newHeaders]);
      setTabTitle(sheet);
      applySheetFormatting(sheet, 2);
    }
  }
  return sheet;
}

function ensureMonthTabs(ss, date) {
  const names = getMonthTabNames(date);
  return {
    leadFunnel: ensureTab(ss, names.leadFunnel, SHEET_HEADERS.leadFunnel),
    stageWise: ensureTab(ss, names.stageWise, SHEET_HEADERS.stageWise),
    reports: ensureTab(ss, names.reports, SHEET_HEADERS.reports),
    finalCount: ensureTab(ss, names.finalCount, SHEET_HEADERS.finalCount),
    sourceWise: ensurePivotTab(ss, names.sourceWise),
    courseWise: ensurePivotTab(ss, names.courseWise),
    sourceEnrollment: ensurePivotTab(ss, names.sourceEnrollment),
  };
}

// ===================== TAB TITLES ============================
// A merged, styled title row (row 1) above the header row, so each tab is
// self-labeled — derives the text directly from the tab's own name, so it
// never needs separate tracking and always stays accurate.
function deriveTitleFromTabName(name) {
  if (name === MASTER_TAB_NAME) return 'MASTER DATA  —  All Months (Live Feed for Dashboard)';
  return name.replace(/_/g, '  —  ');
}

function setTabTitle(sheet) {
  const numCols = Math.max(sheet.getLastColumn(), 3);
  sheet.setFrozenColumns(0); // unfreeze first — can't merge across a freeze boundary
  try { sheet.getRange(1, 1, 1, numCols).breakApart(); } catch (e) { /* wasn't merged — safe to ignore */ }

  // Leave columns 1-2 (Date, Counselor Name) OUT of the merge, so freezing
  // them later doesn't cut through a merged cell. Title spans column 3+.
  sheet.getRange(1, 1, 1, 2).setBackground('#0b3d91');
  const titleRange = sheet.getRange(1, 3, 1, numCols - 2);
  try { titleRange.merge(); } catch (e) { /* couldn't merge — leave unmerged, formatting continues */ }
  titleRange.setValue(deriveTitleFromTabName(sheet.getName()))
    .setFontSize(13).setFontWeight('bold')
    .setHorizontalAlignment('center').setVerticalAlignment('middle')
    .setBackground('#0b3d91').setFontColor('#ffffff');
  sheet.setRowHeight(1, 28);
}

// ===================== SHEET FORMATTING ============================
// Applied once when a tab is first created (headerRow = the row holding
// column titles: 2 for most tabs, 1 for Master Data). Reads headers
// straight from the sheet, so it works identically for every tab without
// needing to know its specific columns — a column is auto-detected as a
// percentage column just by having "%" in its header text.
function applySheetFormatting(sheet, headerRow) {
  const numCols = Math.max(sheet.getLastColumn(), 2);
  const maxRows = sheet.getMaxRows();
  const headers = sheet.getRange(headerRow, 1, 1, numCols).getValues()[0];

  // Header row: bold, white-on-blue, centered
  sheet.getRange(headerRow, 1, 1, numCols)
    .setBackground('#1a73e8').setFontColor('#ffffff').setFontWeight('bold')
    .setHorizontalAlignment('center').setVerticalAlignment('middle');
  sheet.setFrozenRows(headerRow);
  sheet.setFrozenColumns(Math.min(2, numCols)); // Date + Counselor Name stay visible when scrolling right

  const dataRowCount = maxRows - headerRow;
  if (dataRowCount > 0) {
    // Date column formatting
    sheet.getRange(headerRow + 1, 1, dataRowCount, 1).setNumberFormat('dd-MM-yyyy'); // numeric month — locale-proof, won't render as text in another language

    // Alternating row shading for readability
    try {
      sheet.getRange(headerRow, 1, dataRowCount + 1, numCols)
        .applyRowBanding(SpreadsheetApp.BandingTheme.LIGHT_GREY, true, false);
    } catch (e) { /* banding may already exist on this range — safe to ignore */ }

    // Percentage columns: auto-detected by "%" in the header, formatted as
    // "12.3%", with a red/green gradient so problems are visible at a glance.
    // "Bad when high" columns (Lost, NR, Overdues, Disqualified, No Task) get
    // reversed coloring vs. "good when high" ones (Enrolled, Modified, Conversion).
    const badWhenHigh = /lost|nr |not reachable|overdue|disqualified|no task/i;
    const rules = [];
    headers.forEach((h, i) => {
      if (!h || !String(h).includes('%')) return;
      const colRange = sheet.getRange(headerRow + 1, i + 1, dataRowCount, 1);
      colRange.setNumberFormat('0.0"%"');
      const isBad = badWhenHigh.test(String(h));
      const lowColor = isBad ? '#57bb8a' : '#e67c73';
      const highColor = isBad ? '#e67c73' : '#57bb8a';
      rules.push(SpreadsheetApp.newConditionalFormatRule()
        .setGradientMinpointWithValue(lowColor, SpreadsheetApp.InterpolationType.MIN, '')
        .setGradientMidpointWithValue('#fce8b2', SpreadsheetApp.InterpolationType.PERCENT, '50')
        .setGradientMaxpointWithValue(highColor, SpreadsheetApp.InterpolationType.MAX, '')
        .setRanges([colRange])
        .build());
    });
    if (rules.length) sheet.setConditionalFormatRules(rules);
  }

  sheet.autoResizeColumns(1, numCols);
}

// Retroactively formats every existing tab in the spreadsheet — useful for
// tabs (like August's) created before this formatting code existed.
function formatAllTabsNow() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.getSheets().forEach(sheet => {
    if (sheet.getLastColumn() < 1) return; // skip empty sheets
    migrateMasterTabIfNeeded(sheet);
    setTabTitle(sheet);
    applySheetFormatting(sheet, 2); // every tab now uses row 2 for headers
  });
  SpreadsheetApp.getUi().alert('Formatting applied', 'All tabs have been formatted and titled.', SpreadsheetApp.getUi().ButtonSet.OK);
}

// ===================== DAY SEPARATOR CLEANUP (ROBUST ALTERNATIVE) ====
// The incremental approach (inserting a blank row at the end of each
// day's sync) only works cleanly if every day was written by the same
// code version in one continuous run — mixing old/new script versions or
// resumed/interrupted backfills can leave some day-boundaries without a
// separator. This scans the WHOLE sheet instead and fixes any gaps,
// regardless of how the data got there — safe to run repeatedly (won't
// double-insert where a separator already exists).
function addDaySeparatorsToTab(sheet) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 4) return; // need at least 2 data rows below the header to compare
  const dateValues = sheet.getRange(3, 1, lastRow - 2, 1).getValues().map(r => r[0]);

  // Walk bottom-to-top so inserting a row doesn't shift indices we haven't processed yet.
  for (let i = dateValues.length - 1; i > 0; i--) {
    const curr = dateValues[i];
    const prev = dateValues[i - 1];
    const currBlank = curr === '' || curr === null;
    const prevBlank = prev === '' || prev === null;
    if (currBlank || prevBlank) continue; // already separated (or this row IS the separator)

    const currTime = curr instanceof Date ? curr.getTime() : curr;
    const prevTime = prev instanceof Date ? prev.getTime() : prev;
    if (currTime !== prevTime) {
      const currRow = 3 + i;
      sheet.insertRowBefore(currRow);
    }
  }
}

function addDaySeparatorsToAllTabs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ss.getSheets().forEach(sheet => {
    const name = sheet.getName();
    const isDailyLogTab = name === MASTER_TAB_NAME
      || /^(Lead Funnel|Stage Wise|Reports|Source Wise|Course Wise)_/.test(name);
    if (isDailyLogTab) addDaySeparatorsToTab(sheet);
  });
}

// Menu-triggered version — has a UI context, so it can show a confirmation.
function addDaySeparatorsNow() {
  addDaySeparatorsToAllTabs();
  SpreadsheetApp.getUi().alert('Done', 'Day-separator rows have been checked and fixed across all tabs.', SpreadsheetApp.getUi().ButtonSet.OK);
}

// ===================== MERGE DUPLICATE CASE-VARIANT COLUMNS =========
// Retroactive fix for Source/Course Wise tabs that already have split
// columns like "ACCA" and "acca" from before writePivotDayBlock started
// canonicalizing case. Sums each duplicate's values into the first
// (canonical) occurrence, row by row — including Total rows — then
// deletes the redundant column. Safe to run repeatedly; a no-op once
// nothing's left to merge.
function mergeDuplicatePivotColumns(sheet) {
  const numCols = sheet.getLastColumn();
  if (numCols < 4) return 0; // need at least 2 dynamic columns (3,4) to have a duplicate
  const headers = sheet.getRange(2, 3, 1, numCols - 2).getValues()[0];
  const lastRow = sheet.getLastRow();
  const dataHeight = lastRow - 2; // rows 3..lastRow

  const seenCol = {}; // lowercase header -> canonical column number
  const toDelete = [];

  for (let i = 0; i < headers.length; i++) {
    const lower = String(headers[i]).toLowerCase();
    const colNum = 3 + i;
    if (seenCol[lower] === undefined) {
      seenCol[lower] = colNum;
      continue;
    }
    const canonicalCol = seenCol[lower];
    if (dataHeight > 0) {
      const dupValues = sheet.getRange(3, colNum, dataHeight, 1).getValues();
      const canonValues = sheet.getRange(3, canonicalCol, dataHeight, 1).getValues();
      const merged = canonValues.map((row, idx) => {
        const aRaw = row[0], bRaw = dupValues[idx][0];
        const aIsNum = typeof aRaw === 'number', bIsNum = typeof bRaw === 'number';
        if (!aIsNum && !bIsNum) return [aRaw]; // both blank (separator row) — leave untouched
        return [(aIsNum ? aRaw : 0) + (bIsNum ? bRaw : 0)];
      });
      sheet.getRange(3, canonicalCol, dataHeight, 1).setValues(merged);
    }
    toDelete.push(colNum);
  }

  toDelete.sort((a, b) => b - a).forEach(col => sheet.deleteColumn(col)); // rightmost first
  if (toDelete.length) { setTabTitle(sheet); applySheetFormatting(sheet, 2); }
  return toDelete.length;
}

function mergeDuplicateColumnsAllTabs() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let totalMerged = 0;
  ss.getSheets().forEach(sheet => {
    if (/^(Source Wise|Course Wise)_/.test(sheet.getName())) {
      totalMerged += mergeDuplicatePivotColumns(sheet);
    }
  });
  SpreadsheetApp.getUi().alert('Merge complete',
    `Merged ${totalMerged} duplicate case-variant column(s) across Source/Course Wise tabs.`,
    SpreadsheetApp.getUi().ButtonSet.OK);
}

// ===================== DYNAMIC PIVOT TABS (Source/Course) ==========
// Unlike Stage Wise (fixed known column list), Source and Course values
// aren't fully known in advance — these tabs grow their own columns
// automatically the first time a new value shows up, so nothing needs
// to be hardcoded or manually updated later.
function ensurePivotTab(ss, name) {
  let sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    sheet.getRange(2, 1, 1, 2).setValues([['Date', 'Counselor Name']]);
    // NOTE: title is intentionally NOT set here. setTabTitle() forces a
    // minimum 3-column merge width, which — with only Date/Counselor (2
    // real columns) present at creation — pollutes column C with
    // formatting, making Sheets think it's "in use" and pushing the first
    // real pivot column to D instead of C. ensurePivotColumns() sets the
    // title once real columns actually exist, avoiding the phantom column.
    sheet.setFrozenRows(2);
  }
  return sheet;
}

function getPivotColumnHeaders(sheet) {
  const lastCol = sheet.getLastColumn();
  if (lastCol < 3) return [];
  return sheet.getRange(2, 3, 1, lastCol - 2).getValues()[0];
}

// Adds any new distinct values as columns (appended at the end), returns
// the FULL current header list (existing + newly added) in column order.
function ensurePivotColumns(sheet, distinctValues) {
  const existing = getPivotColumnHeaders(sheet);
  const toAdd = distinctValues.filter(v => v && !existing.includes(v));
  if (toAdd.length) {
    const startCol = sheet.getLastColumn() + 1;
    sheet.getRange(2, startCol, 1, toAdd.length).setValues([toAdd]);
    setTabTitle(sheet); // re-merge title across the new width
    applySheetFormatting(sheet, 2); // re-extend formatting/banding to cover the new column(s)
  }
  return getPivotColumnHeaders(sheet);
}

// Scans the WHOLE sheet (not just the top) for a block matching `target`'s
// date, and removes it if found — needed so resyncing an arbitrary past day
// (not just "today"/"yesterday", which always land at the top) replaces
// that day in place instead of creating a duplicate elsewhere in the sheet.
function removeExistingDayBlockAnywhere(sheet, target) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 3) return;
  const dates = sheet.getRange(3, 1, lastRow - 2, 1).getValues();
  const sameDay = d => d instanceof Date
    && d.getFullYear() === target.getFullYear() && d.getMonth() === target.getMonth() && d.getDate() === target.getDate();

  let startIdx = -1;
  for (let i = 0; i < dates.length; i++) {
    if (sameDay(dates[i][0])) { startIdx = i; break; }
  }
  if (startIdx === -1) return; // no existing block for this date — nothing to remove

  // Walk forward while rows belong to this date, or are blank (Total row /
  // separator), to find where this one block ends.
  let endIdx = startIdx;
  while (endIdx < dates.length && (sameDay(dates[endIdx][0]) || dates[endIdx][0] === '' || dates[endIdx][0] === null)) {
    endIdx++;
  }
  sheet.deleteRows(3 + startIdx, endIdx - startIdx);
}

// Finds the correct row to insert `target`'s block at, so the sheet stays
// in newest-first order even when resyncing a day that isn't the most
// recent — returns the row right before the first existing row whose date
// is EARLIER than target (or appends at the end if target is the oldest).
function findInsertionRow(sheet, target) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 3) return 3; // empty — insert right after the header
  const dates = sheet.getRange(3, 1, lastRow - 2, 1).getValues();
  for (let i = 0; i < dates.length; i++) {
    const d = dates[i][0];
    if (d instanceof Date && d.getTime() < target.getTime()) return 3 + i;
  }
  return lastRow + 1; // target is older than everything currently in the sheet
}

// ===================== DAY-BLOCK INSERTION (NEWEST FIRST) ===========
// Inserts a full day's rows in the correct chronological slot (newest-first
// order), pushing older rows down. Optionally adds a bold Total row right
// after the data, then a blank separator row. Returns the row number where
// the data block starts, so callers can apply per-row formulas immediately.
function insertDayBlock(sheet, dataRows, totalRowValues, target) {
  const n = dataRows.length;
  if (n === 0) return null;
  if (target) removeExistingDayBlockAnywhere(sheet, target);
  const insertRow = target ? findInsertionRow(sheet, target) : 3;
  const numCols = dataRows[0].length;
  const blockSize = n + (totalRowValues ? 1 : 0) + 1; // data + optional total + blank separator
  sheet.insertRowsBefore(insertRow, blockSize);
  sheet.getRange(insertRow, 1, n, numCols).setValues(dataRows);
  if (totalRowValues) {
    sheet.getRange(insertRow + n, 1, 1, totalRowValues.length).setValues([totalRowValues]);
    sheet.getRange(insertRow + n, 1, 1, totalRowValues.length).setFontWeight('bold');
  }
  return insertRow;
}

// Builds and inserts a full day's block for a Source/Course Wise pivot tab,
// including a Total row summing every (dynamic) column.
// counselorLeadsMap: { counselorName: [leads for that counselor today] }
function writePivotDayBlock(sheet, target, counselorLeadsMap, valueField) {
  // Trim before checking for blank — a whitespace-only value (e.g. " ")
  // is truthy in JS and would otherwise slip past `|| '(Blank)'`, creating
  // a column whose header LOOKS empty even though it technically isn't.
  const cleanValue = v => (v == null ? '' : String(v).trim()) || '(Blank)';

  // Case-insensitive canonicalization: "ACCA", "acca", "Acca" must all land
  // in the SAME column, not three separate ones. Merges against already-
  // established column headers first (keeping their existing casing), then
  // against other values seen earlier THIS SAME DAY (first-seen casing wins
  // for anything brand new).
  const lowerToExisting = {};
  getPivotColumnHeaders(sheet).forEach(h => { lowerToExisting[String(h).toLowerCase()] = h; });
  const newValueCanonical = {};
  const canonicalize = raw => {
    const v = cleanValue(raw);
    const lower = v.toLowerCase();
    if (lowerToExisting[lower]) return lowerToExisting[lower];
    if (newValueCanonical[lower]) return newValueCanonical[lower];
    newValueCanonical[lower] = v;
    return v;
  };

  const allDistinct = new Set();
  Object.values(counselorLeadsMap).forEach(leads => {
    leads.forEach(l => allDistinct.add(canonicalize(l[valueField])));
  });
  const headers = ensurePivotColumns(sheet, Array.from(allDistinct));

  const totals = headers.map(() => 0);
  const dataRows = Object.keys(counselorLeadsMap).map(counselor => {
    const leads = counselorLeadsMap[counselor];
    const counts = {};
    leads.forEach(l => {
      const v = canonicalize(l[valueField]);
      counts[v] = (counts[v] || 0) + 1;
    });
    return [target, counselor, ...headers.map((h, i) => {
      const c = counts[h] || 0;
      totals[i] += c;
      return c;
    })];
  });

  const totalRow = ['', 'Total', ...totals];
  insertDayBlock(sheet, dataRows, totalRow, target);
}

function ensureMasterTab(ss) {
  let sheet = ss.getSheetByName(MASTER_TAB_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(MASTER_TAB_NAME);
    sheet.getRange(2, 1, 1, MASTER_HEADERS.length).setValues([MASTER_HEADERS]);
    setTabTitle(sheet);
    applySheetFormatting(sheet, 2);
    ss.setActiveSheet(sheet);
    ss.moveActiveSheet(1); // pin it as the first tab, easy to find
  }
  return sheet;
}

// Old versions had Master Data's header at row 1 (no title row). Detects
// that layout and shifts everything down one row so row 1 is free for a
// title, matching every other tab. Safe to call on an already-migrated
// sheet — it's a no-op then.
function migrateMasterTabIfNeeded(sheet) {
  if (sheet.getName() !== MASTER_TAB_NAME) return;
  const row1First = sheet.getRange(1, 1).getValue();
  const row2First = sheet.getRange(2, 1).getValue();
  if (row1First === 'Date' && row2First !== 'Date') {
    sheet.insertRowBefore(1);
  }
}

// ===================== ACTIVE COUNSELORS (LIVE) ===================
// Pulls the current user list from LeadSquared. StatusCode 0 = active,
// 1 = inactive/deactivated — inactive users are automatically excluded,
// so leavers drop off the report without any code changes.
function getActiveCounselors() {
  const props = PropertiesService.getScriptProperties();
  const accessKey = props.getProperty('ACCESS_KEY');
  const secretKey = props.getProperty('SECRET_KEY');
  const url = `https://${CONFIG.API_HOST}/v2/UserManagement.svc/Users.Get`
    + `?accessKey=${encodeURIComponent(accessKey)}&secretKey=${encodeURIComponent(secretKey)}`;

  const res = UrlFetchApp.fetch(url, { method: 'get', muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) {
    throw new Error(`LeadSquared Get Users error ${res.getResponseCode()}: ${res.getContentText()}`);
  }
  const users = JSON.parse(res.getContentText());

  return users
    .filter(u => u.StatusCode === 0) // active only
    .filter(u => !CONFIG.COUNSELOR_EXCLUDE_ROLES.includes(u.Role))
    .map(u => ({
      id: u.ID,
      name: `${u.FirstName}${u.LastName ? ' ' + u.LastName : ''}`.trim(),
      // name format matches what OwnerIdName returns on leads (e.g. "Mahima Rai")
    }))
    .filter(c => !CONFIG.COUNSELOR_EXCLUDE_NAMES.includes(c.name));
}

// ===================== BATCH FETCH (PERFORMANCE) ====================
// Fires multiple HTTP requests in PARALLEL (via UrlFetchApp.fetchAll)
// instead of one at a time — this is the fix for sync runs that got slow
// as lead volume grew: hundreds of sequential 220ms-paced calls easily
// balloon a single day's sync past 30 minutes. Batches of 20 stay safely
// under LeadSquared's 25-calls/5-sec limit, with a pause between batches.
function batchUrlFetch(requests, batchSize) {
  batchSize = batchSize || 20;
  const allResponses = [];
  for (let i = 0; i < requests.length; i += batchSize) {
    const batch = requests.slice(i, i + batchSize);
    const responses = UrlFetchApp.fetchAll(batch);
    allResponses.push(...responses);
    if (i + batchSize < requests.length) Utilities.sleep(1000); // pause between batches
  }
  return allResponses;
}

// ===================== OVERDUE TASKS (PER COUNSELOR) ===============
// Pulls a counselor's pending tasks and counts how many are overdue
// (DueDate already passed). This is a live snapshot, not a daily delta —
// so dailySync overwrites these values each run rather than summing them.
function getOverdueTaskCounts(ownerId) {
  const props = PropertiesService.getScriptProperties();
  const accessKey = props.getProperty('ACCESS_KEY');
  const secretKey = props.getProperty('SECRET_KEY');
  const url = `https://${CONFIG.API_HOST}/v2/Task.svc/Retrieve`
    + `?accessKey=${encodeURIComponent(accessKey)}&secretKey=${encodeURIComponent(secretKey)}`;

  const payload = {
    Parameter: { LookupName: 'OwnerId', LookupValue: ownerId, StatusCode: 0 }, // 0 = incomplete/pending
    Columns: { Exclude_CSV: 'Description' },
    Sorting: { ColumnName: 'DueDate', Direction: '0' },
    Paging: { Offset: 0, RowCount: 500 },
  };

  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  if (res.getResponseCode() !== 200) return { total: 0, thisMonth: 0, totalPending: 0 };
  const data = JSON.parse(res.getContentText());
  const tasks = data.List || [];

  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  // DueDate is UTC from the API — must parse as UTC (see parseUtcTimestamp),
  // not with a plain `new Date(str)` which most engines treat as local time.
  const overdue = tasks.filter(t => parseUtcTimestamp(t.DueDate) < now);

  return {
    total: overdue.length,
    thisMonth: overdue.filter(t => parseUtcTimestamp(t.DueDate) >= monthStart).length,
    totalPending: tasks.length, // denominator for a meaningful Overdues % (not "leads created that day")
  };
}

// Batched version: fetches overdue counts for ALL counselors in parallel
// instead of one at a time. Returns { ownerId: {total, thisMonth, totalPending} }.
function getOverdueTaskCountsBatch(ownerIds) {
  const props = PropertiesService.getScriptProperties();
  const accessKey = props.getProperty('ACCESS_KEY');
  const secretKey = props.getProperty('SECRET_KEY');
  const url = `https://${CONFIG.API_HOST}/v2/Task.svc/Retrieve`
    + `?accessKey=${encodeURIComponent(accessKey)}&secretKey=${encodeURIComponent(secretKey)}`;

  const requests = ownerIds.map(ownerId => ({
    url,
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      Parameter: { LookupName: 'OwnerId', LookupValue: ownerId, StatusCode: 0 },
      Columns: { Exclude_CSV: 'Description' },
      Sorting: { ColumnName: 'DueDate', Direction: '0' },
      Paging: { Offset: 0, RowCount: 500 },
    }),
    muteHttpExceptions: true,
  }));

  const responses = batchUrlFetch(requests);
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);
  const results = {};
  responses.forEach((res, i) => {
    const ownerId = ownerIds[i];
    if (res.getResponseCode() !== 200) { results[ownerId] = { total: 0, thisMonth: 0, totalPending: 0 }; return; }
    const tasks = (JSON.parse(res.getContentText()).List) || [];
    const overdue = tasks.filter(t => parseUtcTimestamp(t.DueDate) < now);
    results[ownerId] = {
      total: overdue.length,
      thisMonth: overdue.filter(t => parseUtcTimestamp(t.DueDate) >= monthStart).length,
      totalPending: tasks.length,
    };
  });
  return results;
}


// Confirmed response shape from LeadSquared docs:
// { "RecordCount": N, "TaskList": [ { "DueDate": "...", "Status": "Pending"/"Completed", ... } ] }
function getTasksForLead(leadId) {
  const props = PropertiesService.getScriptProperties();
  const accessKey = props.getProperty('ACCESS_KEY');
  const secretKey = props.getProperty('SECRET_KEY');
  const url = `https://${CONFIG.API_HOST}/v2/LeadManagement.svc/RetrieveTaskByLeadId`
    + `?accessKey=${encodeURIComponent(accessKey)}&secretKey=${encodeURIComponent(secretKey)}&leadId=${encodeURIComponent(leadId)}`;
  const res = UrlFetchApp.fetch(url, { method: 'get', muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) return [];
  const data = JSON.parse(res.getContentText());
  return data.TaskList || [];
}

// For Lead Funnel's Task / Overdues / No Task columns: looks at ONLY the
// leads created that specific day (not the counselor's whole pipeline).
function computeDayWiseTaskMetrics(leadsCreatedToday) {
  let totalTasks = 0, overdueTasks = 0, noTaskLeads = 0;
  const now = new Date();
  leadsCreatedToday.forEach(lead => {
    const tasks = getTasksForLead(lead.ProspectID);
    Utilities.sleep(220); // pace to respect 25-calls/5-sec rate limit
    totalTasks += tasks.length;
    if (tasks.length === 0) noTaskLeads++;
    overdueTasks += tasks.filter(t =>
      t.Status === 'Pending' && parseUtcTimestamp(t.DueDate) < now
    ).length;
  });
  return { totalTasks, overdueTasks, noTaskLeads };
}

// Batched: fetches tasks for MANY leads in parallel. Returns
// { leadId: [tasks...] }. Used once for ALL of today's created leads
// (across every counselor), instead of a separate sequential pass per
// counselor — this was one of the biggest contributors to slow syncs.
function getTasksForLeadsBatch(leadIds) {
  const props = PropertiesService.getScriptProperties();
  const accessKey = props.getProperty('ACCESS_KEY');
  const secretKey = props.getProperty('SECRET_KEY');
  const requests = leadIds.map(leadId => ({
    url: `https://${CONFIG.API_HOST}/v2/LeadManagement.svc/RetrieveTaskByLeadId`
      + `?accessKey=${encodeURIComponent(accessKey)}&secretKey=${encodeURIComponent(secretKey)}&leadId=${encodeURIComponent(leadId)}`,
    method: 'get',
    muteHttpExceptions: true,
  }));
  const responses = batchUrlFetch(requests);
  const results = {};
  responses.forEach((res, i) => {
    const leadId = leadIds[i];
    if (res.getResponseCode() !== 200) { results[leadId] = []; return; }
    results[leadId] = (JSON.parse(res.getContentText()).TaskList) || [];
  });
  return results;
}

// Batched: fetches each lead's Source field directly. Needed because
// searchOpportunitiesByEnrolledDate's P_Source field comes back null
// (confirmed via diagnostic) even though it's requested — so for Source
// Wise Enrolment, we instead look up each enrolled opportunity's lead
// (via RelatedProspectId, which IS reliably present) and fetch its Source
// this way. Returns { leadId: sourceValue }.
function getLeadSourcesBatch(leadIds) {
  const props = PropertiesService.getScriptProperties();
  const accessKey = props.getProperty('ACCESS_KEY');
  const secretKey = props.getProperty('SECRET_KEY');
  const url = `https://${CONFIG.API_HOST}/v2/LeadManagement.svc/Leads.Get`
    + `?accessKey=${encodeURIComponent(accessKey)}&secretKey=${encodeURIComponent(secretKey)}`;
  const requests = leadIds.map(leadId => ({
    url,
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      Parameter: { LookupName: 'ProspectID', LookupValue: leadId, SqlOperator: '=' },
      Columns: { Include_CSV: CONFIG.LEAD_SOURCE_FIELD },
      Paging: { PageIndex: 1, PageSize: 1 },
    }),
    muteHttpExceptions: true,
  }));
  const responses = batchUrlFetch(requests);
  const results = {};
  responses.forEach((res, i) => {
    const leadId = leadIds[i];
    if (res.getResponseCode() !== 200) { results[leadId] = null; return; }
    const data = JSON.parse(res.getContentText());
    const list = Array.isArray(data) ? data : (data.List || []);
    results[leadId] = list.length ? (list[0][CONFIG.LEAD_SOURCE_FIELD] || null) : null;
  });
  return results;
}

// Computes Task/Overdues/No Task metrics from a pre-fetched tasks map
// (from getTasksForLeadsBatch), rather than making its own API calls.
function computeDayWiseTaskMetricsFromMap(leadsCreatedToday, tasksByLeadId) {
  let totalTasks = 0, overdueTasks = 0, noTaskLeads = 0;
  const now = new Date();
  leadsCreatedToday.forEach(lead => {
    const tasks = tasksByLeadId[lead.ProspectID] || [];
    totalTasks += tasks.length;
    if (tasks.length === 0) noTaskLeads++;
    overdueTasks += tasks.filter(t =>
      t.Status === 'Pending' && parseUtcTimestamp(t.DueDate) < now
    ).length;
  });
  return { totalTasks, overdueTasks, noTaskLeads };
}

// ================= OPPORTUNITY ADVANCED SEARCH (ENROLLED DATE) ======
// Admin-only endpoint that searches Opportunities DIRECTLY by Enrolled
// Date — no more inferring enrollment from "was this lead modified today"
// (which misses leads touched again on a later day). One call per day
// covers ALL counselors at once — far cheaper than per-lead lookups too.
// Structure confirmed working from the account's own captured browser
// payload (LeadSquared's OpportunityGrid network call).
function searchOpportunitiesByEnrolledDate(dayStart, dayEnd) {
  const props = PropertiesService.getScriptProperties();
  const accessKey = props.getProperty('ACCESS_KEY');
  const secretKey = props.getProperty('SECRET_KEY');
  const url = `https://${CONFIG.API_HOST}/v2/OpportunityManagement.svc/Retrieve/BySearchParameter`
    + `?accessKey=${encodeURIComponent(accessKey)}&secretKey=${encodeURIComponent(secretKey)}`;

  // Format matches the captured example exactly: "yyyy-MM-dd hh:mm:ss a TO yyyy-MM-dd hh:mm:ss a"
  const fmt = d => Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy-MM-dd hh:mm:ss a');
  const rangeStr = `${fmt(dayStart)} TO ${fmt(dayEnd)}`;

  const advancedSearch = JSON.stringify({
    GrpConOp: 'And',
    QueryTimeZone: 'India Standard Time',
    Conditions: [
      {
        Type: 'Activity', ConOp: 'and',
        RowCondition: [{ SubConOp: 'And', LSO: 'ActivityEvent', LSO_Type: 'PAEvent', Operator: 'eq', RSO: String(CONFIG.OPPORTUNITY_EVENT_CODE) }],
      },
      {
        Type: 'Activity', ConOp: 'and',
        RowCondition: [{ SubConOp: 'and', LSO: CONFIG.ENROLLED_DATE_FIELD, LSO_Type: 'DateTime', Operator: 'between', RSO: rangeStr }],
      },
    ],
  });

  const allResults = [];
  let pageIndex = 1;
  const pageSize = 200;
  while (pageIndex <= 20) { // safety cap: 4000 records
    const payload = {
      OpportunityEventCode: CONFIG.OPPORTUNITY_EVENT_CODE,
      AdvancedSearch: advancedSearch,
      Columns: { Include_CSV: `Owner,Status,${CONFIG.OPPORTUNITY_STAGE_FIELD},P_${CONFIG.LEAD_SOURCE_FIELD}` },
      Paging: { PageIndex: pageIndex, PageSize: pageSize },
      Sorting: { ColumnName: 'CreatedOn', Direction: 1 },
    };
    const res = UrlFetchApp.fetch(url, {
      method: 'post', contentType: 'application/json',
      payload: JSON.stringify(payload), muteHttpExceptions: true,
    });
    if (res.getResponseCode() !== 200) {
      Logger.log(`searchOpportunitiesByEnrolledDate failed: ${res.getResponseCode()} — ${res.getContentText()}`);
      break;
    }
    const data = JSON.parse(res.getContentText());
    const list = data.List || [];
    allResults.push(...list);
    if (list.length < pageSize) break;
    pageIndex++;
    Utilities.sleep(220);
  }
  return allResults;
}

// ===================== DIAGNOSTIC: untracked/excluded owners ==========
// Finds every lead created this month whose owner is NOT in today's active
// counselor list — catches both the 3 explicitly-excluded names AND anyone
// who left the company mid-month (their earlier leads would be invisible
// to the whole sheet, since we always use TODAY's roster, not a
// point-in-time one). Directly quantifies how many leads this explains.
function diagnoseUntrackedOwners() {
  const MONTH_START = '2026-08-01'; // yyyy-MM-dd — adjust to the month you're checking
  const MONTH_END = '2026-09-01';   // exclusive upper bound — first day of the NEXT month

  const start = new Date(MONTH_START + 'T00:00:00');
  const end = new Date(MONTH_END + 'T00:00:00');
  const lowerBoundUtc = Utilities.formatDate(start, 'Etc/UTC', 'yyyy-MM-dd HH:mm:ss');
  const allLeadsRaw = lsqSearchAllPages('CreatedOn', lowerBoundUtc, '>=', 'ProspectID,OwnerIdName,CreatedOn');
  // Bound to August only — without this, "now" being in September would
  // pull September's leads into the count too, inflating the comparison.
  const allLeads = allLeadsRaw.filter(l => parseUtcTimestamp(l.CreatedOn) < end);

  const counselors = getActiveCounselors();
  const trackedNames = new Set(counselors.map(c => c.name));

  const byOwner = {};
  allLeads.forEach(l => {
    const owner = l.OwnerIdName || '(no owner)';
    byOwner[owner] = (byOwner[owner] || 0) + 1;
  });

  Logger.log(`Total leads created ${MONTH_START} through ${MONTH_END} (exclusive): ${allLeads.length}`);
  Logger.log(`Currently tracked counselors: ${counselors.length}`);
  Logger.log('--- Owners with leads this month who are NOT in the tracked list ---');
  let untrackedTotal = 0;
  Object.keys(byOwner).forEach(owner => {
    if (!trackedNames.has(owner)) {
      Logger.log(`${owner}: ${byOwner[owner]} leads`);
      untrackedTotal += byOwner[owner];
    }
  });
  Logger.log(`TOTAL leads invisible to the sheet due to untracked ownership: ${untrackedTotal}`);
}

// ===================== DIAGNOSTIC: course-specific gap ================
// Same idea as diagnoseUntrackedOwners, but filtered to ONE course, so you
// can see exactly how much of a reported course-level gap (e.g. "ACCA is
// short by 100+") is explained by untracked ownership vs. still unexplained.
function diagnoseCourseGap() {
  const MONTH_START = '2026-08-01';
  const MONTH_END = '2026-09-01';
  const COURSE_NAME = 'ACCA'; // case-insensitive match

  const start = new Date(MONTH_START + 'T00:00:00');
  const end = new Date(MONTH_END + 'T00:00:00');
  const lowerBoundUtc = Utilities.formatDate(start, 'Etc/UTC', 'yyyy-MM-dd HH:mm:ss');
  const allLeadsRaw = lsqSearchAllPages('CreatedOn', lowerBoundUtc, '>=',
    `ProspectID,OwnerIdName,CreatedOn,${CONFIG.PROGRAM_FIELD}`);
  const allLeads = allLeadsRaw.filter(l => parseUtcTimestamp(l.CreatedOn) < end);

  const courseLeads = allLeads.filter(l =>
    String(l[CONFIG.PROGRAM_FIELD] || '').trim().toLowerCase() === COURSE_NAME.toLowerCase()
  );

  const counselors = getActiveCounselors();
  const trackedNames = new Set(counselors.map(c => c.name));

  let trackedCount = 0, untrackedCount = 0;
  const untrackedByOwner = {};
  courseLeads.forEach(l => {
    const owner = l.OwnerIdName || '(no owner)';
    if (trackedNames.has(owner)) {
      trackedCount++;
    } else {
      untrackedCount++;
      untrackedByOwner[owner] = (untrackedByOwner[owner] || 0) + 1;
    }
  });

  Logger.log(`Total "${COURSE_NAME}" leads ${MONTH_START} to ${MONTH_END} (exclusive): ${courseLeads.length}`);
  Logger.log(`  Owned by TRACKED counselors (should appear in sheet): ${trackedCount}`);
  Logger.log(`  Owned by UNTRACKED owners (excluded by design): ${untrackedCount}`);
  Logger.log('  Untracked breakdown:');
  Logger.log(JSON.stringify(untrackedByOwner, null, 2));
  Logger.log(`Compare "${trackedCount}" against the SUM of the Course Wise "${COURSE_NAME}" column for August in your sheet.`);
}

// One-off test — run this FIRST, before trusting the function above in the
// real sync. Prints raw results for Aug 1-20, 2026 so you can compare
// against the count you saw in LeadSquared's own UI for the same range.
function testOpportunityAdvancedSearch() {
  const dayStart = new Date(2026, 7, 1); // Aug 1, 2026 (month is 0-indexed)
  const dayEnd = new Date(2026, 7, 20);  // Aug 20, 2026
  const results = searchOpportunitiesByEnrolledDate(dayStart, dayEnd);
  Logger.log(`Found ${results.length} enrolled opportunities Aug 1-20, 2026.`);

  const counselors = getActiveCounselors();
  const idToName = {};
  counselors.forEach(c => idToName[c.id] = c.name);

  const byOwner = {};
  results.forEach(o => {
    const name = idToName[o.Owner] || `Unknown (${o.Owner})`;
    byOwner[name] = (byOwner[name] || 0) + 1;
  });
  Logger.log(JSON.stringify(byOwner, null, 2));

  // Source field check — new: does P_Source actually come back?
  const sourceField = `P_${CONFIG.LEAD_SOURCE_FIELD}`;
  Logger.log(`--- Checking "${sourceField}" field on first 5 results ---`);
  if (results.length === 0) {
    Logger.log('No results to check.');
  } else {
    results.slice(0, 5).forEach((o, i) => {
      Logger.log(`Result ${i + 1}: ${sourceField} = ${JSON.stringify(o[sourceField])}`);
    });
    Logger.log('--- Full raw keys on first result (so we can see what IS available) ---');
    Logger.log(JSON.stringify(Object.keys(results[0])));
  }
}

// ================= OPPORTUNITY STAGE (PER LEAD) ===================
// Stage (Cold/Warm/Hot/etc.) lives on the Opportunity record, not the
// Lead. This calls GetOpportunitiesOfLead for one lead and returns its
// most recently modified opportunity's stage + status.
// Rate limit: LeadSquared allows 25 calls / 5 sec, so callers should
// pace these (see the sleep in dailySync's enrichment loop).
function getOpportunityStage(leadId) {
  const props = PropertiesService.getScriptProperties();
  const accessKey = props.getProperty('ACCESS_KEY');
  const secretKey = props.getProperty('SECRET_KEY');
  const url = `https://${CONFIG.API_HOST}/v2/OpportunityManagement.svc/GetOpportunitiesOfLead`
    + `?accessKey=${encodeURIComponent(accessKey)}&secretKey=${encodeURIComponent(secretKey)}`
    + `&leadId=${encodeURIComponent(leadId)}`;

  const payload = {
    Columns: { Include_CSV: `${CONFIG.OPPORTUNITY_STAGE_FIELD},${CONFIG.OPPORTUNITY_STATUS_FIELD},${CONFIG.ENROLLED_DATE_FIELD}` },
    Paging: { PageIndex: 1, PageSize: 5 },
    Sorting: { ColumnName: 'ModifiedOn', Direction: '1' }, // 1 = descending = most recent first
  };

  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  if (res.getResponseCode() !== 200) return null; // lead may have no opportunity yet
  const data = JSON.parse(res.getContentText());
  const list = data.List || data; // response shape varies slightly by account config
  if (!list || !list.length) return null;

  return {
    stage: list[0][CONFIG.OPPORTUNITY_STAGE_FIELD] || null,
    status: list[0][CONFIG.OPPORTUNITY_STATUS_FIELD] || null,
    enrolledDate: list[0][CONFIG.ENROLLED_DATE_FIELD] || null,
  };
}

// Batched: the single biggest performance win, since this lookup runs once
// per unique lead across BOTH created and modified sets — often the largest
// volume of calls in a day's sync. Returns { leadId: {stage,status,enrolledDate} }.
function getOpportunityStagesBatch(leadIds) {
  const props = PropertiesService.getScriptProperties();
  const accessKey = props.getProperty('ACCESS_KEY');
  const secretKey = props.getProperty('SECRET_KEY');
  const requests = leadIds.map(leadId => ({
    url: `https://${CONFIG.API_HOST}/v2/OpportunityManagement.svc/GetOpportunitiesOfLead`
      + `?accessKey=${encodeURIComponent(accessKey)}&secretKey=${encodeURIComponent(secretKey)}&leadId=${encodeURIComponent(leadId)}`,
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({
      Columns: { Include_CSV: `${CONFIG.OPPORTUNITY_STAGE_FIELD},${CONFIG.OPPORTUNITY_STATUS_FIELD},${CONFIG.ENROLLED_DATE_FIELD}` },
      Paging: { PageIndex: 1, PageSize: 5 },
      Sorting: { ColumnName: 'ModifiedOn', Direction: '1' },
    }),
    muteHttpExceptions: true,
  }));

  const responses = batchUrlFetch(requests);
  const results = {};
  responses.forEach((res, i) => {
    const leadId = leadIds[i];
    if (res.getResponseCode() !== 200) { results[leadId] = null; return; }
    const data = JSON.parse(res.getContentText());
    const list = data.List || data;
    if (!list || !list.length) { results[leadId] = null; return; }
    results[leadId] = {
      stage: list[0][CONFIG.OPPORTUNITY_STAGE_FIELD] || null,
      status: list[0][CONFIG.OPPORTUNITY_STATUS_FIELD] || null,
      enrolledDate: list[0][CONFIG.ENROLLED_DATE_FIELD] || null,
    };
  });
  return results;
}

// One-off helper: run THIS (not getActiveCounselors directly) to see the
// list in View > Logs. getActiveCounselors() itself just returns a value,
// which is invisible unless something logs it.
function logActiveCounselors() {
  const list = getActiveCounselors();
  Logger.log(`Will count ${list.length} counselors (Admin/Marketing excluded):`);
  Logger.log(JSON.stringify(list.map(c => c.name), null, 2));
}

// ========================= UTC TIME HELPERS =========================
// LeadSquared's API requires UTC in query values and returns UTC in
// responses, but as "naive" strings with no timezone marker (e.g.
// "2026-08-03 05:30:00.000"). If these are parsed with a plain
// `new Date(str)`, most JS engines treat them as LOCAL time, silently
// shifting every comparison by your UTC offset (5:30 for IST). This
// helper forces correct UTC interpretation.
function parseUtcTimestamp(str) {
  if (!str) return null;
  return new Date(str.replace(' ', 'T') + 'Z');
}

// Compares a Date instant against `target` (an IST-midnight-normalized Date)
// by calendar day — uses the script's local timezone (IST) for the
// comparison, matching how `target` itself is constructed.
function isSameCalendarDay(d, target) {
  return d instanceof Date
    && d.getFullYear() === target.getFullYear()
    && d.getMonth() === target.getMonth()
    && d.getDate() === target.getDate();
}

// ===================== ENROLLMENT RECONCILIATION =====================
// The day-by-day sync only checks leads MODIFIED on that exact day — but a
// lead can enroll on day X and then get touched again (a note, a follow-up)
// on a LATER day Y. Since it's no longer in day X's "modified" list, and its
// Enrolled Date doesn't match day Y, that enrollment falls through the
// cracks on BOTH days. This widens the search to everything modified in the
// last DAYS_BACK days, checks each lead's real Enrolled Date, and directly
// overwrites the affected historical rows with the corrected count — fixing
// exactly this gap without needing Admin-only Opportunity Search API access.
function findReportsRow(sheet, targetDate, counselor) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 3) return null;
  const dates = sheet.getRange(3, 1, lastRow - 2, 1).getValues();
  const names = sheet.getRange(3, 2, lastRow - 2, 1).getValues();
  for (let i = 0; i < dates.length; i++) {
    if (isSameCalendarDay(dates[i][0], targetDate) && names[i][0] === counselor) return 3 + i;
  }
  return null;
}

function reconcileEnrollments() {
  const DAYS_BACK = 45; // wide enough to catch late-touched enrollments; narrow this if it's too slow
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  showWaitToast(ss);

  const now = new Date();
  const windowStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - DAYS_BACK);
  const lowerBoundUtc = Utilities.formatDate(windowStart, 'Etc/UTC', 'yyyy-MM-dd HH:mm:ss');

  const leads = lsqSearchAllPages('ModifiedOn', lowerBoundUtc, '>=', 'ProspectID,OwnerIdName');
  Logger.log(`Checking ${leads.length} leads modified in the last ${DAYS_BACK} days for enrollments...`);

  const counts = {}; // counts[yyyy-MM-dd][counselor] = enrolled count
  let checked = 0;
  leads.forEach(lead => {
    const opp = getOpportunityStage(lead.ProspectID);
    Utilities.sleep(220);
    checked++;
    if (opp && opp.enrolledDate) {
      const d = parseUtcTimestamp(opp.enrolledDate);
      const dateKey = Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy-MM-dd');
      const counselor = lead.OwnerIdName;
      counts[dateKey] = counts[dateKey] || {};
      counts[dateKey][counselor] = (counts[dateKey][counselor] || 0) + 1;
    }
    if (checked % 100 === 0) Logger.log(`...checked ${checked}/${leads.length}`);
  });

  let updated = 0, missingRows = 0;
  Object.keys(counts).forEach(dateKey => {
    const dayDate = new Date(dateKey + 'T00:00:00');
    const names = getMonthTabNames(dayDate);
    const sheet = ss.getSheetByName(names.reports);
    if (!sheet) return;
    Object.keys(counts[dateKey]).forEach(counselor => {
      const row = findReportsRow(sheet, dayDate, counselor);
      if (row) {
        sheet.getRange(row, 18).setValue(counts[dateKey][counselor]); // R = Enrolled Today
        updated++;
      } else {
        missingRows++; // that day/counselor combo isn't in the sheet yet (not backfilled)
      }
    });
  });

  const summary = `Reconciled enrollments: checked ${checked} leads over ${DAYS_BACK} days, `
    + `corrected ${updated} day/counselor rows` + (missingRows ? `, ${missingRows} skipped (day not yet synced)` : '') + '.';
  Logger.log(summary);
  ss.toast(summary, 'Reconcile complete ✅', 8);
  SpreadsheetApp.getUi().alert('Reconcile complete', summary, SpreadsheetApp.getUi().ButtonSet.OK);
}

// ========================= LSQ API CALL =========================
function lsqSearch(lookupName, lookupValue, sqlOperator, includeCsv, pageSize, pageIndex) {
  const props = PropertiesService.getScriptProperties();
  const accessKey = props.getProperty('ACCESS_KEY');
  const secretKey = props.getProperty('SECRET_KEY');
  const url = `https://${CONFIG.API_HOST}/v2/LeadManagement.svc/Leads.Get`
    + `?accessKey=${encodeURIComponent(accessKey)}&secretKey=${encodeURIComponent(secretKey)}`;

  const payload = {
    Parameter: { LookupName: lookupName, LookupValue: lookupValue, SqlOperator: sqlOperator },
    Columns: { Include_CSV: includeCsv },
    Sorting: { ColumnName: 'CreatedOn', Direction: '1' },
    Paging: { PageIndex: pageIndex || 1, PageSize: pageSize || 1000 },
  };

  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });

  if (res.getResponseCode() !== 200) {
    throw new Error(`LeadSquared API error ${res.getResponseCode()}: ${res.getContentText()}`);
  }
  return JSON.parse(res.getContentText());
}

// Fetches ALL matching pages, not just the first — required whenever the
// query only has a lower bound (>=) and no true upper bound at the API
// level (LeadSquared's Search-by-Criteria only supports one condition).
// A single page + assumed sort order silently drops data once the window
// between the lower bound and "now" grows large — exactly what happened
// during backfill, where old historical days got outrun by more recent
// leads piling up ahead of them in the result set. Paginating through
// everything sidesteps the sort-order assumption entirely.
// maxPages=100 at 1000/page = up to 100,000 records scanned as a safety
// cap — raised from 20,000 after finding real data gaps on a busy,
// multi-course account where the lower-bound-to-now window had grown large.
function lsqSearchAllPages(lookupName, lookupValue, sqlOperator, includeCsv, maxPages) {
  const pageSize = 1000;
  maxPages = maxPages || 100;
  let all = [];
  for (let pageIndex = 1; pageIndex <= maxPages; pageIndex++) {
    const page = lsqSearch(lookupName, lookupValue, sqlOperator, includeCsv, pageSize, pageIndex);
    if (!page || page.length === 0) break;
    all = all.concat(page);
    if (page.length < pageSize) break; // reached the last page
    if (pageIndex === maxPages) {
      Logger.log(`WARNING: lsqSearchAllPages hit the ${maxPages}-page safety cap for ${lookupName} ${sqlOperator} ${lookupValue} — results may be incomplete. Consider narrowing the date range.`);
    }
  }
  return all;
}

// ===================== DIAGNOSTIC: CreatedOn vs LeadConversionDate ========
// LeadSquared sometimes has TWO "created" timestamps: CreatedOn (raw record)
// and LeadConversionDate ("Prospect Creation Date" — when an anonymous
// visitor became a qualified Lead). The UI's "Created On" column may be
// sourced from either, depending on account config. Run this and compare
// both columns against what the LeadSquared UI shows for the same leads.
// ===================== DIAGNOSTIC: count leads for a specific date ========
// Properly bounded (both ends, correct UTC conversion, big enough page size,
// no ordering trap) so you can test an exact historical day against the
// LeadSquared UI, independent of what "today" currently is.
// Usage: edit DIAG_DATE / DIAG_OWNER below, then run this function.
function countLeadsForDate() {
  const DIAG_DATE = '2026-08-03';           // yyyy-MM-dd, IST calendar date to test
  const DIAG_OWNER = 'Anuj Thakur';         // set to null to check all owners

  const dayStart = new Date(DIAG_DATE + 'T00:01:00'); // 12:01 AM, matches production boundary
  const dayEnd = new Date(dayStart.getTime() + 86400000);
  const lowerBoundUtc = Utilities.formatDate(dayStart, 'Etc/UTC', 'yyyy-MM-dd HH:mm:ss');

  const raw = lsqSearchAllPages('CreatedOn', lowerBoundUtc, '>=',
    'ProspectID,FirstName,OwnerIdName,CreatedOn,LeadConversionDate');
  let leads = raw.filter(l => parseUtcTimestamp(l.CreatedOn) < dayEnd);
  if (DIAG_OWNER) leads = leads.filter(l => l.OwnerIdName === DIAG_OWNER);

  Logger.log(`${leads.length} leads created on ${DIAG_DATE}` + (DIAG_OWNER ? ` for ${DIAG_OWNER}` : ''));
  leads.forEach(l => Logger.log(`${l.FirstName} | ${l.OwnerIdName} | ${l.CreatedOn}`));
}

function diagnoseCreatedOnField() {
  const result = lsqSearch('CreatedOn', '2026-08-02 18:30:00', '>=',
    'ProspectID,FirstName,OwnerIdName,CreatedOn,LeadConversionDate', 50);
  Logger.log(`${result.length} leads found. ProspectID | Owner | CreatedOn | LeadConversionDate`);
  result.forEach(l => {
    Logger.log(`${l.FirstName} | ${l.OwnerIdName} | ${l.CreatedOn} | ${l.LeadConversionDate}`);
  });
}

// ===================== DIAGNOSTIC: Enrolled Date format ================
// Cross-references Enrolled Date (unknown format, e.g. "08/02/2026 05:27
// PM") against the Opportunity's own ModifiedOn (KNOWN format: UTC,
// "yyyy-MM-dd HH:mm:ss") for the same lead. Since enrolling a lead updates
// both fields within seconds of each other, comparing them tells us
// definitively whether Enrolled Date is MM/DD or DD/MM.
function diagnoseEnrolledDateFormat() {
  const props = PropertiesService.getScriptProperties();
  const accessKey = props.getProperty('ACCESS_KEY');
  const secretKey = props.getProperty('SECRET_KEY');

  // Widened: scan ALL leads modified since account inception (paginated),
  // not just recent ones — we just need a handful of Enrolled examples,
  // wherever they are.
  const modifiedRecent = lsqSearchAllPages('ModifiedOn', '2020-01-01 00:00:00', '>=',
    'ProspectID,FirstName,OwnerIdName', 10); // up to 10 pages x 1000 = 10,000 leads scanned

  Logger.log(`Scanning ${modifiedRecent.length} leads for Enrolled examples...`);
  let found = 0, checked = 0;
  const MAX_CHECK = 300; // safety cap — ~300 * 220ms ≈ 66 sec, well within limits
  for (const lead of modifiedRecent) {
    if (found >= 5 || checked >= MAX_CHECK) break;
    checked++;
    const url = `https://${CONFIG.API_HOST}/v2/OpportunityManagement.svc/GetOpportunitiesOfLead`
      + `?accessKey=${encodeURIComponent(accessKey)}&secretKey=${encodeURIComponent(secretKey)}&leadId=${encodeURIComponent(lead.ProspectID)}`;
    const payload = {
      Columns: { Include_CSV: `${CONFIG.OPPORTUNITY_STAGE_FIELD},${CONFIG.ENROLLED_DATE_FIELD},ModifiedOn` },
      Paging: { PageIndex: 1, PageSize: 5 },
      Sorting: { ColumnName: 'ModifiedOn', Direction: '1' },
    };
    const res = UrlFetchApp.fetch(url, { method: 'post', contentType: 'application/json', payload: JSON.stringify(payload), muteHttpExceptions: true });
    Utilities.sleep(220);
    if (res.getResponseCode() !== 200) continue;
    const data = JSON.parse(res.getContentText());
    const list = data.List || data;
    if (!list || !list.length) continue;
    const opp = list[0];
    if (opp[CONFIG.OPPORTUNITY_STAGE_FIELD] === 'Enrolled' && opp[CONFIG.ENROLLED_DATE_FIELD]) {
      found++;
      Logger.log(`Lead: ${lead.FirstName} | Owner: ${lead.OwnerIdName}`);
      Logger.log(`  Opportunity ModifiedOn (KNOWN: UTC, yyyy-MM-dd HH:mm:ss): ${opp.ModifiedOn}`);
      Logger.log(`  Enrolled Date (format TBD): ${opp[CONFIG.ENROLLED_DATE_FIELD]}`);
    }
    if (checked % 50 === 0) Logger.log(`...checked ${checked}, found ${found} so far`);
  }
  if (found === 0) Logger.log(`Checked ${checked} leads, found zero currently in "Enrolled" stage. This account may use a different stage name for enrolled students, or genuinely has none yet.`);
}

// ===================== ONE-TIME VERIFICATION =====================
// Run this manually FIRST. It pulls a handful of recent leads and logs
// the raw fields LeadSquared returns, so you can confirm OwnerIdName
// (or whatever your account calls it) actually comes back populated
// with counselor names like "Anuj". View results: View > Logs (Ctrl+Enter).
function testFieldNames() {
  const result = lsqSearch('CreatedOn', '2020-01-01 00:00:00', '>',
    ['ProspectID','FirstName','OwnerId','OwnerIdName',
     CONFIG.LEAD_SOURCE_FIELD,CONFIG.PROGRAM_FIELD,'CreatedOn','ModifiedOn'].join(','), 5);
  Logger.log('--- Lead fields ---');
  Logger.log(JSON.stringify(result, null, 2));

  Logger.log('--- Opportunity stage lookup (first lead) ---');
  if (result.length) {
    const opp = getOpportunityStage(result[0].ProspectID);
    Logger.log(JSON.stringify(opp, null, 2));
  }

  Logger.log('--- Overdue task count (first active counselor) ---');
  const counselors = getActiveCounselors();
  if (counselors.length) {
    const overdue = getOverdueTaskCounts(counselors[0].id);
    Logger.log(`${counselors[0].name}: ${JSON.stringify(overdue)}`);
  }
}

// ===================== DAILY SYNC (MAIN JOB) =====================
function dailySync() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // Sync yesterday's completed day
  const now = new Date();
  const target = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1); // yesterday, midnight

  runSyncForDate(ss, target);
}

// Syncs TODAY — a partial, still-accumulating day. Safe to re-run as often
// as you like (e.g. hourly): the dedup logic in insertDayBlock means each
// run replaces today's block in place rather than duplicating it, so
// numbers just keep updating throughout the day.
function syncToday() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  runSyncForDate(ss, today);
}

// Resyncs exactly ONE arbitrary day — no clearing of anything else, unlike
// the full backfill dialog. Relies entirely on insertDayBlock's dedup logic
// (finds and removes that day's existing block wherever it sits in the
// sheet, then reinserts it in the correct chronological position), so every
// OTHER already-synced day is left completely untouched.
function resyncOneDay(dateStr) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const day = new Date(dateStr + 'T00:00:00');
  runSyncForDate(ss, day);
  return `Resynced ${dateStr}. All other days were left untouched.`;
}

function showResyncOneDayDialog() {
  const html = HtmlService.createHtmlOutput(`
    <div style="font-family:Arial,sans-serif;font-size:13px;padding:4px;">
      <p style="margin-top:0;">Re-syncs ONE specific day only — every other already-synced day stays exactly as it is.</p>
      <div style="margin-bottom:14px;">
        <label style="display:block;margin-bottom:4px;">Date to resync</label>
        <input type="date" id="theDate" style="width:100%;padding:6px;box-sizing:border-box;">
      </div>
      <button onclick="run()" id="runBtn" style="padding:8px 16px;background:#1a73e8;color:#fff;border:none;border-radius:4px;cursor:pointer;">Resync This Day</button>
      <p id="status" style="margin-top:12px;color:#555;"></p>
    </div>
    <script>
      function run() {
        var d = document.getElementById('theDate').value;
        var status = document.getElementById('status');
        if (!d) { status.textContent = 'Please pick a date.'; return; }
        document.getElementById('runBtn').disabled = true;
        status.textContent = 'Resyncing — please wait...';
        google.script.run
          .withSuccessHandler(function(msg) {
            status.textContent = msg;
            document.getElementById('runBtn').disabled = false;
          })
          .withFailureHandler(function(err) {
            status.textContent = 'Error: ' + err.message;
            document.getElementById('runBtn').disabled = false;
          })
          .resyncOneDay(d);
      }
    </script>
  `).setWidth(340).setHeight(220);
  SpreadsheetApp.getUi().showModalDialog(html, 'Resync One Day');
}

// ===================== ROLLING RECONCILIATION ========================
// The real fix for "old data goes stale as things change later" (a lead
// enrolls weeks after creation, a stage flips to Lost, a task gets added
// late): instead of waiting for someone to notice a mismatch and manually
// resync, this automatically re-touches a rolling window of recent days
// on a schedule — each day gets safely REPLACED in place (same dedup logic
// as Resync One Day), never appended as a duplicate, and days outside the
// window are never touched at all.
//
// Deliberately does NOT reuse the backfill infrastructure — backfill
// clears whole months when starting a range it doesn't recognize as a
// resume-in-progress, which would be actively dangerous here since the
// rolling window's dates shift every single day (it would never match a
// prior "in progress" range and would wipe entire months on every run).
const ROLLING_RECONCILE_KEY = 'ROLLING_RECONCILE_PROGRESS'; // stores {end, completedThrough}
const ROLLING_RECONCILE_TIME_LIMIT_MS = 5 * 60 * 1000; // same 1-min safety buffer as backfill

function rollingReconcileRange(startDateStr, endDateStr) {
  const execStart = Date.now();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  showWaitToast(ss);

  const props = PropertiesService.getScriptProperties();
  const saved = props.getProperty(ROLLING_RECONCILE_KEY);
  const savedProgress = saved ? JSON.parse(saved) : null;
  const isResuming = savedProgress && savedProgress.start === startDateStr && savedProgress.end === endDateStr;

  let resumeFrom = new Date(startDateStr + 'T00:00:00');
  if (isResuming) {
    resumeFrom = new Date(savedProgress.completedThrough + 'T00:00:00');
    resumeFrom.setDate(resumeFrom.getDate() + 1);
  }
  const end = new Date(endDateStr + 'T00:00:00');

  let processed = 0, failed = 0, stoppedEarly = false, lastCompleted = null;
  for (let d = new Date(resumeFrom); d <= end; d.setDate(d.getDate() + 1)) {
    if (Date.now() - execStart > ROLLING_RECONCILE_TIME_LIMIT_MS) { stoppedEarly = true; break; }
    const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const dayLabel = Utilities.formatDate(day, Session.getScriptTimeZone(), 'yyyy-MM-dd');
    try {
      runSyncForDate(ss, day); // safely replaces just this day, wherever it sits — no clearing
      processed++;
      lastCompleted = dayLabel;
    } catch (err) {
      Logger.log(`Rolling reconcile FAILED on ${dayLabel}: ${err}`);
      failed++;
    }
    Utilities.sleep(1000);
  }

  let summary;
  if (stoppedEarly && lastCompleted) {
    props.setProperty(ROLLING_RECONCILE_KEY, JSON.stringify({ start: startDateStr, end: endDateStr, completedThrough: lastCompleted }));
    ScriptApp.getProjectTriggers().forEach(t => { if (t.getHandlerFunction() === 'continueRollingReconcileTrigger') ScriptApp.deleteTrigger(t); });
    ScriptApp.newTrigger('continueRollingReconcileTrigger').timeBased().after(90 * 1000).create();
    summary = `Rolling reconcile paused after ${lastCompleted} (${processed} refreshed this run) — auto-continuing in ~90 seconds.`;
  } else {
    props.deleteProperty(ROLLING_RECONCILE_KEY);
    summary = `Rolling reconcile complete: refreshed ${startDateStr} to ${endDateStr} (${processed} day(s)` + (failed ? `, ${failed} failed` : '') + ').';
  }
  Logger.log(summary);
  ss.toast(summary, stoppedEarly ? 'Reconciling ⏳' : 'Reconcile done ✅', 8);
  return summary;
}

function continueRollingReconcileTrigger() {
  const props = PropertiesService.getScriptProperties();
  const saved = props.getProperty(ROLLING_RECONCILE_KEY);
  if (!saved) return;
  const progress = JSON.parse(saved);
  rollingReconcileRange(progress.start, progress.end);
}

// Manual trigger — refreshes the last N days right now.
function rollingReconcileNow() {
  const DAYS_BACK = 14; // how far back to refresh each time — adjust as needed
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1); // yesterday
  const start = new Date(end.getFullYear(), end.getMonth(), end.getDate() - DAYS_BACK + 1);
  const startStr = Utilities.formatDate(start, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  const endStr = Utilities.formatDate(end, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  const summary = rollingReconcileRange(startStr, endStr);
  SpreadsheetApp.getUi().alert('Rolling reconcile', summary, SpreadsheetApp.getUi().ButtonSet.OK);
}

// Sets up an automatic weekly reconcile (e.g. every Sunday) so recent
// history stays fresh without anyone remembering to run it manually.
function setupRollingReconcileTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'rollingReconcileNow') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('rollingReconcileNow')
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.SUNDAY)
    .atHour(3)
    .create();
  SpreadsheetApp.getUi().alert('Auto-reconcile enabled',
    'The last 14 days will now automatically refresh every Sunday at 3 AM.', SpreadsheetApp.getUi().ButtonSet.OK);
}

// Core sync logic for ONE date, extracted so both dailySync (yesterday)
// and backfillMonth (any date range) can call the identical code path.
function runSyncForDate(ss, target) {
  const tabs = ensureMonthTabs(ss, target);
  const masterTab = ensureMasterTab(ss);
  const counselors = getActiveCounselors(); // live list, no hardcoding

  const includeCols = ['ProspectID','FirstName', CONFIG.OWNER_FIELD,
    CONFIG.LEAD_SOURCE_FIELD, CONFIG.PROGRAM_FIELD, 'CreatedOn', 'ModifiedOn'].join(',');

  // Pull all leads CREATED yesterday (covers "New Today" / Created On columns)
  // NOTE: LeadSquared's API works in UTC. `target` is local (IST) midnight —
  // Utilities.formatDate with 'Etc/UTC' converts that exact instant to its
  // correct UTC wall-clock string, which is what the API's LookupValue needs.
  // (Sending local-time digits labeled as UTC — the old bug — shifts every
  // query by your UTC offset, e.g. 5:30 for IST, causing under/overcounts.)
  //
  // Day window: 12:01:00 AM through 11:59:59 PM the same calendar day
  // (only the start shifts by a minute — the end stays at true midnight,
  // i.e. the window does not spill into the next calendar day).
  const DAY_START_OFFSET_MS = 60 * 1000; // 1 minute
  const queryStart = new Date(target.getTime() + DAY_START_OFFSET_MS); // 12:01:00 AM
  const nextDayStart = new Date(target.getTime() + 86400000); // next day's true midnight (i.e. up through 11:59:59 PM)
  const lowerBoundUtc = Utilities.formatDate(queryStart, 'Etc/UTC', 'yyyy-MM-dd HH:mm:ss');

  const createdLeadsRaw = lsqSearchAllPages('CreatedOn', lowerBoundUtc, '>=', includeCols);
  const createdLeads = createdLeadsRaw.filter(l => parseUtcTimestamp(l.CreatedOn) < nextDayStart);

  // Pull all leads MODIFIED yesterday (covers Modified On / Stage Wise columns)
  const modifiedLeadsRaw = lsqSearchAllPages('ModifiedOn', lowerBoundUtc, '>=', includeCols);
  const modifiedLeads = modifiedLeadsRaw.filter(l => parseUtcTimestamp(l.ModifiedOn) < nextDayStart);

  // Enrich modified leads with their Opportunity stage + status — batched
  // in parallel (was: one sequential 220ms-paced call per lead, a major
  // contributor to slow/timed-out syncs as lead volume grew).
  const modifiedOppResults = getOpportunityStagesBatch(modifiedLeads.map(l => l.ProspectID));
  modifiedLeads.forEach(lead => {
    const opp = modifiedOppResults[lead.ProspectID];
    lead.OpportunityStage = opp ? opp.stage : null;
    lead.OpportunityStatus = opp ? opp.status : null;
    lead.EnrolledDate = opp ? opp.enrolledDate : null;
  });

  // Stage/status lookup keyed by ProspectID, for Stage Wise (which is based
  // on CREATED leads, not modified ones, so its totals reconcile with
  // "Created On_Day wise"). Most just-created leads already appear in
  // modifiedLeads above (creation itself sets ModifiedOn); only the
  // non-overlapping ones need their own batch call.
  const oppLookup = {};
  modifiedLeads.forEach(l => {
    oppLookup[l.ProspectID] = { stage: l.OpportunityStage, status: l.OpportunityStatus };
  });
  const createdOnlyLeadIds = createdLeads
    .map(l => l.ProspectID)
    .filter(id => !oppLookup[id]);
  if (createdOnlyLeadIds.length) {
    const createdOppResults = getOpportunityStagesBatch(createdOnlyLeadIds);
    createdOnlyLeadIds.forEach(id => {
      const opp = createdOppResults[id];
      oppLookup[id] = { stage: opp ? opp.stage : null, status: opp ? opp.status : null };
    });
  }

  const overdueByCounselor = {};
  const createdByCounselorForPivot = {}; // for Source/Course Wise day-block builders
  const leadFunnelRows = [], stageWiseRows = [], reportsRows = [], masterRows = [];
  // Running totals for each tab's Total row (index-aligned with the numeric columns)
  const stageWiseTotals = new Array(CONFIG.STAGES.length).fill(0); // just the 15 stage sums
  let stageNotModifiedTotal = 0, stageGrandTotal = 0;
  let lfTotals = { created: 0, modified: 0, overdues: 0, task: 0, noTask: 0 };
  let rptTotals = { newToday: 0, lostToday: 0, nrToday: 0, enrolledToday: 0 };

  // TRUE enrolled counts for this day, one call for ALL counselors — queries
  // the Opportunity directly by Enrolled Date, so it correctly catches leads
  // created any time that enrolled specifically on this day (confirmed
  // against LeadSquared's own UI: Anuj Thakur matched exactly, 10 vs 10).
  const enrolledOppsToday = searchOpportunitiesByEnrolledDate(queryStart, nextDayStart);
  const enrolledCountByOwnerId = {};
  enrolledOppsToday.forEach(o => {
    enrolledCountByOwnerId[o.Owner] = (enrolledCountByOwnerId[o.Owner] || 0) + 1;
  });

  // Overdue task counts for ALL counselors, batched in parallel (was:
  // one sequential 220ms-paced call per counselor).
  const overdueByCounselorId = getOverdueTaskCountsBatch(counselors.map(c => c.id));

  // Task/Overdue/No-Task metrics for ALL of today's created leads (across
  // every counselor), batched in parallel — this was the single biggest
  // contributor to slow syncs, since it used to run once per lead, per
  // counselor, sequentially.
  const allCreatedLeadIds = createdLeads.map(l => l.ProspectID);
  const tasksByLeadId = allCreatedLeadIds.length ? getTasksForLeadsBatch(allCreatedLeadIds) : {};

  counselors.forEach(({ name: counselor, id: counselorId }) => {
    const createdForCounselor = createdLeads.filter(l => l[CONFIG.OWNER_FIELD] === counselor);
    const modifiedForCounselor = modifiedLeads.filter(l => l[CONFIG.OWNER_FIELD] === counselor);
    createdByCounselorForPivot[counselor] = createdForCounselor;

    // Overdue tasks: live snapshot as of this sync run (not a daily delta).
    // Used for Final Count's Overdues_Monthly/Total (a "current state" metric).
    const overdue = overdueByCounselorId[counselorId] || { total: 0, thisMonth: 0, totalPending: 0 };
    overdueByCounselor[counselor] = overdue;

    // Day-wise task metrics: ONLY for leads created today, tied to THIS
    // day's row — different from the live snapshot above. Used for Lead
    // Funnel's Task / Overdues / No Task columns.
    const dayTasks = computeDayWiseTaskMetricsFromMap(createdForCounselor, tasksByLeadId);

    // --- Lead Funnel row ---
    const modifiedPct = createdForCounselor.length
      ? (modifiedForCounselor.length / createdForCounselor.length * 100).toFixed(1)
      : 0;
    const dayOverduePct = dayTasks.totalTasks
      ? (dayTasks.overdueTasks / dayTasks.totalTasks * 100).toFixed(1) : 0;
    const noTaskPct = createdForCounselor.length
      ? (dayTasks.noTaskLeads / createdForCounselor.length * 100).toFixed(1) : 0;
    leadFunnelRows.push([
      target, counselor, createdForCounselor.length, '', // C Created Day wise, D Created Monthly (formula)
      modifiedForCounselor.length, '', '', // E Modified Daily, F Modified Monthly (formula), G Modified %_Monthly (formula)
      dayTasks.overdueTasks, dayTasks.totalTasks, dayOverduePct, // H Overdues, I Task, J Overdues %
      dayTasks.noTaskLeads, noTaskPct, // K No Task, L No Task %
    ]);
    lfTotals.created += createdForCounselor.length;
    lfTotals.modified += modifiedForCounselor.length;
    lfTotals.overdues += dayTasks.overdueTasks;
    lfTotals.task += dayTasks.totalTasks;
    lfTotals.noTask += dayTasks.noTaskLeads;

    // --- Stage Wise row ---
    // Based on CREATED leads (not modified), so sum(stages) + Not Modified
    // always equals Created On_Day wise for this counselor/day.
    const stageCounts = CONFIG.STAGES.map(stage =>
      createdForCounselor.filter(l => (oppLookup[l.ProspectID] || {}).stage === stage).length
    );
    const notModified = createdForCounselor.filter(
      l => !(oppLookup[l.ProspectID] || {}).stage
    ).length;
    const total = stageCounts.reduce((a, b) => a + b, 0) + notModified;
    const disqualifiedIdx = CONFIG.STAGES.indexOf('Disqualified');
    const enrolledIdx = CONFIG.STAGES.indexOf('Enrolled');
    const disqualifiedPct = total ? (stageCounts[disqualifiedIdx] / total * 100).toFixed(1) : 0;
    const enrolledPct = total ? (stageCounts[enrolledIdx] / total * 100).toFixed(1) : 0;
    stageWiseRows.push([target, counselor, ...stageCounts, notModified, '', total, disqualifiedPct, enrolledPct]);
    stageCounts.forEach((c, i) => stageWiseTotals[i] += c);
    stageNotModifiedTotal += notModified;
    stageGrandTotal += total;

    // --- Reports row ---
    // "Today" columns: computed directly from yesterday's pulled data
    // (the row we're writing represents "target" date = LeadSquared's "yesterday").
    const lostToday = modifiedForCounselor.filter(l => l.OpportunityStatus === 'Lost').length;
    const nrToday = modifiedForCounselor.filter(l => l.OpportunityStage === 'Not Reachable').length;
    // Enrolled Today: from the direct Opportunity search above (by real
    // Enrolled Date), keyed by owner GUID — NOT inferred from "modified
    // today," which misses leads touched again on a later day.
    const enrolledToday = enrolledCountByOwnerId[counselorId] || 0;
    const lostTodayPct = modifiedForCounselor.length
      ? (lostToday / modifiedForCounselor.length * 100).toFixed(1) : 0;
    const nrTodayPct = modifiedForCounselor.length
      ? (nrToday / modifiedForCounselor.length * 100).toFixed(1) : 0;
    reportsRows.push([
      target, counselor, createdForCounselor.length, // A Date, B Counselor, C New Today
      '', '', '', // D Total Yesterday, E Lost Yesterday, F Lost Yesterday % (formulas)
      lostToday, lostTodayPct, // G Lost Today, H Lost Today %
      '', '', // I NR Yesterday, J NR Yesterday % (formula)
      nrToday, nrTodayPct, // K NR Today, L NR Today %
      '', '', '', '', '', // M-Q: Total/Lost/Lost%/NR/NR% This Month (formulas)
      enrolledToday, '', // R Enrolled Today, S Enrolled This Month (formula)
    ]);
    rptTotals.newToday += createdForCounselor.length;
    rptTotals.lostToday += lostToday;
    rptTotals.nrToday += nrToday;
    rptTotals.enrolledToday += enrolledToday;

    // --- Master Data row (for Looker Studio / any BI tool) ---
    // Uses the LIVE overdue snapshot (`overdue`), consistent with Final Count.
    const liveOverduePct = overdue.totalPending
      ? (overdue.total / overdue.totalPending * 100).toFixed(1) : 0;
    masterRows.push([
      target, counselor, createdForCounselor.length, modifiedForCounselor.length, modifiedPct,
      overdue.total, liveOverduePct, ...stageCounts, total,
      lostToday, lostTodayPct, nrToday, nrTodayPct,
    ]);
  });

  // --- Insert each tab's day-block at the TOP (newest-first ordering) ---
  const lfStart = insertDayBlock(tabs.leadFunnel, leadFunnelRows,
    ['', 'Total', lfTotals.created, '', lfTotals.modified, '', '', lfTotals.overdues, lfTotals.task, '', lfTotals.noTask, ''], target);
  const swDisqPct = stageGrandTotal
    ? (stageWiseTotals[CONFIG.STAGES.indexOf('Disqualified')] / stageGrandTotal * 100).toFixed(1) : 0;
  const swEnrolledPct = stageGrandTotal
    ? (stageWiseTotals[CONFIG.STAGES.indexOf('Enrolled')] / stageGrandTotal * 100).toFixed(1) : 0;
  insertDayBlock(tabs.stageWise, stageWiseRows,
    ['', 'Total', ...stageWiseTotals, stageNotModifiedTotal, '', stageGrandTotal, swDisqPct, swEnrolledPct], target);
  const rptStart = insertDayBlock(tabs.reports, reportsRows,
    ['', 'Total', rptTotals.newToday, '', '', '', rptTotals.lostToday, '', '', '', rptTotals.nrToday, '', '', '', '', '', '', rptTotals.enrolledToday, ''], target);
  insertDayBlock(masterTab, masterRows, null, target); // no Total row requested for Master Data

  writePivotDayBlock(tabs.sourceWise, target, createdByCounselorForPivot, CONFIG.LEAD_SOURCE_FIELD);
  writePivotDayBlock(tabs.courseWise, target, createdByCounselorForPivot, CONFIG.PROGRAM_FIELD);

  // Formulas that reference each row's own date — order-independent, so
  // they stay correct regardless of newest-first insertion or backfill order.
  if (lfStart) fillLeadFunnelMonthlyFormulas(tabs.leadFunnel, target, lfStart, leadFunnelRows.length);
  if (rptStart) fillReportsRollupFormulas(tabs.reports, target, rptStart, reportsRows.length);

  // --- Final Count: roll-up formulas + overdue snapshot + Referral/Direct Walk In ---
  refreshFinalCount(ss, target, counselors, overdueByCounselor, tabs.sourceWise);

  // --- Source Wise Enrolment ---
  refreshSourceEnrollmentTab(tabs.sourceEnrollment, target, counselors, tabs.sourceWise);
}


// ========================= BACKFILL ==============================
// Wipes existing rows for the given month's 4 tabs (keeps headers), so
// re-running backfill doesn't create duplicates.
function clearMonthDataRows(ss, date) {
  const names = getMonthTabNames(date);
  Object.values(names).forEach(name => {
    const sheet = ss.getSheetByName(name);
    if (sheet && sheet.getLastRow() > 2) {
      sheet.getRange(3, 1, sheet.getLastRow() - 2, sheet.getLastColumn()).clearContent();
    }
  });
}

// Master Data is one continuous table across all months, so it can't be
// wiped wholesale like the per-month tabs — this removes only the rows
// falling within [start, end] before backfill rewrites them, leaving
// everything outside that range untouched.
function clearMasterRowsForRange(ss, start, end) {
  const sheet = ss.getSheetByName(MASTER_TAB_NAME);
  if (!sheet || sheet.getLastRow() < 2) return;
  const numRows = sheet.getLastRow() - 1;
  const range = sheet.getRange(2, 1, numRows, sheet.getLastColumn());
  const values = range.getValues();
  const kept = values.filter(row => {
    const d = new Date(row[0]);
    return !(d >= start && d <= end);
  });
  range.clearContent();
  if (kept.length) {
    sheet.getRange(2, 1, kept.length, kept[0].length).setValues(kept);
  }
}

// Clears month tabs for EVERY month touched by [start, end] — a range can
// span more than one month (e.g. backfilling Jul 25 - Aug 5), and each
// month's 4 tabs need clearing before that month's days are re-synced.
function clearMonthsInRange(ss, start, end) {
  let cursor = new Date(start.getFullYear(), start.getMonth(), 1);
  const endMonth = new Date(end.getFullYear(), end.getMonth(), 1);
  while (cursor <= endMonth) {
    clearMonthDataRows(ss, cursor);
    cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1);
  }
}

// Shows the "grab a chai" popup while a long-running sync is in progress.
// duration -1 keeps it visible until replaced by another toast call.
function showWaitToast(ss) {
  ss.toast('suno jara time lag raha he, chai pike aao aaram se 🍵', 'Syncing LeadSquared data...', -1);
}

// Core backfill logic, parameterized so both the manual editor function
// and the dialog UI can share it.
// - startDateStr: 'yyyy-MM-dd', required.
// - endDateStr: 'yyyy-MM-dd', optional — defaults to yesterday (same
//   boundary dailySync uses) if omitted.
// Returns a short summary string.
//
// RESUMABLE: Apps Script hard-kills any execution at 6 minutes, and older
// backfilled days take longer (more pages to scan through as the gap to
// "now" grows). Rather than lose completed work when that happens, this
// stops itself gracefully with a safety margin BEFORE the hard limit, saves
// how far it got, and picks up from there on the next run — it only clears
// existing rows and starts over when you request a genuinely different
// range than the one already in progress.
const BACKFILL_PROGRESS_KEY = 'BACKFILL_PROGRESS'; // stores {start, end, completedThrough}
const BACKFILL_TIME_LIMIT_MS = 5 * 60 * 1000; // stop with 1 min of buffer before Google's 6-min kill

function runBackfillRange(startDateStr, endDateStr) {
  const execStart = Date.now();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  showWaitToast(ss);

  const start = new Date(startDateStr + 'T00:00:00');
  const now = new Date();
  const end = endDateStr
    ? new Date(endDateStr + 'T00:00:00')
    : new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1); // default: yesterday
  const endLabel = Utilities.formatDate(end, Session.getScriptTimeZone(), 'yyyy-MM-dd');

  // Check for an in-progress backfill matching this exact range.
  const props = PropertiesService.getScriptProperties();
  const saved = props.getProperty(BACKFILL_PROGRESS_KEY);
  const savedProgress = saved ? JSON.parse(saved) : null;
  const isResuming = savedProgress && savedProgress.start === startDateStr && savedProgress.end === endLabel;

  let resumeFrom = start;
  if (isResuming) {
    resumeFrom = new Date(savedProgress.completedThrough + 'T00:00:00');
    resumeFrom.setDate(resumeFrom.getDate() + 1); // day AFTER the last completed one
    Logger.log(`Resuming backfill: ${startDateStr}-${endLabel} was previously interrupted after ${savedProgress.completedThrough}. Continuing from ${Utilities.formatDate(resumeFrom, Session.getScriptTimeZone(), 'yyyy-MM-dd')}.`);
  } else {
    Logger.log(`Backfilling ${startDateStr} through ${endLabel}...`);
    clearMonthsInRange(ss, start, end);
    clearMasterRowsForRange(ss, start, end);
  }

  let daysProcessed = 0, daysFailed = 0, stoppedEarly = false;
  let lastCompletedDay = null;
  for (let d = new Date(resumeFrom); d <= end; d.setDate(d.getDate() + 1)) {
    if (Date.now() - execStart > BACKFILL_TIME_LIMIT_MS) {
      stoppedEarly = true;
      break;
    }
    const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const dayLabel = Utilities.formatDate(day, Session.getScriptTimeZone(), 'yyyy-MM-dd');
    Logger.log(`--- Syncing ${dayLabel} ---`);
    try {
      runSyncForDate(ss, day);
      daysProcessed++;
      lastCompletedDay = dayLabel;
    } catch (err) {
      Logger.log(`FAILED on ${dayLabel}: ${err}`);
      daysFailed++;
    }
    // Cooldown between days — spreads load out to avoid bursting
    // LeadSquared's rate/quota limits over a long range.
    Utilities.sleep(1500);
  }

  let summary;
  if (stoppedEarly && lastCompletedDay) {
    props.setProperty(BACKFILL_PROGRESS_KEY, JSON.stringify({ start: startDateStr, end: endLabel, completedThrough: lastCompletedDay }));
    scheduleBackfillContinuation();
    summary = `Backfill paused (time limit) after completing through ${lastCompletedDay}. `
      + `${daysProcessed} day(s) synced this run. It will automatically continue in ~90 seconds — no action needed, check back shortly.`;
  } else {
    props.deleteProperty(BACKFILL_PROGRESS_KEY); // range fully finished — clear so next new range starts fresh
    clearScheduledBackfillContinuation(); // nothing left to auto-resume
    addDaySeparatorsToAllTabs(); // final safety pass — fixes any missing separators from mixed runs
    summary = `Backfill complete: ${startDateStr} to ${endLabel} — `
      + `${daysProcessed} day(s) synced` + (daysFailed ? `, ${daysFailed} FAILED (check View > Logs)` : '.');
  }
  Logger.log(summary);
  ss.toast(summary, stoppedEarly ? 'Paused ⏸️ (auto-resuming)' : 'Done ✅', 10);
  return summary;
}

// Schedules ONE-TIME auto-continuation (deletes any previous pending one
// first, so repeated pauses don't stack up multiple concurrent chains).
function scheduleBackfillContinuation() {
  clearScheduledBackfillContinuation();
  ScriptApp.newTrigger('continueBackfillTrigger').timeBased().after(90 * 1000).create();
}

function clearScheduledBackfillContinuation() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'continueBackfillTrigger') ScriptApp.deleteTrigger(t);
  });
}

// Fired by the auto-continuation trigger above — runs unattended (no menu,
// no dialog), picks up the saved progress, and keeps the chain going until
// the full range is done or it needs to pause again.
function continueBackfillTrigger() {
  const props = PropertiesService.getScriptProperties();
  const saved = props.getProperty(BACKFILL_PROGRESS_KEY);
  if (!saved) return; // nothing pending — already finished or was cleared
  const progress = JSON.parse(saved);
  runBackfillRange(progress.start, progress.end);
}

// Manual editor version — edit START_DATE and run directly from the Apps
// Script editor (no dialog). Always runs through yesterday.
function backfillMonth() {
  const START_DATE = '2026-08-01'; // yyyy-MM-dd — edit this to your desired start
  const summary = runBackfillRange(START_DATE, null);
  SpreadsheetApp.getUi().alert('Backfill complete', summary, SpreadsheetApp.getUi().ButtonSet.OK);
}

// ===================== BACKFILL DIALOG (MENU) =======================
// Shows a small popup with Start Date / End Date pickers, so anyone can
// backfill any range from the Sheet itself — no editor, no code edits.
function showBackfillDialog() {
  const html = HtmlService.createHtmlOutput(`
    <div style="font-family:Arial,sans-serif;font-size:13px;padding:4px;">
      <p style="margin-top:0;">Re-syncs LeadSquared data for the range you pick (fixes/rewrites those days using current logic).</p>
      <div style="margin-bottom:10px;">
        <label style="display:block;margin-bottom:4px;">Start date</label>
        <input type="date" id="startDate" style="width:100%;padding:6px;box-sizing:border-box;">
      </div>
      <div style="margin-bottom:14px;">
        <label style="display:block;margin-bottom:4px;">End date (leave blank for yesterday)</label>
        <input type="date" id="endDate" style="width:100%;padding:6px;box-sizing:border-box;">
      </div>
      <button onclick="run()" id="runBtn" style="padding:8px 16px;background:#1a73e8;color:#fff;border:none;border-radius:4px;cursor:pointer;">Run Backfill</button>
      <p id="status" style="margin-top:12px;color:#555;"></p>
    </div>
    <script>
      function run() {
        var start = document.getElementById('startDate').value;
        var end = document.getElementById('endDate').value;
        var status = document.getElementById('status');
        if (!start) { status.textContent = 'Please pick a start date.'; return; }
        document.getElementById('runBtn').disabled = true;
        status.textContent = 'suno jara time lag raha he, chai pike aao aaram se 🍵 (this window will update when done)';
        google.script.run
          .withSuccessHandler(function(msg) {
            status.textContent = msg;
            document.getElementById('runBtn').disabled = false;
          })
          .withFailureHandler(function(err) {
            status.textContent = 'Error: ' + err.message;
            document.getElementById('runBtn').disabled = false;
          })
          .runBackfillFromDialog(start, end || null);
      }
    </script>
  `).setWidth(360).setHeight(300);
  SpreadsheetApp.getUi().showModalDialog(html, 'Backfill LeadSquared Data');
}

// Called by the dialog above via google.script.run. Must be a top-level
// function so the client-side script can reach it.
function runBackfillFromDialog(startDateStr, endDateStr) {
  return runBackfillRange(startDateStr, endDateStr);
}

// Fills the Reports tab's "Yesterday" and "This Month" columns using
// formulas that look at this tab's own historical rows for each counselor.
// Formulas use full-column ranges + date comparisons (against the row's own
// date, or that date minus 1) rather than row-position ranges — this makes
// them correct regardless of physical row order, which matters now that
// rows are inserted newest-first rather than appended chronologically.
function fillReportsRollupFormulas(reportsSheet, target, startRow, numRows) {
  const monthStartStr = Utilities.formatDate(
    new Date(target.getFullYear(), target.getMonth(), 1), Session.getScriptTimeZone(), 'M/d/yyyy');

  for (let i = 0; i < numRows; i++) {
    const row = startRow + i;

    // Yesterday columns: match this counselor's row where Date = (this row's date - 1)
    reportsSheet.getRange(row, 4).setFormula(`=SUMIFS($C:$C,$B:$B,B${row},$A:$A,A${row}-1)`); // D Total Yesterday
    reportsSheet.getRange(row, 5).setFormula(`=SUMIFS($G:$G,$B:$B,B${row},$A:$A,A${row}-1)`); // E Lost Yesterday
    reportsSheet.getRange(row, 6).setFormula(`=IF(D${row}=0,0,ROUND(E${row}/D${row}*100,1))`); // F Lost Yesterday % = Lost Yesterday / Total Yesterday
    reportsSheet.getRange(row, 9).setFormula(`=SUMIFS($K:$K,$B:$B,B${row},$A:$A,A${row}-1)`); // I NR Yesterday (K = NR Today)
    reportsSheet.getRange(row, 10).setFormula(`=IF(D${row}=0,0,ROUND(I${row}/D${row}*100,1))`); // J NR Yesterday % = NR Yesterday / Total Yesterday

    // This Month totals: this counselor's rows from the 1st of the month
    // through this row's own date (order-independent).
    reportsSheet.getRange(row, 13).setFormula(
      `=SUMIFS($C:$C,$B:$B,B${row},$A:$A,">="&"${monthStartStr}",$A:$A,"<="&A${row})`); // M Total This Month
    reportsSheet.getRange(row, 14).setFormula(
      `=SUMIFS($G:$G,$B:$B,B${row},$A:$A,">="&"${monthStartStr}",$A:$A,"<="&A${row})`); // N Lost This Month
    reportsSheet.getRange(row, 15).setFormula(`=IF(M${row}=0,0,ROUND(N${row}/M${row}*100,1))`); // O Lost This Month % = Lost This Month / Total This Month
    reportsSheet.getRange(row, 16).setFormula(
      `=SUMIFS($K:$K,$B:$B,B${row},$A:$A,">="&"${monthStartStr}",$A:$A,"<="&A${row})`); // P NR This Month
    reportsSheet.getRange(row, 17).setFormula(`=IF(M${row}=0,0,ROUND(P${row}/M${row}*100,1))`); // Q NR This Month % = NR This Month / Total This Month
    reportsSheet.getRange(row, 19).setFormula(
      `=SUMIFS($R:$R,$B:$B,B${row},$A:$A,">="&"${monthStartStr}",$A:$A,"<="&A${row})`); // S Enrolled This Month (R = Enrolled Today)
  }
}

// Fills Lead Funnel's cumulative monthly columns: Created On (Monthly) and
// Modified On (Monthly) are running totals from the 1st of the month
// through this row's own date; Modified %_Monthly divides those two.
function fillLeadFunnelMonthlyFormulas(sheet, target, startRow, numRows) {
  const monthStartStr = Utilities.formatDate(
    new Date(target.getFullYear(), target.getMonth(), 1), Session.getScriptTimeZone(), 'M/d/yyyy');

  for (let i = 0; i < numRows; i++) {
    const row = startRow + i;
    sheet.getRange(row, 4).setFormula( // D: Created On (Monthly)
      `=SUMIFS($C:$C,$B:$B,B${row},$A:$A,">="&"${monthStartStr}",$A:$A,"<="&A${row})`);
    sheet.getRange(row, 6).setFormula( // F: Modified On (Monthly)
      `=SUMIFS($E:$E,$B:$B,B${row},$A:$A,">="&"${monthStartStr}",$A:$A,"<="&A${row})`);
    sheet.getRange(row, 7).setFormula( // G: Modified %_Monthly = Modified Monthly / Created Monthly
      `=IF(D${row}=0,0,ROUND(F${row}/D${row}*100,1))`);
  }
}

function refreshFinalCount(ss, date, counselors, overdueByCounselor, sourceWiseSheet) {
  const names = getMonthTabNames(date);
  const finalSheet = ss.getSheetByName(names.finalCount);
  const monthStartStr = Utilities.formatDate(
    new Date(date.getFullYear(), date.getMonth(), 1), Session.getScriptTimeZone(), 'M/d/yyyy');
  const sourceWiseName = sourceWiseSheet.getName();
  const referralCol = findPivotColumnByHeader(sourceWiseSheet, 'Referrals');
  const directWalkInCol = findPivotColumnByHeader(sourceWiseSheet, 'Direct Walk In');

  finalSheet.getRange(3, 1, counselors.length, 1)
    .setValues(counselors.map(() => ['']));
  counselors.forEach(({ name: counselor }, i) => {
    const row = i + 3; // row 3 onward, matches your template
    const overdue = overdueByCounselor[counselor] || { total: 0, thisMonth: 0 };
    finalSheet.getRange(row, 2).setValue(counselor);
    finalSheet.getRange(row, 3).setFormula(
      `=SUMIF('${names.leadFunnel}'!B:B,B${row},'${names.leadFunnel}'!C:C)`); // Created On
    finalSheet.getRange(row, 4).setFormula(
      `=SUMIF('${names.leadFunnel}'!B:B,B${row},'${names.leadFunnel}'!E:E)`); // Modified On
    finalSheet.getRange(row, 5).setValue(overdue.thisMonth); // Overdues_Monthly (live snapshot)
    finalSheet.getRange(row, 6).setValue(overdue.total);     // Overdues_Total (live snapshot)
    finalSheet.getRange(row, 7).setFormula( // No Task_Monthly: this month's No Task total from Lead Funnel (col K)
      `=SUMIFS('${names.leadFunnel}'!K:K,'${names.leadFunnel}'!B:B,B${row},'${names.leadFunnel}'!A:A,">="&"${monthStartStr}")`);
    finalSheet.getRange(row, 8).setFormula( // No Task_Total: all-time No Task total from Lead Funnel (col K)
      `=SUMIF('${names.leadFunnel}'!B:B,B${row},'${names.leadFunnel}'!K:K)`);
    finalSheet.getRange(row, 9).setFormula(
      `=SUMIF('${names.reports}'!B:B,B${row},'${names.reports}'!R:R)`);   // Enrolled — sum of true daily enrollments (Enrolled Date field), NOT Stage Wise's creation-date-based snapshot
    finalSheet.getRange(row, 10).setFormula(`=IF(C${row}=0,0,ROUND(I${row}/C${row}*100,1))`); // Conversion % = Enrolled / Created On
    if (referralCol) {
      const letter = getColumnLetter(referralCol);
      finalSheet.getRange(row, 11).setFormula(`=SUMIF('${sourceWiseName}'!B:B,B${row},'${sourceWiseName}'!${letter}:${letter})`);
    } else {
      finalSheet.getRange(row, 11).setValue(0); // no Referral leads yet this month
    }
    if (directWalkInCol) {
      const letter = getColumnLetter(directWalkInCol);
      finalSheet.getRange(row, 12).setFormula(`=SUMIF('${sourceWiseName}'!B:B,B${row},'${sourceWiseName}'!${letter}:${letter})`);
    } else {
      finalSheet.getRange(row, 12).setValue(0); // no Direct Walk In leads yet this month
    }
  });
}

// ===================== NEW TABS: MONTHLY SOURCE ROLLUPS + SOURCE ENROLMENT ====

// Converts a 1-based column number to its letter (1->A, 27->AA, etc.) —
// needed because Source Wise's columns grow dynamically, so we can't
// hardcode which letter holds "Referrals" or "Direct Walk In".
function getColumnLetter(colNum) {
  let letter = '';
  while (colNum > 0) {
    const rem = (colNum - 1) % 26;
    letter = String.fromCharCode(65 + rem) + letter;
    colNum = Math.floor((colNum - 1) / 26);
  }
  return letter;
}

// Finds which column in a pivot tab (Source/Course Wise) currently holds a
// given header, case-insensitively. Returns null if that value hasn't
// appeared yet this month (e.g. no Referral leads logged so far).
function findPivotColumnByHeader(sheet, headerText) {
  const headers = getPivotColumnHeaders(sheet);
  const lower = headerText.toLowerCase();
  for (let i = 0; i < headers.length; i++) {
    if (String(headers[i]).toLowerCase() === lower) return 3 + i;
  }
  return null;
}

// Refreshes Monthly Referral / Monthly Direct Walk ins: one row per
// counselor, a live running total of that ONE source's Created count for
// the month, pulled from Source Wise via formula.
function refreshMonthlySourceRollup(targetSheet, sourceWiseSheet, sourceName, counselors) {
  targetSheet.getRange(3, 1, counselors.length, 1).setValues(counselors.map(() => ['']));
  const col = findPivotColumnByHeader(sourceWiseSheet, sourceName);
  const sourceWiseName = sourceWiseSheet.getName();
  counselors.forEach(({ name: counselor }, i) => {
    const row = i + 3;
    targetSheet.getRange(row, 2).setValue(counselor);
    if (col) {
      const colLetter = getColumnLetter(col);
      targetSheet.getRange(row, 3).setFormula(
        `=SUMIF('${sourceWiseName}'!B:B,B${row},'${sourceWiseName}'!${colLetter}:${colLetter})`);
    } else {
      targetSheet.getRange(row, 3).setValue(0); // no leads from this source yet this month
    }
  });
}

// Refreshes "Source Wise Enrolment_[Month]": rows = counselor, and for
// EVERY source seen this month, two columns — "{Source} Enrolled" and
// "{Source} Conversion %". Enrolled counts come from a month-wide direct
// query by Enrolled Date (same accurate method as Reports' Enrolled Today,
// just for the whole month at once); Created counts come from Source Wise.
function refreshSourceEnrollmentTab(sheet, date, counselors, sourceWiseSheet) {
  const monthStart = new Date(date.getFullYear(), date.getMonth(), 1);
  const monthEnd = new Date(date.getFullYear(), date.getMonth() + 1, 1);
  const enrolledOpps = searchOpportunitiesByEnrolledDate(monthStart, monthEnd);

  const idToName = {};
  counselors.forEach(c => { idToName[c.id] = c.name; });

  // P_Source on the Opportunity search comes back null (confirmed via
  // diagnostic) even though requested — so look up each enrolled lead's
  // Source directly instead, via RelatedProspectId (reliably present).
  const leadIds = [...new Set(enrolledOpps.map(o => o.RelatedProspectId).filter(Boolean))];
  const sourceByLeadId = leadIds.length ? getLeadSourcesBatch(leadIds) : {};

  // enrolledCounts[counselorName][sourceName] = count
  const enrolledCounts = {};
  enrolledOpps.forEach(o => {
    const counselor = idToName[o.Owner];
    if (!counselor) return; // owner not currently tracked — excluded by design
    const source = (sourceByLeadId[o.RelatedProspectId] || '(Blank)').toString().trim() || '(Blank)';
    enrolledCounts[counselor] = enrolledCounts[counselor] || {};
    enrolledCounts[counselor][source] = (enrolledCounts[counselor][source] || 0) + 1;
  });

  // Column set = whatever sources exist in Source Wise this month, so it
  // always matches what's actually being tracked.
  const sources = getPivotColumnHeaders(sourceWiseSheet);
  const headers = ['Date', 'Counselor Name'];
  sources.forEach(s => headers.push(`${s} Enrolled`, `${s} Conversion %`));

  // Rebuild header row (row 2) and data rows fresh each time, since the
  // source list can grow month to month.
  sheet.getRange(2, 1, 1, Math.max(sheet.getLastColumn(), headers.length)).clearContent();
  sheet.getRange(2, 1, 1, headers.length).setValues([headers]);

  const sourceWiseName = sourceWiseSheet.getName();
  const dataRows = counselors.map(({ name: counselor }) => {
    const row = [date, counselor];
    sources.forEach(source => {
      const enrolled = (enrolledCounts[counselor] && enrolledCounts[counselor][source]) || 0;
      row.push(enrolled, ''); // Conversion % filled via formula below, after rows are written
    });
    return row;
  });

  if (sheet.getLastRow() > 2) sheet.getRange(3, 1, sheet.getLastRow() - 2, sheet.getLastColumn()).clearContent();
  if (dataRows.length) sheet.getRange(3, 1, dataRows.length, headers.length).setValues(dataRows);

  // Conversion % per source = that source's Enrolled (just written) ÷ that
  // source's Created-this-month (from Source Wise, via formula).
  sources.forEach((source, sIdx) => {
    const enrolledCol = 3 + sIdx * 2;
    const pctCol = enrolledCol + 1;
    const enrolledLetter = getColumnLetter(enrolledCol);
    const sourceWiseCol = findPivotColumnByHeader(sourceWiseSheet, source);
    counselors.forEach((_, i) => {
      const row = i + 3;
      if (sourceWiseCol) {
        const swLetter = getColumnLetter(sourceWiseCol);
        const createdFormula = `SUMIF('${sourceWiseName}'!B:B,B${row},'${sourceWiseName}'!${swLetter}:${swLetter})`;
        sheet.getRange(row, pctCol).setFormula(
          `=IF(${createdFormula}=0,0,ROUND(${enrolledLetter}${row}/(${createdFormula})*100,1))`);
      } else {
        sheet.getRange(row, pctCol).setValue(0);
      }
    });
  });

  setTabTitle(sheet);
  applySheetFormatting(sheet, 2);
}

// ========================= CUSTOM MENU ============================
// Adds an "LSQ Sync" menu to the Sheet's top nav, so anyone can run these
// without opening the Apps Script editor. Runs automatically whenever the
// Sheet is opened (this is a "simple trigger" — no setup needed).
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('LSQ Sync')
    .addItem('Run sync for yesterday', 'dailySyncUi')
    .addItem('Sync today (live, partial day)', 'syncTodayUi')
    .addItem('Resync one day...', 'showResyncOneDayDialog')
    .addItem('Reconcile last 14 days now', 'rollingReconcileNow')
    .addItem('Backfill a date range...', 'showBackfillDialog')
    .addSeparator()
    .addItem('Turn on daily auto-sync (7 AM)', 'setupDailyTrigger')
    .addItem('Turn on live today-sync (hourly)', 'setupTodayTrigger')
    .addItem('Turn on auto-reconcile (weekly)', 'setupRollingReconcileTrigger')
    .addSeparator()
    .addItem('Show active counselor list', 'logActiveCounselorsUi')
    .addItem('Run diagnostics', 'testFieldNames')
    .addSeparator()
    .addItem('Format all tabs now', 'formatAllTabsNow')
    .addItem('Reconcile enrollments (last 45 days)', 'reconcileEnrollments')
    .addItem('Fix day-separator rows now', 'addDaySeparatorsNow')
    .addItem('Merge duplicate case-variant columns', 'mergeDuplicateColumnsAllTabs')
    .addToUi();
}

// Menu-only wrapper around dailySync(). dailySync() itself stays free of any
// getUi() calls, because it also runs from the unattended time-based trigger
// — which has no UI context and would throw if it tried to show an alert.
function dailySyncUi() {
  showWaitToast(SpreadsheetApp.getActiveSpreadsheet());
  dailySync();
  SpreadsheetApp.getUi().alert('Sync complete', 'Yesterday\'s data has been synced.', SpreadsheetApp.getUi().ButtonSet.OK);
}

// Menu-only wrapper around syncToday() — same UI-free-core pattern, since
// this also runs from the optional hourly trigger.
function syncTodayUi() {
  showWaitToast(SpreadsheetApp.getActiveSpreadsheet());
  syncToday();
  SpreadsheetApp.getUi().alert('Sync complete', "Today's data has been synced (partial day so far — numbers will keep growing as the day goes on).", SpreadsheetApp.getUi().ButtonSet.OK);
}

// UI-friendly version of logActiveCounselors: shows the count/list in an
// alert box instead of the Apps Script log, since menu users won't have
// the Logs panel open.
function logActiveCounselorsUi() {
  const list = getActiveCounselors();
  const msg = `${list.length} counselors will be counted:\n\n` + list.map(c => c.name).join('\n');
  SpreadsheetApp.getUi().alert('Active Counselors', msg, SpreadsheetApp.getUi().ButtonSet.OK);
}

// ========================= TRIGGER SETUP =========================
function setupDailyTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'dailySync') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('dailySync')
    .timeBased()
    .everyDays(1)
    .atHour(7)
    .create();
}

// Optional: keeps "today" refreshed throughout the day (every hour), on
// top of the once-daily 7 AM run that finalizes "yesterday". Each run
// replaces today's block rather than duplicating it (see
// insertDayBlock's dedup logic), so this is safe to leave running.
function setupTodayTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'syncToday') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('syncToday')
    .timeBased()
    .everyHours(1)
    .create();
  SpreadsheetApp.getUi().alert('Live sync enabled', "Today's data will now refresh automatically every hour.", SpreadsheetApp.getUi().ButtonSet.OK);
}