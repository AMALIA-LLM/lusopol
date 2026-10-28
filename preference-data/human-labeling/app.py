#!/usr/bin/env python3
"""Flask app for side-by-side human preference labeling.

Run the seeding script first, then:

    python app.py            # http://0.0.0.0:8000
"""

import os
import secrets
import time
from collections import defaultdict
from functools import wraps
from pathlib import Path
from statistics import median

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db
import export as export_mod
from render import render_markdown

APP_DIR = Path(__file__).resolve().parent
LOGIN_WINDOW = 300      # seconds
LOGIN_MAX_FAILURES = 10

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or None,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
    MAX_CONTENT_LENGTH=1024 * 1024,
)

if not app.config["SECRET_KEY"]:
    # Persisted next to the database so sessions survive a restart of the process.
    db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    key_file = db.DB_PATH.parent / "secret_key.txt"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")
        key_file.chmod(0o600)
    app.config["SECRET_KEY"] = key_file.read_text(encoding="utf-8").strip()

_login_failures = defaultdict(list)


# --- request plumbing --------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = db.connect()
    return g.db


@app.teardown_appcontext
def close_db(exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@app.before_request
def load_user():
    g.user = None
    username = session.get("username")
    if username:
        g.user = db.get_user(get_db(), username)
        if g.user is None:
            session.clear()


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


@app.before_request
def check_csrf():
    if request.method == "POST":
        if not secrets.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
            abort(400, "invalid or expired form token — please reload the page")


@app.context_processor
def template_globals():
    return {"user": g.get("user"), "csrf_token": csrf_token}


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not g.user:
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not g.user:
            return redirect(url_for("login", next=request.path))
        if g.user["role"] != "admin":
            abort(403)
        return view(*a, **kw)
    return wrapped


# --- auth --------------------------------------------------------------------

def throttled(ip: str) -> bool:
    cutoff = time.time() - LOGIN_WINDOW
    hits = [t for t in _login_failures[ip] if t > cutoff]
    _login_failures[ip] = hits
    return len(hits) >= LOGIN_MAX_FAILURES


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if throttled(ip):
            flash("Too many failed attempts. Wait a few minutes and try again.", "error")
            return render_template("login.html"), 429
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = db.get_user(get_db(), username)
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.permanent = True
            session["username"] = user["username"]
            csrf_token()
            target = request.args.get("next", "")
            safe = target.startswith("/") and not target.startswith("//")
            return redirect(target if safe else url_for("index"))
        _login_failures[ip].append(time.time())
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# --- annotation --------------------------------------------------------------

@app.route("/")
@login_required
def index():
    if g.user["role"] == "admin":
        return redirect(url_for("admin_overview"))
    position = db.next_unlabeled_position(get_db(), g.user["username"])
    if position is None:
        return redirect(url_for("done"))
    return redirect(url_for("annotate", position=position))


@app.route("/item/<int:position>")
@login_required
def annotate(position):
    conn = get_db()
    username = g.user["username"]
    item = db.item_at_position(conn, username, position)
    if item is None:
        abort(404)
    stats = db.progress(conn, username)
    return render_template(
        "annotate.html",
        item=item,
        position=position,
        stats=stats,
        prompt_html=render_markdown(item["prompt"]),
        response_a_html=render_markdown(item["response_a"]),
        response_b_html=render_markdown(item["response_b"]),
        has_prev=position > 1,
        has_next=position < stats["total"],
    )


@app.route("/item/<int:position>", methods=["POST"])
@login_required
def save(position):
    conn = get_db()
    username = g.user["username"]
    item = db.item_at_position(conn, username, position)
    if item is None:
        abort(404)

    choice = request.form.get("choice", "")
    comment = request.form.get("comment", "").strip()[:4000]
    action = request.form.get("action", "next")
    elapsed = request.form.get("elapsed_ms", "")
    elapsed = int(elapsed) if elapsed.isdigit() else None

    if choice not in db.CHOICES:
        # Going back without an answer is fine; going forward is not.
        if action == "prev":
            return redirect(url_for("annotate", position=max(1, position - 1)))
        flash("Pick one of the two answers, or mark them as a tie.", "error")
        return redirect(url_for("annotate", position=position))

    db.save_annotation(conn, item["id"], username, choice, comment, elapsed)
    conn.commit()

    stats = db.progress(conn, username)
    if action == "prev":
        return redirect(url_for("annotate", position=max(1, position - 1)))
    if position < stats["total"]:
        return redirect(url_for("annotate", position=position + 1))
    nxt = db.next_unlabeled_position(conn, username)
    return redirect(url_for("annotate", position=nxt) if nxt else url_for("done"))


@app.route("/overview")
@login_required
def overview():
    """The annotator's own queue, so they can jump back to any item."""
    if g.user["role"] == "admin":
        return redirect(url_for("admin_items"))
    conn = get_db()
    return render_template(
        "overview.html",
        rows=db.slice_for(conn, g.user["username"]),
        stats=db.progress(conn, g.user["username"]),
    )


@app.route("/done")
@login_required
def done():
    conn = get_db()
    username = g.user["username"]
    counts = {row["choice"]: row["n"] for row in conn.execute(
        """
        SELECT an.choice, COUNT(*) AS n
        FROM annotations an JOIN assignments a ON a.item_id = an.item_id
        WHERE an.username = ? AND a.username = an.username
        GROUP BY an.choice
        """,
        (username,),
    )}
    return render_template("done.html", stats=db.progress(conn, username), counts=counts)


# --- admin -------------------------------------------------------------------

def _renumber(conn, username):
    """Compact a user's queue positions to 1..N, preserving order."""
    rows = conn.execute(
        "SELECT item_id FROM assignments WHERE username = ? ORDER BY position",
        (username,),
    ).fetchall()
    for i, row in enumerate(rows, 1):
        conn.execute("UPDATE assignments SET position = ? WHERE item_id = ?", (i, row["item_id"]))


@app.route("/admin")
@admin_required
def admin_overview():
    conn = get_db()
    people = conn.execute(
        """
        SELECT u.username, u.lang, u.display_name,
               COUNT(a.item_id) AS assigned,
               SUM(CASE WHEN an.choice IS NOT NULL THEN 1 ELSE 0 END) AS labeled,
               SUM(CASE WHEN an.choice = 'A' THEN 1 ELSE 0 END) AS n_a,
               SUM(CASE WHEN an.choice = 'B' THEN 1 ELSE 0 END) AS n_b,
               SUM(CASE WHEN an.choice = 'tie' THEN 1 ELSE 0 END) AS n_tie,
               SUM(CASE WHEN an.comment != '' THEN 1 ELSE 0 END) AS n_comments,
               MAX(an.updated_at) AS last_activity
        FROM users u
        LEFT JOIN assignments a ON a.username = u.username
        LEFT JOIN annotations an ON an.item_id = a.item_id AND an.username = u.username
        WHERE u.role = 'annotator'
        GROUP BY u.username
        ORDER BY u.lang, u.username
        """
    ).fetchall()

    times = defaultdict(list)
    for row in conn.execute(
        "SELECT username, time_on_item_ms FROM annotations WHERE time_on_item_ms IS NOT NULL"
    ):
        times[row["username"]].append(row["time_on_item_ms"])
    medians = {}
    for username, values in times.items():
        medians[username] = median(values) / 1000.0

    agreement = conn.execute(
        """
        SELECT i.lang,
               SUM(CASE WHEN (an.choice = 'A') = (i.a_is_chosen = 1) AND an.choice != 'tie'
                        THEN 1 ELSE 0 END) AS agree,
               SUM(CASE WHEN an.choice != 'tie' THEN 1 ELSE 0 END) AS decided,
               COUNT(*) AS labeled
        FROM annotations an JOIN items i ON i.id = an.item_id
        GROUP BY i.lang
        """
    ).fetchall()

    return render_template("admin/overview.html", people=people, medians=medians,
                           agreement=agreement, total=db.progress_all(conn))


@app.route("/admin/items")
@admin_required
def admin_items():
    conn = get_db()
    filters, params = [], []
    for column, key in (("i.lang", "lang"), ("a.username", "user"),
                        ("i.category", "category"), ("an.choice", "choice")):
        value = request.args.get(key, "")
        if value:
            filters.append(f"{column} = ?")
            params.append(value)
    status = request.args.get("status", "")
    if status == "labeled":
        filters.append("an.choice IS NOT NULL")
    elif status == "pending":
        filters.append("an.choice IS NULL")
    where = (" WHERE " + " AND ".join(filters)) if filters else ""

    rows = conn.execute(
        f"""
        SELECT i.id, i.lang, i.prompt_id, i.paraphrase_id, i.category, i.prompt,
               i.a_is_chosen, a.username, a.position,
               an.choice, an.comment, an.updated_at, an.edited_by_admin
        FROM items i
        LEFT JOIN assignments a ON a.item_id = i.id
        LEFT JOIN annotations an ON an.item_id = i.id AND an.username = a.username
        {where}
        ORDER BY i.lang, a.username, a.position
        LIMIT 1000
        """,
        params,
    ).fetchall()
    categories = [r[0] for r in conn.execute(
        "SELECT DISTINCT category FROM items WHERE category IS NOT NULL ORDER BY category")]
    return render_template("admin/items.html", rows=rows, categories=categories,
                           people=db.annotators(conn), args=request.args)


@app.route("/admin/item/<int:item_id>")
@admin_required
def admin_item(item_id):
    conn = get_db()
    row = conn.execute(
        """
        SELECT i.*, a.username, a.position, an.choice, an.comment, an.updated_at,
               an.time_on_item_ms, an.edited_by_admin
        FROM items i
        LEFT JOIN assignments a ON a.item_id = i.id
        LEFT JOIN annotations an ON an.item_id = i.id AND an.username = a.username
        WHERE i.id = ?
        """,
        (item_id,),
    ).fetchone()
    if row is None:
        abort(404)
    events = conn.execute(
        "SELECT * FROM events WHERE item_id = ? ORDER BY id DESC LIMIT 20", (item_id,)
    ).fetchall()
    return render_template(
        "admin/item.html", item=row, events=events,
        peers=db.annotators(conn, row["lang"]),
        prompt_html=render_markdown(row["prompt"]),
        response_a_html=render_markdown(row["response_a"]),
        response_b_html=render_markdown(row["response_b"]),
        judge_html=render_markdown(row["judge_reasoning"] or ""),
    )


@app.route("/admin/item/<int:item_id>", methods=["POST"])
@admin_required
def admin_item_edit(item_id):
    conn = get_db()
    row = conn.execute(
        "SELECT i.id, i.lang, a.username FROM items i "
        "LEFT JOIN assignments a ON a.item_id = i.id WHERE i.id = ?",
        (item_id,),
    ).fetchone()
    if row is None:
        abort(404)
    action = request.form.get("action", "")
    actor = g.user["username"]

    if action == "save_label":
        choice = request.form.get("choice", "")
        comment = request.form.get("comment", "").strip()[:4000]
        if not row["username"]:
            flash("This item has no annotator assigned.", "error")
        elif choice not in db.CHOICES:
            flash("Pick a label first.", "error")
        else:
            db.save_annotation(conn, item_id, row["username"], choice, comment, by_admin=True)
            db.log_event(conn, actor, "admin_edit_label", item_id,
                         {"choice": choice, "annotator": row["username"]})
            flash("Label updated.", "ok")

    elif action == "clear_label":
        conn.execute("DELETE FROM annotations WHERE item_id = ?", (item_id,))
        db.log_event(conn, actor, "admin_clear_label", item_id, None)
        flash("Label cleared.", "ok")

    elif action == "reassign":
        target = request.form.get("username", "")
        user = db.get_user(conn, target)
        if not user or user["role"] != "annotator" or user["lang"] != row["lang"]:
            flash("Pick an annotator working on this language.", "error")
        elif conn.execute("SELECT 1 FROM annotations WHERE item_id = ?", (item_id,)).fetchone():
            flash("Clear the existing label before reassigning this item.", "error")
        else:
            previous = row["username"]
            top = conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 AS p FROM assignments WHERE username = ?",
                (target,),
            ).fetchone()["p"]
            conn.execute(
                "INSERT INTO assignments (item_id, username, position) VALUES (?, ?, ?) "
                "ON CONFLICT(item_id) DO UPDATE SET username = excluded.username, "
                "position = excluded.position",
                (item_id, target, top),
            )
            if previous:
                _renumber(conn, previous)
            db.log_event(conn, actor, "admin_reassign", item_id,
                         {"from": previous, "to": target})
            flash(f"Reassigned to {target}.", "ok")

    conn.commit()
    return redirect(url_for("admin_item", item_id=item_id))


@app.route("/admin/users")
@admin_required
def admin_users():
    conn = get_db()
    return render_template("admin/users.html",
                           users=conn.execute(
                               "SELECT * FROM users ORDER BY role, lang, username").fetchall(),
                           new_password=session.pop("new_password", None))


@app.route("/admin/users/<username>/rotate", methods=["POST"])
@admin_required
def admin_rotate(username):
    conn = get_db()
    if db.get_user(conn, username) is None:
        abort(404)
    import seed  # local import: only needed for the password generator
    password = seed.make_password()
    conn.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                 (generate_password_hash(password), username))
    db.log_event(conn, g.user["username"], "admin_rotate_password", None, {"username": username})
    conn.commit()
    session["new_password"] = {"username": username, "password": password}
    return redirect(url_for("admin_users"))


@app.route("/admin/export.<fmt>")
@admin_required
def admin_export(fmt):
    if fmt not in ("jsonl", "csv"):
        abort(404)
    include = request.args.get("include_unlabeled") == "1"
    records = export_mod.collect(get_db(), include, request.args.get("lang") or None)
    body = export_mod.to_jsonl(records) if fmt == "jsonl" else export_mod.to_csv(records)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return Response(
        body,
        mimetype="application/json" if fmt == "jsonl" else "text/csv",
        headers={"Content-Disposition": f'attachment; filename="annotations-{stamp}.{fmt}"'},
    )


@app.route("/healthz")
def healthz():
    return {"ok": True}


@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="Not your page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Nothing here."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("error.html", code=400, message=str(e.description)), 400


if __name__ == "__main__":
    if not db.DB_PATH.exists():
        raise SystemExit(f"no database at {db.DB_PATH} — run seed.py first")
    app.run(host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", 8000)),
            threaded=True, debug=os.environ.get("DEBUG") == "1")
