# 專案說明（給 Claude Code）

程優教育科技｜主管人才評比系統。主要內容：
- `index.html` / `備用_自包含版.html`：靜態網站前端（3D 主管人才評比）。
- `school-scraper/`：Python 爬蟲，定期抓取學校行事曆/班級編制資料（見 `.github/workflows/scrape-schools.yml`）。
- `自評問卷系統_GoogleAppsScript.gs`：獨立的 Google Apps Script，不屬於網站程式碼。

## Code Review Workflow

這個 repo 有兩層自動化程式碼審查：

1. **雲端（GitHub Actions）**：`.github/workflows/claude-code-review.yml` 會在每次 PR 開啟或更新時，
   自動叫 Claude 審查這次變更並貼 PR comment。需要 repo 先設定好 `ANTHROPIC_API_KEY`
   （或 `CLAUDE_CODE_OAUTH_TOKEN`）這個 secret 才會生效，細節見該檔案開頭的註解。
2. **本機/session 內**：在 Claude Code 對話中對目前的 diff 或某個 PR 做審查，直接下
   `/code-review` 即可（找正確性 bug、可簡化/重複的程式碼；效果依 effort 等級調整）。
   要順手套用建議的話接著下 `/code-review --fix`。

送出 PR 前建議先在本機跑一次 `/code-review`，雲端那份 workflow 是給沒先跑過的變更多一層把關，不是取代本機審查。
