"""User accounts, login sessions and exam attempts, kept in their own
SQLite database (USERS_DB) since the question database is rebuilt on every
start.

    users       username and password hash (PBKDF2-SHA256)
    sessions    login sessions, by the SHA-256 of their cookie token
    exams       one per attempt: category, language, when it started and
                finished, points scored and whether it passed
    exam_items  its 32 questions in order, with their points and correct
                answer as they were when drawn, and the answer given
"""

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time

import config
import exam

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,   -- casefolded, for lookups
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    category TEXT NOT NULL,
    lang TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,                    -- NULL while in progress
    score INTEGER,
    passed INTEGER
);
CREATE INDEX IF NOT EXISTS exams_by_user ON exams (user_id, started_at);
CREATE TABLE IF NOT EXISTS exam_items (
    exam_id INTEGER NOT NULL REFERENCES exams(id),
    position INTEGER NOT NULL,           -- 0-31, the order they're asked
    question_id INTEGER NOT NULL,
    scope TEXT NOT NULL,
    points INTEGER NOT NULL,
    correct TEXT NOT NULL,
    answer TEXT,                         -- NULL: not answered (yet)
    answered INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (exam_id, position)
);
"""

USERNAME_RE = re.compile(r"[\w.\-]{3,32}")
MIN_PASSWORD = 6
PBKDF2_ITERATIONS = 200000
SESSION_DAYS = 30
# How long past the 25 minutes an answer is still taken (slow networks).
GRACE_SECONDS = 30


class Error(ValueError):
    """A request that can't be done, with a message for the user."""


def connect():
    conn = sqlite3.connect(config.USERS_DB, timeout=10)
    conn.row_factory = lambda cursor, row: {
        d[0]: v for d, v in zip(cursor.description, row)}
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init():
    conn = connect()
    with conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
    conn.close()


# --- accounts ---------------------------------------------------------

def _hash_password(password, salt=None, iterations=PBKDF2_ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt.encode("ascii"), iterations)
    return "pbkdf2_sha256$%d$%s$%s" % (iterations, salt, digest.hex())


def _check_password(password, stored):
    _, iterations, salt, _ = stored.split("$")
    return hmac.compare_digest(
        _hash_password(password, salt, int(iterations)), stored)


def create_user(conn, username, password):
    username = (username or "").strip()
    if not USERNAME_RE.fullmatch(username):
        raise Error("Nazwa użytkownika: 3–32 znaki, litery, cyfry, "
                    "kropka, myślnik lub podkreślnik.")
    if len(password or "") < MIN_PASSWORD:
        raise Error("Hasło musi mieć co najmniej %d znaków." % MIN_PASSWORD)
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO users (username, username_key, password_hash, "
                "created_at) VALUES (?, ?, ?, ?)",
                (username, username.casefold(), _hash_password(password),
                 time.time()))
    except sqlite3.IntegrityError:
        raise Error("Ta nazwa użytkownika jest już zajęta.")
    return {"id": cursor.lastrowid, "username": username}


def check_login(conn, username, password):
    """Returns the user, or None if the name or password is wrong."""
    user = conn.execute(
        "SELECT id, username, password_hash FROM users "
        "WHERE username_key = ?",
        ((username or "").strip().casefold(),)).fetchone()
    if user and _check_password(password or "", user["password_hash"]):
        return {"id": user["id"], "username": user["username"]}
    if not user:
        _hash_password(password or "")  # take as long as a wrong password
    return None


def _token_hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(conn, user_id):
    """Returns a new session's token, for the cookie."""
    token = secrets.token_urlsafe(32)
    with conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?",
                     (time.time(),))
        conn.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                     (_token_hash(token), user_id,
                      time.time() + SESSION_DAYS * 86400))
    return token


def session_user(conn, token):
    """Returns the session's user, or None; extends the session."""
    if not token:
        return None
    try:
        key = _token_hash(token)
    except UnicodeEncodeError:
        return None
    user = conn.execute(
        "SELECT u.id, u.username FROM sessions s JOIN users u "
        "ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ?",
        (key, time.time())).fetchone()
    if user:
        with conn:
            conn.execute("UPDATE sessions SET expires_at = ? "
                         "WHERE token_hash = ?",
                         (time.time() + SESSION_DAYS * 86400, key))
    return user


def delete_session(conn, token):
    if token:
        with conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?",
                         (_token_hash(token),))


# --- exams ------------------------------------------------------------

def _deadline(started_at):
    return started_at + exam.DURATION_MINUTES * 60


def finish(conn, exam_id):
    """Scores the exam; unanswered questions score nothing."""
    items = conn.execute("SELECT points, correct, answer FROM exam_items "
                         "WHERE exam_id = ?", (exam_id,)).fetchall()
    score = sum(i["points"] for i in items if i["answer"] == i["correct"])
    with conn:
        conn.execute("UPDATE exams SET finished_at = ?, score = ?, "
                     "passed = ? WHERE id = ? AND finished_at IS NULL",
                     (time.time(), score, int(score >= exam.PASS_POINTS),
                      exam_id))


def _finish_expired(conn, user_id):
    """Finishes the user's exams whose time is up."""
    for row in conn.execute(
            "SELECT id, started_at FROM exams WHERE user_id = ? "
            "AND finished_at IS NULL", (user_id,)).fetchall():
        if time.time() > _deadline(row["started_at"]) + GRACE_SECONDS:
            finish(conn, row["id"])


def start_exam(conn, user_id, category, lang, questions):
    """Records a new exam of questions (from exam.draw); an exam the user
    left unfinished is finished first, as it stands."""
    for row in conn.execute("SELECT id FROM exams WHERE user_id = ? "
                            "AND finished_at IS NULL", (user_id,)).fetchall():
        finish(conn, row["id"])
    with conn:
        exam_id = conn.execute(
            "INSERT INTO exams (user_id, category, lang, started_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, category, lang, time.time())).lastrowid
        conn.executemany(
            "INSERT INTO exam_items (exam_id, position, question_id, scope, "
            "points, correct) VALUES (?, ?, ?, ?, ?, ?)",
            [(exam_id, i, q["id"], q["scope"], q["points"], q["correct"])
             for i, q in enumerate(questions)])
    return exam_id


def get_exam(conn, user_id, exam_id=None):
    """The user's exam by id, or their exam in progress; None if there's
    no such exam."""
    _finish_expired(conn, user_id)
    if exam_id is None:
        row = conn.execute("SELECT * FROM exams WHERE user_id = ? AND "
                           "finished_at IS NULL", (user_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM exams WHERE user_id = ? AND id = ?",
                           (user_id, exam_id)).fetchone()
    if row:
        row["items"] = conn.execute(
            "SELECT * FROM exam_items WHERE exam_id = ? ORDER BY position",
            (row["id"],)).fetchall()
        row["remaining"] = max(0, _deadline(row["started_at"]) - time.time())
    return row


def answer(conn, user_id, exam_id, position, given):
    """Records the answer to the exam's next question (given None: no
    answer); finishes the exam after the last one."""
    row = get_exam(conn, user_id, exam_id)
    if not row:
        raise Error("Nie ma takiego egzaminu.")
    if row["finished_at"] is not None:
        raise Error("Ten egzamin jest już zakończony.")
    items = row["items"]
    next_position = next((i["position"] for i in items if not i["answered"]),
                         None)
    if position != next_position:
        raise Error("Odpowiadać można tylko na bieżące pytanie, "
                    "do poprzednich nie można wracać.")
    allowed = ("T", "N") if items[position]["scope"] == "basic" \
        else ("A", "B", "C")
    if given is not None and given not in allowed:
        raise Error("Nieprawidłowa odpowiedź.")
    with conn:
        conn.execute("UPDATE exam_items SET answer = ?, answered = 1 "
                     "WHERE exam_id = ? AND position = ?",
                     (given, exam_id, position))
    if position == len(items) - 1:
        finish(conn, exam_id)
        return True
    return False


def stats(conn, user_id):
    _finish_expired(conn, user_id)
    row = conn.execute(
        "SELECT COUNT(*) AS taken, COALESCE(SUM(passed), 0) AS passed, "
        "AVG(score) AS average FROM exams "
        "WHERE user_id = ? AND finished_at IS NOT NULL",
        (user_id,)).fetchone()
    return {"taken": row["taken"], "passed": row["passed"],
            "failed": row["taken"] - row["passed"],
            "average": round(row["average"], 1)
            if row["average"] is not None else None}


def history(conn, user_id, limit=20):
    return conn.execute(
        "SELECT id, category, lang, started_at, finished_at, score, passed "
        "FROM exams WHERE user_id = ? AND finished_at IS NOT NULL "
        "ORDER BY started_at DESC LIMIT ?", (user_id, limit)).fetchall()
