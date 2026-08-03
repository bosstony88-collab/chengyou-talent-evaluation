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
