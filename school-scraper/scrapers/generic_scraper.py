"""通用備援爬蟲：用於 cms_type 為 asp_legacy / unknown 的學校（目前是大有國小）。

這類學校在研究階段完全無法確認頁面結構（甚至連現行正式站網域都不確定），
所以這裡不假裝有專屬 parser，而是老實地：
  1. 嘗試連線 base_url，確認網站是否還活著
  2. 用關鍵字（"行事曆" / "編班" / "導師"）在首頁找相關連結
  3. 找得到就套用跟 NSS 一樣的寬鬆規則擷取，找不到就明確回報需要人工調查
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseSchoolScraper, ScrapeOutcome
from .heuristics import extract_events_heuristic
from .http_utils import polite_get
from .pdf_utils import parse_class_teacher_pairs
from .base import ClassAssignment
import re

logger = logging.getLogger("school_scraper")

CALENDAR_LINK_KEYWORDS = ["行事曆", "校歷", "行事簡曆"]
ROSTER_LINK_KEYWORDS = ["編班", "導師編配", "班級編制", "導師"]
SCHOOL_YEAR_RE = re.compile(r"(\d{2,3})\s*學年度")


class GenericScraper(BaseSchoolScraper):
    def scrape_calendar(self) -> ScrapeOutcome:
        return self._scrape_by_link_keyword("calendar", self.school.get("calendar_url"), CALENDAR_LINK_KEYWORDS)

    def scrape_roster(self) -> ScrapeOutcome:
        return self._scrape_by_link_keyword("roster", self.school.get("roster_list_url"), ROSTER_LINK_KEYWORDS)

    def _scrape_by_link_keyword(self, target: str, known_url: str | None, keywords: list[str]) -> ScrapeOutcome:
        base_url = self.school["base_url"]
        try:
            resp = polite_get(self.session, known_url or base_url)
        except Exception as exc:
            return ScrapeOutcome(
                target=target, status="failed",
                message=f"連線 {known_url or base_url} 失敗: {exc}；此校CMS狀態不明(cms_type={self.school['cms_type']})，"
                        f"需要人工先確認正確的現行官網網址",
            )
        if resp.status_code != 200:
            return ScrapeOutcome(
                target=target, status="failed",
                message=f"連線 {known_url or base_url} 回傳 HTTP {resp.status_code}，需要人工確認正確網址",
            )

        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text(" ", strip=True)

        if target == "calendar":
            events = extract_events_heuristic(text, known_url or base_url)
            if events:
                return ScrapeOutcome(
                    target=target, status="partial",
                    message=f"用寬鬆規則從 {known_url or base_url} 擷取到 {len(events)} 筆疑似行事曆項目，"
                            f"此校CMS結構完全未知，強烈建議人工核對正確性",
                    calendar_events=events,
                )
        else:
            pairs = parse_class_teacher_pairs(text)
            m = SCHOOL_YEAR_RE.search(text)
            if pairs and m:
                assignments = [
                    ClassAssignment(
                        school_year=m.group(1), grade=g, class_number=c, teacher_name=t,
                        is_carried_over=False, source_url=known_url or base_url,
                    )
                    for g, c, t in pairs
                ]
                return ScrapeOutcome(
                    target=target, status="partial",
                    message=f"用寬鬆規則解析出 {len(assignments)} 筆班級-導師資料，"
                            f"此校CMS結構完全未知，強烈建議人工核對正確性",
                    class_assignments=assignments,
                )

        # 找不到直接內容，退而求其次找看看有沒有關鍵字連結，至少提供人工調查的起點
        found_links = [
            urljoin(known_url or base_url, a["href"])
            for a in soup.find_all("a", href=True)
            if any(kw in a.get_text(strip=True) for kw in keywords)
        ]
        if found_links:
            return ScrapeOutcome(
                target=target, status="failed",
                message=f"首頁沒有直接找到內容，但找到 {len(found_links)} 個疑似相關連結（例如 {found_links[0]}），"
                        f"需要人工追蹤這些連結確認正確頁面",
            )
        return ScrapeOutcome(
            target=target, status="failed",
            message=f"在 {known_url or base_url} 完全找不到相關內容或連結，此校需要完整人工調查（"
                    f"包含確認官網是否為現行正式站）",
        )
