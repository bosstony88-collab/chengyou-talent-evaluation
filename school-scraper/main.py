#!/usr/bin/env python3
"""程優教育科技 - 學校公開資訊爬蟲主程式。

用法：
    python main.py                  # 爬取 schools.json 內所有學校
    python main.py --school yes_es  # 只爬單一學校（除錯用）
    python main.py --only-calendar  # 只跑行事曆，不跑班級編制
    python main.py --only-roster    # 只跑班級編制，不跑行事曆

設計原則：單一學校爬取失敗（連線錯誤、解析失敗、任何未預期例外）都不能讓整體流程中斷，
一律記錄到 scrape_log 並繼續下一所學校，最後印出總結報告方便在 GitHub Actions log 檢視。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from db.init_db import init_db, DB_PATH, SCHOOLS_JSON_PATH  # noqa: E402
from db.store import apply_carry_over, log_scrape, upsert_calendar_events, upsert_class_assignments  # noqa: E402
from scrapers import get_scraper  # noqa: E402
from scrapers.http_utils import build_session  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("school_scraper")


def run(school_filter: str | None, do_calendar: bool, do_roster: bool) -> dict:
    schools = json.loads(SCHOOLS_JSON_PATH.read_text(encoding="utf-8"))["schools"]
    if school_filter:
        schools = [s for s in schools if s["id"] == school_filter]
        if not schools:
            raise SystemExit(f"找不到學校 id={school_filter}，請檢查 config/schools.json")

    conn = init_db(DB_PATH)
    session = build_session()

    summary = {"success": 0, "partial": 0, "failed": 0, "skipped": 0}

    for school in schools:
        scraper = get_scraper(school, session)
        logger.info("=== 開始處理 %s（%s，cms=%s）===", school["short_name"], school["id"], school["cms_type"])

        if do_calendar:
            outcome = _run_target(scraper.scrape_calendar, school)
            summary[outcome.status] = summary.get(outcome.status, 0) + 1
            log_scrape(conn, school["id"], "calendar", outcome.status, outcome.message)
            if outcome.calendar_events:
                n = upsert_calendar_events(conn, school["id"], outcome.calendar_events)
                logger.info("[%s] 行事曆：%s（寫入/更新 %d 筆）", school["id"], outcome.message, n)
            else:
                logger.info("[%s] 行事曆：%s", school["id"], outcome.message)
            conn.commit()

        if do_roster:
            outcome = _run_target(scraper.scrape_roster, school)
            summary[outcome.status] = summary.get(outcome.status, 0) + 1
            log_scrape(conn, school["id"], "roster", outcome.status, outcome.message)
            if outcome.class_assignments:
                n = upsert_class_assignments(conn, school["id"], outcome.class_assignments)
                logger.info("[%s] 班級編制：%s（寫入/更新 %d 筆）", school["id"], outcome.message, n)
            else:
                logger.info("[%s] 班級編制：%s", school["id"], outcome.message)

            carried = apply_carry_over(conn, school["id"])
            if carried:
                logger.info("[%s] 延續前次資料補上 %d 筆未公告年級（is_carried_over=1）", school["id"], carried)
            conn.commit()

    conn.close()
    return summary


def _run_target(fn, school):
    """包一層 try/except，任何未預期例外都不能讓整體爬蟲中斷。"""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - 這裡刻意 catch-all，單校錯誤不該中斷整體流程
        logger.exception("[%s] 發生未預期例外", school["id"])
        from scrapers.base import ScrapeOutcome
        return ScrapeOutcome(target="unknown", status="failed", message=f"未預期例外: {exc}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--school", help="只爬取指定 school id（見 config/schools.json）")
    parser.add_argument("--only-calendar", action="store_true", help="只爬行事曆")
    parser.add_argument("--only-roster", action="store_true", help="只爬班級編制")
    args = parser.parse_args()

    do_calendar = not args.only_roster
    do_roster = not args.only_calendar

    summary = run(args.school, do_calendar, do_roster)

    logger.info("=== 執行完畢 === success=%d partial=%d failed=%d skipped=%d",
                summary.get("success", 0), summary.get("partial", 0),
                summary.get("failed", 0), summary.get("skipped", 0))


if __name__ == "__main__":
    main()
