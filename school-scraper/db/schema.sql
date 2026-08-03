-- 程優教育科技 - 學校公開資訊資料庫 schema
-- 用途：內部行政參考（行事曆比對排課、班級編制概況），不含任何學生個資

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schools (
    id            TEXT PRIMARY KEY,      -- 對應 config/schools.json 的 id
    name          TEXT NOT NULL,         -- 學校全名
    short_name    TEXT NOT NULL,
    level         TEXT NOT NULL CHECK (level IN ('junior_high', 'elementary')),
    district      TEXT NOT NULL,
    base_url      TEXT NOT NULL,
    cms_type      TEXT NOT NULL,
    updated_at    TEXT NOT NULL          -- ISO8601，最後一次成功同步時間
);

-- 學期行事曆事件（完全公開資訊，無個資疑慮）
CREATE TABLE IF NOT EXISTS calendar_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id     TEXT NOT NULL REFERENCES schools(id),
    school_year   TEXT,                  -- 例如 "114"（民國學年度），可為 NULL 表示無法判斷
    semester      TEXT,                  -- "上學期" / "下學期" / NULL
    title         TEXT NOT NULL,
    start_date    TEXT,                  -- ISO8601 date，若無法解析日期則為 NULL
    end_date      TEXT,
    raw_text      TEXT,                  -- 原始文字備份，日期解析失敗時的 fallback
    source_url    TEXT NOT NULL,
    scraped_at    TEXT NOT NULL,
    UNIQUE (school_id, title, start_date, source_url)
);

CREATE INDEX IF NOT EXISTS idx_calendar_events_school ON calendar_events(school_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_dates ON calendar_events(start_date, end_date);

-- 班級編制表（僅班級-導師結構，不含任何學生姓名/學生個資）
-- 因多數學校並無固定總表頁面，是每學年度以教務處公告零星發布，
-- 且通常只公告當學年重新編班的年級（國小常見1、3、5年級），
-- 故採「歷史累加」設計：每學年度一筆快照，is_carried_over 標示是否為延續前次資料推算。
CREATE TABLE IF NOT EXISTS class_teacher_assignments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id         TEXT NOT NULL REFERENCES schools(id),
    school_year       TEXT NOT NULL,     -- 民國學年度，例如 "114"
    grade             INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 9),
    class_number      INTEGER NOT NULL,
    teacher_name      TEXT,              -- 可能為 NULL（只找到班級數，找不到導師姓名時）
    is_carried_over   INTEGER NOT NULL DEFAULT 0,  -- 0/1，1表示非當學年度公告直接來源，是延續前次資料
    source_url        TEXT,
    scraped_at        TEXT NOT NULL,
    UNIQUE (school_id, school_year, grade, class_number)
);

CREATE INDEX IF NOT EXISTS idx_class_teacher_school_year ON class_teacher_assignments(school_id, school_year);

-- 班級學生名單：只儲存學校官網公告上「本來就遮罩過」的姓名（例如 王○明），原樣保存。
-- 隱私保證：db/store.py 的寫入函式會拒絕任何不含遮罩符號的姓名，系統結構上不可能儲存完整學生姓名，
-- 也絕不嘗試還原/比對出完整姓名。entry_index 是該班名單在公告中的出現順序（遮罩姓名可能同班重複）。
CREATE TABLE IF NOT EXISTS student_roster_entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id     TEXT NOT NULL REFERENCES schools(id),
    school_year   TEXT NOT NULL,
    grade         INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 9),
    class_number  INTEGER NOT NULL,
    entry_index   INTEGER NOT NULL,
    masked_name   TEXT NOT NULL,
    source_url    TEXT,
    scraped_at    TEXT NOT NULL,
    UNIQUE (school_id, school_year, grade, class_number, entry_index)
);

CREATE INDEX IF NOT EXISTS idx_student_roster_school_year ON student_roster_entries(school_id, school_year);

-- 每次爬取的執行紀錄，方便排查個別學校失敗原因，單校失敗不應中斷整體流程
CREATE TABLE IF NOT EXISTS scrape_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id     TEXT NOT NULL REFERENCES schools(id),
    target        TEXT NOT NULL CHECK (target IN ('calendar', 'roster')),
    status        TEXT NOT NULL CHECK (status IN ('success', 'partial', 'failed', 'skipped')),
    message       TEXT,
    run_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scrape_log_school ON scrape_log(school_id, run_at);
