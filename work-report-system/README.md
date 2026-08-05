# 程優教育科技｜克雷斯技術團隊工作回報系統 — 部署包

這是一個**靜態網站**，部署後會得到兩個公開網址：一個給克雷斯技術團隊每天回報，一個給 CEO 看儀表板。

## 📦 內容
| 檔案 | 說明 |
|---|---|
| `report.html` | **團隊回報頁**。手機優先，姓名+PIN 登入後逐筆填寫今日任務；記得上次的專案/複雜度、可一鍵「延續／複製」既有任務，送出即寫入試算表。 |
| `dashboard.html` | **CEO 儀表板**。3D 立體「誠信×產能」總覽（淡色漸層科技風）＋ 評比等級、工作建議、警示中心、團隊排行榜、個人熱力圖／雷達圖／趨勢圖／任務狀態與專案時間分佈／任務明細。 |
| `技術團隊工作回報系統_GoogleAppsScript.gs` | 後端：一鍵建置試算表 + Web App API + 每日排程計分（＋選用 GitHub 比對模組）。 |
| `demo-data.json` | 示範資料。兩個頁面在 `API_URL` 未設定時會自動讀取，方便在部署 Apps Script 之前先預覽介面。 |
| `建置與使用說明.md` | 完整部署與操作說明（含評分邏輯細節、CORS 注意事項、GitHub 模組啟用方式）。 |

---

## 🚀 三步驟上線

### 1. 建立後端（Google Apps Script）
1. 打開 https://script.google.com → 新增專案
2. 貼上 `技術團隊工作回報系統_GoogleAppsScript.gs` 全部內容 → 存檔
3. 執行 `buildSystem()` → 授權 → 完成後會建立一份試算表（花名冊／每日回報／查核／分數彙總等分頁）
4. **部署為 Web App**（這步無法用程式自動完成，需手動做一次）：
   右上「部署 → 新增部署作業 → 網頁應用程式」，執行身份選「我」、存取權限選「任何人」，複製 `.../exec` 網址

### 2. 設定前端
打開 `report.html` 與 `dashboard.html`，把開頭的：
```js
const API_URL = "";
```
換成剛剛複製的 `.../exec` 網址。（選用）在 `dashboard.html` 設定 `ADMIN_KEY`，需與 Apps Script 端一致才能使用「查核標記」功能——留空的話系統會在第一次使用時跳出提示輸入，僅存在瀏覽器當次工作階段，不會寫進檔案。

### 3. 部署成網站
把整個 `work-report-system/` 資料夾拖進 **Netlify Drop**（https://app.netlify.com/drop ，免註冊）即可取得兩個公開網址：
- `https://xxxx.netlify.app/report.html` → 發給克雷斯技術團隊
- `https://xxxx.netlify.app/dashboard.html` → CEO 自己用

也可用 GitHub Pages / Cloudflare Pages / Vercel，一樣是靜態託管。

---

## 🧪 先預覽再部署（示範模式）

`API_URL` 留空時，兩個頁面會自動改讀同資料夾的 `demo-data.json`，用假資料把 3D 場景、象限分佈、評比等級、警示與建議、熱力圖、排行榜、雷達圖都跑起來，畫面會標示「🧪 示範資料」。這讓你在還沒建立 Apps Script 之前，就能直接雙擊打開 `dashboard.html` 看到完整視覺效果。

---

## ☁ 團隊人員設定

到試算表「設定_人員對照」分頁，把範例列改成真實成員：姓名、PIN（4碼通行碼）、狀態（在職/停用）。團隊成員之後用瀏覽器打開 `report.html`，輸入姓名+PIN 就能回報，可勾選「記住我」方便每天使用。

---

## 🔐 機密與操作重點
- 試算表請勿開啟「知道連結可編輯」給團隊成員，只有 `report.html` 的連結給他們。
- GitHub PAT、ADMIN_KEY 一律存在 Apps Script 的「指令碼屬性」，不會出現在任何 HTML 檔或試算表儲存格中。
- 詳細操作、評分邏輯、CORS 技術細節請見《建置與使用說明.md》。

*程優教育科技股份有限公司 · 克雷斯技術團隊工作回報系統 v1.1*
