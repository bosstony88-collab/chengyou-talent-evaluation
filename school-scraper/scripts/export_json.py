#!/usr/bin/env python3
"""把 SQLite 資料庫匯出成單一靜態 JSON，供前端查詢頁面讀取（沿用 repo 既有 GitHub Pages 靜態站模式，
不需要另外架設 API 伺服器）。"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from db.init_db import DB_PATH  # noqa: E402

OUTPUT_PATH = ROOT / "data" / "export" / "data.json"


def export():
    if not DB_PATH.exists():
        raise SystemExit(f"找不到資料庫 {DB_PATH}，請先執行 python main.py")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    schools = [dict(r) for r in conn.execute("SELECT * FROM schools ORDER BY level, id")]

    for school in schools:
        school_id = school["id"]

        events = [
            dict(r) for r in conn.execute(
                "SELECT title, start_date, end_date, school_year, semester, source_url "
                "FROM calendar_events WHERE school_id = ? ORDER BY start_date IS NULL, start_date",
                (school_id,),
            )
        ]
        school["calendar_events"] = events

        assignments = [
            dict(r) for r in conn.execute(
                "SELECT school_year, grade, class_number, teacher_name, is_carried_over, source_url "
                "FROM class_teacher_assignments WHERE school_id = ? "
                "ORDER BY school_year DESC, grade, class_number",
                (school_id,),
            )
        ]
        for a in assignments:
            a["is_carried_over"] = bool(a["is_carried_over"])
        school["class_teacher_assignments"] = assignments

        # 遮罩學生名單：資料庫層已保證只含學校官網公告上本來就遮罩過的姓名
        student_roster = [
            dict(r) for r in conn.execute(
                "SELECT school_year, grade, class_number, entry_index, masked_name, source_url "
                "FROM student_roster_entries WHERE school_id = ? "
                "ORDER BY school_year DESC, grade, class_number, entry_index",
                (school_id,),
            )
        ]
        school["student_roster"] = student_roster

        latest_log = conn.execute(
            "SELECT target, status, message, run_at FROM scrape_log "
            "WHERE school_id = ? ORDER BY run_at DESC LIMIT 4",
            (school_id,),
        ).fetchall()
        school["last_scrape_log"] = [dict(r) for r in latest_log]

    conn.close()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "school_count": len(schools),
        "schools": schools,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已匯出 {len(schools)} 所學校資料到 {OUTPUT_PATH}")


if __name__ == "__main__":
    export()
