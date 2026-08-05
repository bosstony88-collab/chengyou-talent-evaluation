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
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .base import BaseSchoolScraper, CalendarEvent, ClassAssignment, MaskedStudentEntry, ScrapeOutcome
from .date_utils import parse_date_guess
from .heuristics import extract_events_heuristic
from .http_utils import polite_get
from .pdf_utils import (
    extract_pdf_text,
    first_masked_context,
    masked_name_samples,
    parse_class_teacher_pairs,
    parse_class_teacher_table,
    parse_masked_student_roster,
    parse_single_grade_from_title,
)

logger = logging.getLogger("school_scraper")

MAX_CALENDAR_PAGES = 14  # 主頁 + 最多再追蹤約一年份的月份導覽連結，避免無窮迴圈
MAX_EVENT_DETAIL_FETCHES = 60  # 單校最多下載幾篇事件詳細頁，避免行事曆事件很多時單校爬取時間失控
MAX_NEWS_ARTICLES_TO_SCAN = 40  # 公告列表最多掃描幾篇標題找編班/導師關鍵字
MAX_CATEGORY_PAGES_TO_TRY = 3  # 公告列表首頁掃不到文章連結時，往下一層分類頁最多試幾個
MAX_PDF_ATTACHMENTS_PER_ARTICLE = 5  # 單篇公告最多下載幾個PDF附件，避免不相關附件拖慢單校處理時間
MAX_EXTRA_ROSTER_LIST_PAGES = 2  # 編班關鍵字在公告列表首頁掃不到時，最多再往後翻幾頁分頁（start=N）
                                  # ——編班公告每學年才發一次，很容易被後續公告擠出首頁

ROSTER_KEYWORDS = ["編班", "導師編配", "導師名單", "班級編制", "新生名單", "分班"]
# 課程計畫等大型公文常跟編班公告一起被附加/轉貼，內容是課程規劃而非班級名單，
# 卻常見「詳見第○○頁」這類頁碼佔位符造成誤判，且文件通常很大、解析耗時，直接跳過不下載
PDF_FILENAME_SKIP_KEYWORDS = ["課程計畫"]
# 附件連結不是每校都乾脆用「.pdf」結尾——同德國中的下載連結是
# "index.php?op=tufdl&files_sn=N#檔名.pdf"（湊巧檔名部分讓endswith也抓得到)，
# 但有些學校的tufdl下載連結沒有這個檔名fragment，單純endswith(".pdf")會漏掉，
# 額外比對常見附件副檔名（含query string/fragment前）跟XOOPS慣用的下載端點
_ATTACHMENT_LINK_RE = re.compile(r"\.(pdf|docx?|xlsx?)(?:[?#]|$)", re.IGNORECASE)
_XOOPS_DOWNLOAD_RE = re.compile(r"op=tufdl", re.IGNORECASE)
# 有些學校（例如慈文國中、文昌國中）沒有tad_cal互動式行事曆，而是用公告夾帶PDF發布，
# 需要靠這組關鍵字掃描公告標題找出來，當作 tad_cal 策略失敗時的備援
CALENDAR_ANNOUNCEMENT_KEYWORDS = ["行事曆", "校歷", "行事簡曆", "行事日曆"]
EVENT_LINK_RE = re.compile(r"event\.php\?sn=\d+")
NEWS_ARTICLE_LINK_RE = re.compile(r"(index|page)\.php\?.*\b(nsn|show_uid|uid)=\d+")
CATEGORY_LINK_RE = re.compile(r"\bncsn=\d+")
PAGINATION_LINK_RE = re.compile(r"[?&]start=\d+")
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

    def _extract_pagination_hrefs(self, list_page_url: str) -> list[str]:
        """從公告列表頁找「下一頁」之類的分頁連結（XOOPS慣例用 start=N 參數）。
        編班公告通常整個學年只發一次，掃描首頁常態編班40篇上限抓不到時，
        很可能是被之後累積的其他公告擠到後面分頁去了，往後多翻幾頁再試。"""
        resp = self._safe_get(list_page_url)
        if resp is None:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        hrefs = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if PAGINATION_LINK_RE.search(href):
                hrefs.append(urljoin(list_page_url, href))
        return list(dict.fromkeys(hrefs))

    def _fetch_known_article(self, url: str) -> tuple[str, str] | None:
        """直接抓取研究階段已經人工確認過的公告連結（schools.json 的
        known_roster_article_urls），不受限於列表頁掃描範圍、也不需要標題關鍵字
        比對——這個URL本身就是可信來源，比再靠關鍵字掃描去猜更準確。"""
        resp = self._safe_get(url)
        if resp is None:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        title_tag = soup.find(["h1", "h2", "h3"]) or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else url
        return url, title

    # ---------- 班級編制表（編班暨導師編配公告） ----------
    def scrape_roster(self) -> ScrapeOutcome:
        list_url = self.school.get("roster_list_url")
        known_urls = list(self.school.get("known_roster_article_urls") or [])

        if not list_url and not known_urls:
            return ScrapeOutcome(target="roster", status="skipped", message="schools.json 未設定 roster_list_url")

        # roster_list_url 研究階段有時直接指向已知的公告本身（例如永順國小），不是列表頁；
        # 這種情況若當成列表頁去找「頁面裡的文章連結」，其實是在找該公告頁面上的其他相關連結，
        # 抓不到真正要的內容——直接把它併入 known_urls 當成已知公告處理才對
        if list_url and NEWS_ARTICLE_LINK_RE.search(list_url):
            known_urls.append(list_url)
            list_url = None

        keyword_matches: list[tuple[str, str]] = []
        scanned_count = 0
        used_url = list_url or "(僅使用 known_roster_article_urls)"
        if list_url:
            candidate_links, used_url = self._discover_article_links(list_url)
            scanned_count = min(len(candidate_links), MAX_NEWS_ARTICLES_TO_SCAN)
            keyword_matches = [
                (url, text) for url, text in candidate_links[:MAX_NEWS_ARTICLES_TO_SCAN]
                if any(kw in text for kw in ROSTER_KEYWORDS)
            ]
            if not keyword_matches:
                # 首頁掃不到，往後多翻幾頁分頁再試——編班公告常態編班年級每年才發一次，
                # 很容易被後續累積的其他公告擠出列表首頁
                for page_url in self._extract_pagination_hrefs(used_url)[:MAX_EXTRA_ROSTER_LIST_PAGES]:
                    more_links = self._extract_article_links(page_url)
                    scanned_count += min(len(more_links), MAX_NEWS_ARTICLES_TO_SCAN)
                    keyword_matches += [
                        (url, text) for url, text in more_links[:MAX_NEWS_ARTICLES_TO_SCAN]
                        if any(kw in text for kw in ROSTER_KEYWORDS)
                    ]

        known_candidates = [c for c in (self._fetch_known_article(u) for u in known_urls) if c]
        known_candidate_urls = {url for url, _ in known_candidates}
        # 已知連結（研究階段人工確認過）優先信任；關鍵字掃描結果補充，避免重複處理同一篇
        all_candidates = known_candidates + [
            (url, text) for url, text in keyword_matches if url not in known_candidate_urls
        ]

        if not all_candidates:
            return ScrapeOutcome(
                target="roster", status="failed",
                message=f"在 {used_url} 掃描了 {scanned_count} 篇公告標題，"
                        f"沒有找到含「編班」「導師編配」等關鍵字的公告，可能該公告目前不在第一頁或用詞不同",
            )

        all_assignments: list[ClassAssignment] = []
        all_student_entries: list[MaskedStudentEntry] = []
        seen_roster_classes: set[tuple[str, int, int]] = set()  # 同班名單以最先掃到的公告（最新）為準
        parse_failures = []
        unattributed_masked_total = 0
        pdf_text_cache: dict[str, str] = {}  # 同一份PDF可能被多篇候選公告重複連結，只下載/解析一次
        for article_url, title in all_candidates:
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
            pairs.extend(parse_class_teacher_table(article_text))
            texts_for_roster = [(article_text, article_url)]

            pdf_links = [
                urljoin(article_url, a["href"])
                for a in article_soup.find_all("a", href=True)
                if (_ATTACHMENT_LINK_RE.search(a["href"]) or _XOOPS_DOWNLOAD_RE.search(a["href"]))
                and not any(kw in unquote(a["href"]) for kw in PDF_FILENAME_SKIP_KEYWORDS)
            ]
            # 上限：實測發現有公告一次貼多個不相關PDF附件，若某個附件網址連線異常（例如
            # IPv6路由問題導致逼近逾時上限才失敗），不設上限會讓單篇公告拖很久
            for pdf_url in pdf_links[:MAX_PDF_ATTACHMENTS_PER_ARTICLE]:
                if pdf_url in pdf_text_cache:
                    pdf_text = pdf_text_cache[pdf_url]
                else:
                    pdf_resp = self._safe_get(pdf_url, count_as_host_failure=False)
                    if pdf_resp is None:
                        continue
                    pdf_text = extract_pdf_text(pdf_resp.content)
                    pdf_text_cache[pdf_url] = pdf_text
                pairs.extend(parse_class_teacher_pairs(pdf_text))
                pairs.extend(parse_class_teacher_table(pdf_text))
                texts_for_roster.append((pdf_text, pdf_url))
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

            # 遮罩學生名單：只收學校公告上本來就遮罩過的姓名（王○明），原樣保存。
            # 「第N班」簡寫式標頭需要年級，從公告標題推斷（僅標題明確單一年級/新生時才用）
            default_grade = parse_single_grade_from_title(title, self.school.get("level"))
            diagnostic_logged = False
            found_anything_this_article = bool(pairs)
            for text, text_source in texts_for_roster:
                classes, unattributed = parse_masked_student_roster(text, default_grade=default_grade)
                unattributed_masked_total += unattributed
                if classes:
                    found_anything_this_article = True
                if unattributed and not classes and not diagnostic_logged:
                    # 名單完全無法歸屬時記錄實際比對到的字串樣本＋來源，供下次判斷
                    # 是真實姓名格式沒吃到、還是不相關PDF附件造成的誤判
                    # （樣本中的姓名本來就是學校遮罩過的版本）
                    samples = masked_name_samples(text)
                    snippet = first_masked_context(text)
                    if samples:
                        logger.info(
                            "[%s] 未歸屬遮罩名單，來源=%s，比對樣本=%s，前文=%r",
                            self.school["id"], text_source, samples, snippet,
                        )
                        diagnostic_logged = True
                for grade, class_number, names in classes:
                    key = (school_year, grade, class_number)
                    if key in seen_roster_classes:
                        continue
                    seen_roster_classes.add(key)
                    for idx, name in enumerate(names):
                        all_student_entries.append(
                            MaskedStudentEntry(
                                school_year=school_year,
                                grade=grade,
                                class_number=class_number,
                                entry_index=idx,
                                masked_name=name,
                                source_url=article_url,
                            )
                        )

            if not found_anything_this_article and not diagnostic_logged:
                # 連遮罩姓名的誤判都沒有、完全比對不到任何東西——可能是純流程說明公告、
                # 圖片掃描PDF(擷取不到文字)、或格式跟目前支援的規則完全不同。既有的診斷log
                # 只在「有疑似姓名但無法歸屬」時才印，這裡補上完全無比對結果時的原始文字樣本，
                # 不然這種case完全沒有線索可以追查
                logged_any_sample = False
                for text, text_source in texts_for_roster:
                    if "班" in text:
                        logger.info(
                            "[%s] 公告「%s」完全比對不到班級-導師配對或遮罩姓名，來源=%s，"
                            "原始文字開頭(%d字): %r",
                            self.school["id"], title, text_source, len(text), text[:400],
                        )
                        logged_any_sample = True
                        break
                if not logged_any_sample:
                    # 所有來源都沒有「班」字內容——可能是圖片掃描PDF擷取不到文字、或內容過短
                    lengths = ", ".join(f"{src}({len(t)}字)" for t, src in texts_for_roster)
                    logger.info(
                        "[%s] 公告「%s」所有來源皆無「班」字內容，可能是圖片掃描PDF或內容過短，來源明細: %s",
                        self.school["id"], title, lengths,
                    )
                if not pdf_links:
                    # 完全沒偵測到附件連結時，把頁面上所有連結都印出來，供下次判斷
                    # 真正的名單附件連結長什麼樣子（是否用了目前規則沒涵蓋到的網址格式）
                    all_hrefs = [a["href"] for a in article_soup.find_all("a", href=True)][:25]
                    logger.info(
                        "[%s] 公告「%s」頁面上沒偵測到任何附件連結，該頁全部連結(最多25個): %s",
                        self.school["id"], title, all_hrefs,
                    )

        if not all_assignments and not all_student_entries:
            return ScrapeOutcome(
                target="roster", status="partial",
                message=f"找到 {len(all_candidates)} 篇疑似編班公告，但都解析不出班級-導師配對或遮罩學生名單，"
                        f"可能是公告格式與預期的regex不符，需要人工檢查該公告原文/PDF格式"
                        + (f"（另有 {unattributed_masked_total} 個遮罩姓名因無法歸屬班級而未收）"
                           if unattributed_masked_total else ""),
            )

        status = "success" if not parse_failures else "partial"
        message = (
            f"從 {len(all_candidates)} 篇公告中解析出 {len(all_assignments)} 筆班級-導師資料、"
            f"{len(all_student_entries)} 筆遮罩學生名單（{len(seen_roster_classes)} 個班級）"
        )
        if unattributed_masked_total:
            message += f"，另有 {unattributed_masked_total} 個遮罩姓名因無法歸屬班級而未收"
        if parse_failures:
            message += f"，{len(parse_failures)} 篇解析失敗"
        return ScrapeOutcome(
            target="roster", status=status,
            message=message,
            class_assignments=all_assignments,
            student_entries=all_student_entries,
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
