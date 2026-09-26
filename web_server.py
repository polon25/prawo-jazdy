"""The app's web server, standard library only. Every /api request and
reply is JSON; errors are {"error": message}.

    GET  /api/meta             categories, languages, which categories each
                               language can make a full exam for, the exam
                               rules and where the questions came from
    POST /api/register         {username, password}: creates an account and
                               logs in (sets the session cookie)
    POST /api/login            {username, password}
    POST /api/logout
    GET  /api/me               the logged-in user, their statistics, recent
                               exams and exam in progress (401 if logged out)
    POST /api/exams            {category, lang}: starts a new exam
    GET  /api/exams/current    the exam in progress, or null
    POST /api/exams/<id>/answer
                               {position, answer}: answers the next question
                               (answer null: no answer)
    POST /api/exams/<id>/finish
                               ends the exam as it stands (time's up, or
                               the user gave up)
    GET  /api/exams/<id>       a finished exam with the correct answers
    GET  /media/<file>         a question's picture or video (with Range
                               requests, so videos can be scrubbed)
    anything else              the static page in web/

An exam in progress is sent without its correct answers; the server keeps
them, takes answers only in order and scores the exam.
"""

import json
import logging
import mimetypes
import os
import re
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import config
import database
import exam
import userdb
from catalog import LANGUAGE_NAMES

log = logging.getLogger("web")

COOKIE = "session"
MAX_BODY = 16 * 1024


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _meta():
    conn = database.connect()
    try:
        info = dict((r["key"], r["value"]) for r in
                    conn.execute("SELECT key, value FROM meta"))
        categories = [r["category"] for r in conn.execute(
            "SELECT DISTINCT category FROM question_categories "
            "ORDER BY category")]
        count = conn.execute("SELECT COUNT(*) AS n FROM questions "
                             "WHERE usable").fetchone()["n"]
        sources = json.loads(info.get("sources") or "{}")
        return {
            "categories": categories,
            "languages": [{"code": code, "name": name}
                          for code, name in LANGUAGE_NAMES.items()],
            "available": exam.availability(conn),
            "rules": exam.RULES,
            "questions": count,
            "catalog": sources.get("catalog", {}).get("file"),
            "built_at": info.get("built_at")}
    finally:
        conn.close()


def _texts(ids, lang):
    """{question id: its media and texts in lang}"""
    conn = database.connect()
    try:
        rows = conn.execute(
            "SELECT q.id, q.media, q.media_type, t.question, t.answer_a, "
            "t.answer_b, t.answer_c FROM questions q LEFT JOIN "
            "question_texts t ON t.question_id = q.id AND t.lang = ? "
            "WHERE q.id IN (%s)" % ",".join("?" * len(ids)),
            [lang] + list(ids)).fetchall()
    finally:
        conn.close()
    return {r["id"]: r for r in rows}


def _exam_json(row, reveal):
    """An exam for the page; reveal adds the correct and given answers."""
    texts = _texts([i["question_id"] for i in row["items"]], row["lang"])
    questions = []
    for item in row["items"]:
        t = texts.get(item["question_id"]) or {}
        q = {"position": item["position"], "id": item["question_id"],
             "scope": item["scope"], "points": item["points"],
             "question": t.get("question"),
             "media_type": t.get("media_type"),
             "media_url": ("media/" + urllib.parse.quote(t["media"])
                           if t.get("media") else None)}
        if item["scope"] == "specialist":
            q["answers"] = {"A": t.get("answer_a"), "B": t.get("answer_b"),
                            "C": t.get("answer_c")}
        if reveal:
            q["correct"] = item["correct"]
            q["answer"] = item["answer"]
        questions.append(q)
    data = {"id": row["id"], "category": row["category"],
            "lang": row["lang"], "started_at": row["started_at"],
            "finished": row["finished_at"] is not None,
            "questions": questions}
    if data["finished"]:
        data.update(score=row["score"], passed=bool(row["passed"]),
                    finished_at=row["finished_at"])
    else:
        data["remaining"] = row["remaining"]
        data["next_position"] = next(
            (i["position"] for i in row["items"] if not i["answered"]), None)
    return data


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=config.WEB_DIR, **kwargs)

    def log_message(self, format, *args):
        log.debug("%s - %s", self.address_string(), format % args)

    # --- dispatch -----------------------------------------------------

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/api/"):
            return self._api("GET", path)
        if path.startswith("/media/"):
            return self._media(urllib.parse.unquote(path[7:]))
        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/api/"):
            return self._api("POST", path)
        self.send_error(405)

    def _api(self, method, path):
        self._cookie = None
        conn = userdb.connect()
        try:
            data = self._route(conn, method, path)
            status = 200
        except userdb.Error as e:
            data, status = {"error": str(e)}, 400
        except HttpError as e:
            data, status = {"error": str(e)}, e.status
        except Exception:
            log.exception("%s %s failed", method, path)
            data, status = {"error": "Błąd serwera."}, 500
        finally:
            conn.close()
        self._json(data, status)

    def _route(self, conn, method, path):
        if method == "GET" and path == "/api/meta":
            return _meta()
        if method == "POST" and path == "/api/register":
            body = self._body()
            user = userdb.create_user(conn, body.get("username"),
                                      body.get("password"))
            self._log_in(conn, user)
            return {"user": user}
        if method == "POST" and path == "/api/login":
            body = self._body()
            user = userdb.check_login(conn, body.get("username"),
                                      body.get("password"))
            if not user:
                time.sleep(1)  # slows down password guessing
                raise HttpError(401, "Nieprawidłowa nazwa użytkownika "
                                     "lub hasło.")
            self._log_in(conn, user)
            return {"user": user}
        if method == "POST" and path == "/api/logout":
            userdb.delete_session(conn, self._token())
            self._cookie = ""
            return {}

        user = userdb.session_user(conn, self._token())
        if not user:
            raise HttpError(401, "Zaloguj się.")
        if method == "GET" and path == "/api/me":
            current = userdb.get_exam(conn, user["id"])
            return {"user": user, "stats": userdb.stats(conn, user["id"]),
                    "history": userdb.history(conn, user["id"]),
                    "current": current and {
                        "id": current["id"], "category": current["category"],
                        "lang": current["lang"],
                        "remaining": current["remaining"]}}
        if method == "POST" and path == "/api/exams":
            body = self._body()
            category = str(body.get("category") or "").upper()
            lang = str(body.get("lang") or "pl")
            qconn = database.connect()
            try:
                questions = exam.draw(qconn, category, lang)
            except ValueError as e:
                raise userdb.Error(str(e))
            finally:
                qconn.close()
            exam_id = userdb.start_exam(conn, user["id"], category, lang,
                                        questions)
            return _exam_json(userdb.get_exam(conn, user["id"], exam_id),
                              False)
        if method == "GET" and path == "/api/exams/current":
            row = userdb.get_exam(conn, user["id"])
            return {"exam": row and _exam_json(row, False)}

        m = re.fullmatch(r"/api/exams/(\d+)(?:/(answer|finish))?", path)
        if not m:
            raise HttpError(404, "Nie ma takiej strony.")
        exam_id, action = int(m.group(1)), m.group(2)
        if method == "POST" and action == "answer":
            body = self._body()
            if not isinstance(body.get("position"), int):
                raise userdb.Error("Brak numeru pytania.")
            finished = userdb.answer(conn, user["id"], exam_id,
                                     body["position"], body.get("answer"))
            return {"finished": finished}
        if method == "POST" and action == "finish":
            if userdb.get_exam(conn, user["id"], exam_id) is None:
                raise HttpError(404, "Nie ma takiego egzaminu.")
            userdb.finish(conn, exam_id)
            return {"finished": True}
        if method == "GET" and not action:
            row = userdb.get_exam(conn, user["id"], exam_id)
            if not row:
                raise HttpError(404, "Nie ma takiego egzaminu.")
            if row["finished_at"] is None:
                raise HttpError(403, "Egzamin jeszcze trwa.")
            return _exam_json(row, True)
        raise HttpError(405, "Niedozwolona metoda.")

    # --- helpers ------------------------------------------------------

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise HttpError(413, "Za duże zapytanie.")
        if "application/json" not in self.headers.get("Content-Type", ""):
            raise HttpError(415, "Oczekiwano JSON.")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            raise HttpError(400, "Nieprawidłowy JSON.")
        if not isinstance(body, dict):
            raise HttpError(400, "Nieprawidłowy JSON.")
        return body

    def _token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        return cookie[COOKIE].value if COOKIE in cookie else None

    def _log_in(self, conn, user):
        self._cookie = userdb.create_session(conn, user["id"])

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if self._cookie is not None:
            max_age = userdb.SESSION_DAYS * 86400 if self._cookie else 0
            self.send_header(
                "Set-Cookie", "%s=%s; Path=/; Max-Age=%d; HttpOnly; "
                "SameSite=Lax" % (COOKIE, self._cookie, max_age))
        self.end_headers()
        self.wfile.write(body)

    def _media(self, name):
        path = os.path.join(config.MEDIA_DIR, os.path.basename(name))
        if os.path.basename(name) != name or not os.path.isfile(path):
            return self.send_error(404)
        size = os.path.getsize(path)
        start, end = 0, size - 1
        m = re.fullmatch(r"bytes=(\d*)-(\d*)",
                         self.headers.get("Range", "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else end
            else:  # the last N bytes
                start = max(size - int(m.group(2)), 0)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range",
                             "bytes %d-%d/%d" % (start, end, size))
        else:
            self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path)[0]
                         or "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            remaining = end - start + 1
            try:
                while remaining > 0:
                    chunk = f.read(min(1 << 16, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser stopped this request, e.g. on seeking


def serve():
    server = ThreadingHTTPServer((config.WEB_HOST, config.WEB_PORT), Handler)
    log.info("Serving on http://%s:%d", config.WEB_HOST, config.WEB_PORT)
    server.serve_forever()
