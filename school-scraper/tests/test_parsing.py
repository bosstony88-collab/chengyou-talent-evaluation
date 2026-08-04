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


def test_masked_student_roster_parsing():
    print("test_masked_student_roster_parsing")
    from scrapers.pdf_utils import parse_masked_student_roster, contains_mask

    text = (
        "114學年度一年級新生編班結果 "
        "一年1班 導師 王小明 1 陳○宇 2 林○彤 3 歐陽○安 4 李○ "
        "一年2班 導師 李小華 1 張○豪 2 黃Ｏ庭 "
        "完整姓名不該被抓：許功蓋 陳大文 "
    )
    classes, unattributed = parse_masked_student_roster(text)
    as_dict = {(g, c): names for g, c, names in classes}

    check("切出2個班級", len(as_dict) == 2, str(as_dict))
    check("1班名單正確（含複姓、含2字名）",
          as_dict.get((1, 1)) == ["陳○宇", "林○彤", "歐陽○安", "李○"], str(as_dict.get((1, 1))))
    check("2班名單正確（含全形Ｏ遮罩）",
          as_dict.get((1, 2)) == ["張○豪", "黃Ｏ庭"], str(as_dict.get((1, 2))))
    check("完整姓名（無遮罩）不會被抓進名單",
          all(not any("許" in n or "大文" in n for n in names) for names in as_dict.values()))
    check("班級標頭前沒有遮罩姓名", unattributed == 0, str(unattributed))
    check("contains_mask 判斷正確", contains_mask("王○明") and not contains_mask("王小明"))


def test_masked_roster_class_number_formats():
    print("test_masked_roster_class_number_formats")
    # 第4次實跑發現慈文國小96個遮罩姓名全數「無法歸屬班級」——班號寫法是中文數字/全形，
    # 不是原本regex唯一支援的半形阿拉伯數字。驗證四種常見班號格式都能歸屬。
    from scrapers.pdf_utils import parse_masked_student_roster, parse_class_teacher_pairs

    text = (
        "114學年度編班結果 "
        "一年一班 陳○宇 林○彤 "          # 中文數字班號
        "一年十二班 張○豪 "               # 中文數字十位班號
        "２年３班 黃○庭 "                 # 全形數字
        "三年忠班 吳○蓁 "                 # 傳統班名
    )
    classes, unattributed = parse_masked_student_roster(text)
    as_dict = {(g, c): names for g, c, names in classes}
    check("中文數字班號可歸屬", as_dict.get((1, 1)) == ["陳○宇", "林○彤"], str(as_dict))
    check("中文數字十位班號(十二)正確轉12", as_dict.get((1, 12)) == ["張○豪"], str(as_dict))
    check("全形數字班號可歸屬", as_dict.get((2, 3)) == ["黃○庭"], str(as_dict))
    check("傳統班名(忠=1)可歸屬", as_dict.get((3, 1)) == ["吳○蓁"], str(as_dict))
    check("四種格式下無漏歸屬", unattributed == 0, str(unattributed))

    pairs = parse_class_teacher_pairs("三年五班 導師 王小明　１年２班 導師 李小華")
    check("導師解析也支援中文數字/全形班號",
          (3, 5, "王小明") in pairs and (1, 2, "李小華") in pairs, str(pairs))


def test_mask_chars_exclude_ascii_o_and_zero():
    print("test_mask_chars_exclude_ascii_o_and_zero")
    # 第6次實跑證實半形O/0會大量誤判：慈文國小避難地圖PDF的教室編號「東001」被當成96個
    # 遮罩姓名、大勇國小側欄的「南一Onebook」也中鏢。確認這類文字不再產生任何遮罩姓名。
    from scrapers.pdf_utils import parse_masked_student_roster

    noise = "南一Onebook 康軒電子書 東001 東102 西102 B1樓梯 避難空間 一年1班 陳○宇"
    classes, unattributed = parse_masked_student_roster(noise)
    as_dict = {(g, c): names for g, c, names in classes}
    check("教室編號/產品名不再誤判，只留真遮罩姓名",
          as_dict == {(1, 1): ["陳○宇"]} and unattributed == 0,
          f"{as_dict} unattributed={unattributed}")


def test_bare_class_header_with_default_grade():
    print("test_bare_class_header_with_default_grade")
    # 新生編班PDF常見「第1班」簡寫標頭（年級只寫在公告標題），需靠標題推斷的default_grade歸屬
    from scrapers.pdf_utils import parse_masked_student_roster, parse_single_grade_from_title

    text = "第1班 陳○宇 林○彤 第2班 張○豪"
    classes, _ = parse_masked_student_roster(text, default_grade=1)
    as_dict = {(g, c): names for g, c, names in classes}
    check("第N班簡寫式＋default_grade可歸屬",
          as_dict.get((1, 1)) == ["陳○宇", "林○彤"] and as_dict.get((1, 2)) == ["張○豪"], str(as_dict))

    classes_none, _ = parse_masked_student_roster(text, default_grade=None)
    check("沒有default_grade時第N班不冒險歸屬", classes_none == [], str(classes_none))

    check("標題單一年級推斷", parse_single_grade_from_title("114學年度一年級新生編班結果") == 1)
    check("標題多年級時不推斷", parse_single_grade_from_title("新生暨三、五年級編班") is None)
    check("標題僅新生時依學制推斷(國小=1)", parse_single_grade_from_title("114學年度新生編班公告", "elementary") == 1)
    check("標題僅新生時依學制推斷(國中=7)", parse_single_grade_from_title("114學年度新生編班公告", "junior_high") == 7)


def test_student_upsert_privacy_guard():
    print("test_student_upsert_privacy_guard")
    import sqlite3
    from db.store import upsert_student_entries
    from scrapers.base import MaskedStudentEntry

    conn = sqlite3.connect(":memory:")
    conn.executescript((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO schools (id, name, short_name, level, district, base_url, cms_type, updated_at) "
        "VALUES ('t1','測試國小','測試國小','elementary','桃園區','https://x/','xoops','2025-01-01')"
    )
    entries = [
        MaskedStudentEntry(school_year="114", grade=1, class_number=1, entry_index=0, masked_name="陳○宇"),
        MaskedStudentEntry(school_year="114", grade=1, class_number=1, entry_index=1, masked_name="王小明"),  # 未遮罩，必須被拒
        MaskedStudentEntry(school_year="114", grade=1, class_number=1, entry_index=2, masked_name="林○彤"),
    ]
    stored, rejected = upsert_student_entries(conn, "t1", entries)
    check("遮罩姓名有寫入", stored == 2, f"stored={stored}")
    check("未遮罩完整姓名被防護拒絕", rejected == 1, f"rejected={rejected}")
    rows = [r[0] for r in conn.execute("SELECT masked_name FROM student_roster_entries ORDER BY entry_index")]
    check("資料庫中完全沒有未遮罩姓名", rows == ["陳○宇", "林○彤"], str(rows))

    # 名單更新時整班先刪後插，不留舊殘留
    entries2 = [MaskedStudentEntry(school_year="114", grade=1, class_number=1, entry_index=0, masked_name="周○安")]
    upsert_student_entries(conn, "t1", entries2)
    rows2 = [r[0] for r in conn.execute("SELECT masked_name FROM student_roster_entries")]
    check("整班重寫不留舊資料", rows2 == ["周○安"], str(rows2))
    conn.close()


def test_xoops_roster_with_masked_students():
    print("test_xoops_roster_with_masked_students")
    news_list_html = """
    <html><body>
      <a href="index.php?nsn=701">114學年度新生編班暨導師編配結果</a>
    </body></html>
    """
    article_html = """
    <html><body>
      <h1>114學年度新生編班暨導師編配結果</h1>
      <p>一年1班 導師 王小明　學生名單：陳○宇 林○彤 李○</p>
      <p>一年2班 導師 李小華　學生名單：張○豪 黃○庭</p>
    </body></html>
    """
    responses = {
        "https://example.tyc.edu.tw/modules/tadnews/": news_list_html,
        "https://example.tyc.edu.tw/modules/tadnews/index.php?nsn=701": article_html,
    }

    def fake_get(session, url, **kwargs):
        html = responses.get(url)
        return _fake_response(html) if html is not None else _fake_response("", status=404)

    school = {
        "id": "test_school", "short_name": "測試國小", "cms_type": "xoops",
        "calendar_url": None,
        "roster_list_url": "https://example.tyc.edu.tw/modules/tadnews/",
    }
    with patch("scrapers.xoops_scraper.polite_get", side_effect=fake_get):
        scraper = XoopsScraper(school, session=MagicMock())
        outcome = scraper.scrape_roster()

    check("狀態為success", outcome.status == "success", outcome.message)
    check("導師資料照舊解析", len(outcome.class_assignments) == 2, str(outcome.class_assignments))
    check("遮罩學生名單共5筆", len(outcome.student_entries) == 5, str(len(outcome.student_entries)))
    cls11 = [e.masked_name for e in outcome.student_entries if e.class_number == 1]
    check("1班名單內容正確", cls11 == ["陳○宇", "林○彤", "李○"], str(cls11))
    check("所有入庫姓名皆含遮罩符號",
          all("○" in e.masked_name or "Ｏ" in e.masked_name for e in outcome.student_entries))


def test_masked_roster_requires_ban_character():
    print("test_masked_roster_requires_ban_character")
    from scrapers.pdf_utils import parse_masked_student_roster

    # 第6次實跑後仍發現慈文國小96個遮罩姓名「未歸屬」，追查發現來源是疏散地圖PDF
    # （東○○一、西○二 這類房間編號巧合符合遮罩pattern）。這類文字完全沒有「班」字，
    # 加上內容相關性過濾後應直接略過，不產生任何未歸屬統計，避免污染診斷log。
    evac_map_text = "避難空間配置圖 東○○一 電機房 樓梯 集會室 西○二 一F 室"
    classes, unattributed = parse_masked_student_roster(evac_map_text)
    check("沒有「班」字的文字直接略過，不產生未歸屬統計",
          classes == [] and unattributed == 0, f"classes={classes} unattributed={unattributed}")

    real_text = "一年1班 陳○宇 林○彤"
    classes2, unattributed2 = parse_masked_student_roster(real_text)
    check("真正的班級名單不受影響", classes2 == [(1, 1, ["陳○宇", "林○彤"])], str(classes2))


def test_masked_name_samples():
    print("test_masked_name_samples")
    from scrapers.pdf_utils import masked_name_samples

    text = "一年1班 陳○宇 林○彤 陳○宇"
    samples = masked_name_samples(text, limit=5)
    check("回傳去重後的比對樣本，供診斷log快速判斷真偽", samples == ["陳○宇", "林○彤"], str(samples))


def test_known_roster_article_urls():
    print("test_known_roster_article_urls")
    # 模擬會稽國中/慈文國小的狀況：schools.json研究階段已經人工確認過真實的編班公告連結
    # (known_roster_article_urls)，但該連結因為分頁/排序不在關鍵字掃描範圍內。
    # 驗證這種已知連結能不受限於列表頁掃描直接被抓取解析。
    news_list_html = """
    <html><body>
      <a href="index.php?nsn=999">校慶運動會花絮</a>
    </body></html>
    """
    known_article_html = """
    <html><body>
      <h1>112學年度編班暨導師編配名單結果</h1>
      <p>一年1班 導師 王小明　學生名單：陳○宇 林○彤</p>
    </body></html>
    """
    responses = {
        "https://example.tyc.edu.tw/modules/tadnews/": news_list_html,
        "https://example.tyc.edu.tw/modules/tadnews/index.php?nsn=13416": known_article_html,
    }

    def fake_get(session, url, **kwargs):
        html = responses.get(url)
        return _fake_response(html) if html is not None else _fake_response("", status=404)

    school = {
        "id": "test_school", "short_name": "測試國中", "cms_type": "xoops",
        "calendar_url": None,
        "roster_list_url": "https://example.tyc.edu.tw/modules/tadnews/",
        "known_roster_article_urls": ["https://example.tyc.edu.tw/modules/tadnews/index.php?nsn=13416"],
    }
    with patch("scrapers.xoops_scraper.polite_get", side_effect=fake_get):
        scraper = XoopsScraper(school, session=MagicMock())
        outcome = scraper.scrape_roster()

    check("known_roster_article_urls不受限關鍵字掃描仍能解析", outcome.status == "success", outcome.message)
    check("班級-導師資料正確",
          len(outcome.class_assignments) == 1 and outcome.class_assignments[0].teacher_name == "王小明",
          str(outcome.class_assignments))
    check("遮罩學生名單也一併解析出", len(outcome.student_entries) == 2, str(outcome.student_entries))


def test_roster_list_url_pointing_directly_to_article():
    print("test_roster_list_url_pointing_directly_to_article")
    # 模擬永順國小的狀況：roster_list_url本身就是已知公告網址(page.php?ncsn=8&nsn=11)，
    # 不是列表頁——不該被當成「列表頁裡找文章連結」，而要直接當成已知公告處理
    article_html = """
    <html><body>
      <h1>113學年度新生編班公告</h1>
      <p>一年1班 導師 陳小美　學生名單：張○豪 黃○庭</p>
    </body></html>
    """
    responses = {
        "https://example.tyc.edu.tw/modules/tadnews/page.php?ncsn=8&nsn=11": article_html,
    }

    def fake_get(session, url, **kwargs):
        html = responses.get(url)
        return _fake_response(html) if html is not None else _fake_response("", status=404)

    school = {
        "id": "test_school", "short_name": "測試國小", "cms_type": "xoops",
        "calendar_url": None,
        "roster_list_url": "https://example.tyc.edu.tw/modules/tadnews/page.php?ncsn=8&nsn=11",
    }
    with patch("scrapers.xoops_scraper.polite_get", side_effect=fake_get):
        scraper = XoopsScraper(school, session=MagicMock())
        outcome = scraper.scrape_roster()

    check("roster_list_url本身是文章網址時能直接解析", outcome.status == "success", outcome.message)
    check("班級-導師資料正確", len(outcome.class_assignments) == 1, str(outcome.class_assignments))
    check("遮罩學生名單正確", len(outcome.student_entries) == 2, str(outcome.student_entries))


def test_masked_name_excludes_page_reference_placeholder():
    print("test_masked_name_excludes_page_reference_placeholder")
    # 實跑發現：慈文國小的課程計畫PDF（跟編班公告連結在一起，但內容完全不相關）
    # 大量出現「詳見第○○頁」這類頁碼佔位符，恰好符合遮罩姓名pattern，
    # 且文中本來就有「普通班」「資源班」等詞彙，無法被"班"字內容過濾擋掉。
    # 驗證「第...頁」這種頁碼佔位樣式會被過濾，不算進姓名或未歸屬統計。
    from scrapers.pdf_utils import parse_masked_student_roster, masked_name_samples

    text = "普通班課程規劃如第○○頁總體課程節數總表，詳見第○頁 一年1班 陳○宇"
    classes, unattributed = parse_masked_student_roster(text)
    as_dict = {(g, c): names for g, c, names in classes}
    check("頁碼佔位符不算進未歸屬統計、也不混進班級名單",
          as_dict == {(1, 1): ["陳○宇"]} and unattributed == 0,
          f"{as_dict} unattributed={unattributed}")

    samples = masked_name_samples("詳見第○○頁 陳○宇")
    check("masked_name_samples也濾掉頁碼佔位符", samples == ["陳○宇"], str(samples))


def test_roster_dedups_and_skips_curriculum_plan_pdf():
    print("test_roster_dedups_and_skips_curriculum_plan_pdf")
    # 實跑發現慈文國小同一份「課程計畫.pdf」被4篇候選公告重複連結，各自重新下載+解析，
    # 拖慢單校爬取時間達16分鐘。驗證：(1) 課程計畫類PDF直接依檔名跳過不下載，
    # (2) 就算沒被檔名擋到，同一個PDF網址在同一次roster爬取中只會下載一次
    news_list_html = """
    <html><body>
      <a href="index.php?nsn=801">113學年度編班暨導師編配公告一</a>
      <a href="index.php?nsn=802">113學年度編班暨導師編配公告二</a>
    </body></html>
    """
    article1_html = """
    <html><body><h1>113學年度編班暨導師編配公告一</h1>
      <p>一年1班 導師 王小明</p>
      <a href="/uploads/113%E5%AD%B8%E5%B9%B4%E8%AA%B2%E7%A8%8B%E8%A8%88%E7%95%AB.pdf">課程計畫PDF(檔名網址編碼)</a>
      <a href="/uploads/shared_attachment.pdf">共用附件</a>
    </body></html>
    """
    article2_html = """
    <html><body><h1>113學年度編班暨導師編配公告二</h1>
      <p>一年2班 導師 李小華</p>
      <a href="/uploads/shared_attachment.pdf">共用附件</a>
    </body></html>
    """
    fetched_urls = []

    def fake_get(session, url, **kwargs):
        fetched_urls.append(url)
        if "shared_attachment.pdf" in url:
            return _fake_response("dummy pdf bytes not actually a pdf")
        if url == "https://example.tyc.edu.tw/modules/tadnews/":
            return _fake_response(news_list_html)
        if "nsn=801" in url:
            return _fake_response(article1_html)
        if "nsn=802" in url:
            return _fake_response(article2_html)
        return _fake_response("", status=404)

    school = {
        "id": "test_school", "short_name": "測試國小", "cms_type": "xoops",
        "calendar_url": None,
        "roster_list_url": "https://example.tyc.edu.tw/modules/tadnews/",
    }
    with patch("scrapers.xoops_scraper.polite_get", side_effect=fake_get), \
         patch("scrapers.xoops_scraper.extract_pdf_text", return_value=""):
        scraper = XoopsScraper(school, session=MagicMock())
        outcome = scraper.scrape_roster()

    from urllib.parse import unquote as _unquote
    check("課程計畫PDF完全沒被下載（檔名直接跳過）",
          not any("課程計畫" in _unquote(u) for u in fetched_urls), str(fetched_urls))
    check("共用附件PDF只下載一次，即使被2篇公告連結",
          sum(1 for u in fetched_urls if "shared_attachment.pdf" in u) == 1, str(fetched_urls))
    check("班級-導師資料仍正確解析出2筆", len(outcome.class_assignments) == 2, str(outcome.class_assignments))


def test_class_teacher_table_format():
    print("test_class_teacher_table_format")
    # 第9次實跑於同德國中真實115學年度新生導師名單PDF發現的表格格式：
    # 「班級 導師」表頭 + 「NNN 姓名」逐行（NNN=年級1碼+班號2碼相連），跟散文式完全不同。
    # 未定案導師會用「[科目] 新進教師」佔位，不是真姓名，不該被收錄。
    from scrapers.pdf_utils import parse_class_teacher_table

    text = (
        "同德國中115學年度七年級新生導師名單\n"
        "班級 導師\n"
        "701 國文 新進教師1\n"
        "702 林○偉\n"
        "703 黃○音\n"
        "704 程○鈴\n"
        "705 連○娟\n"
        "706 理化 新進教師\n"
    )
    pairs = parse_class_teacher_table(text)
    check("解析出4筆真實姓名（未定案佔位2筆被排除）", len(pairs) == 4, str(pairs))
    check("班級代碼正確拆解為年級+班號",
          (7, 2, "林○偉") in pairs and (7, 3, "黃○音") in pairs
          and (7, 4, "程○鈴") in pairs and (7, 5, "連○娟") in pairs, str(pairs))
    check("「[科目] 新進教師」佔位不被當成姓名",
          not any(c == 1 for g, c, t in pairs), str(pairs))

    check("沒有「班級 導師」表頭時完全不啟用，避免誤判", parse_class_teacher_table("115學年度公告 701 測試") == [])

    # 防呆：確認不會把「115 學年度」（PDF擷取常見的數字與文字間帶空格）誤判成班級代碼
    noisy = "班級 導師\n701 林○偉\n本名單為 115 學年度公告內容，如有異動另行通知"
    pairs_noisy = parse_class_teacher_table(noisy)
    check("「115 學年度」不會被誤判成(年級1,班號15)",
          not any(g == 1 and c == 15 for g, c, _ in pairs_noisy), str(pairs_noisy))


def test_roster_keyword_pagination_fallback():
    print("test_roster_keyword_pagination_fallback")
    # 模擬會稽國中在真實跑的時候發生的狀況：公告列表首頁40篇掃不到編班關鍵字
    # （被之後累積的其他公告擠到後面分頁去了），需要跟著分頁連結(start=N)往後找
    page1_html = """
    <html><body>
      <a href="index.php?nsn=801">校園安全演練紀實</a>
      <a href="index.php?start=20">下一頁</a>
    </body></html>
    """
    page2_html = """
    <html><body>
      <a href="index.php?nsn=701">113學年度編班暨導師編配結果</a>
    </body></html>
    """
    article_html = "<html><body><h1>113學年度編班暨導師編配結果</h1><p>一年1班 導師 王小明</p></body></html>"

    responses = {
        "https://example.tyc.edu.tw/modules/tadnews/": page1_html,
        "https://example.tyc.edu.tw/modules/tadnews/index.php?start=20": page2_html,
        "https://example.tyc.edu.tw/modules/tadnews/index.php?nsn=701": article_html,
    }

    def fake_get(session, url, **kwargs):
        html = responses.get(url)
        return _fake_response(html) if html is not None else _fake_response("", status=404)

    school = {
        "id": "test_school", "short_name": "測試國中", "cms_type": "xoops",
        "calendar_url": None,
        "roster_list_url": "https://example.tyc.edu.tw/modules/tadnews/",
    }
    with patch("scrapers.xoops_scraper.polite_get", side_effect=fake_get):
        scraper = XoopsScraper(school, session=MagicMock())
        outcome = scraper.scrape_roster()

    check("首頁掃不到關鍵字時會跟著分頁連結往後找", outcome.status == "success", outcome.message)
    check("分頁上找到的編班資料正確",
          len(outcome.class_assignments) == 1 and outcome.class_assignments[0].teacher_name == "王小明",
          str(outcome.class_assignments))


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
    test_masked_student_roster_parsing()
    test_masked_roster_class_number_formats()
    test_mask_chars_exclude_ascii_o_and_zero()
    test_bare_class_header_with_default_grade()
    test_student_upsert_privacy_guard()
    test_xoops_roster_with_masked_students()
    test_masked_roster_requires_ban_character()
    test_masked_name_samples()
    test_known_roster_article_urls()
    test_roster_list_url_pointing_directly_to_article()
    test_masked_name_excludes_page_reference_placeholder()
    test_roster_dedups_and_skips_curriculum_plan_pdf()
    test_class_teacher_table_format()
    test_roster_keyword_pagination_fallback()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
