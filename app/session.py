"""SQLite-backed session and attempt storage. Phase 4 substrate.

No ORM. Stdlib sqlite3 with a thin context-manager wrapper. Connection per
call is acceptable for v1 single-user usage.
"""
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "data" / "maatru.db"

_SCHEMA_SESSIONS = """\
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT NULL,
    language TEXT NOT NULL,
    focus TEXT NULL,
    fallback_used INTEGER NOT NULL DEFAULT 1,
    reasoning TEXT NULL
)
"""

_SCHEMA_ATTEMPTS = """\
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    target TEXT NOT NULL,
    chosen TEXT NOT NULL,
    correct INTEGER NOT NULL,
    feedback TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
)
"""

_INDEX_ATTEMPTS_TARGET = "CREATE INDEX IF NOT EXISTS idx_attempts_target ON attempts(target)"

_SCHEMA_SETTINGS = """\
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

_DEFAULT_PARENT_PIN = "4242"


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def _connect(db_path: str | Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Idempotent. Creates tables and indices if missing.

    Also adds the `sessions.reasoning` column on existing pre-Phase-5.5 DBs
    where CREATE TABLE IF NOT EXISTS is a no-op. ALTER fails harmlessly if the
    column already exists (older sqlite3 raises sqlite3.OperationalError).
    """
    with _connect(db_path) as conn:
        conn.execute(_SCHEMA_SESSIONS)
        conn.execute(_SCHEMA_ATTEMPTS)
        conn.execute(_INDEX_ATTEMPTS_TARGET)
        conn.execute(_SCHEMA_SETTINGS)
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "reasoning" not in existing:
            conn.execute("ALTER TABLE sessions ADD COLUMN reasoning TEXT NULL")


def create_session(
    language: str = "te",
    focus: str | None = None,
    fallback_used: bool = True,
    reasoning: str | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> str:
    """Insert a new session row and return its UUID.

    `reasoning` persists the planner's session-level justification for
    planner-driven sessions; pass None for deterministic/fallback sessions.
    """
    session_id = str(uuid.uuid4())
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (id, started_at, ended_at, language, focus, fallback_used, reasoning) "
            "VALUES (?, ?, NULL, ?, ?, ?, ?)",
            (session_id, _now_utc_iso(), language, focus, 1 if fallback_used else 0, reasoning),
        )
    return session_id


def record_attempt(
    session_id: str,
    step_index: int,
    target: str,
    chosen: str,
    correct: bool,
    feedback: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO attempts (session_id, step_index, target, chosen, correct, feedback, attempted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, step_index, target, chosen, 1 if correct else 0, feedback, _now_utc_iso()),
        )


def end_session(session_id: str, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE sessions SET ended_at = ? WHERE id = ?", (_now_utc_iso(), session_id))


def get_setting(key: str, default: str | None = None, db_path: str | Path = DEFAULT_DB_PATH) -> str | None:
    """Return the stored value for `key`, or `default` if the row (or table) is absent."""
    with _connect(db_path) as conn:
        try:
            cursor = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cursor.fetchone()
        except sqlite3.OperationalError:
            return default
    return row["value"] if row is not None else default


def set_setting(key: str, value: str, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, _now_utc_iso()),
        )


def get_parent_pin(db_path: str | Path = DEFAULT_DB_PATH) -> str:
    """Return the stored parent PIN, or the default '4242' if never set."""
    stored = get_setting("parent_pin", default=None, db_path=db_path)
    return stored if stored is not None else _DEFAULT_PARENT_PIN


def set_parent_pin(new_pin: str, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Validate (3-6 digits, numeric) and persist a new parent PIN."""
    if not isinstance(new_pin, str) or not new_pin.isdigit() or not (3 <= len(new_pin) <= 6):
        raise ValueError("parent PIN must be 3-6 numeric digits")
    set_setting("parent_pin", new_pin, db_path=db_path)
    set_setting("parent_pin_changed", "1", db_path=db_path)


def is_parent_pin_default(db_path: str | Path = DEFAULT_DB_PATH) -> bool:
    """True iff the parent PIN has never been changed from the default."""
    flag = get_setting("parent_pin_changed", default="0", db_path=db_path)
    return flag != "1"


def get_letter_attempts(letter: str, db_path: str | Path = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Return all attempts for a letter across sessions, oldest first.

    Returns dicts with keys: session_id, attempted_at, correct (bool), chosen.
    Empty list if the table doesn't exist yet (DB never initialised).
    """
    with _connect(db_path) as conn:
        try:
            cursor = conn.execute(
                "SELECT session_id, attempted_at, correct, chosen FROM attempts WHERE target = ? ORDER BY attempted_at ASC",
                (letter,),
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            return []
    return [
        {
            "session_id": r["session_id"],
            "attempted_at": r["attempted_at"],
            "correct": bool(r["correct"]),
            "chosen": r["chosen"],
        }
        for r in rows
    ]
