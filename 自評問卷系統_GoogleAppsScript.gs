/*****************************************************************
 * 程優教育科技 ｜ 主任雙軌評比 · 自評問卷系統（Google 一鍵建置）
 * ---------------------------------------------------------------
 * 這段程式會自動幫你建立：
 *   1) 一份「主任季度自評」Google 表單  → 連結 A（發給主任填）
 *   2) 一個 Google 試算表後台          → 連結 B（CEO 看，做公司評）
 *   3) 自動帶入：主任一送出，系統就把自評分數寫進「CEO評核台」
 *   4) 自動計算：三軸分數、總分、Δ差異、8型定位、分紅級距
 *
 * 使用方式（約 3 分鐘，只需做一次）：
 *   1. 打開 https://script.google.com → 新增專案
 *   2. 把本檔全部內容貼上、取代預設程式碼 → 存檔（Ctrl/Cmd+S）
 *   3. 上方函式選單選「buildSystem」→ 按「執行 ▶」
 *   4. 第一次會跳出授權 → 用你的 Google 帳號允許
 *   5. 執行完成後，點上方「執行紀錄 / Logs」即可看到 連結A、連結B
 *      （連結也會寫在試算表的「系統連結」分頁）
 *
 * 注意：此系統屬 CEO 機密。試算表請勿開「知道連結可編輯」，
 *       公司評欄位只給自己。表單連結才發給主任。
 *****************************************************************/

/* ===== 維度與指標（對應制度六大維度 A–F；分數採 1–10）===== */
var DIMS = [
  {k:'A', name:'經營績效',      w:35, items:[
    {t:'A1 新生招生達成率', h:'本季邀約__位試聽、成功報名__位、達成目標__%'},
    {t:'A2 舊生留班率',     h:'本季應留班__位、實際留班__位、留班率__%'},
    {t:'A3 分校淨利潤達成', h:'本季是否達損益平衡？主要成本控制挑戰？'},
    {t:'A4 招生行動量',     h:'平均每週班宣__次、主動聯繫潛在家長__次'},
    {t:'A5 現金流管理',     h:'收費準時率、是否有未收學費／壞帳'}
  ]},
  {k:'B', name:'領導統御',      w:25, items:[
    {t:'B1 日會執行品質', h:'日會執行率__%、是否有書面紀錄'},
    {t:'B2 員工向心力',   h:'是否有員工離職／抱怨？原因？'},
    {t:'B3 任務分配與追蹤', h:'交辦任務準時完成率__%'},
    {t:'B4 衝突處理能力', h:'本季衝突或投訴如何處理'},
    {t:'B5 人才培育成效', h:'花多少時間指導員工？誰明顯成長'}
  ]},
  {k:'C', name:'執行力與紀律',  w:20, items:[
    {t:'C1 出勤與工作紀律', h:'假日訊息回應率__%'},
    {t:'C2 指令執行準時率', h:'總部交辦準時完成率__%、有無延誤'},
    {t:'C3 報告與回報品質', h:'週報／月報是否準時、完整'},
    {t:'C4 問題主動回報',   h:'主動回報__次（主動 vs 被動發現）'}
  ]},
  {k:'D', name:'創業心態',      w:10, items:[
    {t:'D1 主動提案與創新', h:'本季主動提出幾個改善建議？'},
    {t:'D2 面對困難的態度', h:'最大挑戰是什麼？如何應對'},
    {t:'D3 主人翁意識',     h:'是否主動關注分校整體、而非只做份內'}
  ]},
  {k:'E', name:'家長與學生關係', w:5, items:[
    {t:'E1 家長滿意度',       h:'家長溝通與滿意度'},
    {t:'E2 學生口碑與介紹率', h:'學生介紹新生比例'}
  ]},
  {k:'F', name:'合規與公司文化', w:5, items:[
    {t:'F1 遵守公司規定',  h:'違規次數、合約遵守'},
    {t:'F2 公司文化傳承',  h:'是否積極傳達公司文化給員工'}
  ]}
];

var OPEN_QUESTIONS = [
  '本季我最滿意自己的一件事是：',
  '本季我最需要改善的一件事是：',
  '我希望公司在哪方面給予更多支持：',
  '對於下一季，我的個人目標是：'
];

/* ============== 主程式：一鍵建置 ============== */
function buildSystem(){
  // 1) 建立表單
  var form = FormApp.create('程優教育科技｜主任季度自評問卷');
  form.setDescription(
    '請依本季（過去三個月）實際表現誠實填寫，分數 1（最低）–10（最高）。\n' +
    '自評結果僅供個人成長與「差異分析」參考，差異將作為一對一面談依據。');
  form.setCollectEmail(false);
  form.setProgressBar(true);

  form.addSectionHeaderItem().setTitle('基本資料');
  form.addTextItem().setTitle('主任姓名').setRequired(true);
  form.addTextItem().setTitle('分校').setRequired(true);
  form.addTextItem().setTitle('評核季度（例：2026 Q2）').setRequired(true);

  // 2) 各維度的 1–10 量表題
  DIMS.forEach(function(d){
    form.addSectionHeaderItem()
        .setTitle(d.k + '. ' + d.name + '（佔總分 ' + d.w + '%）')
        .setHelpText('以下每題請給 1–10 分');
    d.items.forEach(function(it){
      form.addScaleItem()
          .setTitle(it.t)
          .setHelpText(it.h)
          .setBounds(1, 10)
          .setLabels('1 最低', '10 最高')
          .setRequired(true);
    });
  });

  // 3) 開放式問題
  form.addSectionHeaderItem().setTitle('開放式問題（選填）');
  OPEN_QUESTIONS.forEach(function(q){ form.addParagraphTextItem().setTitle(q); });

  // 4) 建立試算表後台，並把表單回應導入
  var ss = SpreadsheetApp.create('程優｜主管人才評比系統（CEO後台）');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());

  // 5) 建立「CEO評核台」分頁（公司評＋差異分析）
  var sh = ss.insertSheet('CEO評核台');
  sh.appendRow([
    '時間','主任','分校','季度',
    '自評·業績','自評·領導','自評·心態','自評總分',
    '公司評·業績','公司評·領導','公司評·心態','公司評總分',
    'Δ業績','Δ領導','Δ心態','Δ總分',
    '8型定位','分紅級距','差異警示'
  ]);
  sh.getRange('1:1').setFontWeight('bold').setBackground('#0b1b33').setFontColor('#ffffff');
  sh.setFrozenRows(1);
  // 提示列（黃底）：公司評三欄請 CEO 手動填 0–100
  sh.getRange('I1:K1').setBackground('#7a5b00');
  sh.setColumnWidths(1, 19, 90);

  // 6) 記住試算表 ID，給觸發器用
  PropertiesService.getScriptProperties().setProperty('SS_ID', ss.getId());

  // 7) 安裝「表單送出自動帶入」觸發器（先清掉舊的避免重複）
  ScriptApp.getProjectTriggers().forEach(function(t){
    if (t.getHandlerFunction() === 'onFormSubmit') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('onFormSubmit').forForm(form).onFormSubmit().create();

  // 8) 連結
  var formUrl = form.getPublishedUrl();
  var editUrl = form.getEditUrl();
  var ssUrl   = ss.getUrl();

  var info = ss.insertSheet('系統連結');
  info.getRange('A1').setValue('① 主任自評問卷（發給主任填寫）').setFontWeight('bold');
  info.getRange('B1').setValue(formUrl);
  info.getRange('A2').setValue('② CEO 系統後台（本檔，做公司評）').setFontWeight('bold');
  info.getRange('B2').setValue(ssUrl);
  info.getRange('A3').setValue('（表單編輯後台）');
  info.getRange('B3').setValue(editUrl);
  info.getRange('A5').setValue('操作').setFontWeight('bold');
  info.getRange('B5').setValue('主任填問卷→自動新增一列到「CEO評核台」。CEO 在 I／J／K 欄填「公司評三軸分數(0–100)」，Δ、8型、分紅自動算出。');
  info.setColumnWidth(1, 220); info.setColumnWidth(2, 620);

  Logger.log('==================== 建置完成 ====================');
  Logger.log('① 主任自評問卷（發給主任）：\n' + formUrl);
  Logger.log('② CEO 系統後台（公司評＋差異分析）：\n' + ssUrl);
  Logger.log('（表單編輯）：\n' + editUrl);
  Logger.log('================================================');
  return {formUrl: formUrl, ssUrl: ssUrl};
}

/* ============== 觸發器：主任送出 → 自動帶入＋計算 ============== */
function onFormSubmit(e){
  var ss = SpreadsheetApp.openById(PropertiesService.getScriptProperties().getProperty('SS_ID'));
  var sh = ss.getSheetByName('CEO評核台');

  var name='', branch='', quarter='';
  var dim = {A:[],B:[],C:[],D:[],E:[],F:[]};
  var resp = e.response.getItemResponses();
  for (var i=0;i<resp.length;i++){
    var title = resp[i].getItem().getTitle();
    var ans   = resp[i].getResponse();
    if (title.indexOf('主任姓名')===0)      name = ans;
    else if (title.indexOf('分校')===0)     branch = ans;
    else if (title.indexOf('評核季度')===0) quarter = ans;
    else {
      var m = title.match(/^([A-F])[1-9]/);
      if (m && !isNaN(parseFloat(ans))) dim[m[1]].push(parseFloat(ans));
    }
  }
  function avg(a){ if(!a.length) return 0; var s=0; for(var j=0;j<a.length;j++) s+=a[j]; return s/a.length; }
  var A=avg(dim.A),B=avg(dim.B),C=avg(dim.C),D=avg(dim.D),E=avg(dim.E),F=avg(dim.F);
  var biz  = A*10;
  var ldr  = (B*25 + C*20)/45*10;
  var mind = (D*10 + E*5 + F*5)/20*10;
  function r1(x){ return Math.round(x*10)/10; }

  sh.appendRow([ new Date(), name, branch, quarter, r1(biz), r1(ldr), r1(mind) ]); // A–G
  var r = sh.getLastRow();
  sh.getRange(r,8 ).setFormula('=E'+r+'*0.35+F'+r+'*0.45+G'+r+'*0.2');               // H 自評總分
  sh.getRange(r,12).setFormula('=IF(COUNT(I'+r+':K'+r+')<3,"",I'+r+'*0.35+J'+r+'*0.45+K'+r+'*0.2)'); // L 公司評總分
  sh.getRange(r,13).setFormula('=IF($L'+r+'="","",E'+r+'-I'+r+')');                  // M Δ業績
  sh.getRange(r,14).setFormula('=IF($L'+r+'="","",F'+r+'-J'+r+')');                  // N Δ領導
  sh.getRange(r,15).setFormula('=IF($L'+r+'="","",G'+r+'-K'+r+')');                  // O Δ心態
  sh.getRange(r,16).setFormula('=IF($L'+r+'="","",H'+r+'-L'+r+')');                  // P Δ總分
  sh.getRange(r,17).setFormula(typeFormula(r));                                      // Q 8型
  sh.getRange(r,18).setFormula(bonusFormula(r));                                     // R 分紅
  sh.getRange(r,19).setFormula(warnFormula(r));                                      // S 差異警示
}

/* ===== 公式產生器（門檻 70 為高/低）===== */
function typeFormula(r){
  var I='I'+r, J='J'+r, K='K'+r;
  return '=IF(COUNT(I'+r+':K'+r+')<3,"待公司評",IFS('+
    'AND('+I+'>=70,'+J+'>=70,'+K+'>=70),"① 全能帥才",'+
    'AND('+I+'>=70,'+J+'>=70,'+K+'<70),"② 傭兵悍將",'+
    'AND('+I+'>=70,'+J+'<70,'+K+'>=70),"③ 單兵王",'+
    'AND('+I+'>=70,'+J+'<70,'+K+'<70),"④ 績效孤星",'+
    'AND('+I+'<70,'+J+'>=70,'+K+'>=70),"⑤ 明日之星",'+
    'AND('+I+'<70,'+J+'>=70,'+K+'<70),"⑥ 山頭老油條",'+
    'AND('+I+'<70,'+J+'<70,'+K+'>=70),"⑦ 忠誠老黃牛",'+
    'AND('+I+'<70,'+J+'<70,'+K+'<70),"⑧ 待轉型"))';
}
function bonusFormula(r){
  var L='L'+r;
  return '=IF('+L+'="","待公司評",IFS('+
    L+'>=90,"+5%（共35%）",'+
    L+'>=80,"維持30%",'+
    L+'>=70,"維持30%＋輔導",'+
    L+'>=60,"-5%（共25%）預警",'+
    L+'<60,"-10%（20%）＋PIP"))';
}
function warnFormula(r){
  var P='P'+r, L='L'+r;
  return '=IF('+L+'="","",IF(ABS('+P+')>=15,IF('+P+'>0,"⚠ 自我高估（鄧寧-克魯格）","⚠ 自我低估（冒牌者）"),IF(ABS('+P+')>=8,"留意差異","認知一致")))';
}

/* ===== 工具：重設（如需重新建置，先執行這個清掉觸發器）===== */
function resetTriggers(){
  ScriptApp.getProjectTriggers().forEach(function(t){ ScriptApp.deleteTrigger(t); });
  Logger.log('已清除所有觸發器，可重新執行 buildSystem。');
}
