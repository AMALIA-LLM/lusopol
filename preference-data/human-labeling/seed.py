#!/usr/bin/env python3
"""Build or refresh the annotation database from the preference JSONL files.

    python seed.py --en ../preferences_en.jsonl --pt ../preferences_pt.jsonl

Re-running is safe: new items are inserted and assigned, existing items and
their annotations are left untouched. Use --reset to start over.
"""

import argparse
import hashlib
import json
import random
import secrets
import sys
from collections import defaultdict
from pathlib import Path

from werkzeug.security import generate_password_hash

import db

PASSWORD_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"  # no look-alikes
SUFFIXES = "abcdefghij"


# --- reading the source files ------------------------------------------------

def _last_assistant_message(turns):
    """Pull the model answer out of a chat-formatted field."""
    if isinstance(turns, str):
        return turns
    if not isinstance(turns, list):
        raise ValueError(f"unsupported response format: {type(turns).__name__}")
    for turn in reversed(turns):
        if isinstance(turn, dict) and turn.get("role") == "assistant":
            return turn.get("content", "")
    last = turns[-1]
    return last.get("content", "") if isinstance(last, dict) else str(last)


def _first_user_message(turns):
    if isinstance(turns, list):
        for turn in turns:
            if isinstance(turn, dict) and turn.get("role") == "user":
                return turn.get("content", "")
    return ""


def _item_key(row, prompt, chosen, rejected):
    prompt_id, paraphrase_id = row.get("prompt_id"), row.get("paraphrase_id")
    if prompt_id is not None and paraphrase_id is not None:
        return f"{prompt_id}:{paraphrase_id}"
    if prompt_id is not None:
        return str(prompt_id)
    digest = hashlib.sha1(f"{prompt}\x00{chosen}\x00{rejected}".encode()).hexdigest()
    return f"h:{digest[:16]}"


def read_items(path: Path, lang: str, one_per_prompt: bool, seed: int):
    """Parse one JSONL file into item dicts ready for insertion."""
    rows = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                sys.exit(f"{path}:{lineno}: invalid JSON ({exc})")
            for field in ("chosen", "rejected"):
                if field not in row:
                    sys.exit(f"{path}:{lineno}: missing required field '{field}'")
            rows.append(row)

    if one_per_prompt:
        best = {}
        for row in rows:
            pid = row.get("prompt_id")
            if pid is None:
                sys.exit(f"{path}: --one-per-prompt needs a 'prompt_id' on every row")
            para = row.get("paraphrase_id") or 0
            if pid not in best or para < (best[pid].get("paraphrase_id") or 0):
                best[pid] = row
        rows = [best[pid] for pid in sorted(best)]

    items = []
    for row in rows:
        chosen = _last_assistant_message(row["chosen"])
        rejected = _last_assistant_message(row["rejected"])
        prompt = row.get("prompt") or _first_user_message(row["chosen"])
        if not prompt:
            sys.exit(f"{path}: row {row.get('prompt_id')} has no prompt")
        key = _item_key(row, prompt, chosen, rejected)
        # Deterministic blinding: the same seed always puts the same side left.
        flip = random.Random(f"{seed}|{lang}|{key}").random() < 0.5
        items.append({
            "lang": lang,
            "item_key": key,
            "prompt_id": row.get("prompt_id"),
            "paraphrase_id": row.get("paraphrase_id"),
            "category": row.get("category"),
            "prompt": prompt,
            "response_a": chosen if flip else rejected,
            "response_b": rejected if flip else chosen,
            "a_is_chosen": int(flip),
            "chosen_model": row.get("chosen_model"),
            "rejected_model": row.get("rejected_model"),
            "judge_reasoning": row.get("reasoning"),
            "raw_json": json.dumps(row, ensure_ascii=False),
            "source_file": str(path),
        })
    return items


# --- users -------------------------------------------------------------------

def make_password() -> str:
    groups = ["".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "-".join(groups)


def ensure_users(conn, per_lang: int, rotate: bool):
    """Create the fixed roster if missing; return {username: plaintext} for new ones."""
    wanted = [("admin", "admin", None, "Administrator")]
    for lang in db.LANGS:
        for i in range(per_lang):
            username = f"{lang}_{SUFFIXES[i]}"
            wanted.append((username, "annotator", lang, f"{lang.upper()} annotator {SUFFIXES[i].upper()}"))

    fresh = {}
    for username, role, lang, display in wanted:
        exists = db.get_user(conn, username) is not None
        if exists and not rotate:
            continue
        password = make_password()
        fresh[username] = password
        if exists:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE username = ?",
                (generate_password_hash(password), username),
            )
            db.log_event(conn, "seed", "rotate_password", payload={"username": username})
        else:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, lang, display_name, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (username, generate_password_hash(password), role, lang, display, db.now()),
            )
    return fresh


def write_credentials(path: Path, fresh: dict, conn, base_url: str):
    lines = [
        "Preference labeling — login credentials",
        f"generated {db.now()}",
        "",
        "Share one block per collaborator. Keep this file out of version control.",
        "",
    ]
    for username, password in sorted(fresh.items()):
        user = db.get_user(conn, username)
        role = "ADMIN" if user["role"] == "admin" else f"{(user['lang'] or '').upper()} annotator"
        lines += [
            "=" * 52,
            f"{role}",
            f"  url:      {base_url}",
            f"  username: {username}",
            f"  password: {password}",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")
    path.chmod(0o600)


# --- items and assignments ---------------------------------------------------

def upsert_items(conn, items):
    inserted, existing = 0, 0
    for item in items:
        cur = conn.execute(
            """
            INSERT INTO items (lang, item_key, prompt_id, paraphrase_id, category, prompt,
                               response_a, response_b, a_is_chosen, chosen_model, rejected_model,
                               judge_reasoning, raw_json, source_file, created_at)
            VALUES (:lang, :item_key, :prompt_id, :paraphrase_id, :category, :prompt,
                    :response_a, :response_b, :a_is_chosen, :chosen_model, :rejected_model,
                    :judge_reasoning, :raw_json, :source_file, :created_at)
            ON CONFLICT (lang, item_key) DO NOTHING
            """,
            {**item, "created_at": db.now()},
        )
        if cur.rowcount:
            inserted += 1
        else:
            existing += 1
    return inserted, existing


def assign_unassigned(conn, lang: str, seed: int):
    """Deal every unassigned item of a language to that language's annotators.

    Items are dealt round-robin within category so each slice is
    category-balanced, then each annotator's queue is shuffled so that category
    does not correlate with position in the queue.
    """
    users = [u["username"] for u in db.annotators(conn, lang)]
    if not users:
        return {}

    pending = conn.execute(
        """
        SELECT i.id, i.category, i.prompt_id, i.paraphrase_id, i.item_key
        FROM items i LEFT JOIN assignments a ON a.item_id = i.id
        WHERE i.lang = ? AND a.item_id IS NULL
        ORDER BY COALESCE(i.category, ''), COALESCE(i.prompt_id, 0),
                 COALESCE(i.paraphrase_id, 0), i.item_key
        """,
        (lang,),
    ).fetchall()
    if not pending:
        return {}

    counts = {u: 0 for u in users}
    for row in conn.execute(
        "SELECT username, COUNT(*) AS n FROM assignments GROUP BY username"
    ):
        if row["username"] in counts:
            counts[row["username"]] = row["n"]
    next_pos = {u: (counts[u] or 0) for u in users}

    by_category = defaultdict(list)
    for row in pending:
        by_category[row["category"] or ""].append(row["id"])

    dealt = defaultdict(list)
    for category in sorted(by_category):
        for item_id in by_category[category]:
            # keep the slices even, deterministically
            owner = min(users, key=lambda u: (counts[u], u))
            counts[owner] += 1
            dealt[owner].append(item_id)

    added = {}
    for owner, item_ids in dealt.items():
        random.Random(f"{seed}|order|{owner}").shuffle(item_ids)
        for item_id in item_ids:
            next_pos[owner] += 1
            conn.execute(
                "INSERT INTO assignments (item_id, username, position) VALUES (?, ?, ?)",
                (item_id, owner, next_pos[owner]),
            )
        added[owner] = len(item_ids)
    return added


def report_missing(conn, lang: str, items):
    """Items in the DB that are no longer present in the source file."""
    seen = {i["item_key"] for i in items}
    rows = conn.execute(
        """
        SELECT i.item_key, a.username, an.choice
        FROM items i
        LEFT JOIN assignments a ON a.item_id = i.id
        LEFT JOIN annotations an ON an.item_id = i.id
        WHERE i.lang = ?
        """,
        (lang,),
    ).fetchall()
    return [r for r in rows if r["item_key"] not in seen]


# --- main --------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--en", type=Path, help="English preferences JSONL")
    parser.add_argument("--pt", type=Path, help="Portuguese preferences JSONL")
    parser.add_argument("--one-per-prompt", action="store_true",
                        help="keep only the lowest paraphrase_id per prompt_id")
    parser.add_argument("--seed", type=int, default=42,
                        help="controls A/B blinding and queue order (default: 42)")
    parser.add_argument("--annotators-per-lang", type=int, default=3)
    parser.add_argument("--reset", action="store_true",
                        help="delete all items, assignments and annotations first")
    parser.add_argument("--rotate-passwords", action="store_true",
                        help="issue new passwords for every account")
    parser.add_argument("--base-url", default="http://localhost:8000",
                        help="URL written into credentials.txt")
    parser.add_argument("--yes", action="store_true", help="skip the --reset confirmation")
    parser.add_argument("--db", type=Path, default=db.DB_PATH)
    args = parser.parse_args()

    if not args.en and not args.pt:
        parser.error("give at least one of --en / --pt")

    conn = db.connect(args.db)
    db.init_schema(conn)

    if args.reset:
        n = conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
        if n and not args.yes:
            answer = input(f"--reset will delete {n} existing annotations. Type 'yes' to confirm: ")
            if answer.strip().lower() != "yes":
                sys.exit("aborted")
        conn.executescript("DELETE FROM annotations; DELETE FROM assignments; DELETE FROM items;")
        db.log_event(conn, "seed", "reset", payload={"deleted_annotations": n})
        print(f"reset: cleared items, assignments and {n} annotations")

    fresh = ensure_users(conn, args.annotators_per_lang, args.rotate_passwords)
    conn.commit()

    sources = {"en": args.en, "pt": args.pt}
    for lang, path in sources.items():
        if not path:
            continue
        if not path.exists():
            sys.exit(f"no such file: {path}")
        items = read_items(path, lang, args.one_per_prompt, args.seed)
        inserted, existing = upsert_items(conn, items)
        stale = report_missing(conn, lang, items)
        print(f"[{lang}] {path.name}: {len(items)} rows -> {inserted} new, {existing} already present")
        if stale:
            labeled = sum(1 for r in stale if r["choice"])
            print(f"[{lang}] warning: {len(stale)} item(s) in the DB are absent from the file "
                  f"({labeled} already labeled); they are kept, use --reset to drop them")

    for lang in db.LANGS:
        added = assign_unassigned(conn, lang, args.seed)
        for username, n in sorted(added.items()):
            print(f"[{lang}] assigned {n} new item(s) to {username}")

    db.set_meta(conn, "seed", args.seed)
    db.set_meta(conn, "one_per_prompt", args.one_per_prompt)
    db.log_event(conn, "seed", "seed_run",
                 payload={"en": str(args.en), "pt": str(args.pt), "seed": args.seed})
    conn.commit()

    if fresh:
        creds = args.db.parent / "credentials.txt"
        write_credentials(creds, fresh, conn, args.base_url)
        print(f"\nwrote {len(fresh)} credential block(s) to {creds}")
        for username, password in sorted(fresh.items()):
            print(f"  {username:8s} {password}")

    print("\ncurrent state")
    for row in conn.execute(
        """
        SELECT u.username, u.lang, COUNT(a.item_id) AS assigned,
               SUM(CASE WHEN an.choice IS NOT NULL THEN 1 ELSE 0 END) AS labeled
        FROM users u
        LEFT JOIN assignments a ON a.username = u.username
        LEFT JOIN annotations an ON an.item_id = a.item_id AND an.username = u.username
        WHERE u.role = 'annotator'
        GROUP BY u.username ORDER BY u.lang, u.username
        """
    ):
        print(f"  {row['username']:8s} {row['labeled'] or 0:4d} / {row['assigned']:<4d} labeled")
    conn.close()


if __name__ == "__main__":
    main()
