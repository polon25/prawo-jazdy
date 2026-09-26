# Prawo jazdy – theory exam practice

A small web app for practising the Polish driving licence theory exam with
the official questions. It downloads the ministry's question catalog and
media from
[gov.pl](https://www.gov.pl/web/infrastruktura/jak-uzyskac-prawo-jazdy),
prepares them for browsers and serves practice exams run like the real
one, for every licence category and language in the catalog, with user
accounts that keep each user's results.

Only the standard library is needed, plus ffmpeg to convert the media
(`imageio-ffmpeg` brings one along). Runs on Python 3.8+.

## Data

On every start `app.py` checks `data/` and fetches or builds what's missing:

| Step | What | Where |
|---|---|---|
| Download | the question catalog, `KATALOG_dla_kandydatów_na_kierowców_<MMYYYY>.xlsx` (1 MB), and the media archives "Multimedia do pytań" (9.5 GB) and "Multimedia do pytań - cz. 2" (33 MB). Links are found on the ministry page by name; an interrupted download resumes. | `data/downloads/`, described in `sources.json` |
| Media | every picture and video a question uses, converted for browsers: videos from WMV to H.264 MP4, pictures scaled to at most 1280 px wide. About 2,600 files, so the first run takes a while (roughly an hour on a 4-core machine); files already converted are kept. | `data/media/` |
| Database | the questions, rebuilt from the catalog on every start (a few seconds) | `data/questions.db` |

Accounts and results are kept separately, in `data/users.db`.

`python3 app.py --update` also asks gov.pl whether there are newer files
(the catalog is republished under a new name every few months) and
downloads them. The sign language (PJM) videos aren't used.

### The catalog

One question per row of the "katalog" sheet (the hidden "W trakcie
weryfikacji" sheet, questions still being reviewed, is ignored):

- its number, text and answers in Polish, English (`[EN]`), German (`[D]`)
  and Ukrainian (`[UA]`),
- scope: PODSTAWOWY (basic) questions are answered yes/no (`T`/`N`),
  SPECJALISTYCZNY (specialist) ones A, B or C,
- points (1–3), the licence categories it's asked for, and its media file.

Quirks the parser deals with: misspelled scopes ("Specajlistyczny"), a few
questions with the wrong scope for their answer (the answer wins), empty
rows at the end, and translations missing for some questions (about a third
have no Ukrainian; a language is only offered for a question where it's
complete). Two media files the catalog names aren't in the archives; their
questions are kept out of exams.

### Database

`data/questions.db` (SQLite):

| Table | Holds |
|---|---|
| `questions` | `id` (the catalog's question number), `scope` (`basic`/`specialist`), `points`, `correct` (`T`/`N`/`A`/`B`/`C`), `media` and `media_type` (`image`/`video`) of its converted file, `usable` (0 when its media is missing) |
| `question_texts` | `question`, `answer_a`–`answer_c` per `question_id` and `lang` (`pl`, `en`, `de`, `uk`) |
| `question_categories` | `question_id`, `category` (A, A1, A2, AM, B, B1, C, C1, D, D1, PT, T) |
| `meta` | when it was built and from which files |

## Exam rules

As at [WORD Warszawa](https://www.word.waw.pl/egzaminy/egzamin-na-prawo-jazdy/teoria)
(`exam.py`): 32 questions for one category, drawn at random.

| Part | 3 pts | 2 pts | 1 pt | Time per question |
|---|---|---|---|---|
| basic (yes/no) | 10 | 6 | 4 | 20 s to read / watch, 15 s to answer |
| specialist (A/B/C) | 6 | 4 | 2 | 50 s |

74 points in all, 68 to pass, 25 minutes, no going back to a question. Every
category can be taken in every language except PT (tram) in Ukrainian,
which has too few questions translated.

## Running

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env        # optional: port, data directory, ffmpeg
./venv/bin/python app.py    # http://<host>:8073
```

`app.py --prepare` only prepares the data, without serving.

### The page

Log in or create an account (just a username and password), then pick a
language and category and take an exam. The dashboard shows how many exams
you passed and failed, your average score and your recent exams, each of
which can be reviewed question by question.

The exam runs like the real one: a basic question shows its text and
picture for 20 s (START cuts this short), its video then plays once, and
there are 15 s to answer; a specialist question has 50 s. Whatever answer is
selected when time runs out counts; there's no going back, and the whole
exam ends after 25 minutes. Keys: T/N or A/B/C to answer, space for START,
Enter for the next question. An exam left mid-way (e.g. by reloading the
page) can be resumed from the dashboard while its 25 minutes last.

### Accounts and results

In `data/users.db` (SQLite, never rebuilt): users with PBKDF2-SHA256
password hashes, login sessions (a 30-day cookie, stored as its SHA-256)
and every exam with its questions, their correct answers and the answers
given. The server draws and scores exams and takes answers only in order;
an exam in progress is sent to the page without its correct answers.

### API

| Request | Returns |
|---|---|
| `GET /api/meta` | categories, languages, which categories each language can make an exam for, the rules, the catalog's name |
| `POST /api/register`, `POST /api/login` | `{username, password}`: logs in (session cookie) |
| `POST /api/logout` | |
| `GET /api/me` | the user, their statistics, recent exams and exam in progress |
| `POST /api/exams` | `{category, lang}`: starts an exam: 32 questions in order, without the correct answers |
| `GET /api/exams/current` | the exam in progress, if any |
| `POST /api/exams/<id>/answer` | `{position, answer}`: answers the next question (`answer` `null` for none) |
| `POST /api/exams/<id>/finish` | ends the exam as it stands |
| `GET /api/exams/<id>` | a finished exam with the correct and given answers |
| `GET /media/<file>` | a question's picture or video (supports Range requests) |

### Running at boot (systemd)

`systemd/prawo-jazdy.service`; install it from the project directory,
filling in its path and the user to run as:

```bash
sed "s|/opt/prawo-jazdy|$PWD|g; s|^User=prawo-jazdy|User=$USER|" \
  systemd/prawo-jazdy.service | sudo tee /etc/systemd/system/prawo-jazdy.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now prawo-jazdy.service
```

Logs: `journalctl -u prawo-jazdy -f`. The first start downloads and
converts everything before the page comes up.

## Licence of the data

The questions and media are published by the Ministry of Infrastructure;
audiovisual materials on gov.pl are under CC BY-NC-ND 4.0 unless stated
otherwise. They're downloaded by the app, not kept in this repository.
