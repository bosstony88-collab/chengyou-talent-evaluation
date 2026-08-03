"""XOOPS 家族學校爬蟲（本專案涵蓋的21校中，約17校屬此類）。

涵蓋兩個模組慣例：
- /modules/tad_cal/ ：互動式行事曆，事件詳細頁通常是 event.php?sn=N
- /modules/tadnews/ ：公告列表，文章頁通常是 index.php?nsn=N（部分校用 page.php?ncsn=X&nsn=N，
  經國國中則用 show_uid=N / uid=N），班級編制表沒有固定總表頁，是每學年度以「編班暨導師編配」
  公告形式發布，通常只公告當學年重新編班的年級，需靠關鍵字掃描公告標題找出來。

因為研究階段沒辦法直接開網頁核對（環境網路政策擋掉外部連線），這裡的爬取邏輯採
「盡量嘗試＋清楚記錄失敗原因」策略：抓不到就記 partial/failed 並附上原因，
不對整體流程造成中斷，之後再依 GitHub Actions 實跑的 log 修正細節。
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .base import BaseSchoolScraper, CalendarEvent, ClassAssignment, ScrapeOutcome
from .date_utils import parse_date_guess
from .heuristics import extract_events_heuristic
from .http_utils import polite_get
from .pdf_utils import extract_pdf_text, parse_class_teacher_pairs

logger = logging.getLogger("school_scraper")

MAX_CALENDAR_PAGES = 14  # 主頁 + 最多再追蹤約一年份的月份導覽連結，避免無窮迴圈
MAX_EVENT_DETAIL_FETCHES = 60  # 單校最多下載幾篇事件詳細頁，避免行事曆事件很多時單校爬取時間失控
MAX_NEWS_ARTICLES_TO_SCAN = 40  # 公告列表最多掃描幾篇標題找編班/導師關鍵字
MAX_CATEGORY_PAGES_TO_TRY = 3  # 公告列表首頁掃不到文章連結時，往下一層分類頁最多試幾個
MAX_PDF_ATTACHMENTS_PER_ARTICLE = 5  # 單篇公告最多下載幾個PDF附件，避免不相關附件拖慢單校處理時間

ROSTER_KEYWORDS = ["編班", "導師編配", "導師名單", "班級編制"]
# 有些學校（例如慈文國中、文昌國中）沒有tad_cal互動式行事曆，而是用公告夾帶PDF發布，
# 需要靠這組關鍵字掃描公告標題找出來，當作 tad_cal 策略失敗時的備援
CALENDAR_ANNOUNCEMENT_KEYWORDS = ["行事曆", "校歷", "行事簡曆", "行事日曆"]
EVENT_LINK_RE = re.compile(r"event\.php\?sn=\d+")
NEWS_ARTICLE_LINK_RE = re.compile(r"(index|page)\.php\?.*\b(nsn|show_uid|uid)=\d+")
CATEGORY_LINK_RE = re.compile(r"\bncsn=\d+")
SCHOOL_YEAR_RE = re.compile(r"(\d{2,3})\s*學年度")


class XoopsScraper(BaseSchoolScraper):
    def __init__(self, school: dict, session):
        super().__init__(school, session)
        # 連線層級失敗（DNS/逾時/拒絕連線）代表整個主機都連不上，記錄下來後同一次爬取
        # 就不要再對同一主機重複嘗試 tad_cal / 公告備援 / roster 三條路徑，避免逾時疊加拖慢整體進度
        self._dead_hosts: set[str] = set()

    # ---------- 行事曆 ----------
    def scrape_calendar(self) -> ScrapeOutcome:
        calendar_url = self.school.get("calendar_url")
        if not calendar_url:
            return ScrapeOutcome(target="calendar", status="skipped", message="schools.json 未設定 calendar_url")

        tad_cal_outcome = self._scrape_tad_cal(calendar_url)
        if tad_cal_outcome.calendar_events:
            return tad_cal_outcome

        # tad_cal 策略找不到任何事件連結，可能這所學校根本沒有互動式行事曆模組，
        # 而是像慈文國中、文昌國中一樣用公告夾帶PDF發布，改用關鍵字掃描公告的備援策略
        announcement_outcome = self._scrape_calendar_via_announcement(calendar_url)
        if announcement_outcome.calendar_events:
            return announcement_outcome

        return ScrapeOutcome(
            target="calendar", status="failed",
            message=f"tad_cal策略：{tad_cal_outcome.message}｜公告PDF備援策略：{announcement_outcome.message}",
        )

    def _scrape_tad_cal(self, calendar_url: str) -> ScrapeOutcome:
        visited = set()
        to_visit = [calendar_url]
        event_links: set[str] = set()

        while to_visit and len(visited) < MAX_CALENDAR_PAGES:
            url = to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)

            resp = self._safe_get(url)
            if resp is None:
                continue

            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if EVENT_LINK_RE.search(href):
                    event_links.add(urljoin(url, href))
                elif "tad_cal" in href and href not in visited and len(visited) + len(to_visit) < MAX_CALENDAR_PAGES:
                    # 可能是月份導覽連結，一併排入待訪清單
                    to_visit.append(urljoin(url, href))

        if not event_links:
            return ScrapeOutcome(
                target="calendar",
                status="failed",
                message=f"在 {calendar_url} 及其連結頁面中找不到任何 event.php?sn= 事件連結，"
                        f"可能是頁面結構與預期不同或需要人工核對正確網址",
            )

        event_links_list = sorted(event_links)
        truncated = len(event_links_list) > MAX_EVENT_DETAIL_FETCHES
        event_links_to_fetch = event_links_list[:MAX_EVENT_DETAIL_FETCHES]

        events: list[CalendarEvent] = []
        for link in event_links_to_fetch:
            resp = self._safe_get(link)
            if resp is None:
                continue
            event = self._parse_event_page(resp.text, link)
            if event:
                events.append(event)

        if not events:
            return ScrapeOutcome(
                target="calendar", status="partial",
                message=f"找到 {len(event_links)} 個事件連結，但逐一解析內容都失敗",
            )

        status = "success" if len(events) == len(event_links_to_fetch) and not truncated else "partial"
        message = f"共找到 {len(event_links)} 個事件連結，成功解析 {len(events)} 筆"
        if truncated:
            message += f"（已達單次上限 {MAX_EVENT_DETAIL_FETCHES} 筆，其餘 {len(event_links) - MAX_EVENT_DETAIL_FETCHES} 筆留待下次執行）"
        return ScrapeOutcome(
            target="calendar", status=status,
            message=message,
            calendar_events=events,
        )

    def _parse_event_page(self, html: str, source_url: str) -> CalendarEvent | None:
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find(["h1", "h2", "h3"]) or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None
        body_text = soup.get_text(" ", strip=True)
        if not title:
            return None

        start_date = parse_date_guess(body_text)
        school_year = None
        m = SCHOOL_YEAR_RE.search(body_text)
        if m:
            school_year = m.group(1)

        return CalendarEvent(
            title=title,
            source_url=source_url,
            start_date=start_date,
            school_year=school_year,
            raw_text=body_text[:1000],
        )

    # ---------- 公告文章連結探索（roster 與 calendar 的 PDF 備援策略共用） ----------
    def _extract_article_links(self, url: str) -> list[tuple[str, str]]:
        resp = self._safe_get(url)
        if resp is None:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if text and NEWS_ARTICLE_LINK_RE.search(href):
                links.append((urljoin(url, href), text))
        return links

    def _discover_article_links(self, list_url: str) -> tuple[list[tuple[str, str]], str]:
        """公告列表頁掃描不到文章連結時的備援策略：
        1) 試著在網址後補上 index.php（有些校網 bare 目錄網址跟 index.php 渲染結果不同）
        2) 往下一層分類頁（page.php?ncsn=N）找
        回傳 (candidate_links, 實際成功取得資料的網址)，方便記錄在 log 裡。"""
        candidates = self._extract_article_links(list_url)
        if candidates:
            return candidates, list_url

        if not list_url.rstrip("/").endswith(".php"):
            alt_url = list_url.rstrip("/") + "/index.php"
            candidates = self._extract_article_links(alt_url)
            if candidates:
                return candidates, alt_url

        resp = self._safe_get(list_url)
        if resp is not None:
            soup = BeautifulSoup(resp.text, "lxml")
            category_urls = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if CATEGORY_LINK_RE.search(href) and not NEWS_ARTICLE_LINK_RE.search(href):
                    category_urls.append(urljoin(list_url, href))
            for cat_url in list(dict.fromkeys(category_urls))[:MAX_CATEGORY_PAGES_TO_TRY]:
                candidates = self._extract_article_links(cat_url)
                if candidates:
                    return candidates, cat_url

        return [], list_url

    # ---------- 班級編制表（編班暨導師編配公告） ----------
    def scrape_roster(self) -> ScrapeOutcome:
        list_url = self.school.get("roster_list_url")
        if not list_url:
            return ScrapeOutcome(target="roster", status="skipped", message="schools.json 未設定 roster_list_url")

        candidate_links, used_url = self._discover_article_links(list_url)

        keyword_matches = [
            (url, text) for url, text in candidate_links[:MAX_NEWS_ARTICLES_TO_SCAN]
            if any(kw in text for kw in ROSTER_KEYWORDS)
        ]

        if not keyword_matches:
            return ScrapeOutcome(
                target="roster", status="failed",
                message=f"在 {used_url} 掃描了 {min(len(candidate_links), MAX_NEWS_ARTICLES_TO_SCAN)} 篇公告標題，"
                        f"沒有找到含「編班」「導師編配」等關鍵字的公告，可能該公告目前不在第一頁或用詞不同",
            )

        all_assignments: list[ClassAssignment] = []
        parse_failures = []
        for article_url, title in keyword_matches:
            resp = self._safe_get(article_url)
            if resp is None:
                parse_failures.append(article_url)
                continue

            article_soup = BeautifulSoup(resp.text, "lxml")
            article_text = article_soup.get_text(" ", strip=True)

            school_year = None
            m = SCHOOL_YEAR_RE.search(title) or SCHOOL_YEAR_RE.search(article_text)
            if m:
                school_year = m.group(1)

            pairs = parse_class_teacher_pairs(article_text)

            pdf_links = [
                urljoin(article_url, a["href"])
                for a in article_soup.find_all("a", href=True)
                if a["href"].lower().endswith(".pdf")
            ]
            # 上限：實測發現有公告一次貼多個不相關PDF附件，若某個附件網址連線異常（例如
            # IPv6路由問題導致逼近逾時上限才失敗），不設上限會讓單篇公告拖很久
            for pdf_url in pdf_links[:MAX_PDF_ATTACHMENTS_PER_ARTICLE]:
                pdf_resp = self._safe_get(pdf_url, count_as_host_failure=False)
                if pdf_resp is None:
                    continue
                pdf_text = extract_pdf_text(pdf_resp.content)
                pairs.extend(parse_class_teacher_pairs(pdf_text))
                if not school_year:
                    m = SCHOOL_YEAR_RE.search(pdf_text)
                    if m:
                        school_year = m.group(1)

            if not school_year:
                parse_failures.append(article_url)
                continue

            for grade, class_number, teacher in pairs:
                all_assignments.append(
                    ClassAssignment(
                        school_year=school_year,
                        grade=grade,
                        class_number=class_number,
                        teacher_name=teacher,
                        is_carried_over=False,
                        source_url=article_url,
                    )
                )

        if not all_assignments:
            return ScrapeOutcome(
                target="roster", status="partial",
                message=f"找到 {len(keyword_matches)} 篇疑似編班公告，但都解析不出班級-導師配對，"
                        f"可能是公告格式與預期的regex不符，需要人工檢查該公告原文/PDF格式",
            )

        status = "success" if not parse_failures else "partial"
        return ScrapeOutcome(
            target="roster", status=status,
            message=f"從 {len(keyword_matches)} 篇公告中解析出 {len(all_assignments)} 筆班級-導師資料"
                    + (f"，{len(parse_failures)} 篇解析失敗" if parse_failures else ""),
            class_assignments=all_assignments,
        )

    # ---------- 行事曆備援：公告夾帶PDF（無tad_cal互動式行事曆的學校，例如慈文國中、文昌國中） ----------
    def _scrape_calendar_via_announcement(self, calendar_url: str) -> ScrapeOutcome:
        candidate_links, used_url = self._discover_article_links(calendar_url)
        matches = [
            (url, text) for url, text in candidate_links[:MAX_NEWS_ARTICLES_TO_SCAN]
            if any(kw in text for kw in CALENDAR_ANNOUNCEMENT_KEYWORDS)
        ]
        if not matches:
            return ScrapeOutcome(
                target="calendar", status="failed",
                message=f"在 {used_url} 掃描了 {min(len(candidate_links), MAX_NEWS_ARTICLES_TO_SCAN)} 篇公告標題，"
                        f"找不到含「行事曆」「校歷」等關鍵字的公告",
            )

        events: list[CalendarEvent] = []
        for article_url, title in matches:
            resp = self._safe_get(article_url)
            if resp is None:
                continue
            article_soup = BeautifulSoup(resp.text, "lxml")
            article_text = article_soup.get_text(" ", strip=True)

            school_year = None
            m = SCHOOL_YEAR_RE.search(title) or SCHOOL_YEAR_RE.search(article_text)
            if m:
                school_year = m.group(1)

            texts_to_scan = [(article_text, article_url)]
            pdf_links = [
                urljoin(article_url, a["href"])
                for a in article_soup.find_all("a", href=True)
                if a["href"].lower().endswith(".pdf")
            ]
            for pdf_url in pdf_links[:MAX_PDF_ATTACHMENTS_PER_ARTICLE]:
                pdf_resp = self._safe_get(pdf_url, count_as_host_failure=False)
                if pdf_resp is None:
                    continue
                pdf_text = extract_pdf_text(pdf_resp.content)
                if pdf_text:
                    texts_to_scan.append((pdf_text, pdf_url))

            for text, source in texts_to_scan:
                for ev in extract_events_heuristic(text, source):
                    ev.school_year = ev.school_year or school_year
                    events.append(ev)

        if not events:
            return ScrapeOutcome(
                target="calendar", status="partial",
                message=f"找到 {len(matches)} 篇疑似行事曆公告，但都解析不出日期事件（可能PDF是圖片掃描檔，"
                        f"沒有可擷取的文字層）",
            )

        return ScrapeOutcome(
            target="calendar", status="partial",
            message=f"公告PDF備援策略：從 {len(matches)} 篇公告中用寬鬆規則擷取到 {len(events)} 筆疑似行事曆事件，"
                    f"建議人工抽查正確性",
            calendar_events=events,
        )

    # ---------- 共用 ----------
    def _safe_get(self, url: str, count_as_host_failure: bool = True):
        """count_as_host_failure=False 用於PDF附件等次要資源：
        單一附件連不上不代表整個主機都連不上（實測發現過主站正常、但特定PDF路徑
        "Network unreachable" 的案例），不應該因此把整個主機標記為死站而連累其他頁面。
        """
        host = urlparse(url).netloc
        if host in self._dead_hosts:
            return None
        try:
            resp = polite_get(self.session, url)
            if resp.status_code != 200:
                logger.info("[%s] GET %s -> HTTP %s", self.school["id"], url, resp.status_code)
                return None
            return resp
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            logger.info(
                "[%s] GET %s 連線層級失敗（DNS/逾時/拒絕連線）: %s", self.school["id"], url, exc,
            )
            if count_as_host_failure:
                logger.info("[%s] 判定 %s 整個主機無法連線，本次爬取跳過此主機後續請求", self.school["id"], host)
                self._dead_hosts.add(host)
            return None
        except Exception as exc:
            logger.info("[%s] GET %s 失敗: %s", self.school["id"], url, exc)
            return None
