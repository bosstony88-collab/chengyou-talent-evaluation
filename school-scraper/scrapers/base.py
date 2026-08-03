"""共用資料結構與爬蟲基底類別。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CalendarEvent:
    title: str
    source_url: str
    start_date: Optional[str] = None   # ISO8601 date (YYYY-MM-DD)，解析不出來就留 None
    end_date: Optional[str] = None
    school_year: Optional[str] = None  # 民國學年度，例如 "114"
    semester: Optional[str] = None
    raw_text: Optional[str] = None


@dataclass
class ClassAssignment:
    school_year: str
    grade: int
    class_number: int
    teacher_name: Optional[str] = None
    is_carried_over: bool = False
    source_url: Optional[str] = None


@dataclass
class ScrapeOutcome:
    """單一目標（calendar 或 roster）的爬取結果。"""
    target: str  # "calendar" | "roster"
    status: str  # "success" | "partial" | "failed" | "skipped"
    message: str = ""
    calendar_events: list[CalendarEvent] = field(default_factory=list)
    class_assignments: list[ClassAssignment] = field(default_factory=list)


class BaseSchoolScraper:
    """各 CMS 類型爬蟲的共同介面。子類別實作 scrape_calendar / scrape_roster。"""

    def __init__(self, school: dict, session):
        self.school = school
        self.session = session

    def scrape_calendar(self) -> ScrapeOutcome:
        return ScrapeOutcome(target="calendar", status="skipped", message="此CMS類型尚未實作行事曆爬蟲")

    def scrape_roster(self) -> ScrapeOutcome:
        return ScrapeOutcome(target="roster", status="skipped", message="此CMS類型尚未實作班級編制爬蟲")
