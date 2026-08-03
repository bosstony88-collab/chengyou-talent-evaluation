# 學校公開資訊爬蟲系統

蒐集桃園21所公立國中小官網「公開發布」的三類資訊，供程優教育科技內部行政參考（排課、行事曆比對）：
1. **學期行事曆**（完全公開資訊）
2. **班級編制表**（班級數與導師姓名對照）
3. **班級學生名單（遮罩）**：僅收學校官網公告上**本來就遮罩過**的姓名（例如「王○明」），原樣保存

## 資料範圍與使用限制（請務必遵守）

- 學生姓名**只收學校自己遮罩後公開的版本**，系統絕不嘗試還原、比對或另行蒐集完整姓名。
  `db/store.py` 的寫入函式有硬性防護：**不含遮罩符號的姓名一律拒絕入庫**（見
  `upsert_student_entries` 與 `scrapers/pdf_utils.py` 的 `MASK_CHARS`），資料庫結構上不可能存到完整學生姓名。
- 用途限定為**內部行政參考**（排課、了解學區概況），**不得**用於對學生/家長的行銷、招生聯繫等目的外利用。
- 所有資料均附 `source_url`，可追溯回原始公告，供人工核對。

## 架構

```
config/schools.json   21校設定檔（官網URL、CMS類型、已知/推測的頁面路徑）
db/schema.sql          SQLite schema
db/init_db.py           初始化DB + 匯入學校清單
db/store.py              寫入邏輯（含「未公告年級延續前次資料」carry-over邏輯）
scrapers/                爬蟲模組（xoops_scraper / nss_scraper / generic_scraper，依cms_type自動選用）
main.py                    主程式，遍歷所有學校爬取，單校失敗不中斷整體流程
scripts/export_json.py     匯出查詢用JSON給前端（../school-info.html）
tests/test_parsing.py      離線解析邏輯測試（不連線，驗證regex/邏輯正確性）
```

爬蟲由 `.github/workflows/scrape-schools.yml` 排程執行（GitHub Actions runner 有完整對外網路權限），
執行後自動 commit 更新 `data/schools.db` 與 `data/export/data.json`。查詢介面在 repo 根目錄的
`school-info.html`，讀取 `data/export/data.json`，是純前端無需另外架設伺服器。

## ⚠️ 已知限制與需要人工核對的項目

`config/schools.json` 的所有網址、CMS類型判斷，是在**開發環境的網路政策擋掉外部連線**的情況下，
只靠搜尋引擎摘要間接研究得出的，**尚未有任何一頁被人眼直接開瀏覽器核對過**。第一次讓 GitHub Actions
實際跑過後，請對照 `scrape_log` 資料表（或 `school-info.html` 上每校的警示訊息）檢查以下已知風險點：

- **大有國小**（`dyes_es`）：官網歸屬本身不確定（多網域並存），技術棧疑似舊式ASP，列為第一優先人工複查對象。
- **青溪國中**（`chjh_jh`）：官網歸屬本次調查中最不確定（4種並存網址）。
- **建國國中、文昌國中**：新舊站並存，需確認現行維護中的是哪一版。
- **福豐國中**：主站與班級網頁子網域是兩套不同技術棧，需分開處理。
- **文山國小、桃園國中、福豐國中(主站)**：NSS系統，疑似前端渲染，`nss_scraper.py` 有 Playwright
  headless browser 備援，但仍可能需要人工找後端 JSON API 才能穩定抓取。
- **班級編制表**：目前設計是「掃描公告標題找編班/導師關鍵字」，如果某校當學年度公告用詞不同
  （例如沒用「編班」二字），會抓不到，需要人工擴充 `xoops_scraper.py` 的 `ROSTER_KEYWORDS`。

## 本地執行

```bash
cd school-scraper
pip install -r requirements.txt
python main.py                    # 爬全部21校
python main.py --school yes_es    # 只爬單一學校（除錯用）
python tests/test_parsing.py      # 跑離線解析測試
python scripts/export_json.py     # 匯出查詢用JSON
```
