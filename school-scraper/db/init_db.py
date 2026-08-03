"""初始化 SQLite 資料庫，並將 config/schools.json 的學校清單 upsert 進 schools 表。"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "db" / "schema.sql"
SCHOOLS_JSON_PATH = ROOT / "config" / "schools.json"
DB_PATH = ROOT / "data" / "schools.db"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    schools = json.loads(SCHOOLS_JSON_PATH.read_text(encoding="utf-8"))["schools"]
    ts = now_iso()
    for s in schools:
        conn.execute(
            """
            INSERT INTO schools (id, name, short_name, level, district, base_url, cms_type, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                short_name=excluded.short_name,
                level=excluded.level,
                district=excluded.district,
                base_url=excluded.base_url,
                cms_type=excluded.cms_type
            """,
            (s["id"], s["name"], s["short_name"], s["level"], s["district"], s["base_url"], s["cms_type"], ts),
        )
    conn.commit()
    return conn


if __name__ == "__main__":
    conn = init_db()
    count = conn.execute("SELECT COUNT(*) FROM schools").fetchone()[0]
    print(f"資料庫已初始化：{DB_PATH}，共 {count} 所學校")
    conn.close()
