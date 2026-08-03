"""民國年/中文日期解析工具，用於行事曆事件。解析失敗一律回傳 None，由呼叫端把原始文字存進 raw_text。"""
from __future__ import annotations

import re
from datetime import date

_ROC_DATE = re.compile(r"(\d{2,3})[年/.-](\d{1,2})[月/.-](\d{1,2})[日]?")
_AD_DATE = re.compile(r"(\d{4})[年/.-](\d{1,2})[月/.-](\d{1,2})[日]?")


def roc_to_ad_year(roc_year: int) -> int:
    return roc_year + 1911


def parse_date_guess(text: str, default_ad_year: int | None = None) -> str | None:
    """嘗試從一段文字中解析出單一日期，回傳 ISO8601 (YYYY-MM-DD) 字串，失敗回傳 None。"""
    if not text:
        return None

    m = _AD_DATE.search(text)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        return _safe_iso(y, mo, d)

    m = _ROC_DATE.search(text)
    if m:
        roc_y, mo, d = (int(x) for x in m.groups())
        return _safe_iso(roc_to_ad_year(roc_y), mo, d)

    # 只有 "8/30" 這種月/日，沒有年份時，靠呼叫端傳入的學年度年份補上
    m = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", text)
    if m and default_ad_year:
        mo, d = (int(x) for x in m.groups())
        return _safe_iso(default_ad_year, mo, d)

    return None


def _safe_iso(y: int, mo: int, d: int) -> str | None:
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def school_year_to_ad_start_year(school_year: str) -> int | None:
    """民國學年度(例如 '114') -> 該學年度上學期所在的西元年（114學年度上學期通常是2025年8-9月開學）。"""
    try:
        return roc_to_ad_year(int(school_year))
    except (TypeError, ValueError):
        return None
