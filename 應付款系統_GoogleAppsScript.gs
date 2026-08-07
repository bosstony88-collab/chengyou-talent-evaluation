/*****************************************************************
 * 程優教育科技｜應付款指揮中心 · 正式系統（Google 一鍵建置）
 * ---------------------------------------------------------------
 * 這個檔案是「後端＋資料庫」。跟它配對的還有一個 Index.html
 * （前端畫面），兩個檔案要放進「同一個」Apps Script 專案。
 *
 * 這個系統會自動幫你建立：
 *   1) 一份 Google 試算表當資料庫（應付款、時間軸、積分、白名單）
 *   2) 一個網頁版 Web App（3 個人都用同一個網址）
 *   3) 用「訪問者自己的 Google 帳號」自動辨識身分，不用另外做登入
 *
 * ============== 建置步驟（第一次設定，約 10 分鐘）==============
 *   1. 打開 https://script.google.com → 新增專案
 *   2. 把本檔全部內容貼上、取代預設的 Code.gs → 存檔
 *   3. 左側「＋」→「HTML」，檔名務必打「Index」（不要加副檔名）
 *      → 把「應付款系統_Index.html」的內容整份貼進去 → 存檔
 *   4. 左上齒輪「專案設定」→ 勾選「在編輯器顯示 appsscript.json」
 *      → 打開 appsscript.json → 整份換成「應付款系統_appsscript.json」
 *        的內容 → 存檔
 *   5. 上方函式選單選「buildSystem」→ 按「執行 ▶」
 *      → 第一次會跳出授權 → 用鄭董的 Google 帳號允許
 *      → 執行完成後點「執行紀錄 / Logs」，會看到試算表連結
 *   6. 右上角「部署 → 新增部署作業」：
 *        類型：網頁應用程式
 *        說明：隨便打（例如 v1）
 *        執行身分：「存取網頁應用程式的使用者」
 *        誰可以存取：「知道這個 Google 帳戶的任何人」
 *      → 部署 → 複製「網頁應用程式」網址，這就是 3 個人都要用的網址
 *   7. 打開第 5 步產生的試算表 → 右上「共用」→ 把淑靜、Alley 的
 *      Gmail 加為「編輯者」（很重要！不加的話他們打開網頁會出現
 *      權限錯誤，因為系統是用「訪問者自己的身分」讀寫試算表）
 *   8. 打開試算表「白名單」分頁，把淑靜、Alley 的真實 Gmail
 *      填進 B、C 欄（A 欄鄭董的信箱已經自動帶入）
 *   9. 把第 6 步的網址傳給 3 個人，用瀏覽器打開即可（手機也可以）
 *
 *   之後如果改了程式碼，記得回到「部署 → 管理部署作業 → 編輯 →
 *   新版本」才會生效，不會自動更新。
 *****************************************************************/

/* ===== 積分規則（可自行調整數字）===== */
var POINTS = {
  ACK: 2,            // 主管確認已讀
  COMPLETE_ON_TIME: 10, // 主管準時完成付款
  COMPLETE_LATE: 3,     // 主管逾期才完成付款
  REPORT_BONUS: 5       // 該筆項目「準時完成」時，回饋給原本回報的助理
};

/* ============== 一鍵建置 ============== */
function buildSystem(){
  var ss = SpreadsheetApp.create('程優教育科技｜應付款指揮中心（資料庫）');
  var me = Session.getActiveUser().getEmail() || 'bosstony88@gmail.com';

  // 1) 白名單分頁
  var users = ss.getSheets()[0].setName('白名單');
  users.appendRow(['Email', '姓名', '身分（主管／助理）']);
  users.appendRow([me, '鄭董', '主管']);
  users.appendRow(['請填入淑靜的 Gmail', '淑靜', '助理']);
  users.appendRow(['請填入Alley的 Gmail', 'Alley', '助理']);
  users.getRange('1:1').setFontWeight('bold').setBackground('#0b1b33').setFontColor('#ffffff');
  users.setFrozenRows(1);
  users.setColumnWidths(1, 3, 220);

  // 2) 應付款主表
  var pay = ss.insertSheet('應付款');
  pay.appendRow(['Id','名稱','廠商','分類','金額','到期日','後果等級','後果說明',
    '狀態','建立人','建立時間','催辦次數','附件JSON']);
  pay.getRange('1:1').setFontWeight('bold').setBackground('#0b1b33').setFontColor('#ffffff');
  pay.setFrozenRows(1);

  // 3) 時間軸（每筆項目的處理紀錄，可當作「誰講過、誰沒回應」的證據）
  var tl = ss.insertSheet('時間軸');
  tl.appendRow(['ItemId','時間','人員','動作','說明']);
  tl.getRange('1:1').setFontWeight('bold').setBackground('#0b1b33').setFontColor('#ffffff');
  tl.setFrozenRows(1);

  // 4) 積分榜
  var pts = ss.insertSheet('積分');
  pts.appendRow(['姓名','積分']);
  pts.appendRow(['鄭董', 0]);
  pts.appendRow(['淑靜', 0]);
  pts.appendRow(['Alley', 0]);
  pts.getRange('1:1').setFontWeight('bold').setBackground('#0b1b33').setFontColor('#ffffff');

  // 5) 系統狀態（目前連續零逾期天數）
  var meta = ss.insertSheet('系統狀態');
  meta.appendRow(['連續零逾期天數']);
  meta.appendRow([0]);
  meta.getRange('1:1').setFontWeight('bold').setBackground('#0b1b33').setFontColor('#ffffff');

  PropertiesService.getScriptProperties().setProperty('SS_ID', ss.getId());

  // 6) 附件用的 Drive 資料夾
  var folder = DriveApp.createFolder('應付款指揮中心_附件');
  PropertiesService.getScriptProperties().setProperty('FOLDER_ID', folder.getId());

  Logger.log('==================== 建置完成 ====================');
  Logger.log('資料庫試算表：\n' + ss.getUrl());
  Logger.log('附件資料夾：\n' + folder.getUrl());
  Logger.log('接下來：');
  Logger.log('1. 把試算表、附件資料夾都「共用」給淑靜、Alley（編輯者權限）');
  Logger.log('2. 打開試算表「白名單」分頁，填入淑靜、Alley 的真實 Gmail');
  Logger.log('3. 回到本專案「部署 → 新增部署作業」發布網頁應用程式');
  Logger.log('================================================');
  return { ssUrl: ss.getUrl(), folderUrl: folder.getUrl() };
}

/* ============== 網頁進入點 ============== */
function doGet(){
  return HtmlService.createTemplateFromFile('Index')
    .evaluate()
    .setTitle('應付款指揮中心')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/* ============== 共用小工具 ============== */
function getSS_(){
  var id = PropertiesService.getScriptProperties().getProperty('SS_ID');
  if(!id) throw new Error('尚未建置系統，請先在 Apps Script 編輯器執行 buildSystem');
  return SpreadsheetApp.openById(id);
}
function sheet_(name){ return getSS_().getSheetByName(name); }
function newId_(){ return 'p' + Utilities.getUuid().slice(0,8); }
function nowIso_(){ return new Date().toISOString(); }

function resolveUser_(email){
  if(!email) return null;
  email = String(email).toLowerCase().trim();
  var rows = sheet_('白名單').getDataRange().getValues();
  for(var i=1;i<rows.length;i++){
    if(String(rows[i][0]).toLowerCase().trim() === email){
      return { email: email, name: rows[i][1], role: rows[i][2] };
    }
  }
  return null;
}
function currentUser_(){
  var email = Session.getActiveUser().getEmail();
  return resolveUser_(email);
}

/* ============== 讀取整包資料（前端每次刷新都呼叫這個）============== */
function apiWhoAmI(){
  var user = currentUser_();
  if(!user) return { ok:false, error:'not_whitelisted', email: Session.getActiveUser().getEmail() };
  return { ok:true, user:user };
}

function apiList(){
  var user = currentUser_();
  if(!user) return { ok:false, error:'not_whitelisted', email: Session.getActiveUser().getEmail() };
  return { ok:true, user:user, data:getSnapshot_() };
}

function getSnapshot_(){
  var payRows = sheet_('應付款').getDataRange().getValues();
  var tlRows  = sheet_('時間軸').getDataRange().getValues();
  var ptsRows = sheet_('積分').getDataRange().getValues();
  var streak  = sheet_('系統狀態').getRange('A2').getValue();

  var timelineByItem = {};
  for(var t=1;t<tlRows.length;t++){
    var itemId = tlRows[t][0];
    if(!timelineByItem[itemId]) timelineByItem[itemId] = [];
    timelineByItem[itemId].push({
      time: new Date(tlRows[t][1]).toISOString(),
      who: tlRows[t][2], type: tlRows[t][3], text: tlRows[t][4]
    });
  }

  var items = [];
  for(var i=1;i<payRows.length;i++){
    var r = payRows[i];
    if(!r[0]) continue;
    var attachments = [];
    try{ attachments = r[12] ? JSON.parse(r[12]) : []; }catch(e){ attachments = []; }
    items.push({
      id:r[0], title:r[1], vendor:r[2], category:r[3], amount:r[4],
      due: Utilities.formatDate(new Date(r[5]), 'Asia/Taipei', 'yyyy-MM-dd'),
      severity:r[6], note:r[7], status:r[8], createdBy:r[9],
      createdAt: new Date(r[10]).toISOString(), remindCount:r[11],
      attachments: attachments,
      timeline: timelineByItem[r[0]] || []
    });
  }

  var points = {};
  for(var p=1;p<ptsRows.length;p++) points[ptsRows[p][0]] = ptsRows[p][1];

  return { items:items, points:points, streak:streak };
}

/* ============== 新增應付款 ============== */
function apiCreate(item){
  var user = currentUser_();
  if(!user) return { ok:false, error:'not_whitelisted' };
  var id = newId_();
  var now = nowIso_();
  sheet_('應付款').appendRow([
    id, item.title, item.vendor || item.category, item.category, Number(item.amount)||0,
    item.due, item.severity || 'normal', item.note || '',
    'pending_ack', user.name, now, 0, JSON.stringify(item.attachments || [])
  ]);
  var note = (item.attachments && item.attachments.length) ? '（含 '+item.attachments.length+' 個附件）' : '';
  logTimeline_(id, user.name, 'create', '建立項目並送出確認' + note);
  return { ok:true, data:getSnapshot_() };
}

/* ============== 狀態轉換：確認已讀 / 開始處理 / 標記完成 / 催辦 ============== */
function apiAck(id){
  var user = currentUser_();
  if(!user) return { ok:false, error:'not_whitelisted' };
  if(user.role !== '主管') return { ok:false, error:'forbidden', message:'只有主管可以確認已讀' };
  setStatus_(id, 'queued');
  logTimeline_(id, user.name, 'ack', '已確認・列入待處理');
  addPoints_(user.name, POINTS.ACK);
  return { ok:true, data:getSnapshot_() };
}

function apiStart(id){
  var user = currentUser_();
  if(!user) return { ok:false, error:'not_whitelisted' };
  if(user.role !== '主管') return { ok:false, error:'forbidden', message:'只有主管可以開始處理' };
  setStatus_(id, 'in_progress');
  logTimeline_(id, user.name, 'start', '開始處理');
  return { ok:true, data:getSnapshot_() };
}

function apiComplete(id){
  var user = currentUser_();
  if(!user) return { ok:false, error:'not_whitelisted' };
  if(user.role !== '主管') return { ok:false, error:'forbidden', message:'只有主管可以標記完成' };

  var sh = sheet_('應付款');
  var rows = sh.getDataRange().getValues();
  var rowIndex = -1, item = null;
  for(var i=1;i<rows.length;i++){ if(rows[i][0]===id){ rowIndex=i+1; item=rows[i]; break; } }
  if(rowIndex<0) return { ok:false, error:'not_found' };

  var dueStr = Utilities.formatDate(new Date(item[5]), 'Asia/Taipei', 'yyyy-MM-dd');
  var todayStr = Utilities.formatDate(new Date(), 'Asia/Taipei', 'yyyy-MM-dd');
  var late = todayStr > dueStr; // yyyy-MM-dd 字串可直接比大小，避免時區換算誤差

  sh.getRange(rowIndex, 9).setValue('done'); // 狀態欄
  logTimeline_(id, user.name, 'done', '已完成付款・' + (late ? '逾期' : '準時'));

  if(late){
    setStreak_(0);
    addPoints_(user.name, POINTS.COMPLETE_LATE);
  } else {
    var curStreak = Number(sheet_('系統狀態').getRange('A2').getValue()) || 0;
    setStreak_(curStreak + 1);
    addPoints_(user.name, POINTS.COMPLETE_ON_TIME);
    var reporter = item[9];
    if(reporter) addPoints_(reporter, POINTS.REPORT_BONUS);
  }
  return { ok:true, data:getSnapshot_() };
}

function apiNudge(id){
  var user = currentUser_();
  if(!user) return { ok:false, error:'not_whitelisted' };

  var sh = sheet_('應付款');
  var rows = sh.getDataRange().getValues();
  for(var i=1;i<rows.length;i++){
    if(rows[i][0]===id){
      sh.getRange(i+1, 12).setValue((Number(rows[i][11])||0) + 1); // 催辦次數欄
      break;
    }
  }
  logTimeline_(id, user.name, 'nudge', '再提醒主管一次');
  return { ok:true, data:getSnapshot_() };
}

/* ============== 附件上傳（存進 Drive，回傳可分享連結） ============== */
function apiUploadAttachment(filename, mimeType, base64Data){
  var user = currentUser_();
  if(!user) return { ok:false, error:'not_whitelisted' };
  var folderId = PropertiesService.getScriptProperties().getProperty('FOLDER_ID');
  var folder = DriveApp.getFolderById(folderId);
  var bytes = Utilities.base64Decode(base64Data);
  var blob = Utilities.newBlob(bytes, mimeType, filename);
  var file = folder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return { ok:true, name:filename, url:file.getUrl() };
}

/* ============== 內部小工具 ============== */
function setStatus_(id, status){
  var sh = sheet_('應付款');
  var rows = sh.getDataRange().getValues();
  for(var i=1;i<rows.length;i++){
    if(rows[i][0]===id){ sh.getRange(i+1, 9).setValue(status); return; }
  }
}
function logTimeline_(itemId, who, type, text){
  sheet_('時間軸').appendRow([itemId, nowIso_(), who, type, text]);
}
function addPoints_(name, delta){
  var sh = sheet_('積分');
  var rows = sh.getDataRange().getValues();
  for(var i=1;i<rows.length;i++){
    if(rows[i][0]===name){ sh.getRange(i+1, 2).setValue((Number(rows[i][1])||0) + delta); return; }
  }
  sh.appendRow([name, delta]);
}
function setStreak_(n){
  sheet_('系統狀態').getRange('A2').setValue(n);
}
