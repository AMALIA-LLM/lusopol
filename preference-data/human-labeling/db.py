"""SQLite access layer for the preference-labeling app.

One small module, no ORM: a connection helper, the schema, and the handful of
queries that both the web app and the CLI scripts need.
"""

import json
import os
import sqlite3
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("LABELING_DB", APP_DIR / "annotations.db"))

LANGS = ("en", "pt")
CHOICES = ("A", "B", "tie")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('annotator', 'admin')),
    lang          TEXT,
    display_name  TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    lang            TEXT NOT NULL,
    item_key        TEXT NOT NULL,
    prompt_id       INTEGER,
    paraphrase_id   INTEGER,
    category        TEXT,
    prompt          TEXT NOT NULL,
    response_a      TEXT NOT NULL,
    response_b      TEXT NOT NULL,
    a_is_chosen     INTEGER NOT NULL,
    chosen_model    TEXT,
    rejected_model  TEXT,
    judge_reasoning TEXT,
    raw_json        TEXT NOT NULL,
    source_file     TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE (lang, item_key)
);

CREATE TABLE IF NOT EXISTS assignments (
    item_id  INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    username TEXT NOT NULL REFERENCES users(username),
    position INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assignments_user ON assignments(username, position);

CREATE TABLE IF NOT EXISTS annotations (
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    username        TEXT NOT NULL REFERENCES users(username),
    choice          TEXT NOT NULL CHECK (choice IN ('A', 'B', 'tie')),
    comment         TEXT NOT NULL DEFAULT '',
    time_on_item_ms INTEGER,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    edited_by_admin INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (item_id, username)
);

CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    actor   TEXT NOT NULL,
    action  TEXT NOT NULL,
    item_id INTEGER,
    payload TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now() -> str:
    """UTC timestamp, ISO-8601 with a trailing Z."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# WAL keeps its index in an mmap'd -shm file, which network and FUSE
# filesystems cannot back — SQLite dies with a bus error there. Fall back to
# the classic rollback journal on those mounts.
NO_MMAP_FS = {"nfs", "nfs4", "cifs", "smbfs", "smb3", "9p", "afs", "ceph",
              "lustre", "glusterfs", "fuseblk", "sshfs"}


def journal_mode(path: Path) -> str:
    override = os.environ.get("LABELING_JOURNAL_MODE")
    if override:
        return override.upper()
    try:
        target = str(Path(path).resolve())
        best, fstype = "", ""
        with open("/proc/mounts", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mount, kind = parts[1], parts[2]
                under = target == mount or target.startswith(mount.rstrip("/") + "/")
                # later entries shadow earlier ones at the same mount point
                if under and len(mount) >= len(best):
                    best, fstype = mount, kind
        family = fstype.split(".")[0]
        if family == "fuse" or family in NO_MMAP_FS or fstype in NO_MMAP_FS:
            return "DELETE"
    except OSError:
        pass
    return "WAL"


def connect(path: Path = None) -> sqlite3.Connection:
    path = path or DB_PATH
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    mode = journal_mode(path)
    conn.execute(f"PRAGMA journal_mode={mode}")
    conn.execute("PRAGMA synchronous=" + ("NORMAL" if mode == "WAL" else "FULL"))
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value)),
    )


def get_meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def log_event(conn, actor: str, action: str, item_id=None, payload=None) -> None:
    conn.execute(
        "INSERT INTO events (ts, actor, action, item_id, payload) VALUES (?, ?, ?, ?, ?)",
        (now(), actor, action, item_id, json.dumps(payload) if payload is not None else None),
    )


# --- queries used by the app -------------------------------------------------

def get_user(conn, username: str):
    return conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def annotators(conn, lang: str = None):
    sql = "SELECT * FROM users WHERE role = 'annotator'"
    args = []
    if lang:
        sql += " AND lang = ?"
        args.append(lang)
    return conn.execute(sql + " ORDER BY lang, username", args).fetchall()


def slice_for(conn, username: str):
    """Every item assigned to a user, in annotation order, with its label."""
    return conn.execute(
        """
        SELECT i.*, a.position, an.choice, an.comment, an.updated_at AS labeled_at
        FROM assignments a
        JOIN items i ON i.id = a.item_id
        LEFT JOIN annotations an ON an.item_id = i.id AND an.username = a.username
        WHERE a.username = ?
        ORDER BY a.position
        """,
        (username,),
    ).fetchall()


def item_at_position(conn, username: str, position: int):
    return conn.execute(
        """
        SELECT i.*, a.position, an.choice, an.comment
        FROM assignments a
        JOIN items i ON i.id = a.item_id
        LEFT JOIN annotations an ON an.item_id = i.id AND an.username = a.username
        WHERE a.username = ? AND a.position = ?
        """,
        (username, position),
    ).fetchone()


def progress(conn, username: str):
    row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN an.choice IS NOT NULL THEN 1 ELSE 0 END) AS done
        FROM assignments a
        LEFT JOIN annotations an ON an.item_id = a.item_id AND an.username = a.username
        WHERE a.username = ?
        """,
        (username,),
    ).fetchone()
    total = row["total"] or 0
    done = row["done"] or 0
    return {"total": total, "done": done, "pct": round(100 * done / total) if total else 0}


def progress_all(conn):
    """Overall counts, plus a per-language breakdown, for the admin overview."""
    def one(sql, args=()):
        row = conn.execute(sql, args).fetchone()
        total, done = row["total"] or 0, row["done"] or 0
        return {"total": total, "done": done, "pct": round(100 * done / total) if total else 0}

    base = """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN an.choice IS NOT NULL THEN 1 ELSE 0 END) AS done
        FROM assignments a
        JOIN items i ON i.id = a.item_id
        LEFT JOIN annotations an ON an.item_id = a.item_id AND an.username = a.username
    """
    out = one(base)
    out["by_lang"] = {lang: one(base + " WHERE i.lang = ?", (lang,)) for lang in LANGS}
    return out


def next_unlabeled_position(conn, username: str, after: int = 0):
    row = conn.execute(
        """
        SELECT a.position
        FROM assignments a
        LEFT JOIN annotations an ON an.item_id = a.item_id AND an.username = a.username
        WHERE a.username = ? AND an.choice IS NULL AND a.position > ?
        ORDER BY a.position LIMIT 1
        """,
        (username, after),
    ).fetchone()
    if row:
        return row["position"]
    # wrap around to catch anything skipped earlier in the queue
    row = conn.execute(
        """
        SELECT a.position
        FROM assignments a
        LEFT JOIN annotations an ON an.item_id = a.item_id AND an.username = a.username
        WHERE a.username = ? AND an.choice IS NULL
        ORDER BY a.position LIMIT 1
        """,
        (username,),
    ).fetchone()
    return row["position"] if row else None


def save_annotation(conn, item_id: int, username: str, choice: str, comment: str,
                    time_on_item_ms=None, by_admin: bool = False) -> None:
    ts = now()
    conn.execute(
        """
        INSERT INTO annotations
            (item_id, username, choice, comment, time_on_item_ms,
             created_at, updated_at, edited_by_admin)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_id, username) DO UPDATE SET
            choice = excluded.choice,
            comment = excluded.comment,
            time_on_item_ms = COALESCE(excluded.time_on_item_ms, annotations.time_on_item_ms),
            updated_at = excluded.updated_at,
            edited_by_admin = MAX(annotations.edited_by_admin, excluded.edited_by_admin)
        """,
        (item_id, username, choice, comment or "", time_on_item_ms, ts, ts, int(by_admin)),
    )


def human_prefers(choice: str, a_is_chosen: int):
    """Translate a display-side choice into dataset terms."""
    if choice == "tie":
        return "tie"
    if choice == "A":
        return "chosen" if a_is_chosen else "rejected"
    if choice == "B":
        return "rejected" if a_is_chosen else "chosen"
    return None
