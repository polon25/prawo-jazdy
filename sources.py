"""Downloads the exam files published on gov.pl: the question catalog (xlsx)
and the two media archives. Links are looked up on the ministry page by
their names, falling back to the ones known to work, and each downloaded
file is described in downloads/sources.json so later runs know it's there.
"""

import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import config

log = logging.getLogger("sources")

USER_AGENT = "Mozilla/5.0 (prawo-jazdy exam practice app)"
MANIFEST = os.path.join(config.DOWNLOAD_DIR, "sources.json")

# key -> (local file name, None to keep the server's; fallback URL)
SOURCES = {
    "catalog": (None, "https://www.gov.pl/attachment/"
                      "a5c6c329-28a5-4274-a1a8-e2813f0a51bd"),
    "media1": ("multimedia_1.zip",
               "https://www.gov.pl/pliki/mi/multimedia_do_pytan.zip"),
    "media2": ("multimedia_2.zip", "https://www.gov.pl/attachment/"
                                   "10d143bf-9e93-4d82-935d-48c89353d3ce"),
}


class _LinkParser(HTMLParser):
    """Collects every link on a page as (href, text)."""

    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._text).replace("​", "").split())
            self.links.append((self._href, text))
            self._href = None


def find_links():
    """Returns {key: URL} for the sources found on the ministry page."""
    page = _open(config.SOURCE_PAGE).read().decode("utf-8", "replace")
    parser = _LinkParser()
    parser.feed(page)
    found = {}
    for href, text in parser.links:
        url = urllib.parse.urljoin(config.SOURCE_PAGE, href)
        low = text.lower()
        if "katalog" in low and "xlsx" in low:
            found.setdefault("catalog", url)
        elif re.fullmatch(r"multimedia do pytań", low):
            found.setdefault("media1", url)
        elif re.fullmatch(r"multimedia do pytań\s*-\s*cz\.?\s*2", low):
            found.setdefault("media2", url)
    return found


def _open(url, headers=None, method=None):
    request = urllib.request.Request(
        url, method=method, headers=dict({"User-Agent": USER_AGENT},
                                         **(headers or {})))
    return urllib.request.urlopen(request, timeout=60)


def _remote_info(url):
    """Returns the file's size, last-modified date and name on the server."""
    with _open(url, method="HEAD") as r:
        name = None
        disposition = r.headers.get("Content-Disposition", "")
        m = re.search(r"filename\*=UTF-8''([^;]+)", disposition)
        if m:
            name = urllib.parse.unquote(m.group(1))
        else:
            m = re.search(r'filename="?([^";]+)', disposition)
            name = m.group(1) if m else None
        if not name:
            name = os.path.basename(urllib.parse.urlparse(r.url).path)
        return {"size": int(r.headers.get("Content-Length") or 0),
                "last_modified": r.headers.get("Last-Modified"),
                "name": os.path.basename(name)}


def _download(url, path, size):
    """Downloads url to path through path.part, resuming a partial one."""
    part = path + ".part"
    done = os.path.getsize(part) if os.path.exists(part) else 0
    if size and done > size:
        done = 0
    headers = {"Range": "bytes=%d-" % done} if done else {}
    with _open(url, headers) as r:
        if done and r.status != 206:
            done = 0  # the server ignored the range; start over
        log.info("Downloading %s (%.1f MB)%s", os.path.basename(path),
                 size / 1e6, ", resuming at %.1f MB" % (done / 1e6)
                 if done else "")
        started = last_report = time.time()
        with open(part, "ab" if done else "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if time.time() - last_report > 15:
                    last_report = time.time()
                    speed = done / max(time.time() - started, 1)
                    log.info("  %s: %.0f%% (%.1f MB/s)",
                             os.path.basename(path),
                             100 * done / size if size else 0, speed / 1e6)
    if size and os.path.getsize(part) != size:
        raise IOError("%s: got %d bytes, expected %d"
                      % (path, os.path.getsize(part), size))
    os.replace(part, path)


def _load_manifest():
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_manifest(manifest):
    with open(MANIFEST + ".tmp", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(MANIFEST + ".tmp", MANIFEST)


def local_path(entry):
    return os.path.join(config.DOWNLOAD_DIR, entry["file"])


def ensure_downloaded(update=False):
    """Makes sure every source file is downloaded and returns the manifest,
    {key: {"url", "file", "size", "last_modified"}}. With update, also asks
    gov.pl whether there are newer files and downloads those."""
    os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
    manifest = _load_manifest()
    missing = [key for key in SOURCES if key not in manifest
               or not os.path.exists(local_path(manifest[key]))]
    if not missing and not update:
        return manifest

    try:
        links = find_links()
    except OSError as e:
        log.warning("Can't read %s (%s), using the known links",
                    config.SOURCE_PAGE, e)
        links = {}
    for key, (file_name, fallback) in SOURCES.items():
        if key not in missing and not update:
            continue
        url = links.get(key)
        if not url:
            log.warning("No link for %s on %s, using %s",
                        key, config.SOURCE_PAGE, fallback)
            url = fallback
        info = _remote_info(url)
        entry = {"url": url, "file": file_name or info["name"],
                 "size": info["size"], "last_modified": info["last_modified"]}
        old = manifest.get(key)
        if key not in missing and old and all(
                old.get(k) == entry[k] for k in ("file", "size",
                                                 "last_modified")):
            continue
        _download(url, local_path(entry), entry["size"])
        if old and old["file"] != entry["file"] \
                and os.path.exists(local_path(old)):
            os.remove(local_path(old))  # e.g. last month's catalog
        manifest[key] = entry
        _save_manifest(manifest)
        log.info("Downloaded %s", entry["file"])
    return manifest
