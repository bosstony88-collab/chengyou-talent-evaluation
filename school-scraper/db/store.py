"""DB 寫入邏輯：行事曆事件 upsert、班級-導師 upsert，以及「未公告年級延續前次資料」的 carry-over 邏輯。

carry-over 假設依據台灣國中小常見的「包班制」慣例：同一屆學生從入學年級一路到畢業年級，
通常由同一位導師帶班（班級編號也維持不變），所以某學年度只公告新編班年級時，
其餘年級可以用「去年 grade-1 的同班號」資料延續下來。這只是慣例推論，不保證每校都適用，
故一律標記 is_carried_over=1，供前端呈現時明確告知使用者這筆資料是推算的、非該學年度官方公告。
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from scrapers.base import CalendarEvent, ClassAssignment, MaskedStudentEntry
from scrapers.pdf_utils import contains_mask

logger = logging.getLogger("school_scraper")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_calendar_events(conn: sqlite3.Connection, school_id: str, events: list[CalendarEvent]) -> int:
    ts = now_iso()
    count = 0
    for e in events:
        conn.execute(
            """
            INSERT INTO calendar_events
                (school_id, school_year, semester, title, start_date, end_date, raw_text, source_url, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(school_id, title, start_date, source_url) DO UPDATE SET
                scraped_at = excluded.scraped_at,
                end_date = excluded.end_date,
                school_year = excluded.school_year,
                semester = excluded.semester
            """,
            (school_id, e.school_year, e.semester, e.title, e.start_date, e.end_date, e.raw_text, e.source_url, ts),
        )
        count += 1
    return count


def upsert_class_assignments(conn: sqlite3.Connection, school_id: str, assignments: list[ClassAssignment]) -> int:
    ts = now_iso()
    count = 0
    for a in assignments:
        conn.execute(
            """
            INSERT INTO class_teacher_assignments
                (school_id, school_year, grade, class_number, teacher_name, is_carried_over, source_url, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(school_id, school_year, grade, class_number) DO UPDATE SET
                teacher_name = excluded.teacher_name,
                is_carried_over = excluded.is_carried_over,
                source_url = excluded.source_url,
                scraped_at = excluded.scraped_at
            """,
            (school_id, a.school_year, a.grade, a.class_number, a.teacher_name,
             int(a.is_carried_over), a.source_url, ts),
        )
        count += 1
    return count


def upsert_student_entries(conn: sqlite3.Connection, school_id: str, entries: list[MaskedStudentEntry]) -> tuple[int, int]:
    """寫入遮罩學生名單。隱私防護（不可繞過）：姓名不含遮罩符號者一律拒收，
    保證資料庫結構上不可能存到完整學生姓名。同一班有新名單時整班先刪後插，
    避免名單縮短時留下舊的殘留項目。回傳 (寫入筆數, 因未遮罩被拒筆數)。"""
    ts = now_iso()
    stored = 0
    rejected_unmasked = 0

    by_class: dict[tuple[str, int, int], list[MaskedStudentEntry]] = {}
    for e in entries:
        if not contains_mask(e.masked_name):
            rejected_unmasked += 1
            continue
        by_class.setdefault((e.school_year, e.grade, e.class_number), []).append(e)

    if rejected_unmasked:
        logger.warning(
            "[%s] 有 %d 筆學生姓名不含遮罩符號，依隱私防護規則拒絕入庫（本系統只收學校已遮罩的姓名）",
            school_id, rejected_unmasked,
        )

    for (school_year, grade, class_number), class_entries in by_class.items():
        conn.execute(
            "DELETE FROM student_roster_entries "
            "WHERE school_id = ? AND school_year = ? AND grade = ? AND class_number = ?",
            (school_id, school_year, grade, class_number),
        )
        for e in class_entries:
            conn.execute(
                """
                INSERT INTO student_roster_entries
                    (school_id, school_year, grade, class_number, entry_index, masked_name, source_url, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (school_id, school_year, grade, class_number, e.entry_index, e.masked_name, e.source_url, ts),
            )
            stored += 1
    return stored, rejected_unmasked


def apply_carry_over(conn: sqlite3.Connection, school_id: str) -> int:
    """對於學校目前資料庫中最新學年度，把「當年沒被直接公告到」的年級，
    用前一學年度 grade-1 的同班號資料補上，標記 is_carried_over=1。"""
    row = conn.execute(
        "SELECT MAX(CAST(school_year AS INTEGER)) FROM class_teacher_assignments WHERE school_id = ?",
        (school_id,),
    ).fetchone()
    if not row or row[0] is None:
        return 0
    latest_year = str(row[0])
    prev_year = str(int(latest_year) - 1)

    level_row = conn.execute("SELECT level FROM schools WHERE id = ?", (school_id,)).fetchone()
    if not level_row:
        return 0
    max_grade = 9 if level_row[0] == "junior_high" else 6

    existing_grades = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT grade FROM class_teacher_assignments WHERE school_id = ? AND school_year = ?",
            (school_id, latest_year),
        )
    }

    ts = now_iso()
    carried = 0
    for grade in range(2, max_grade + 1):
        if grade in existing_grades:
            continue
        prev_rows = conn.execute(
            "SELECT class_number, teacher_name, source_url FROM class_teacher_assignments "
            "WHERE school_id = ? AND school_year = ? AND grade = ?",
            (school_id, prev_year, grade - 1),
        ).fetchall()
        for class_number, teacher_name, source_url in prev_rows:
            cur = conn.execute(
                """
                INSERT INTO class_teacher_assignments
                    (school_id, school_year, grade, class_number, teacher_name, is_carried_over, source_url, scraped_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(school_id, school_year, grade, class_number) DO NOTHING
                """,
                (school_id, latest_year, grade, class_number, teacher_name, source_url, ts),
            )
            carried += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return carried


def log_scrape(conn: sqlite3.Connection, school_id: str, target: str, status: str, message: str) -> None:
    conn.execute(
        "INSERT INTO scrape_log (school_id, target, status, message, run_at) VALUES (?, ?, ?, ?, ?)",
        (school_id, target, status, message, now_iso()),
    )
