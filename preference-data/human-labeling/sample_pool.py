#!/usr/bin/env python3
"""Draw an annotation round out of the full preference files.

Samples N prompts, stratified over categories, one paraphrase variant per
prompt, and writes an EN and a PT file that cover the *same* prompts and the
same paraphrase variants — so the two rounds stay alignable by
(prompt_id, paraphrase_id).

    python sample_pool.py --n 50 --out-prefix round1

The selection is a pure function of --seed, and the manifest written alongside
the files records exactly what was drawn.
"""

import argparse
import collections
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_EN = HERE.parent / "preferences_en.jsonl"
DEFAULT_PT = HERE.parent / "preferences_pt.jsonl"


def load(path: Path):
    if not path.exists():
        sys.exit(f"no such file: {path}")
    rows = {}
    for lineno, line in enumerate(path.open(encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.exit(f"{path}:{lineno}: invalid JSON ({exc})")
        for field in ("prompt_id", "paraphrase_id", "category"):
            if field not in row:
                sys.exit(f"{path}:{lineno}: missing required field '{field}'")
        rows[(row["prompt_id"], row["paraphrase_id"])] = row
    return rows


def quota(n: int, categories, rng):
    """Split n over the categories as evenly as possible, remainder at random."""
    base, extra = divmod(n, len(categories))
    counts = {c: base for c in categories}
    for category in rng.sample(sorted(categories), extra):
        counts[category] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--en", type=Path, default=DEFAULT_EN)
    parser.add_argument("--pt", type=Path, default=DEFAULT_PT)
    parser.add_argument("--n", type=int, default=50, help="prompts per language (default: 50)")
    parser.add_argument("--seed", type=int, default=2024)
    parser.add_argument("--paraphrase", choices=("random", "zero"), default="random",
                        help="which variant represents each prompt (default: random)")
    parser.add_argument("--out-dir", type=Path, default=HERE / "rounds")
    parser.add_argument("--out-prefix", default="round1")
    args = parser.parse_args()

    en, pt = load(args.en), load(args.pt)

    # Only prompts that exist in both languages, and only variants both languages have.
    variants = collections.defaultdict(set)
    category = {}
    for (prompt_id, paraphrase_id), row in en.items():
        if (prompt_id, paraphrase_id) in pt:
            variants[prompt_id].add(paraphrase_id)
            category[prompt_id] = row["category"]

    mismatched = [p for p in category
                  if pt[(p, min(variants[p]))]["category"] != category[p]]
    if mismatched:
        sys.exit(f"category disagrees between languages for prompt_id(s): {mismatched[:5]}")

    by_category = collections.defaultdict(list)
    for prompt_id in sorted(variants):
        by_category[category[prompt_id]].append(prompt_id)

    rng = random.Random(args.seed)
    counts = quota(args.n, by_category.keys(), rng)

    picked = []
    for category_name in sorted(by_category):
        pool = by_category[category_name]
        want = counts[category_name]
        if want > len(pool):
            sys.exit(f"category {category_name} has {len(pool)} prompts, need {want}")
        for prompt_id in sorted(rng.sample(pool, want)):
            shared = sorted(variants[prompt_id])
            if args.paraphrase == "zero":
                paraphrase_id = 0 if 0 in shared else shared[0]
            else:
                paraphrase_id = rng.choice(shared)
            picked.append((prompt_id, paraphrase_id, category_name))

    picked.sort()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for lang, rows in (("en", en), ("pt", pt)):
        out = args.out_dir / f"{args.out_prefix}_{lang}.jsonl"
        with out.open("w", encoding="utf-8") as fh:
            for prompt_id, paraphrase_id, _ in picked:
                fh.write(json.dumps(rows[(prompt_id, paraphrase_id)], ensure_ascii=False) + "\n")
        print(f"wrote {len(picked)} rows to {out}")

    manifest = args.out_dir / f"{args.out_prefix}_manifest.json"
    manifest.write_text(json.dumps({
        "prefix": args.out_prefix,
        "n": args.n,
        "seed": args.seed,
        "paraphrase": args.paraphrase,
        "sources": {"en": str(args.en), "pt": str(args.pt)},
        "per_category": {c: counts[c] for c in sorted(counts)},
        "items": [{"prompt_id": p, "paraphrase_id": v, "category": c} for p, v, c in picked],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {manifest}")

    print("\nper category:")
    for category_name in sorted(counts):
        print(f"  {category_name:26s} {counts[category_name]}")


if __name__ == "__main__":
    main()
