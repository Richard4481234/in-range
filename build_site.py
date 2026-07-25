#!/usr/bin/env python3
"""
build_site.py — bake colleges.json into the web page.

Produces a single self-contained HTML file: no data file beside it, no
server, no drag-and-drop step. Double-click it, or drop it on any static
host, and it works.

    python get_college_data.py     # produces colleges.json
    python build_site.py           # produces InRange.html

The data is stored as a column list plus one array per school rather than
as repeated JSON objects, which roughly halves the size.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

COLS = ["id", "name", "city", "state", "control", "admit_rate",
        "sat25", "sat75", "act25", "act75", "size",
        "tuition_in", "tuition_out", "grad_rate"]

START, END = "/*<<<DATA>>>*/", "/*<<<END>>>*/"


def pack(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    schools = raw["schools"] if isinstance(raw, dict) else raw
    if not schools:
        raise SystemExit(f"{path} contains no schools")

    rows = []
    for s in schools:
        row = []
        for c in COLS:
            v = s.get(c)
            if isinstance(v, float):
                v = round(v, 4)
            row.append(v)
        rows.append(row)

    meta = {}
    if isinstance(raw, dict):
        for k in ("source", "source_url", "data_updated", "generated_utc", "note"):
            if raw.get(k):
                meta[k] = raw[k]

    # Older extracts couldn't read the release date off the page and stored a
    # placeholder. The date is in the download filename, so recover it here.
    if str(meta.get("data_updated", "")).startswith("see "):
        m = re.search(r"_(\d{2})(\d{2})(\d{4})\.zip", meta.get("source_url", ""))
        if m:
            from datetime import datetime
            mm, dd, yyyy = (int(x) for x in m.groups())
            try:
                meta["data_updated"] = datetime(yyyy, mm, dd).strftime("%B %d, %Y").replace(" 0", " ")
            except ValueError:
                meta.pop("data_updated", None)
        else:
            meta.pop("data_updated", None)

    return {"cols": COLS, "meta": meta, "rows": rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="colleges.json")
    ap.add_argument("--template", default="in-range.html")
    ap.add_argument("--out", default="InRange.html")
    a = ap.parse_args()

    for p in (a.data, a.template):
        if not os.path.exists(p):
            print(f"Missing {p}. Run get_college_data.py first, and keep all the "
                  f"files in one folder.", file=sys.stderr)
            sys.exit(1)

    packed = pack(a.data)
    html = open(a.template, encoding="utf-8").read()

    if START not in html or END not in html:
        print(f"Could not find the data placeholder in {a.template}. "
              f"Use the original template file.", file=sys.stderr)
        sys.exit(1)

    blob = json.dumps(packed, ensure_ascii=False, separators=(",", ":"))
    # </script> inside a string literal would end the script block early
    blob = blob.replace("</", "<\\/")

    out = re.sub(re.escape(START) + r".*?" + re.escape(END),
                 lambda _m: START + blob + END, html, count=1, flags=re.S)

    with open(a.out, "w", encoding="utf-8") as f:
        f.write(out)

    n = len(packed["rows"])
    size = os.path.getsize(a.out)
    print(f"  schools embedded   {n:,}")
    print(f"  data released      {packed['meta'].get('data_updated', 'unknown')}")
    print(f"  {a.out}   {size/1e6:.2f} MB")
    print()
    print(f"  {a.out} is now standalone. Double-click it, email it, or drop it on")
    print(f"  any static host. It needs nothing else to run.")


if __name__ == "__main__":
    main()
