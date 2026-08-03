"""離線測試：用模擬的 HTML 內容驗證解析邏輯，不連線到真實網站。

因為開發環境的網路政策擋掉外部連線，沒辦法對真實學校網站做整合測試，
這組測試至少確保「假設頁面結構符合研究報告的猜測」時，parser 邏輯是正確的。
之後在 GitHub Actions 實跑後，若真實頁面結構跟猜測不同，可以再對照 scrape_log 調整。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.date_utils import parse_date_guess  # noqa: E402
from scrapers.pdf_utils import parse_class_teacher_pairs  # noqa: E402
from scrapers.xoops_scraper import XoopsScraper  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok  - {name}")
    else:
        FAIL += 1
        print(f"FAIL  - {name}  {detail}")


def test_date_parsing():
    print("test_date_parsing")
    check("民國年日期", parse_date_guess("114年8月30日") == "2025-08-30")
    check("西元年日期", parse_date_guess("2025/08/30") == "2025-08-30")
    check("月/日補西元年", parse_date_guess("開學日 8/30", default_ad_year=2025) == "2025-08-30")
    check("無法解析回傳None", parse_date_guess("完全沒有日期的文字") is None)


def test_class_teacher_regex():
    print("test_class_teacher_regex")
    text = "113學年度常態編班暨導師編配結果：一年1班 導師 王小明　二年3班 導師 李小華　9年10班 陳大文老師"
    pairs = parse_class_teacher_pairs(text)
    check("解析出3筆", len(pairs) == 3, str(pairs))
    check("中文數字年級轉換正確", (1, 1, "王小明") in pairs, str(pairs))
    check("阿拉伯數字年級也支援", (9, 10, "陳大文") in pairs, str(pairs))
    check("過濾雜訊詞", all(t not in ("編班", "作業", "公告", "結果", "編配") for _, _, t in pairs))


def _fake_response(html: str, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = html
    return resp


def test_xoops_calendar_scraper():
    print("test_xoops_calendar_scraper")
    calendar_index_html = """
    <html><body>
      <div class="tad_cal">
        <a href="event.php?sn=101">10/1 校慶運動會</a>
        <a href="event.php?sn=102">10/15 期中考</a>
        <a href="?op=cal&month=11&year=2025">下個月</a>
      </div>
    </body></html>
    """
    event_101_html = "<html><head><title>校慶運動會</title></head><body>114年10月1日 校慶運動會</body></html>"
    event_102_html = "<html><head><title>期中考</title></head><body>114年10月15日 期中考</body></html>"
    next_month_html = "<html><body>本月無其他事件</body></html>"

    responses = {
        "https://example.tyc.edu.tw/modules/tad_cal/": calendar_index_html,
        "https://example.tyc.edu.tw/modules/tad_cal/event.php?sn=101": event_101_html,
        "https://example.tyc.edu.tw/modules/tad_cal/event.php?sn=102": event_102_html,
        "https://example.tyc.edu.tw/modules/tad_cal/?op=cal&month=11&year=2025": next_month_html,
    }

    def fake_get(session, url, **kwargs):
        html = responses.get(url)
        if html is None:
            return _fake_response("", status=404)
        return _fake_response(html)

    school = {
        "id": "test_school",
        "short_name": "測試國小",
        "cms_type": "xoops",
        "calendar_url": "https://example.tyc.edu.tw/modules/tad_cal/",
        "roster_list_url": None,
    }

    with patch("scrapers.xoops_scraper.polite_get", side_effect=fake_get):
        scraper = XoopsScraper(school, session=MagicMock())
        outcome = scraper.scrape_calendar()

    check("狀態為success", outcome.status == "success", outcome.message)
    check("找到2筆行事曆事件", len(outcome.calendar_events) == 2, str(outcome.calendar_events))
    titles = {e.title for e in outcome.calendar_events}
    check("標題正確", titles == {"校慶運動會", "期中考"}, str(titles))
    dates = {e.start_date for e in outcome.calendar_events}
    check("日期解析正確", dates == {"2025-10-01", "2025-10-15"}, str(dates))


def test_xoops_roster_scraper():
    print("test_xoops_roster_scraper")
    news_list_html = """
    <html><body>
      <a href="index.php?nsn=501">113學年度新生暨三、五年級學生公開編班暨導師編配作業公告</a>
      <a href="index.php?nsn=502">校慶運動會活動紀實</a>
    </body></html>
    """
    article_html = """
    <html><body>
      <h1>113學年度新生暨三、五年級學生公開編班暨導師編配作業公告</h1>
      <p>一年1班 導師 王小明　一年2班 導師 林美玲　三年1班 導師 張志豪</p>
    </body></html>
    """

    responses = {
        "https://example.tyc.edu.tw/modules/tadnews/": news_list_html,
        "https://example.tyc.edu.tw/modules/tadnews/index.php?nsn=501": article_html,
    }

    def fake_get(session, url, **kwargs):
        html = responses.get(url)
        if html is None:
            return _fake_response("", status=404)
        return _fake_response(html)

    school = {
        "id": "test_school",
        "short_name": "測試國小",
        "cms_type": "xoops",
        "calendar_url": None,
        "roster_list_url": "https://example.tyc.edu.tw/modules/tadnews/",
    }

    with patch("scrapers.xoops_scraper.polite_get", side_effect=fake_get):
        scraper = XoopsScraper(school, session=MagicMock())
        outcome = scraper.scrape_roster()

    check("狀態為success", outcome.status == "success", outcome.message)
    check("找到3筆班級-導師資料", len(outcome.class_assignments) == 3, str(outcome.class_assignments))
    check("學年度正確解析", all(a.school_year == "113" for a in outcome.class_assignments))
    names = {(a.grade, a.class_number, a.teacher_name) for a in outcome.class_assignments}
    check("內容正確", names == {(1, 1, "王小明"), (1, 2, "林美玲"), (3, 1, "張志豪")}, str(names))
    check("非公告文章被正確排除", "校慶運動會活動紀實" not in [a.source_url for a in outcome.class_assignments])


def test_carry_over_logic():
    print("test_carry_over_logic")
    import sqlite3
    from db.store import apply_carry_over, upsert_class_assignments
    from scrapers.base import ClassAssignment

    conn = sqlite3.connect(":memory:")
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO schools (id, name, short_name, level, district, base_url, cms_type, updated_at) "
        "VALUES ('t1','測試國小','測試國小','elementary','桃園區','https://x/','xoops','2025-01-01')"
    )
    # 113學年度：只公告1、3、5年級（模擬國小常態編班慣例）
    upsert_class_assignments(conn, "t1", [
        ClassAssignment(school_year="113", grade=1, class_number=1, teacher_name="王小明"),
        ClassAssignment(school_year="113", grade=3, class_number=1, teacher_name="舊三年級老師"),
        ClassAssignment(school_year="113", grade=5, class_number=1, teacher_name="舊五年級老師"),
    ])
    # 114學年度：只公告1、3、5年級的新編班，2、4、6年級應該靠carry-over補上
    upsert_class_assignments(conn, "t1", [
        ClassAssignment(school_year="114", grade=1, class_number=1, teacher_name="新一年級老師"),
        ClassAssignment(school_year="114", grade=3, class_number=1, teacher_name="新三年級老師"),
        ClassAssignment(school_year="114", grade=5, class_number=1, teacher_name="新五年級老師"),
    ])
    carried = apply_carry_over(conn, "t1")
    check("carry-over補了2筆(2年級、4年級，6年級因113無5年級以外資料所以補不出來？)",
          carried >= 1, f"carried={carried}")

    row = conn.execute(
        "SELECT teacher_name, is_carried_over FROM class_teacher_assignments "
        "WHERE school_id='t1' AND school_year='114' AND grade=2 AND class_number=1"
    ).fetchone()
    check("2年級延續113年1年級的王小明", row == ("王小明", 1), str(row))

    row4 = conn.execute(
        "SELECT teacher_name, is_carried_over FROM class_teacher_assignments "
        "WHERE school_id='t1' AND school_year='114' AND grade=4 AND class_number=1"
    ).fetchone()
    check("4年級延續113年3年級的舊三年級老師", row4 == ("舊三年級老師", 1), str(row4))
    conn.close()


def test_roster_index_php_fallback():
    print("test_roster_index_php_fallback")
    # 模擬真實跑到的狀況：bare目錄網址(tadnews/)掃不到文章連結，但補上index.php後就找得到
    bare_dir_html = "<html><body><p>這是模組首頁，沒有直接列出文章連結</p></body></html>"
    index_php_html = """
    <html><body>
      <a href="index.php?nsn=901">113學年度新生編班暨導師編配結果公告</a>
    </body></html>
    """
    article_html = "<html><body><h1>編班公告</h1><p>一年1班 導師 陳小美</p></body></html>"

    responses = {
        "https://example.tyc.edu.tw/modules/tadnews/": bare_dir_html,
        "https://example.tyc.edu.tw/modules/tadnews/index.php": index_php_html,
        "https://example.tyc.edu.tw/modules/tadnews/index.php?nsn=901": article_html,
    }

    def fake_get(session, url, **kwargs):
        html = responses.get(url)
        if html is None:
            return _fake_response("", status=404)
        return _fake_response(html)

    school = {
        "id": "test_school", "short_name": "測試國小", "cms_type": "xoops",
        "calendar_url": None,
        "roster_list_url": "https://example.tyc.edu.tw/modules/tadnews/",
    }
    with patch("scrapers.xoops_scraper.polite_get", side_effect=fake_get):
        scraper = XoopsScraper(school, session=MagicMock())
        outcome = scraper.scrape_roster()

    check("index.php備援後狀態為success", outcome.status == "success", outcome.message)
    check("解析出1筆", len(outcome.class_assignments) == 1, str(outcome.class_assignments))


def test_calendar_pdf_announcement_fallback():
    print("test_calendar_pdf_announcement_fallback")
    # 模擬慈文國中/文昌國中的狀況：沒有tad_cal，行事曆是公告夾帶純文字內容（不含PDF二進位，簡化測試）
    tad_cal_empty_html = "<html><body><p>本模組沒有任何 event.php 連結</p></body></html>"
    news_list_html = """
    <html><body>
      <a href="index.php?nsn=501">115學年度上學期行事曆</a>
      <a href="index.php?nsn=502">畢業典禮花絮</a>
    </body></html>
    """
    calendar_article_html = "<html><body><h1>115學年度上學期行事曆</h1><p>114年8月30日 開學日　114年9月1日 始業式</p></body></html>"

    responses = {
        "https://example.tyc.edu.tw/modules/tadnews/": news_list_html,
        "https://example.tyc.edu.tw/modules/tadnews/index.php?nsn=501": calendar_article_html,
    }

    def fake_get(session, url, **kwargs):
        html = responses.get(url)
        if html is None:
            return _fake_response("", status=404)
        return _fake_response(html)

    school = {
        "id": "test_school", "short_name": "測試國中", "cms_type": "xoops",
        "calendar_url": "https://example.tyc.edu.tw/modules/tadnews/",
        "roster_list_url": None,
    }
    with patch("scrapers.xoops_scraper.polite_get", side_effect=fake_get):
        scraper = XoopsScraper(school, session=MagicMock())
        outcome = scraper.scrape_calendar()

    check("tad_cal沒有事件連結時能fallback成功找到事件", len(outcome.calendar_events) >= 2, outcome.message)
    dates = {e.start_date for e in outcome.calendar_events}
    check("從公告內文寬鬆解析出日期", "2025-08-30" in dates and "2025-09-01" in dates, str(dates))


def test_dead_host_circuit_breaker():
    print("test_dead_host_circuit_breaker")
    # 模擬完全連不上的網域(建國國中在真實跑的時候就是這樣)：
    # calendar(tad_cal)、calendar公告備援、roster 三條路徑理論上都會各打一次這個主機，
    # 但確認只有第一次真的呼叫 polite_get，之後都被 _dead_hosts 擋掉，不會再逾時重試
    import requests as requests_module

    call_count = {"n": 0}

    def fake_get_always_times_out(session, url, **kwargs):
        call_count["n"] += 1
        raise requests_module.exceptions.ConnectTimeout("simulated dead host")

    school = {
        "id": "dead_school", "short_name": "測試死站", "cms_type": "xoops",
        "calendar_url": "https://dead.example.tw/modules/tad_cal/",
        "roster_list_url": "https://dead.example.tw/modules/tadnews/",
    }
    with patch("scrapers.xoops_scraper.polite_get", side_effect=fake_get_always_times_out):
        scraper = XoopsScraper(school, session=MagicMock())
        cal_outcome = scraper.scrape_calendar()
        roster_outcome = scraper.scrape_roster()

    check("calendar狀態為failed", cal_outcome.status == "failed", cal_outcome.message)
    check("roster狀態為failed", roster_outcome.status == "failed", roster_outcome.message)
    check("死主機只被真的呼叫過一次，之後都被circuit breaker擋下",
          call_count["n"] == 1, f"實際呼叫次數={call_count['n']}")


def test_pdf_failure_does_not_poison_host():
    print("test_pdf_failure_does_not_poison_host")
    # 模擬中興國中在真實跑的時候發生的狀況：主站頁面都連得上，但公告裡某個PDF附件
    # 網址連不上（Network unreachable）。這種情況不該把整個主機標記為死站，
    # 否則後續 roster 對同一主機的正常頁面也會被circuit breaker誤擋
    import requests as requests_module

    news_list_html = """
    <html><body>
      <a href="index.php?nsn=601">115學年度編班暨導師編配結果</a>
    </body></html>
    """
    article_html = """
    <html><body>
      <h1>115學年度編班暨導師編配結果</h1>
      <p>一年1班 導師 王小明</p>
      <a href="/gov/unreachable.pdf">附件</a>
    </body></html>
    """

    def fake_get(session, url, **kwargs):
        if url.endswith("unreachable.pdf"):
            raise requests_module.exceptions.ConnectionError("simulated network unreachable")
        if "index.php?nsn=601" in url:
            return _fake_response(article_html)
        if url == "https://example.tyc.edu.tw/modules/tadnews/":
            return _fake_response(news_list_html)
        return _fake_response("", status=404)

    school = {
        "id": "test_school", "short_name": "測試國中", "cms_type": "xoops",
        "calendar_url": None,
        "roster_list_url": "https://example.tyc.edu.tw/modules/tadnews/",
    }
    with patch("scrapers.xoops_scraper.polite_get", side_effect=fake_get):
        scraper = XoopsScraper(school, session=MagicMock())
        outcome = scraper.scrape_roster()

    check("PDF連不上不影響HTML內文已解析出的班級-導師資料",
          outcome.status == "success" and len(outcome.class_assignments) == 1, outcome.message)
    check("PDF失敗不會把主機標記為死站", "example.tyc.edu.tw" not in scraper._dead_hosts, scraper._dead_hosts)


if __name__ == "__main__":
    test_date_parsing()
    test_class_teacher_regex()
    test_xoops_calendar_scraper()
    test_xoops_roster_scraper()
    test_carry_over_logic()
    test_roster_index_php_fallback()
    test_calendar_pdf_announcement_fallback()
    test_dead_host_circuit_breaker()
    test_pdf_failure_does_not_poison_host()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
