#!/usr/bin/env python3
"""Export annotations with their full metadata.

    python export.py --out annotations.jsonl
    python export.py --format csv --out annotations.csv --include-unlabeled
"""

import argparse
import csv
import io
import json
from pathlib import Path

import db

# raw_json is kept last: it is long, and only the JSONL export carries it well.
FIELDS = [
    "item_id", "lang", "prompt_id", "paraphrase_id", "category",
    "annotator", "choice", "human_prefers", "human_preferred_model",
    "agrees_with_judge", "comment",
    "labeled_at", "first_labeled_at", "time_on_item_ms", "edited_by_admin",
    "a_is_chosen", "chosen_model", "rejected_model",
    "prompt", "response_a", "response_b", "judge_reasoning", "raw_json",
]


def collect(conn, include_unlabeled=False, lang=None):
    sql = """
        SELECT i.*, a.username AS annotator, a.position,
               an.choice, an.comment, an.created_at AS first_labeled_at,
               an.updated_at AS labeled_at, an.time_on_item_ms, an.edited_by_admin
        FROM items i
        LEFT JOIN assignments a ON a.item_id = i.id
        LEFT JOIN annotations an ON an.item_id = i.id AND an.username = a.username
        WHERE 1 = 1
    """
    params = []
    if not include_unlabeled:
        sql += " AND an.choice IS NOT NULL"
    if lang:
        sql += " AND i.lang = ?"
        params.append(lang)
    sql += " ORDER BY i.lang, a.username, a.position"

    records = []
    for row in conn.execute(sql, params):
        prefers = db.human_prefers(row["choice"], row["a_is_chosen"]) if row["choice"] else None
        if prefers == "chosen":
            preferred_model, agrees = row["chosen_model"], True
        elif prefers == "rejected":
            preferred_model, agrees = row["rejected_model"], False
        else:
            preferred_model, agrees = None, None
        records.append({
            "item_id": row["id"],
            "lang": row["lang"],
            "prompt_id": row["prompt_id"],
            "paraphrase_id": row["paraphrase_id"],
            "category": row["category"],
            "annotator": row["annotator"],
            "choice": row["choice"],
            "human_prefers": prefers,
            "human_preferred_model": preferred_model,
            "agrees_with_judge": agrees,
            "comment": row["comment"] or "",
            "labeled_at": row["labeled_at"],
            "first_labeled_at": row["first_labeled_at"],
            "time_on_item_ms": row["time_on_item_ms"],
            "edited_by_admin": bool(row["edited_by_admin"]) if row["choice"] else None,
            "a_is_chosen": bool(row["a_is_chosen"]),
            "chosen_model": row["chosen_model"],
            "rejected_model": row["rejected_model"],
            "prompt": row["prompt"],
            "response_a": row["response_a"],
            "response_b": row["response_b"],
            "judge_reasoning": row["judge_reasoning"],
            "raw_json": json.loads(row["raw_json"]),
        })
    return records


def to_jsonl(records) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)


def to_csv(records) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        flat = dict(record)
        flat["raw_json"] = json.dumps(record["raw_json"], ensure_ascii=False)
        writer.writerow(flat)
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="output file (default: stdout)")
    parser.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    parser.add_argument("--lang", choices=db.LANGS)
    parser.add_argument("--include-unlabeled", action="store_true",
                        help="also emit items with no label yet")
    parser.add_argument("--db", type=Path, default=db.DB_PATH)
    args = parser.parse_args()

    conn = db.connect(args.db)
    records = collect(conn, args.include_unlabeled, args.lang)
    conn.close()

    text = to_jsonl(records) if args.format == "jsonl" else to_csv(records)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        labeled = sum(1 for r in records if r["choice"])
        print(f"wrote {len(records)} record(s) ({labeled} labeled) to {args.out}")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
