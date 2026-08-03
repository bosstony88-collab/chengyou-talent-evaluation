"""跨 CMS 類型共用的寬鬆擷取規則（用於 NSS、ASP legacy 等未知結構的頁面）。"""
from __future__ import annotations

import re

from .base import CalendarEvent
from .date_utils import parse_date_guess

_DATE_FRAGMENT_RE = re.compile(r"(\d{1,3}[年/.\-]\d{1,2}[月/.\-]\d{1,2}日?)")


def extract_events_heuristic(text: str, source_url: str) -> list[CalendarEvent]:
    """在文字中找日期片段＋鄰近文字當標題，去重。信心度低，僅供 partial 結果使用。"""
    events = []
    seen_dates = set()
    for m in _DATE_FRAGMENT_RE.finditer(text):
        date_str = parse_date_guess(m.group(1))
        if not date_str or date_str in seen_dates:
            continue
        seen_dates.add(date_str)
        start = max(0, m.start() - 5)
        end = min(len(text), m.end() + 25)
        snippet = text[start:end].strip()
        events.append(CalendarEvent(title=snippet, source_url=source_url, start_date=date_str, raw_text=snippet))
    return events
