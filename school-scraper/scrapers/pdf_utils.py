"""PDF 附件（行事曆、編班暨導師編配公告）文字擷取與班級-導師配對解析。

這裡的班級-導師 regex 是根據台灣國中小公告常見寫法（"一年1班 導師 王小明" 之類）歸納的
best-effort heuristic，不同學校格式可能不同。解析結果務必保留 raw_text 來源，
供後續人工核對，不保證 100% 準確率。
"""
from __future__ import annotations

import io
import logging
import re

import pdfplumber

logger = logging.getLogger("school_scraper")

_CHINESE_GRADE_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

# 例如："一年1班 導師 王小明" / "1年01班：王小明" / "三年5班 王小明老師"
_CLASS_TEACHER_PATTERN = re.compile(
    r"([一二三四五六七八九1-9])\s*年[級]?\s*([0-9]{1,2})\s*班"
    r"[\s:：]*(?:導師)?[\s:：]*([一-龥]{2,4}?)(?:老師|導師)?"
    r"(?=[\s　，。、]|$|[一二三四五六七八九0-9]{1,2}\s*年)"
)

# ---------- 遮罩學生姓名（隱私關鍵區） ----------
# 只比對學校官網公告上「本來就遮罩過」的姓名（例如 王○明、歐陽○明、林○），原樣保存。
# 本系統絕不嘗試還原完整姓名；寫入層(db/store.py)另有防護，不含遮罩符號的姓名一律拒絕入庫。
MASK_CHARS = "○◯〇●ＯO0＊*×Ｘ□"

# CJK前綴1-2字（含複姓）＋遮罩符號1-2個＋可選CJK結尾字；前後不能緊貼其他中文字，
# 避免把一般句子中的符號誤認成姓名（代價是無分隔的連續姓名可能漏抓，寧可漏、不可錯）
_MASKED_NAME_RE = re.compile(
    rf"(?<![一-龥])[一-龥]{{1,2}}[{re.escape(MASK_CHARS)}]{{1,2}}[一-龥]?(?![一-龥])"
)

# 班級標頭（用於把公告文字切成逐班區段）："一年1班" / "3年12班" / "七年級5班"
_CLASS_HEADER_RE = re.compile(r"([一二三四五六七八九1-9])\s*年[級]?\s*([0-9]{1,2})\s*班")


def contains_mask(name: str) -> bool:
    return any(c in MASK_CHARS for c in name)


def extract_pdf_text(pdf_bytes: bytes) -> str:
    text_parts = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
    except Exception as exc:  # pdfplumber 對壞掉的PDF可能丟出各種例外，統一吞下並記錄
        logger.warning("PDF 解析失敗: %s", exc)
        return ""
    return "\n".join(text_parts)


def parse_class_teacher_pairs(text: str) -> list[tuple[int, int, str]]:
    """回傳 [(grade, class_number, teacher_name), ...]，是 best-effort 結果。"""
    results = []
    for match in _CLASS_TEACHER_PATTERN.finditer(text):
        grade_raw, class_raw, teacher = match.groups()
        grade = _CHINESE_GRADE_MAP.get(grade_raw, None)
        if grade is None and grade_raw.isdigit():
            grade = int(grade_raw)
        if grade is None:
            continue
        try:
            class_number = int(class_raw)
        except ValueError:
            continue
        # 過濾明顯不合理的姓名（例如把「編班」「作業」這種詞誤抓進來）
        if teacher in ("編班", "作業", "公告", "結果", "編配"):
            continue
        results.append((grade, class_number, teacher))
    return results


def parse_masked_student_roster(text: str) -> tuple[list[tuple[int, int, list[str]]], int]:
    """從公告/PDF文字解析「學校已遮罩」的班級學生名單。

    以班級標頭（一年1班）把文字切成逐班區段，各區段內比對遮罩姓名。
    回傳 ([(grade, class_number, [遮罩姓名...]), ...], 無法歸屬到任何班級的遮罩姓名數)。
    同一班出現多個標頭（例如導師行與名單表各一次）時會合併名單並保持出現順序。
    """
    headers = list(_CLASS_HEADER_RE.finditer(text))
    if not headers:
        return [], len(_MASKED_NAME_RE.findall(text))

    unattributed = len(_MASKED_NAME_RE.findall(text[: headers[0].start()]))

    merged: dict[tuple[int, int], list[str]] = {}
    order: list[tuple[int, int]] = []
    for i, m in enumerate(headers):
        grade_raw, class_raw = m.groups()
        grade = _CHINESE_GRADE_MAP.get(grade_raw)
        if grade is None and grade_raw.isdigit():
            grade = int(grade_raw)
        try:
            class_number = int(class_raw)
        except ValueError:
            continue
        if grade is None:
            continue

        seg_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        names = _MASKED_NAME_RE.findall(text[m.end():seg_end])
        if not names:
            continue
        key = (grade, class_number)
        if key not in merged:
            merged[key] = []
            order.append(key)
        merged[key].extend(names)

    return [(g, c, merged[(g, c)]) for g, c in order], unattributed
