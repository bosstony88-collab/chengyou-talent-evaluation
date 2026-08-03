"""NSS 系統學校爬蟲（桃園國中、福豐國中主站、文山國小；西門國小同款可作為未來擴校參考）。

研究階段觀察到這套系統疑似前端渲染（SPA），單純 requests 抓到的 HTML 可能只有殼、沒有實際內容。
策略：
  1. 先用一般 requests 抓取，若內文長度看起來合理就直接解析（有些頁面其實是伺服器端渲染的）。
  2. 若判斷內容過短（疑似空殼），且環境有安裝 Playwright，才動用 headless browser 重新抓取一次。
  3. 兩者都拿不到足夠內容時，明確記錄為 failed 並註明「疑似需要JS渲染，建議人工查是否有可直接呼叫的
     後端JSON API（通常SPA背後會有 /api/ 或類似路徑）」，不要假裝成功。
"""
from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseSchoolScraper, ClassAssignment, ScrapeOutcome
from .heuristics import extract_events_heuristic
from .http_utils import polite_get
from .pdf_utils import parse_class_teacher_pairs

logger = logging.getLogger("school_scraper")

MIN_MEANINGFUL_TEXT_LEN = 200  # 低於這個字數，判斷疑似SPA空殼頁面
ROSTER_KEYWORDS = ["編班", "導師編配", "導師名單", "班級編制"]
SCHOOL_YEAR_RE = re.compile(r"(\d{2,3})\s*學年度")


def _try_playwright_render(url: str) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.info("Playwright 未安裝，略過 headless browser fallback（見 requirements.txt）")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, timeout=20000, wait_until="networkidle")
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        logger.info("Playwright 渲染 %s 失敗: %s", url, exc)
        return None


class NssScraper(BaseSchoolScraper):
    def scrape_calendar(self) -> ScrapeOutcome:
        url = self.school.get("calendar_url")
        if not url:
            return ScrapeOutcome(target="calendar", status="skipped", message="schools.json 未設定 calendar_url")

        html, note = self._fetch_with_fallback(url)
        if html is None:
            return ScrapeOutcome(target="calendar", status="failed", message=note)

        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(" ", strip=True)

        # NSS 頁面結構未知，先用「找出所有看起來像日期的片段＋鄰近文字」的寬鬆策略
        events = extract_events_heuristic(text, url)

        if not events:
            return ScrapeOutcome(
                target="calendar", status="failed",
                message=f"{note}；頁面內文長度 {len(text)} 字，但找不到可辨識的日期片段，"
                        f"NSS頁面結構與XOOPS不同，建議人工開瀏覽器開發者工具找後端資料來源",
            )
        return ScrapeOutcome(
            target="calendar", status="partial",
            message=f"{note}；用寬鬆規則擷取到 {len(events)} 筆疑似行事曆項目，"
                    f"NSS格式尚未逐一驗證，建議人工抽查正確性",
            calendar_events=events,
        )

    def scrape_roster(self) -> ScrapeOutcome:
        url = self.school.get("roster_list_url")
        if not url:
            return ScrapeOutcome(target="roster", status="skipped", message="schools.json 未設定 roster_list_url")

        html, note = self._fetch_with_fallback(url)
        if html is None:
            return ScrapeOutcome(target="roster", status="failed", message=note)

        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(" ", strip=True)

        if not any(kw in text for kw in ROSTER_KEYWORDS):
            return ScrapeOutcome(
                target="roster", status="failed",
                message=f"{note}；頁面內文找不到「編班」「導師編配」等關鍵字，"
                        f"可能班級編制資訊在其他子頁面，需要人工確認正確網址",
            )

        pairs = parse_class_teacher_pairs(text)
        school_year = None
        m = SCHOOL_YEAR_RE.search(text)
        if m:
            school_year = m.group(1)

        if not pairs or not school_year:
            return ScrapeOutcome(
                target="roster", status="partial",
                message=f"{note}；頁面含編班相關關鍵字，但抓不到完整的班級-導師配對或學年度，需人工核對格式",
            )

        assignments = [
            ClassAssignment(
                school_year=school_year, grade=g, class_number=c, teacher_name=t,
                is_carried_over=False, source_url=url,
            )
            for g, c, t in pairs
        ]
        return ScrapeOutcome(
            target="roster", status="success",
            message=f"{note}；解析出 {len(assignments)} 筆班級-導師資料",
            class_assignments=assignments,
        )

    def _fetch_with_fallback(self, url: str) -> tuple[str | None, str]:
        resp = None
        try:
            resp = polite_get(self.session, url)
        except Exception as exc:
            logger.info("[%s] GET %s 失敗: %s", self.school["id"], url, exc)

        html = resp.text if resp is not None and resp.status_code == 200 else None
        if html and len(BeautifulSoup(html, "lxml").get_text(strip=True)) >= MIN_MEANINGFUL_TEXT_LEN:
            return html, "使用一般HTTP請求取得內容（伺服器端渲染或無JS依賴）"

        rendered = _try_playwright_render(url)
        if rendered and len(BeautifulSoup(rendered, "lxml").get_text(strip=True)) >= MIN_MEANINGFUL_TEXT_LEN:
            return rendered, "一般HTTP請求內容過短，改用Playwright headless browser渲染成功"

        if html:
            return None, "一般HTTP請求取得內容但過短（疑似SPA空殼），且Playwright渲染也未取得足夠內容"
        return None, "一般HTTP請求失敗，且Playwright渲染也未取得足夠內容"
