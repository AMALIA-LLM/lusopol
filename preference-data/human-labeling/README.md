# Human labeling app

A small Flask app for validating the LLM-judge preference pairs by hand. Annotators see the prompt
and the two candidate answers side by side, blinded, and pick **A**, **B** or **tie**, optionally
leaving a comment.

Six accounts annotate: three on English, three on Portuguese. Each language's pool is split into
three **disjoint** slices, so no item is labeled twice and the three annotators of a language never
overlap. Annotators never see which answer the judge preferred, which model produced it, or the
judge's reasoning — the admin does.

## Where things live

| what | where | why |
| --- | --- | --- |
| code | `preference-data/human-labeling/` (this dir, on `/mnt/home`) | in git |
| round files | `rounds/round1_{en,pt}.jsonl` + `round1_manifest.json` | in git, small and reproducible |
| database, credentials, session key | `/mnt/scratch-artemis/giuseppe/lusopol/labeling/` | local ext4 |

The data directory is **not** on `/mnt/home` on purpose: that mount is GlusterFS, where SQLite's WAL
mode dies with a bus error on its mmap'd index. On scratch the app runs in WAL as intended.
`run.sh` points `LABELING_DB` there; pass `--db` to the CLI scripts (or export `LABELING_DB`).

## Setup

```bash
cd preference-data/human-labeling
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## 1. Sample a round

```bash
.venv/bin/python sample_pool.py --n 50 --out-prefix round1
```

Draws N prompts stratified over the seven categories (50 → 8/7/7/7/7/7/7, the extra category picked
by the seed), one randomly chosen paraphrase variant per prompt, and writes an EN and a PT file
covering the **same** prompt_ids and the same variants — so the two languages stay alignable by
`(prompt_id, paraphrase_id)`. `round1_manifest.json` records the seed and the exact selection.

Flags: `--n`, `--seed` (default 2024), `--paraphrase random|zero`, `--out-dir`, `--out-prefix`,
`--en/--pt` to point at different source files.

## 2. Seed the database

```bash
.venv/bin/python seed.py \
    --en rounds/round1_en.jsonl --pt rounds/round1_pt.jsonl \
    --db /mnt/scratch-artemis/giuseppe/lusopol/labeling/annotations.db \
    --base-url https://your-zrok-url
```

This creates the database, the seven accounts (`admin`, `en_a`/`en_b`/`en_c`, `pt_a`/`pt_b`/`pt_c`),
the item pool and the disjoint assignment, and writes the generated passwords to
**`credentials.txt`** next to the database — one block per collaborator, ready to paste into a DM.
Passwords are shown once; use the admin *Users* page (or `--rotate-passwords`) to issue new ones.

Useful flags:

| flag | effect |
| --- | --- |
| `--one-per-prompt` | keep only the lowest `paraphrase_id` per `prompt_id` (unnecessary for round files, which already hold one row per prompt) |
| `--seed N` | controls A/B blinding and queue order (default 42, reproducible) |
| `--annotators-per-lang N` | roster size per language (default 3) |
| `--reset` | wipe items, assignments **and annotations**, then rebuild |
| `--rotate-passwords` | issue new passwords for every account |

Re-running **without** `--reset` is safe and incremental: new rows are inserted and dealt to whoever
has the fewest items, existing items and their labels are left alone, and any DB item that has
disappeared from the file is reported but kept. That is how you top up a running round — or add a
`round2` on top of `round1`.

## 3. Run

```bash
./run.sh                                  # waitress on 0.0.0.0:8000, data dir preset
zrok share public localhost:8000          # in another shell
```

`PORT` and `LABELING_DB` override the defaults. `.venv/bin/python app.py` runs the Flask dev server
instead (set `LABELING_DB` yourself). Other environment variables: `SECRET_KEY` (otherwise persisted
as `secret_key.txt` in the data dir), `SESSION_COOKIE_SECURE=1` once you serve over HTTPS only,
`LABELING_JOURNAL_MODE` to force the SQLite journal mode.

## Annotating

`/` sends the annotator to their next unlabeled item. Clicking a card selects it; **Next** stays
disabled until something is selected. Keyboard: `1` / `2` pick a side, `t` marks a tie, `Enter`
continues. Long answers scroll inside their own pane — there is a *Taller panes* toggle and an
optional *Sync scrolling* checkbox for comparing. **My queue** lists the whole slice so any item can
be revisited and changed.

## Admin

Log in as `admin`:

- **Dashboard** — per-language and per-annotator progress, A/B/tie counts, comment counts, median
  time per item, last activity, and how often humans agree with the LLM judge.
- **Items** — filter by language, annotator, status, label or category; open any item to see both
  answers, the judge's original preference and reasoning, and the edit history.
- Per item you can **override or clear a label** and **reassign** an unlabeled item to another
  annotator of the same language. Every edit is recorded in the `events` table.
- **Users** — issue a new password for anyone who loses theirs.

## Export

From the dashboard (JSONL / CSV buttons), or on the command line:

```bash
export LABELING_DB=/mnt/scratch-artemis/giuseppe/lusopol/labeling/annotations.db
.venv/bin/python export.py --out annotations.jsonl
.venv/bin/python export.py --format csv --out annotations.csv
.venv/bin/python export.py --lang pt --include-unlabeled --out pt_all.jsonl
```

Each record carries the full metadata:

| field | meaning |
| --- | --- |
| `lang`, `prompt_id`, `paraphrase_id`, `category` | item identity, alignable with the source files and across languages |
| `annotator`, `choice` | who labeled it, and what they saw (`A` / `B` / `tie`) |
| `human_prefers` | the choice in dataset terms: `chosen` / `rejected` / `tie` |
| `human_preferred_model`, `agrees_with_judge` | derived from the blinding |
| `a_is_chosen` | whether the judge-preferred answer was shown on the left |
| `comment`, `time_on_item_ms` | annotator's note and time spent on the item |
| `first_labeled_at`, `labeled_at`, `edited_by_admin` | provenance of the label |
| `prompt`, `response_a`, `response_b`, `judge_reasoning` | the displayed content |
| `raw_json` | the original JSONL row, verbatim |

## Notes

- The database is a single SQLite file. Back it up by copying `annotations.db`.
- `db.py` picks the journal mode from the filesystem: WAL on local disk, the classic rollback
  journal on network/FUSE mounts, so the app still runs (more slowly) if the DB ends up on
  `/mnt/home`.
- `credentials.txt`, `secret_key.txt` and any database file are gitignored — none of them belong in
  the repository.
