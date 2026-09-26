"""Parses the ministry's question catalog (KATALOG_..._<MMYYYY>.xlsx).

Its "katalog" sheet has one question per row: its number, text and answers
in Polish, English, German and Ukrainian, the correct answer, the media file
it shows, its scope (PODSTAWOWY: yes/no questions, SPECJALISTYCZNY: A/B/C),
points and the licence categories it's asked for. Columns are found by their
header, so a reordered sheet still reads. Sign language (PJM) columns are
ignored.
"""

import logging

import xlsx

log = logging.getLogger("catalog")

SHEET = "katalog"
# Language code -> suffix of its columns' headers.
LANGUAGES = {"pl": "", "en": " [EN]", "de": " [D]", "uk": " [UA]"}
LANGUAGE_NAMES = {"pl": "polski", "en": "English", "de": "Deutsch",
                  "uk": "українська"}
VIDEO_EXTENSIONS = (".wmv", ".mp4", ".avi", ".mov", ".mpg", ".mpeg")


def _scope(value):
    value = value.strip().upper()
    if value.startswith("POD"):
        return "basic"
    if value.startswith("SPE"):  # also the catalog's "Specajlistyczny"
        return "specialist"
    return None


def parse(path):
    """Returns the catalog's questions as dicts:
    {"id", "scope", "points", "correct", "media", "categories",
     "texts": {lang: {"question", "a", "b", "c"}}}.
    Rows that can't make a question are skipped with a warning; a language
    is left out of "texts" where the question isn't fully translated."""
    rows = xlsx.read_rows(path, SHEET)
    header = {name.strip(): i for i, name in enumerate(rows[0])}

    def column(row, name):
        i = header.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    questions, seen = [], set()
    for row in rows[1:]:
        number = column(row, "Numer pytania")
        if not number:
            continue  # the sheet ends with rows holding only "Lp"
        where = "question %s" % number
        scope = _scope(column(row, "Zakres struktury"))
        points = column(row, "Liczba punktów")
        correct = column(row, "Poprawna odp").upper()
        categories = sorted({c.strip().upper() for c
                             in column(row, "Kategorie").split(",")
                             if c.strip()})
        if not number.isdigit() or int(number) in seen:
            log.warning("%s: bad or repeated number, skipped", where)
            continue
        # A few questions have the wrong scope (yes/no ones marked
        # SPECJALISTYCZNY and vice versa); the answer tells which it is.
        actual = {"T": "basic", "N": "basic"}.get(
            correct, "specialist" if correct in ("A", "B", "C") else None)
        if scope and actual and actual != scope:
            log.info("%s: marked %s but answered %s, taken as %s",
                     where, scope, correct, actual)
            scope = actual
        if scope is None or points not in ("1", "2", "3") \
                or correct not in ("TN" if scope == "basic" else "ABC") \
                or not categories:
            log.warning("%s: bad scope, points, answer or categories "
                        "(%r, %r, %r, %r), skipped", where,
                        column(row, "Zakres struktury"), points, correct,
                        column(row, "Kategorie"))
            continue

        texts = {}
        for lang, suffix in LANGUAGES.items():
            text = {"question": column(row, "Pytanie" + suffix)}
            for letter in "abc":
                text[letter] = column(
                    row, "Odpowiedź %s%s" % (letter.upper(), suffix))
            if text["question"] and (scope == "basic" or all(
                    text[letter] for letter in "abc")):
                texts[lang] = text
        if "pl" not in texts:
            log.warning("%s: no Polish text, skipped", where)
            continue

        seen.add(int(number))
        questions.append({
            "id": int(number), "scope": scope, "points": int(points),
            "correct": correct, "media": column(row, "Media") or None,
            "categories": categories, "texts": texts})
    return questions
