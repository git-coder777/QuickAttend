"""
QuickAttend - QR based attendance system for college
Backend: Python (Flask) + SQLite
Run:  python app.py   then open  http://127.0.0.1:5000
"""
import os
import io
import csv
import time
import random
import base64
import sqlite3
from datetime import date, datetime
from functools import wraps

import qrcode
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, g, Response)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "change-this-secret-key-before-submitting"   # needed for login sessions

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "attendance.db")

QR_GRACE_SECONDS = 5      # small extra time so a scan at the last second still works
MARK_WINDOW_SECONDS = 120  # student must press "Present" within 2 minutes of scanning


# ---------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------
def get_db():
    """One database connection per request."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row   # lets us use row["name"]
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create the tables if they do not exist yet."""
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id    TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name          TEXT NOT NULL,
            class_name    TEXT DEFAULT '',
            division      TEXT DEFAULT '',
            roll_no       TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS teachers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            class_name TEXT NOT NULL,
            subject    TEXT NOT NULL,
            date       TEXT NOT NULL,      -- stored as YYYY-MM-DD
            start_time TEXT NOT NULL,      -- HH:MM
            end_time   TEXT NOT NULL,
            qr_seconds INTEGER DEFAULT 15,
            token      TEXT DEFAULT '',    -- the code inside the current QR
            token_time REAL DEFAULT 0,     -- when that code was made
            is_active  INTEGER DEFAULT 1,
            FOREIGN KEY (teacher_id) REFERENCES teachers(id)
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            student_id INTEGER NOT NULL,
            marked_at  TEXT NOT NULL,
            UNIQUE (session_id, student_id),   -- a student can mark only once per session
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (student_id) REFERENCES students(id)
        );
    """)
    db.commit()
    db.close()


# ---------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------
def clean_class(text):
    """TYCS, tycs, ' ty cs ' -> all become TYCS so they match."""
    return text.replace(" ", "").upper()


def to_12h(t):
    """'14:30' -> '2:30 PM'"""
    try:
        return datetime.strptime(t, "%H:%M").strftime("%I:%M %p").lstrip("0")
    except (ValueError, TypeError):
        return t


def to_ddmmyyyy(d):
    """'2026-10-15' -> '15-10-2026'"""
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d-%m-%Y")
    except (ValueError, TypeError):
        return d


def month_label(m):
    """'2026-10' -> 'October 2026'"""
    try:
        return datetime.strptime(m, "%Y-%m").strftime("%B %Y")
    except (ValueError, TypeError):
        return m


app.jinja_env.filters["t12"] = to_12h
app.jinja_env.filters["dmy"] = to_ddmmyyyy
app.jinja_env.filters["month_label"] = month_label


def make_qr_image(text):
    """Make a QR code and return it as a base64 'data:' string for <img src=...>"""
    img = qrcode.make(text, box_size=8, border=2)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def new_code(db):
    """Make a random 6 digit code that no other live session is using."""
    while True:
        code = f"{random.randint(0, 999999):06d}"
        used = db.execute("SELECT 1 FROM sessions WHERE token=? AND is_active=1",
                          (code,)).fetchone()
        if not used:
            return code


def sort_roll(row):
    """Sort roll numbers as numbers (2 before 10)."""
    r = str(row["roll_no"])
    return (0, int(r)) if r.isdigit() else (1, r)


# login protection ------------------------------------------------
def student_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "student":
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def teacher_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("role") != "teacher":
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def current_student():
    return get_db().execute("SELECT * FROM students WHERE id=?",
                            (session["user_id"],)).fetchone()


def get_teacher_session(session_id):
    """Fetch a session only if it belongs to the logged in teacher."""
    return get_db().execute("SELECT * FROM sessions WHERE id=? AND teacher_id=?",
                            (session_id, session["user_id"])).fetchone()


# ---------------------------------------------------------------
# LOGIN / SIGN UP / LOGOUT
# ---------------------------------------------------------------
@app.route("/")
def home():
    if session.get("role") == "student":
        return redirect(url_for("student_dashboard"))
    if session.get("role") == "teacher":
        return redirect(url_for("teacher_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    role = request.form.get("role", "student")
    if request.method == "POST":
        identifier = request.form["identifier"].strip()
        password = request.form["password"]
        db = get_db()

        if role == "student":
            user = db.execute("SELECT * FROM students WHERE student_id=?",
                              (identifier,)).fetchone()
        else:
            user = db.execute("SELECT * FROM teachers WHERE email=?",
                              (identifier.lower(),)).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["role"] = role
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            return redirect(url_for("home"))
        flash("Wrong ID/email or password. Please try again.", "error")
    return render_template("login.html", role=role)


@app.route("/signup", methods=["GET", "POST"])
def signup():
    role = request.form.get("role", request.args.get("role", "student"))
    if request.method == "POST":
        name = request.form["name"].strip()
        password = request.form["password"]
        db = get_db()

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("signup.html", role=role)

        try:
            if role == "student":
                db.execute("INSERT INTO students (student_id, password_hash, name) VALUES (?,?,?)",
                           (request.form["student_id"].strip(),
                            generate_password_hash(password), name))
            else:
                db.execute("INSERT INTO teachers (name, email, password_hash) VALUES (?,?,?)",
                           (name, request.form["email"].strip().lower(),
                            generate_password_hash(password)))
            db.commit()
        except sqlite3.IntegrityError:
            flash("This Student ID / Email is already registered.", "error")
            return render_template("signup.html", role=role)

        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("signup.html", role=role)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------
# TEACHER PAGES
# ---------------------------------------------------------------
@app.route("/teacher/dashboard")
@teacher_required
def teacher_dashboard():
    db = get_db()
    tid = session["user_id"]
    total_sessions = db.execute("SELECT COUNT(*) FROM sessions WHERE teacher_id=?",
                                (tid,)).fetchone()[0]
    today_sessions = db.execute("SELECT COUNT(*) FROM sessions WHERE teacher_id=? AND date=?",
                                (tid, date.today().isoformat())).fetchone()[0]
    recent = db.execute("""
        SELECT s.*, (SELECT COUNT(*) FROM attendance a WHERE a.session_id = s.id) AS present_count
        FROM sessions s WHERE teacher_id=? ORDER BY s.id DESC LIMIT 5""", (tid,)).fetchall()
    return render_template("teacher_dashboard.html", total_sessions=total_sessions,
                           today_sessions=today_sessions, recent=recent)


@app.route("/teacher/create", methods=["GET", "POST"])
@teacher_required
def create_session():
    if request.method == "POST":
        class_name = clean_class(request.form["class_name"])
        subject = request.form["subject"].strip()
        s_date = request.form["date"]
        start, end = request.form["start_time"], request.form["end_time"]
        qr_seconds = int(request.form.get("qr_seconds", 15))

        if not class_name or not subject:
            flash("Please fill in the class and subject.", "error")
            return render_template("create_session.html", today=date.today().isoformat())
        if end <= start:
            flash("End time must be after the start time.", "error")
            return render_template("create_session.html", today=date.today().isoformat())

        db = get_db()
        cur = db.execute("""INSERT INTO sessions
            (teacher_id, class_name, subject, date, start_time, end_time, qr_seconds)
            VALUES (?,?,?,?,?,?,?)""",
            (session["user_id"], class_name, subject, s_date, start, end, qr_seconds))
        db.commit()
        return redirect(url_for("session_qr", session_id=cur.lastrowid))
    return render_template("create_session.html", today=date.today().isoformat())


@app.route("/teacher/session/<int:session_id>")
@teacher_required
def session_qr(session_id):
    s = get_teacher_session(session_id)
    if not s:
        return redirect(url_for("teacher_dashboard"))
    count = get_db().execute("SELECT COUNT(*) FROM attendance WHERE session_id=?",
                             (session_id,)).fetchone()[0]
    return render_template("session_qr.html", s=s, count=count)


@app.route("/teacher/session/<int:session_id>/refresh", methods=["POST"])
@teacher_required
def refresh_qr(session_id):
    """Called by JavaScript every few seconds to get a brand new QR code."""
    s = get_teacher_session(session_id)
    if not s or not s["is_active"]:
        return jsonify(ok=False)
    db = get_db()
    code = new_code(db)
    db.execute("UPDATE sessions SET token=?, token_time=? WHERE id=?",
               (code, time.time(), session_id))
    db.commit()
    return jsonify(ok=True, code=code, image=make_qr_image(code), seconds=s["qr_seconds"])


@app.route("/teacher/session/<int:session_id>/count")
@teacher_required
def session_count(session_id):
    if not get_teacher_session(session_id):
        return jsonify(count=0)
    count = get_db().execute("SELECT COUNT(*) FROM attendance WHERE session_id=?",
                             (session_id,)).fetchone()[0]
    return jsonify(count=count)


@app.route("/teacher/session/<int:session_id>/stop", methods=["POST"])
@teacher_required
def stop_session(session_id):
    if get_teacher_session(session_id):
        db = get_db()
        db.execute("UPDATE sessions SET is_active=0, token='' WHERE id=?", (session_id,))
        db.commit()
        flash("Session ended. Students can no longer mark attendance.", "success")
    return redirect(url_for("session_attendance", session_id=session_id))


@app.route("/teacher/session/<int:session_id>/attendance")
@teacher_required
def session_attendance(session_id):
    s = get_teacher_session(session_id)
    if not s:
        return redirect(url_for("teacher_dashboard"))
    students = get_db().execute("""
        SELECT st.name, st.roll_no, st.class_name, st.division, a.marked_at
        FROM attendance a JOIN students st ON st.id = a.student_id
        WHERE a.session_id=?""", (session_id,)).fetchall()
    students = sorted(students, key=sort_roll)
    return render_template("session_attendance.html", s=s, students=students)


def build_report(teacher_id, class_name, month):
    """
    Monthly report for one class.
    Returns (list of sessions, list of student rows with present count and percentage)
    """
    db = get_db()
    sessions = db.execute("""SELECT * FROM sessions
        WHERE teacher_id=? AND class_name=? AND date LIKE ?
        ORDER BY date, start_time""", (teacher_id, class_name, month + "-%")).fetchall()
    ids = [s["id"] for s in sessions]

    # all students of that class (so absentees also show up)
    students = {r["id"]: dict(r) for r in db.execute(
        "SELECT * FROM students WHERE UPPER(REPLACE(class_name,' ',''))=?", (class_name,))}

    marks = set()   # (student_id, session_id) pairs that are present
    if ids:
        marks_query = db.execute(
            "SELECT student_id, session_id FROM attendance WHERE session_id IN (%s)"
            % ",".join("?" * len(ids)), ids).fetchall()
        for m in marks_query:
            marks.add((m["student_id"], m["session_id"]))
            if m["student_id"] not in students:      # student changed class later
                students[m["student_id"]] = dict(db.execute(
                    "SELECT * FROM students WHERE id=?", (m["student_id"],)).fetchone())

    rows = []
    for sid, st in students.items():
        flags = [(sid, s_id) in marks for s_id in ids]
        present = sum(flags)
        percent = round(present * 100 / len(ids)) if ids else 0
        rows.append({"name": st["name"], "roll_no": st["roll_no"], "student_id": st["student_id"],
                     "flags": flags, "present": present, "total": len(ids), "percent": percent})
    rows.sort(key=sort_roll)
    return sessions, rows


@app.route("/teacher/history")
@teacher_required
def history():
    db = get_db()
    classes = [r[0] for r in db.execute(
        "SELECT DISTINCT class_name FROM sessions WHERE teacher_id=? ORDER BY class_name",
        (session["user_id"],))]

    today = date.today()
    this_month = today.strftime("%Y-%m")
    last_month = (date(today.year - 1, 12, 1) if today.month == 1
                  else date(today.year, today.month - 1, 1)).strftime("%Y-%m")

    selected_class = request.args.get("class_name", classes[0] if classes else "")
    month = request.args.get("month", this_month)

    sessions, rows = [], []
    if selected_class:
        sessions, rows = build_report(session["user_id"], selected_class, month)

    average = round(sum(r["percent"] for r in rows) / len(rows)) if rows and sessions else 0
    return render_template("history.html", classes=classes, selected_class=selected_class,
                           month=month, this_month=this_month, last_month=last_month,
                           sessions=sessions, rows=rows, average=average)


@app.route("/teacher/history/report.csv")
@teacher_required
def download_report():
    class_name = request.args.get("class_name", "")
    month = request.args.get("month", "")
    sessions, rows = build_report(session["user_id"], class_name, month)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([f"Attendance report - {class_name} - {month_label(month)}"])
    writer.writerow(["Roll No", "Name", "Student ID"]
                    + [f"{to_ddmmyyyy(s['date'])} {s['subject']}" for s in sessions]
                    + ["Present", "Total lectures", "Percentage"])
    for r in rows:
        writer.writerow([r["roll_no"], r["name"], r["student_id"]]
                        + ["P" if f else "A" for f in r["flags"]]
                        + [r["present"], r["total"], f"{r['percent']}%"])

    filename = f"attendance_{class_name}_{month}.csv"
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


# ---------------------------------------------------------------
# STUDENT PAGES
# ---------------------------------------------------------------
@app.route("/student/dashboard")
@student_required
def student_dashboard():
    db = get_db()
    st = current_student()
    present = db.execute("SELECT COUNT(*) FROM attendance WHERE student_id=?",
                         (st["id"],)).fetchone()[0]
    total = 0
    if st["class_name"]:
        total = db.execute("SELECT COUNT(*) FROM sessions WHERE class_name=?",
                           (clean_class(st["class_name"]),)).fetchone()[0]
    percent = round(present * 100 / total) if total else 0
    return render_template("student_dashboard.html", st=st, present=present,
                           total=total, percent=percent)


@app.route("/student/profile", methods=["GET", "POST"])
@student_required
def student_profile():
    db = get_db()
    if request.method == "POST":
        db.execute("UPDATE students SET name=?, class_name=?, division=?, roll_no=? WHERE id=?",
                   (request.form["name"].strip(), clean_class(request.form["class_name"]),
                    request.form["division"].strip().upper(),
                    request.form["roll_no"].strip(), session["user_id"]))
        db.commit()
        session["name"] = request.form["name"].strip()
        flash("Profile saved.", "success")
        return redirect(url_for("student_profile"))

    st = current_student()
    history_rows = db.execute("""
        SELECT s.subject, s.date, s.start_time, s.end_time, a.marked_at
        FROM attendance a JOIN sessions s ON s.id = a.session_id
        WHERE a.student_id=? ORDER BY a.id DESC""", (st["id"],)).fetchall()

    # subject wise summary: lectures held vs lectures attended
    subjects = []
    if st["class_name"]:
        subjects = db.execute("""
            SELECT s.subject,
                   COUNT(*) AS total,
                   SUM(CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END) AS present
            FROM sessions s
            LEFT JOIN attendance a ON a.session_id = s.id AND a.student_id = ?
            WHERE s.class_name = ?
            GROUP BY s.subject ORDER BY s.subject""",
            (st["id"], clean_class(st["class_name"]))).fetchall()
    return render_template("student_profile.html", st=st, history=history_rows, subjects=subjects)


@app.route("/student/scan")
@student_required
def student_scan():
    return render_template("student_scan.html")


@app.route("/student/scan", methods=["POST"])
@student_required
def student_scan_code():
    """Student scanned (or typed) a code. Check it and send back the session details."""
    code = (request.get_json() or {}).get("code", "").strip()
    db = get_db()
    st = current_student()

    if not st["class_name"] or not st["roll_no"]:
        return jsonify(ok=False, message="Please complete your profile (class, division and roll number) first.")

    s = db.execute("SELECT * FROM sessions WHERE token=? AND is_active=1", (code,)).fetchone()
    if not s or time.time() - s["token_time"] > s["qr_seconds"] + QR_GRACE_SECONDS:
        return jsonify(ok=False, message="This QR code is invalid or has expired. Scan the latest code on the teacher's screen.")

    if clean_class(st["class_name"]) != s["class_name"]:
        return jsonify(ok=False, message=f"This session is for class {s['class_name']}, but your profile says {st['class_name']}.")

    already = db.execute("SELECT 1 FROM attendance WHERE session_id=? AND student_id=?",
                         (s["id"], st["id"])).fetchone()
    if already:
        return jsonify(ok=False, message="You have already marked your attendance for this session.")

    session["scan"] = {"session_id": s["id"], "time": time.time()}
    teacher = db.execute("SELECT name FROM teachers WHERE id=?", (s["teacher_id"],)).fetchone()
    return jsonify(ok=True, subject=s["subject"], class_name=s["class_name"],
                   date=to_ddmmyyyy(s["date"]),
                   time=f"{to_12h(s['start_time'])} - {to_12h(s['end_time'])}",
                   teacher=teacher["name"])


@app.route("/student/mark", methods=["POST"])
@student_required
def student_mark():
    """Student pressed the 'Present' button."""
    scan = session.get("scan")
    if not scan or time.time() - scan["time"] > MARK_WINDOW_SECONDS:
        return jsonify(ok=False, message="Scan session timed out. Please scan the QR again.")

    db = get_db()
    s = db.execute("SELECT is_active FROM sessions WHERE id=?", (scan["session_id"],)).fetchone()
    if not s or not s["is_active"]:
        return jsonify(ok=False, message="This session has ended.")

    try:
        db.execute("INSERT INTO attendance (session_id, student_id, marked_at) VALUES (?,?,?)",
                   (scan["session_id"], session["user_id"],
                    datetime.now().strftime("%d-%m-%Y %I:%M %p")))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify(ok=False, message="You have already marked your attendance.")

    session.pop("scan", None)
    return jsonify(ok=True, message="Attendance marked successfully!")


# ---------------------------------------------------------------
init_db()

if __name__ == "__main__":
    # Camera access on a phone needs HTTPS. To use it set USE_HTTPS=1 (needs: pip install cryptography)
    use_https = os.environ.get("USE_HTTPS") == "1"
    app.run(host="0.0.0.0", port=5000, debug=True,
            ssl_context="adhoc" if use_https else None)
