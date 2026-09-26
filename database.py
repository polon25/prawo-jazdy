"""The question database (SQLite), built from the parsed catalog and the
converted media. It's rebuilt from scratch whenever the app starts, so it
always matches the files it was made from.

    questions            one row per question; usable = 0 when its media
                         is named in the catalog but couldn't be prepared
    question_texts       its text and answers in each language it has
    question_categories  the licence categories it's asked for
    meta                 where the data came from
"""

import json
import os
import sqlite3
import time

import config

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE questions (
    id INTEGER PRIMARY KEY,           -- "Numer pytania" in the catalog
    scope TEXT NOT NULL,              -- basic (yes/no) or specialist (A/B/C)
    points INTEGER NOT NULL,          -- 1, 2 or 3
    correct TEXT NOT NULL,            -- T/N or A/B/C
    source_media TEXT,                -- media file named in the catalog
    media TEXT,                       -- its converted file in data/media
    media_type TEXT,                  -- image or video
    usable INTEGER NOT NULL
);
CREATE TABLE question_texts (
    question_id INTEGER NOT NULL REFERENCES questions(id),
    lang TEXT NOT NULL,
    question TEXT NOT NULL,
    answer_a TEXT, answer_b TEXT, answer_c TEXT,
    PRIMARY KEY (question_id, lang)
);
CREATE TABLE question_categories (
    question_id INTEGER NOT NULL REFERENCES questions(id),
    category TEXT NOT NULL,
    PRIMARY KEY (category, question_id)
);
"""


def build(questions, media_files, source_info):
    """Writes the database from catalog.parse()'s questions and
    media.prepare()'s {catalog name: converted file}."""
    partial = config.DB_FILE + ".tmp"
    if os.path.exists(partial):
        os.remove(partial)
    conn = sqlite3.connect(partial)
    with conn:
        conn.executescript(SCHEMA)
        for q in questions:
            media = media_files.get(q["media"]) if q["media"] else None
            media_type = None
            if media:
                media_type = "video" if media.endswith(".mp4") else "image"
            conn.execute(
                "INSERT INTO questions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (q["id"], q["scope"], q["points"], q["correct"], q["media"],
                 media, media_type, int(not q["media"] or bool(media))))
            conn.executemany(
                "INSERT INTO question_texts VALUES (?, ?, ?, ?, ?, ?)",
                [(q["id"], lang, t["question"], t["a"] or None,
                  t["b"] or None, t["c"] or None)
                 for lang, t in q["texts"].items()])
            conn.executemany("INSERT INTO question_categories VALUES (?, ?)",
                             [(q["id"], c) for c in q["categories"]])
        conn.executemany("INSERT INTO meta VALUES (?, ?)", [
            ("built_at", time.strftime("%Y-%m-%d %H:%M:%S")),
            ("sources", json.dumps(source_info, ensure_ascii=False))])
    conn.close()
    os.replace(partial, config.DB_FILE)


def connect():
    """A read-only connection, with rows as dicts."""
    conn = sqlite3.connect("file:%s?mode=ro" % config.DB_FILE, uri=True)
    conn.row_factory = lambda cursor, row: {
        d[0]: v for d, v in zip(cursor.description, row)}
    return conn
