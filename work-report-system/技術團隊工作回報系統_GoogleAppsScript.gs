/*****************************************************************
 * 程優教育科技 ｜ 克雷斯技術團隊工作回報系統（Google 一鍵建置）
 * ---------------------------------------------------------------
 * 這段程式會自動幫你建立一份 Google 試算表當後台資料庫，內含：
 *   設定_人員對照（花名冊/PIN/GitHub對照）
 *   每日回報（團隊成員逐筆送出的任務級回報，append-only）
 *   每日查核（CEO 手動標記某人某天「查核未通過」等）
 *   GitHub活動快取（選用：自動比對 commit/PR，佐證真實性）
 *   每日分數彙總（誠信分數、產能分數、象限、旗標，供 dashboard 顯示）
 *   系統連結
 *
 * 使用方式（約 3 分鐘＋部署 Web App 一次）：
 *   1. 打開 https://script.google.com → 新增專案
 *   2. 把本檔全部內容貼上、取代預設程式碼 → 存檔（Ctrl/Cmd+S）
 *   3. 上方函式選單選「buildSystem」→ 按「執行 ▶」→ 授權
 *   4. 執行完成後點「執行紀錄 / Logs」看到試算表網址
 *   5.【必做】部署為 Web App：右上「部署 → 新增部署作業 → 網頁應用程式」
 *      執行身份選「我」、存取權限選「任何人」→ 複製 .../exec 網址
 *      貼進 report.html 與 dashboard.html 開頭的 API_URL
 *   6.（選用）執行 setAdminKey("你的密鑰")，並把同一組字串貼進
 *      dashboard.html 的 ADMIN_KEY，才能使用「標記查核」功能
 *   7.（選用）執行 setGithubToken("你的GitHub PAT")，並在「設定_人員
 *      對照」填妥成員的 GitHub帳號／監控Repo，啟用自動比對真實性
 *
 * 機密提醒：GitHub PAT、ADMIN_KEY 一律存在 PropertiesService（指令碼
 * 屬性），絕不寫進任何 Sheet 儲存格或 HTML 檔，避免試算表「發布到
 * 網路」或原始碼外流時外洩。
 *****************************************************************/

/* ===== 分頁名稱 ===== */
var SS_NAME = '程優｜克雷斯技術團隊工作回報系統（後台）';
var SHEETS = {
  ROSTER:  '設定_人員對照',
  REPORTS: '每日回報',
  AUDIT:   '每日查核',
  GITHUB:  'GitHub活動快取',
  SCORES:  '每日分數彙總',
  LINKS:   '系統連結'
};

/* ===== 可調參數（門檻/權重都是預設值，之後可依實際資料分佈調整）===== */
var QUADRANT_THRESHOLD = 70;           // 誠信/產能 高低分界線，沿用主管人才評比系統已用的門檻
var EXPECTED_POINTS_PER_DAY = 1.5;     // 每人每工作日預期「加權產出點數」，可被人員對照表個人化覆寫
var EXPECTED_HOURS_PER_POINT = 2;      // 1 個複雜度點的預期工時，用於工時效率常態化
var DUPLICATE_SIMILARITY_THRESHOLD = 0.85; // 任務描述重複判定門檻（2-gram Jaccard）
var MAX_ONTIME_BACKFILL_DAYS = 1;      // 補登超過幾天開始視為「補登」旗標
var ROLLING_WINDOW_DAYS = 7;           // 誠信/產能分數採「過去 N 天」滾動窗口，避免單日資料量太少造成分數暴衝
var MIN_DESC_LENGTH = 8;               // 任務描述低於此字數視為「內容過於簡略」，難以驗證真實性
var HOURS_VARIANCE_RATIO = 0.5;        // 實際工時與預估工時相對落差超過此比例，列入「工時落差大」旗標

var WEIGHTS_AUTH_NO_GH = { evidence: 0.40, timing: 0.30, duplicate: 0.20, audit: 0.10 };
var WEIGHTS_AUTH_GH    = { evidence: 0.25, timing: 0.20, duplicate: 0.15, github: 0.30, audit: 0.10 };
var WEIGHTS_PROD_NO_GH = { output: 0.35, completion: 0.30, ontime: 0.15, efficiency: 0.20 };
var WEIGHTS_PROD_GH    = { output: 0.25, completion: 0.20, ontime: 0.10, efficiency: 0.15, github: 0.30 };

/* ============== 一、一鍵建置 ============== */
function buildSystem() {
  var ss = SpreadsheetApp.create(SS_NAME);
  PropertiesService.getScriptProperties().setProperty('SS_ID', ss.getId());

  var roster = ss.insertSheet(SHEETS.ROSTER);
  roster.appendRow(['姓名', 'PIN(4碼)', '狀態(在職/停用)', 'GitHub帳號(選填)', '監控Repo(owner/repo,逗號分隔,選填)', '個人每日預期產出點數(選填)', '到職日', '備註']);
  styleHeader(roster, '#4a6fa5');
  roster.appendRow(['王小明', '1234', '在職', '', '', '', '', '範例列，請改成真實成員資料，或刪除此列']);
  roster.getRange('A2:H2').setBackground('#fff6d8');
  roster.setColumnWidths(1, 8, 130);

  var reports = ss.insertSheet(SHEETS.REPORTS);
  reports.appendRow(['時間戳記', '回報批次ID', '姓名', '回報日期', '專案/系統別', '任務描述', '複雜度自評(1-5)', '預估工時', '實際工時', '完成狀態', '原訂完成日', '證據連結', '無證據原因', '備註', '補登天數', '是否有效證據']);
  styleHeader(reports, '#4a6fa5');
  reports.setColumnWidths(1, 16, 130);

  var audit = ss.insertSheet(SHEETS.AUDIT);
  audit.appendRow(['姓名', '日期', '查核狀態(未查核/已查核通過/查核未通過)', '查核備註', '查核人', '查核時間']);
  styleHeader(audit, '#4a6fa5');
  audit.setColumnWidths(1, 6, 150);

  var github = ss.insertSheet(SHEETS.GITHUB);
  github.appendRow(['姓名', 'GitHub帳號', '日期', 'commit數', 'PR開啟數', 'PR合併數', '同步時間戳記']);
  styleHeader(github, '#4a6fa5');
  github.setColumnWidths(1, 7, 130);

  var scores = ss.insertSheet(SHEETS.SCORES);
  scores.appendRow(['日期', '姓名', '任務數', '已完成任務數', '完成率(%)', '加權產出量', '回報工時合計', '誠信分數', '產能分數', '象限', '旗標', '是否含GitHub佐證', '計算時間戳記']);
  styleHeader(scores, '#4a6fa5');
  scores.setColumnWidths(1, 13, 130);

  var links = ss.insertSheet(SHEETS.LINKS);
  links.getRange('A1').setValue('① 試算表網址（本檔）').setFontWeight('bold');
  links.getRange('B1').setValue(ss.getUrl());
  links.getRange('A2').setValue('② Web App 網址（需手動部署一次，見下方說明）').setFontWeight('bold');
  links.getRange('B2').setValue('尚未部署──請至「部署 → 新增部署作業 → 網頁應用程式」，執行身份選「我」、存取權限選「任何人」，完成後把 .../exec 網址貼在這裡，並貼進 report.html 與 dashboard.html 開頭的 API_URL');
  links.getRange('A4').setValue('③ 啟用 GitHub 比對（選用）').setFontWeight('bold');
  links.getRange('B4').setValue('執行 setGithubToken("你的GitHub PAT") 一次即可，並在「設定_人員對照」填妥成員的 GitHub帳號/監控Repo，syncGithubActivity 排程會自動每日抓取比對');
  links.getRange('A5').setValue('④ 設定管理密鑰（啟用 CEO 查核標記功能）').setFontWeight('bold');
  links.getRange('B5').setValue('執行 setAdminKey("你的密鑰") 一次，並把同一組字串貼進 dashboard.html 的 ADMIN_KEY 常數');
  links.setColumnWidth(1, 280);
  links.setColumnWidth(2, 640);

  var defaultSheet = ss.getSheetByName('工作表1') || ss.getSheetByName('Sheet1');
  if (defaultSheet) ss.deleteSheet(defaultSheet);

  ScriptApp.getProjectTriggers().forEach(function (t) {
    var fn = t.getHandlerFunction();
    if (fn === 'dailyScoreRollup' || fn === 'syncGithubActivity') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('dailyScoreRollup').timeBased().everyDays(1).atHour(23).create();
  ScriptApp.newTrigger('syncGithubActivity').timeBased().everyDays(1).atHour(2).create();

  Logger.log('==================== 建置完成 ====================');
  Logger.log('試算表網址：' + ss.getUrl());
  Logger.log('下一步（必做）：部署為 Web App，report.html / dashboard.html 才能讀寫資料。');
  Logger.log('部署 → 新增部署作業 → 網頁應用程式 → 執行身份「我」、存取權限「任何人」 → 複製 .../exec 網址');
  Logger.log('===================================================');
  return { ssUrl: ss.getUrl() };
}

function styleHeader(sheet, color) {
  var lastCol = sheet.getLastColumn();
  sheet.getRange(1, 1, 1, lastCol).setFontWeight('bold').setBackground(color).setFontColor('#ffffff');
  sheet.setFrozenRows(1);
}

function resetTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  Logger.log('已清除所有觸發器，可重新執行 buildSystem()。');
}

function setGithubToken(token) {
  PropertiesService.getScriptProperties().setProperty('GITHUB_PAT', token);
  Logger.log('GitHub PAT 已設定。請在「設定_人員對照」填妥 GitHub帳號/監控Repo，syncGithubActivity 排程將自動啟用比對。');
}

function setAdminKey(key) {
  PropertiesService.getScriptProperties().setProperty('ADMIN_KEY', key);
  Logger.log('ADMIN_KEY 已設定。請把同一組字串貼進 dashboard.html 的 ADMIN_KEY 常數，查核標記功能才能使用。');
}

/* ============== 二、Web 入口（doGet 讀 / doPost 寫）============== */
function doGet(e) {
  var action = (e && e.parameter && e.parameter.action) || 'ping';
  try {
    if (action === 'ping') return jsonOut({ ok: true, time: new Date().toISOString() });
    if (action === 'dashboard') return jsonOut(getDashboardData(e.parameter));
    return jsonOut({ ok: false, error: '未知的 action：' + action });
  } catch (err) {
    return jsonOut({ ok: false, error: String(err) });
  }
}

function doPost(e) {
  var body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return jsonOut({ ok: false, error: '請求格式錯誤（非有效 JSON）' });
  }
  try {
    var action = body.action;
    if (action === 'login') return jsonOut(handleLogin(body));
    if (action === 'submitReport') return jsonOut(handleSubmitReport(body));
    if (action === 'setAudit') return jsonOut(handleSetAudit(body));
    return jsonOut({ ok: false, error: '未知的 action：' + action });
  } catch (err) {
    return jsonOut({ ok: false, error: String(err) });
  }
}

// 保留給少數瀏覽器/環境仍發送 preflight 的情況；正常情況下 report.html /
// dashboard.html 用 text/plain 送出 POST 可完全避開 preflight，見建置說明 CORS 章節。
function doOptions(e) {
  return ContentService.createTextOutput('');
}

function jsonOut(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

/* ===== doPost 動作處理 ===== */
function handleLogin(body) {
  var roster = findRosterByName(body.name);
  if (!roster || String(roster.pin) !== String(body.pin) || roster.status !== '在職') {
    return { ok: false, error: '姓名或通行碼錯誤，或帳號已停用' };
  }
  var todayStr = fmtDate(new Date());
  var todayTasks = getReportRows().filter(function (t) { return t.name === roster.name && t.date === todayStr; });
  return { ok: true, name: roster.name, todayTasks: todayTasks };
}

function handleSubmitReport(body) {
  var roster = findRosterByName(body.name);
  if (!roster || String(roster.pin) !== String(body.pin) || roster.status !== '在職') {
    return { ok: false, error: '姓名或通行碼錯誤，或帳號已停用' };
  }
  var tasks = body.tasks || [];
  if (!tasks.length) return { ok: false, error: '沒有要送出的任務' };

  var sheet = getSheet(SHEETS.REPORTS);
  var batchId = Utilities.getUuid();
  var now = new Date();
  tasks.forEach(function (t) { appendReportRow(sheet, now, batchId, roster.name, t); });
  return { ok: true, savedCount: tasks.length };
}

function appendReportRow(sheet, ts, batchId, name, t) {
  var workDate = parseDate(t.date) || ts;
  sheet.appendRow([
    ts, batchId, name, workDate, t.project || '', t.desc || '',
    Number(t.complexity) || 0, Number(t.estHours) || 0, Number(t.actHours) || 0,
    t.status || '進行中', t.plannedDate ? parseDate(t.plannedDate) : '',
    t.evidenceUrl || '', t.noEvidenceReason || '', t.note || '', '', ''
  ]);
  var r = sheet.getLastRow();
  sheet.getRange(r, 15).setFormula('=IFERROR(INT(A' + r + ')-INT(D' + r + '),"")');
  sheet.getRange(r, 16).setFormula('=OR(LEN(L' + r + ')>0,LEN(M' + r + ')>0)');
}

function handleSetAudit(body) {
  var adminKey = PropertiesService.getScriptProperties().getProperty('ADMIN_KEY');
  if (!adminKey || body.adminKey !== adminKey) {
    return { ok: false, error: '管理密鑰錯誤' };
  }
  var sheet = getSheet(SHEETS.AUDIT);
  var data = sheet.getDataRange().getValues();
  var dateStr = body.date;
  for (var i = 1; i < data.length; i++) {
    if (data[i][0] === body.name && data[i][1] && fmtDate(data[i][1]) === dateStr) {
      sheet.getRange(i + 1, 3).setValue(body.status || '未查核');
      sheet.getRange(i + 1, 4).setValue(body.note || '');
      sheet.getRange(i + 1, 5).setValue(Session.getActiveUser().getEmail() || 'CEO');
      sheet.getRange(i + 1, 6).setValue(new Date());
      return { ok: true, updated: true };
    }
  }
  sheet.appendRow([body.name, parseDate(dateStr), body.status || '未查核', body.note || '', Session.getActiveUser().getEmail() || 'CEO', new Date()]);
  return { ok: true, updated: false };
}

/* ===== doGet：dashboard 資料組裝 ===== */
function getDashboardData(params) {
  params = params || {};
  var from = params.from ? parseDate(params.from) : addDays(new Date(), -30);
  var to = params.to ? parseDate(params.to) : new Date();
  var personFilter = (params.person && params.person !== 'ALL') ? params.person : null;

  var roster = getRosterRows().map(function (r) {
    return { name: r.name, status: r.status, githubUser: r.githubUser || '' };
  });

  var tasks = getReportRows().filter(function (t) {
    return inRangeStr(t.date, from, to) && (!personFilter || t.name === personFilter);
  });

  var audit = getAuditRows().filter(function (a) {
    return inRangeStr(a.date, from, to) && (!personFilter || a.name === personFilter);
  });

  var daily = getScoreRows().filter(function (s) {
    return inRangeStr(s.date, from, to) && (!personFilter || s.name === personFilter);
  });

  var todayStr = fmtDate(new Date());
  if (inRangeStr(todayStr, from, to)) {
    var activeRoster = roster.filter(function (r) {
      return r.status === '在職' && (!personFilter || r.name === personFilter);
    });
    activeRoster.forEach(function (r) {
      var already = daily.some(function (s) { return s.name === r.name && s.date === todayStr; });
      if (!already) {
        var live = computePersonScoreForWindow(r.name, new Date(), ROLLING_WINDOW_DAYS);
        live.live = true;
        daily.push(live);
      }
    });
  }

  return {
    generatedAt: new Date().toISOString(),
    githubEnabled: isGithubEnabled(),
    roster: roster,
    tasks: tasks,
    daily: daily,
    audit: audit
  };
}

/* ============== 三、試算表讀寫工具 ============== */
// 單次 doGet/doPost 執行期間的簡易快取：getDashboardData 在同一次請求中可能
// 對多位成員重複呼叫 computePersonScoreForWindow（例如今天分數尚未跑排程、
// 需即時現算），若每次都整張分頁重讀會隨人數線性放大 API 呼叫。Apps Script
// 每次請求都是全新的執行環境，全域變數不會跨請求殘留，故此處快取安全。
var _cache = {};
function clearRequestCache() { _cache = {}; }

function getSpreadsheet() {
  var id = PropertiesService.getScriptProperties().getProperty('SS_ID');
  if (!id) throw new Error('尚未執行 buildSystem()，找不到試算表。');
  return SpreadsheetApp.openById(id);
}
function getSheet(name) {
  var sh = getSpreadsheet().getSheetByName(name);
  if (!sh) throw new Error('找不到分頁：' + name);
  return sh;
}

function getRosterRows() {
  if (_cache.roster) return _cache.roster;
  var data = getSheet(SHEETS.ROSTER).getDataRange().getValues();
  var rows = [];
  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    if (!row[0]) continue;
    rows.push({
      name: row[0], pin: row[1], status: row[2],
      githubUser: row[3], githubRepos: row[4],
      expectedPoints: row[5] ? Number(row[5]) : null,
      startDate: row[6], note: row[7]
    });
  }
  _cache.roster = rows;
  return rows;
}
function findRosterByName(name) {
  var rows = getRosterRows();
  for (var i = 0; i < rows.length; i++) if (rows[i].name === name) return rows[i];
  return null;
}

function getReportRows() {
  if (_cache.reports) return _cache.reports;
  var data = getSheet(SHEETS.REPORTS).getDataRange().getValues();
  var rows = [];
  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    if (!row[2]) continue;
    rows.push({
      ts: row[0], batchId: row[1], name: row[2], date: fmtDate(row[3]),
      project: row[4], desc: row[5], complexity: Number(row[6]) || 0,
      estHours: Number(row[7]) || 0, actHours: Number(row[8]) || 0, status: row[9],
      plannedDate: row[10] ? fmtDate(row[10]) : '', evidenceUrl: row[11],
      noEvidenceReason: row[12], note: row[13], backfillDays: row[14], hasEvidence: !!row[15]
    });
  }
  _cache.reports = rows;
  return rows;
}
function getReportRowsForPersonInRange(name, start, end) {
  return getReportRows().filter(function (t) { return t.name === name && inRangeStr(t.date, start, end); });
}

function getAuditRows() {
  if (_cache.audit) return _cache.audit;
  var data = getSheet(SHEETS.AUDIT).getDataRange().getValues();
  var rows = [];
  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    if (!row[0]) continue;
    rows.push({ name: row[0], date: fmtDate(row[1]), status: row[2], note: row[3], reviewer: row[4], ts: row[5] });
  }
  _cache.audit = rows;
  return rows;
}
function getAuditRowsForPersonInRange(name, start, end) {
  return getAuditRows().filter(function (a) { return a.name === name && inRangeStr(a.date, start, end); });
}

function getGithubRows() {
  if (_cache.github) return _cache.github;
  var data = getSheet(SHEETS.GITHUB).getDataRange().getValues();
  var rows = [];
  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    if (!row[0]) continue;
    rows.push({
      name: row[0], githubUser: row[1], date: fmtDate(row[2]),
      commits: Number(row[3]) || 0, prOpened: Number(row[4]) || 0, prMerged: Number(row[5]) || 0, syncedAt: row[6]
    });
  }
  _cache.github = rows;
  return rows;
}
function getGithubRowsForPersonInRange(name, start, end) {
  return getGithubRows().filter(function (g) { return g.name === name && inRangeStr(g.date, start, end); });
}

function getScoreRows() {
  var data = getSheet(SHEETS.SCORES).getDataRange().getValues();
  var rows = [];
  for (var i = 1; i < data.length; i++) {
    var row = data[i];
    if (!row[0] || !row[1]) continue;
    rows.push({
      date: fmtDate(row[0]), name: row[1], taskCount: row[2], completedCount: row[3],
      completionRate: row[4], weightedOutput: row[5], totalHours: row[6],
      authenticity: row[7], productivity: row[8], quadrant: row[9], flags: row[10],
      githubEnabled: !!row[11], computedAt: row[12]
    });
  }
  return rows;
}
function upsertScoreRow(score) {
  var sheet = getSheet(SHEETS.SCORES);
  var data = sheet.getDataRange().getValues();
  for (var i = 1; i < data.length; i++) {
    if (data[i][1] === score.name && data[i][0] && fmtDate(data[i][0]) === score.date) {
      writeScoreRow(sheet, i + 1, score);
      return;
    }
  }
  sheet.appendRow(new Array(13));
  writeScoreRow(sheet, sheet.getLastRow(), score);
}
function writeScoreRow(sheet, r, score) {
  sheet.getRange(r, 1, 1, 13).setValues([[
    parseDate(score.date), score.name, score.taskCount, score.completedCount,
    score.completionRate, score.weightedOutput, score.totalHours || 0,
    score.authenticity, score.productivity, score.quadrant, score.flags,
    score.githubEnabled, new Date()
  ]]);
}

function upsertGithubActivityRows(name, githubUser, commitsByDate, prOpenedByDate, prMergedByDate) {
  var dates = {};
  Object.keys(commitsByDate).forEach(function (d) { dates[d] = true; });
  Object.keys(prOpenedByDate).forEach(function (d) { dates[d] = true; });
  Object.keys(prMergedByDate).forEach(function (d) { dates[d] = true; });

  var sheet = getSheet(SHEETS.GITHUB);
  var data = sheet.getDataRange().getValues();
  Object.keys(dates).forEach(function (d) {
    var commits = commitsByDate[d] || 0, opened = prOpenedByDate[d] || 0, merged = prMergedByDate[d] || 0;
    for (var i = 1; i < data.length; i++) {
      if (data[i][0] === name && data[i][2] && fmtDate(data[i][2]) === d) {
        sheet.getRange(i + 1, 4, 1, 4).setValues([[commits, opened, merged, new Date()]]);
        return;
      }
    }
    sheet.appendRow([name, githubUser, parseDate(d), commits, opened, merged, new Date()]);
  });
}

/* ============== 四、誠信分數 / 產能分數計算（JS 函式，非試算表公式）==============
 * 為什麼不用逐列公式：這兩個分數需要跨列彙總（同一人一段期間的多筆任務）、跨表 join
 * （GitHub活動快取、每日查核），而且權重之後會依實際資料調整——寫成公式的話，調權重
 * 就要回頭改寫成千上萬歷史列，不划算。改用函式即時算，並由 dailyScoreRollup 寫入
 * 「每日分數彙總」留存歷史。
 */
function computePersonScoreForWindow(name, asOfDate, windowDays) {
  var roster = findRosterByName(name) || {};
  var end = asOfDate;
  var start = addDays(end, -(windowDays - 1));
  var githubOn = isGithubEnabled() && !!roster.githubUser && !!roster.githubRepos;

  var tasks = getReportRowsForPersonInRange(name, start, end);
  var audits = getAuditRowsForPersonInRange(name, start, end);
  var githubRows = githubOn ? getGithubRowsForPersonInRange(name, start, end) : [];

  var applicable = tasks.filter(function (t) { return t.status !== '取消'; });
  var evidenceApplicable = applicable.filter(function (t) { return t.status !== '請假或無工作'; });
  var completed = applicable.filter(function (t) { return t.status === '已完成'; });

  var evidenceCoverage = evidenceApplicable.length
    ? clamp0to100(average(evidenceApplicable.map(evidenceQuality)) * 100)
    : 100;
  var timing = timingScore(tasks);
  var duplicate = duplicateScore(applicable);
  var auditScore = auditScoreFn(audits);
  var githubEvidence = githubOn ? githubEvidenceScore(applicable, githubRows) : 0;

  var authWeights = githubOn ? WEIGHTS_AUTH_GH : WEIGHTS_AUTH_NO_GH;
  var authenticity =
    evidenceCoverage * authWeights.evidence +
    timing * authWeights.timing +
    duplicate * authWeights.duplicate +
    auditScore * authWeights.audit +
    (githubOn ? githubEvidence * authWeights.github : 0);

  var expectedPtsPerDay = roster.expectedPoints || EXPECTED_POINTS_PER_DAY;
  var weightedOutput = completed.reduce(function (s, t) { return s + (t.complexity || 0); }, 0);
  var outputScore = clamp0to100(pct(weightedOutput, expectedPtsPerDay * windowDays));
  var completionRate = applicable.length ? pct(completed.length, applicable.length) : 100;
  var ontime = ontimeScore(completed);
  var totalHours = applicable.reduce(function (s, t) { return s + (t.actHours || 0); }, 0);
  var efficiency = totalHours > 0
    ? clamp0to100(pct(weightedOutput / totalHours, 1 / EXPECTED_HOURS_PER_POINT))
    : (weightedOutput > 0 ? 100 : 0);
  var githubOutput = githubOn ? githubOutputScore(githubRows, windowDays) : 0;

  var prodWeights = githubOn ? WEIGHTS_PROD_GH : WEIGHTS_PROD_NO_GH;
  var productivity =
    outputScore * prodWeights.output +
    completionRate * prodWeights.completion +
    ontime * prodWeights.ontime +
    efficiency * prodWeights.efficiency +
    (githubOn ? githubOutput * prodWeights.github : 0);

  var quadrant = classifyQuadrant(authenticity, productivity);
  var flags = buildFlags({
    start: start, end: end, tasks: tasks, applicable: applicable, evidenceApplicable: evidenceApplicable,
    evidenceCoverage: evidenceCoverage, duplicate: duplicate, audits: audits
  });

  return {
    date: fmtDate(end), name: name, taskCount: applicable.length, completedCount: completed.length,
    completionRate: round1(completionRate), weightedOutput: round1(weightedOutput), totalHours: round1(totalHours),
    authenticity: round1(authenticity), productivity: round1(productivity),
    quadrant: quadrant, flags: flags.join('、'), githubEnabled: githubOn
  };
}

function timingScore(tasks) {
  if (!tasks.length) return 100;
  var batches = groupBy(tasks, 'batchId');
  var scores = [];
  Object.keys(batches).forEach(function (bid) {
    var batchTasks = batches[bid];
    var distinctDates = {};
    batchTasks.forEach(function (t) { distinctDates[t.date] = true; });
    var dateCount = Object.keys(distinctDates).length;
    batchTasks.forEach(function (t) {
      var days = Number(t.backfillDays);
      var s;
      if (isNaN(days) || days <= 1) s = 100;
      else if (days <= 3) s = 70;
      else if (days <= 7) s = 40;
      else s = 10;
      if (dateCount >= 3) s = Math.max(0, s - 20);
      scores.push(s);
    });
  });
  return average(scores);
}

// 證據可信度分級（非單純有/無二分法，更精準反映真實性）：
//   1.0 = 附上看起來像網址的證據連結；0.6 = 有填證據欄但不像網址（自由文字聲稱）；
//   0.4 = 沒附連結但誠實說明原因（透明但不可驗證）；0 = 完全沒有
function evidenceQuality(t) {
  var url = t.evidenceUrl ? String(t.evidenceUrl).trim() : '';
  if (url) return /^https?:\/\//i.test(url) ? 1 : 0.6;
  var reason = t.noEvidenceReason ? String(t.noEvidenceReason).trim() : '';
  return reason ? 0.4 : 0;
}

// 只比對「同一天」內的任務描述重複度，而非整個滾動窗口——多日延續同一項工作
// （例如連續 3 天修同一個報表 bug）是正常現象，不應被誤判為灌水；同一天內
// 出現高度相似的多筆描述，才是比較可能的「灌水湊筆數」訊號。
function duplicateScore(tasks) {
  var descTasks = tasks.filter(function (t) { return t.desc && String(t.desc).trim().length >= 4; });
  if (descTasks.length < 2) return 100;
  var byDate = groupBy(descTasks, 'date');
  var dupCount = 0;
  Object.keys(byDate).forEach(function (d) {
    var dayTasks = byDate[d];
    for (var i = 0; i < dayTasks.length; i++) {
      for (var j = 0; j < i; j++) {
        if (bigramJaccard(dayTasks[i].desc, dayTasks[j].desc) >= DUPLICATE_SIMILARITY_THRESHOLD) { dupCount++; break; }
      }
    }
  });
  return clamp0to100(100 - (dupCount / descTasks.length) * 100);
}
function bigramJaccard(a, b) {
  var setA = bigramSet(a), setB = bigramSet(b);
  if (!setA.size || !setB.size) return 0;
  var intersect = 0;
  setA.forEach(function (g) { if (setB.has(g)) intersect++; });
  var union = setA.size + setB.size - intersect;
  return union ? intersect / union : 0;
}
function bigramSet(s) {
  var set = new Set();
  var str = String(s).replace(/\s+/g, '');
  for (var i = 0; i < str.length - 1; i++) set.add(str.substr(i, 2));
  return set;
}

function auditScoreFn(audits) {
  if (!audits.length) return 100;
  var scores = audits.map(function (a) { return a.status === '查核未通過' ? 0 : 100; });
  return average(scores);
}

function githubEvidenceScore(tasks, githubRows) {
  var activeDates = {};
  tasks.forEach(function (t) { if (t.status === '已完成' || t.status === '進行中') activeDates[t.date] = true; });
  var dates = Object.keys(activeDates);
  if (!dates.length) return 100;
  var ghByDate = {};
  githubRows.forEach(function (g) { ghByDate[g.date] = (g.commits > 0 || g.prMerged > 0); });
  var matched = dates.filter(function (d) { return ghByDate[d]; }).length;
  return pct(matched, dates.length);
}

function githubOutputScore(githubRows, windowDays) {
  var commits = githubRows.reduce(function (s, g) { return s + (g.commits || 0); }, 0);
  var merged = githubRows.reduce(function (s, g) { return s + (g.prMerged || 0); }, 0);
  return clamp0to100(pct(commits + merged * 2, windowDays));
}

function ontimeScore(completed) {
  var withPlan = completed.filter(function (t) { return t.plannedDate; });
  if (!withPlan.length) return 100;
  var ontime = withPlan.filter(function (t) { return parseDate(t.date) <= parseDate(t.plannedDate); }).length;
  return pct(ontime, withPlan.length);
}

function classifyQuadrant(auth, prod) {
  if (auth >= QUADRANT_THRESHOLD && prod >= QUADRANT_THRESHOLD) return '明星型';
  if (auth < QUADRANT_THRESHOLD && prod >= QUADRANT_THRESHOLD) return '需查核型';
  if (auth >= QUADRANT_THRESHOLD && prod < QUADRANT_THRESHOLD) return '待協助型';
  return '高風險型';
}

function buildFlags(ctx) {
  var flags = [];
  var reportedDates = {};
  ctx.tasks.forEach(function (t) { reportedDates[t.date] = true; });
  var missing = 0;
  var cursor = new Date(ctx.start);
  while (cursor <= ctx.end) {
    if (!reportedDates[fmtDate(cursor)]) missing++;
    cursor = addDays(cursor, 1);
  }
  if (missing > 0) flags.push('缺交' + missing + '天');
  if (ctx.tasks.some(function (t) { return Number(t.backfillDays) > MAX_ONTIME_BACKFILL_DAYS; })) flags.push('補登');
  if (ctx.duplicate < 70) flags.push('重複文字疑慮');
  if (ctx.evidenceCoverage < 60) flags.push('證據偏低');
  if (ctx.audits.some(function (a) { return a.status === '查核未通過'; })) flags.push('查核未通過');
  if (hasShortDescriptions(ctx.evidenceApplicable)) flags.push('內容過於簡略');
  if (hasHoursVariance(ctx.applicable)) flags.push('工時落差大');
  return flags;
}

// 半數以上任務描述過短（少於 MIN_DESC_LENGTH 字），內容難以驗證真實性與工作量
function hasShortDescriptions(tasks) {
  if (!tasks.length) return false;
  var shortCount = tasks.filter(function (t) { return String(t.desc || '').trim().length < MIN_DESC_LENGTH; }).length;
  return shortCount / tasks.length > 0.5;
}

// 預估工時與實際工時長期落差過大（無論高估或低估），代表自評能力或誠實度可能有問題
function hasHoursVariance(tasks) {
  var withEst = tasks.filter(function (t) { return t.estHours > 0; });
  if (withEst.length < 2) return false;
  var totalEst = withEst.reduce(function (s, t) { return s + t.estHours; }, 0);
  var totalAct = withEst.reduce(function (s, t) { return s + t.actHours; }, 0);
  return Math.abs(totalAct - totalEst) / totalEst > HOURS_VARIANCE_RATIO;
}

/* ============== 五、每日排程 ============== */
function dailyScoreRollup() {
  var roster = getRosterRows().filter(function (r) { return r.status === '在職'; });
  var today = new Date();
  roster.forEach(function (person) {
    var score = computePersonScoreForWindow(person.name, today, ROLLING_WINDOW_DAYS);
    upsertScoreRow(score);
  });
  Logger.log('dailyScoreRollup 完成，共處理 ' + roster.length + ' 位在職成員。');
}

/* ============== 六、GitHub 交叉比對模組（選用）============== */
function isGithubEnabled() {
  return !!PropertiesService.getScriptProperties().getProperty('GITHUB_PAT');
}

function syncGithubActivity() {
  var pat = PropertiesService.getScriptProperties().getProperty('GITHUB_PAT');
  if (!pat) return; // 未設定 PAT 時安全不執行，buildSystem() 仍可放心安裝此排程

  var roster = getRosterRows().filter(function (r) { return r.status === '在職' && r.githubUser && r.githubRepos; });
  var today = new Date();
  var since = addDays(today, -(ROLLING_WINDOW_DAYS + 1));

  roster.forEach(function (person) {
    var repos = String(person.githubRepos).split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    var commitsByDate = {}, prOpenedByDate = {}, prMergedByDate = {};
    repos.forEach(function (repo) {
      try {
        fetchCommitsIntoBucket(repo, person.githubUser, since, today, pat, commitsByDate);
        fetchPRCountsIntoBucket(repo, person.githubUser, since, today, pat, 'created', prOpenedByDate);
        fetchPRCountsIntoBucket(repo, person.githubUser, since, today, pat, 'merged', prMergedByDate);
      } catch (err) {
        Logger.log('GitHub 同步失敗：' + person.name + ' / ' + repo + '：' + err);
      }
    });
    upsertGithubActivityRows(person.name, person.githubUser, commitsByDate, prOpenedByDate, prMergedByDate);
  });
  Logger.log('syncGithubActivity 完成，共處理 ' + roster.length + ' 位已設定 GitHub 的成員。');
}

function fetchCommitsIntoBucket(repo, user, since, until, pat, bucket) {
  var url = 'https://api.github.com/repos/' + repo + '/commits?author=' + encodeURIComponent(user)
    + '&since=' + since.toISOString() + '&until=' + until.toISOString() + '&per_page=100';
  var res = UrlFetchApp.fetch(url, { headers: { Authorization: 'Bearer ' + pat, 'User-Agent': 'chengyou-work-report' }, muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) { Logger.log('commits API ' + res.getResponseCode() + '：' + res.getContentText()); return; }
  var data = JSON.parse(res.getContentText());
  data.forEach(function (c) {
    if (!c.commit || !c.commit.author || !c.commit.author.date) return;
    var d = fmtDate(new Date(c.commit.author.date));
    bucket[d] = (bucket[d] || 0) + 1;
  });
}

function fetchPRCountsIntoBucket(repo, user, since, until, pat, mode, bucket) {
  var field = mode === 'merged' ? 'merged' : 'created';
  var q = 'repo:' + repo + '+type:pr+author:' + user + '+' + field + ':' + fmtDate(since) + '..' + fmtDate(until);
  var url = 'https://api.github.com/search/issues?q=' + q + '&per_page=100';
  var res = UrlFetchApp.fetch(url, { headers: { Authorization: 'Bearer ' + pat, 'User-Agent': 'chengyou-work-report' }, muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) { Logger.log('PR search API ' + res.getResponseCode() + '：' + res.getContentText()); return; }
  var data = JSON.parse(res.getContentText());
  (data.items || []).forEach(function (item) {
    var dateStr = mode === 'merged' ? (item.pull_request && item.pull_request.merged_at) : item.created_at;
    if (!dateStr) return;
    var d = fmtDate(new Date(dateStr));
    bucket[d] = (bucket[d] || 0) + 1;
  });
}

/* ============== 七、共用工具函式 ============== */
function fmtDate(d) {
  if (!d) return '';
  if (typeof d === 'string') return d.length >= 10 ? d.substring(0, 10) : d;
  return Utilities.formatDate(new Date(d), Session.getScriptTimeZone() || 'Asia/Taipei', 'yyyy-MM-dd');
}
function parseDate(s) {
  if (!s) return null;
  if (s instanceof Date) return s;
  return new Date(s + 'T00:00:00');
}
function addDays(d, n) {
  var nd = new Date(d);
  nd.setDate(nd.getDate() + n);
  return nd;
}
function inRangeStr(dateStr, from, to) {
  if (!dateStr) return false;
  var f = (from instanceof Date) ? fmtDate(from) : from;
  var t = (to instanceof Date) ? fmtDate(to) : to;
  return dateStr >= f && dateStr <= t;
}
function pct(a, b) { return b ? clamp0to100((a / b) * 100) : 0; }
function clamp0to100(x) { return Math.max(0, Math.min(100, x)); }
function average(arr) { return arr.length ? arr.reduce(function (s, x) { return s + x; }, 0) / arr.length : 100; }
function round1(x) { return Math.round(x * 10) / 10; }
function groupBy(arr, key) {
  var out = {};
  arr.forEach(function (item) {
    var k = item[key];
    if (!out[k]) out[k] = [];
    out[k].push(item);
  });
  return out;
}

/* ============== 八、自我測試（不動試算表，純函式驗證用）==============
 * 修改上方權重常數後，先跑這個函式看數字是否符合預期，比重新跑一輪表單/
 * 觸發器流程快很多。
 */
function selfTestScoring() {
  // 同一天內兩筆描述幾乎相同 → 應被判定為灌水重複；跨日的相同描述（第4筆延續
  // 第1筆的登入頁面工作到隔天）屬正常多日任務，不應被誤判為重複
  var dupTasks = [
    { date: '2026-08-01', desc: '開發登入頁面' },
    { date: '2026-08-01', desc: '開發登入頁面' },
    { date: '2026-08-02', desc: '開發登入頁面' }
  ];
  var contTasks = [
    { date: '2026-08-01', desc: '開發登入頁面' },
    { date: '2026-08-02', desc: '開發登入頁面' },
    { date: '2026-08-03', desc: '開發登入頁面' }
  ];
  var timingTasks = [
    { batchId: 'b1', date: '2026-08-01', backfillDays: 0 },
    { batchId: 'b1', date: '2026-08-01', backfillDays: 0 }
  ];

  Logger.log('timingScore（皆準時送出，應接近100）：' + timingScore(timingTasks));
  Logger.log('duplicateScore(同日重複兩筆，應明顯低於100)：' + duplicateScore(dupTasks));
  Logger.log('duplicateScore(跨日延續同一任務，不應被扣分，應為100)：' + duplicateScore(contTasks));
  Logger.log('bigramJaccard(開發登入頁面, 修正登入頁面樣式問題)（應為中等相似度）：' + bigramJaccard('開發登入頁面', '修正登入頁面樣式問題').toFixed(2));

  Logger.log('evidenceQuality(有https連結)（應為1）：' + evidenceQuality({ evidenceUrl: 'https://github.com/x/y/pull/1' }));
  Logger.log('evidenceQuality(有填但非網址)（應為0.6）：' + evidenceQuality({ evidenceUrl: '已截圖給PM' }));
  Logger.log('evidenceQuality(無連結但有說明原因)（應為0.4）：' + evidenceQuality({ evidenceUrl: '', noEvidenceReason: '內部系統無公開連結' }));
  Logger.log('evidenceQuality(完全沒填)（應為0）：' + evidenceQuality({ evidenceUrl: '', noEvidenceReason: '' }));

  Logger.log('hasShortDescriptions(半數以上過短)（應為true）：' + hasShortDescriptions([{ desc: '做東西' }, { desc: '修bug' }, { desc: '這是一段夠長、可驗證的具體任務描述' }]));
  Logger.log('hasHoursVariance(兩筆預估皆嚴重偏離實際)（應為true）：' + hasHoursVariance([{ estHours: 3, actHours: 10 }, { estHours: 2, actHours: 7 }]));
  Logger.log('hasHoursVariance(預估與實際接近)（應為false）：' + hasHoursVariance([{ estHours: 3, actHours: 3.5 }, { estHours: 2, actHours: 2.2 }]));
  Logger.log('hasHoursVariance(僅1筆資料不足以判斷，應為false)：' + hasHoursVariance([{ estHours: 3, actHours: 10 }]));

  Logger.log('classifyQuadrant(80,80)（應為 明星型）：' + classifyQuadrant(80, 80));
  Logger.log('classifyQuadrant(50,85)（應為 需查核型）：' + classifyQuadrant(50, 85));
  Logger.log('classifyQuadrant(85,50)（應為 待協助型）：' + classifyQuadrant(85, 50));
  Logger.log('classifyQuadrant(40,40)（應為 高風險型）：' + classifyQuadrant(40, 40));
  Logger.log('以上數字若符合括號內預期，代表評分函式邏輯正常，可安心調整上方權重常數。');
}
