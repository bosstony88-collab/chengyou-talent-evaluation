"""共用 HTTP 工具：session 設定、重試、編碼偵測（部分老舊校網仍用 Big5）。"""
from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("school_scraper")

USER_AGENT = (
    "Mozilla/5.0 (compatible; ChengyouSchoolInfoBot/1.0; "
    "+internal use only, aggregating publicly posted class-teacher rosters and school calendars)"
)

REQUEST_TIMEOUT = 20  # 秒
# 對公立學校網站保持禮貌的請求間隔，避免造成負擔
POLITE_DELAY_SECONDS = 1.5


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def polite_get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """GET 並自動處理編碼；呼叫端仍需自行 raise_for_status / 檢查狀態碼。"""
    time.sleep(POLITE_DELAY_SECONDS)
    resp = session.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
    # 許多桃園市老舊校網（尤其 XOOPS/ASP系統）仍用 Big5，requests 預設偵測常常猜錯
    if resp.encoding is None or resp.encoding.lower() in ("iso-8859-1",):
        for enc in ("utf-8", "big5", "cp950"):
            try:
                resp.encoding = enc
                _ = resp.text
                break
            except UnicodeDecodeError:
                continue
    return resp
