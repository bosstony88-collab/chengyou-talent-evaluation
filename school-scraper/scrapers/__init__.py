from .base import BaseSchoolScraper, CalendarEvent, ClassAssignment, ScrapeOutcome
from .generic_scraper import GenericScraper
from .nss_scraper import NssScraper
from .xoops_scraper import XoopsScraper

_SCRAPER_BY_CMS = {
    "xoops": XoopsScraper,
    "nss": NssScraper,
    "asp_legacy": GenericScraper,
    "unknown": GenericScraper,
}


def get_scraper(school: dict, session) -> BaseSchoolScraper:
    cls = _SCRAPER_BY_CMS.get(school["cms_type"], GenericScraper)
    return cls(school, session)


__all__ = [
    "BaseSchoolScraper",
    "CalendarEvent",
    "ClassAssignment",
    "ScrapeOutcome",
    "get_scraper",
]
