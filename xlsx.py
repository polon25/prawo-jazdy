"""Reads a sheet of an .xlsx workbook into rows of strings, using only the
standard library (an xlsx file is a zip of XML files)."""

import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _column(ref):
    """'C12' -> 2"""
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _text(element):
    return "".join(t.text or "" for t in element.iter(_NS + "t"))


def _sheet_path(z, sheet_name):
    workbook = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target")
               for r in rels.iter(_PKG_REL_NS + "Relationship")}
    for sheet in workbook.iter(_NS + "sheet"):
        if sheet.get("name") == sheet_name:
            target = targets[sheet.get(_REL_NS + "id")]
            if target.startswith("/"):
                return target.lstrip("/")
            return posixpath.normpath(posixpath.join("xl", target))
    raise KeyError("no sheet named %r" % sheet_name)


def read_rows(path, sheet_name):
    """Returns the sheet's rows as lists of strings ("" for empty cells)."""
    with zipfile.ZipFile(path) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            strings = [_text(si) for si in root.findall(_NS + "si")]
        sheet = ET.fromstring(z.read(_sheet_path(z, sheet_name)))

    rows = []
    for row in sheet.iter(_NS + "row"):
        cells = {}
        for c in row.findall(_NS + "c"):
            kind, value = c.get("t"), c.find(_NS + "v")
            if kind == "s":
                text = strings[int(value.text)]
            elif kind == "inlineStr":
                text = _text(c)
            else:
                text = value.text if value is not None else ""
            cells[_column(c.get("r"))] = text or ""
        width = max(cells) + 1 if cells else 0
        rows.append([cells.get(i, "") for i in range(width)])
    return rows
