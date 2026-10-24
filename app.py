"""Driving licence theory exam practice: the app's entry point.

On start it makes sure the ministry's exam files are downloaded (the
question catalog and both media archives, see sources.py), converts the
media the questions use for browsers (media.py, slow only the first time),
builds the question database (database.py) and serves the web page
(web_server.py; accounts and results are in userdb.py).

    python3 app.py             prepare what's missing, then serve
    python3 app.py --prepare   only prepare, don't serve
    python3 app.py --update    also check gov.pl for newer files first
    python3 app.py --set-password USER   set a user's password (asked for,
                                         or read from stdin)
"""

import argparse
import logging
import os
import sys

import config
import catalog
import database
import media
import sources

log = logging.getLogger("app")


def prepare(update=False):
    manifest = sources.ensure_downloaded(update)
    questions = catalog.parse(sources.local_path(manifest["catalog"]))
    log.info("Catalog %s: %d questions", manifest["catalog"]["file"],
             len(questions))
    archives = [sources.local_path(manifest[key])
                for key in ("media1", "media2")]
    media_files = media.prepare(archives,
                                [q["media"] for q in questions if q["media"]])
    database.build(questions, media_files, manifest)
    conn = database.connect()
    unusable = conn.execute("SELECT COUNT(*) AS n FROM questions "
                            "WHERE NOT usable").fetchone()["n"]
    conn.close()
    log.info("Database ready: %d questions, %d of them without their media",
             len(questions), unusable)


def set_password(username):
    import getpass
    import userdb
    if sys.stdin.isatty():
        password = getpass.getpass("Nowe hasło dla %s: " % username)
        if getpass.getpass("Powtórz hasło: ") != password:
            sys.exit("Hasła się różnią.")
    else:
        password = sys.stdin.readline().rstrip("\n")
    userdb.init()
    conn = userdb.connect()
    try:
        stored = userdb.set_password(conn, username, password)
    except userdb.Error as e:
        sys.exit(str(e))
    finally:
        conn.close()
    if not stored:
        sys.exit("Nie ma użytkownika %s." % username)
    print("Hasło użytkownika %s zmienione; jego logowania zostały "
          "zakończone." % stored)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--prepare", action="store_true",
                        help="only prepare the data, don't serve")
    parser.add_argument("--update", action="store_true",
                        help="check gov.pl for newer files first")
    parser.add_argument("--set-password", metavar="USER",
                        help="set a user's password and exit")
    args = parser.parse_args()
    if args.set_password:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        return set_password(args.set_password)
    logging.basicConfig(
        level=logging.INFO, stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.makedirs(config.DATA_DIR, exist_ok=True)
    prepare(args.update)
    if not args.prepare:
        import userdb
        import web_server
        userdb.init()
        web_server.serve()


if __name__ == "__main__":
    main()
