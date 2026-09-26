"""Draws a practice exam the way the real theory exam is made up (see
https://www.word.waw.pl/egzaminy/egzamin-na-prawo-jazdy/teoria and the
regulation, Dz.U. 2023 poz. 2659): for one licence category, 20 basic
(yes/no) questions and 12 specialist (A/B/C) ones, by points:

    basic       10 x 3 pts, 6 x 2 pts, 4 x 1 pt
    specialist   6 x 3 pts, 4 x 2 pts, 2 x 1 pt

74 points in all, 68 to pass, 25 minutes. The basic questions come first,
each with 20 s to read it (and watch its media) and 15 s to answer; a
specialist question has 50 s for both. There's no going back to a question.
"""

import random

from catalog import LANGUAGE_NAMES

# scope -> {points: how many questions}
COMPOSITION = {"basic": {3: 10, 2: 6, 1: 4},
               "specialist": {3: 6, 2: 4, 1: 2}}
PASS_POINTS = 68
MAX_POINTS = sum(p * n for parts in COMPOSITION.values()
                 for p, n in parts.items())
DURATION_MINUTES = 25
# scope -> seconds to read the question, seconds to answer (None: one
# limit for both)
TIME_LIMITS = {"basic": {"read": 20, "answer": 15},
               "specialist": {"read": None, "answer": 50}}

RULES = {"composition": {s: {str(p): n for p, n in parts.items()}
                         for s, parts in COMPOSITION.items()},
         "pass_points": PASS_POINTS, "max_points": MAX_POINTS,
         "duration_minutes": DURATION_MINUTES, "time_limits": TIME_LIMITS}

_POOL = """
    SELECT q.id, q.scope, q.points, q.correct, q.media, q.media_type,
           t.question, t.answer_a, t.answer_b, t.answer_c
    FROM questions q
    JOIN question_categories c ON c.question_id = q.id AND c.category = ?
    JOIN question_texts t ON t.question_id = q.id AND t.lang = ?
    WHERE q.usable
"""


def _pool_counts(conn):
    """{(lang, category, scope, points): number of usable questions}"""
    rows = conn.execute("""
        SELECT t.lang, c.category, q.scope, q.points, COUNT(*) AS n
        FROM questions q
        JOIN question_categories c ON c.question_id = q.id
        JOIN question_texts t ON t.question_id = q.id
        WHERE q.usable
        GROUP BY t.lang, c.category, q.scope, q.points""")
    return {(r["lang"], r["category"], r["scope"], r["points"]): r["n"]
            for r in rows}


def availability(conn):
    """{lang: [categories with enough questions for a full exam]}"""
    counts = _pool_counts(conn)
    categories = sorted({key[1] for key in counts})
    return {lang: [c for c in categories if all(
                counts.get((lang, c, scope, points), 0) >= n
                for scope, parts in COMPOSITION.items()
                for points, n in parts.items())]
            for lang in LANGUAGE_NAMES}


def draw(conn, category, lang, rng=random):
    """Returns the exam's 32 questions, in the order they're asked.
    Raises ValueError if the category and language don't have enough."""
    pool = conn.execute(_POOL, (category, lang)).fetchall()
    exam = []
    for scope, parts in COMPOSITION.items():
        chosen = []
        for points, n in parts.items():
            candidates = [q for q in pool
                          if q["scope"] == scope and q["points"] == points]
            if len(candidates) < n:
                raise ValueError(
                    "category %s in %s has %d %s questions worth %d points, "
                    "the exam needs %d" % (category, lang, len(candidates),
                                           scope, points, n))
            chosen += rng.sample(candidates, n)
        rng.shuffle(chosen)
        exam += chosen
    return exam
