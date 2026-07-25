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
        "tuition_in", "tuition_out", "cost", "grad_rate"]

START, END = "/*<<<DATA>>>*/", "/*<<<END>>>*/"
PSTART, PEND = "/*<<<PEOPLE>>>*/", "/*<<<ENDPEOPLE>>>*/"

# Community profile fields. `apps` is packed as [school, round, result] triples.
PCOLS = ["gpa", "gpa_weighted", "gpa_from_percent", "sat", "act", "unified",
         "ethnicity", "gender", "residency", "major", "income", "cycle", "ecs", "apps"]


# ---------------------------------------------------------------------
# Linking the two datasets.
#
# The community catalog uses short names ("UC Berkeley"); the Scorecard uses
# official ones ("University of California-Berkeley"). Fuzzy matching is not
# safe here — an earlier attempt mapped "Virginia Tech" onto "University of
# Virginia", which are unrelated institutions. So: exact normalised match, or
# an explicit entry below, or no link at all. Never a guess.
#
# Every entry here was verified to exist in colleges.json.
# ---------------------------------------------------------------------
SCHOOL_ALIAS = {
    "UC Berkeley": "University of California-Berkeley",
    "UCLA": "University of California-Los Angeles",
    "UC San Diego": "University of California-San Diego",
    "UC Davis": "University of California-Davis",
    "UC Irvine": "University of California-Irvine",
    "UC Santa Barbara": "University of California-Santa Barbara",
    "UC Santa Cruz": "University of California-Santa Cruz",
    "UC Riverside": "University of California-Riverside",
    "UC Merced": "University of California-Merced",
    "MIT": "Massachusetts Institute of Technology",
    "Caltech": "California Institute of Technology",
    "Georgia Tech": "Georgia Institute of Technology-Main Campus",
    "Virginia Tech": "Virginia Polytechnic Institute and State University",
    "UIUC": "University of Illinois Urbana-Champaign",
    "UT Austin": "The University of Texas at Austin",
    "UNC Chapel Hill": "University of North Carolina at Chapel Hill",
    "UMass Amherst": "University of Massachusetts-Amherst",
    "University of Michigan": "University of Michigan-Ann Arbor",
    "Penn State University": "Pennsylvania State University-Main Campus",
    "Rutgers University": "Rutgers University-New Brunswick",
    "Rutgers Newark": "Rutgers University-Newark",
    "Arizona State University": "Arizona State University Campus Immersion",
    "Texas A&M University": "Texas A&M University-College Station",
    "North Carolina State University": "North Carolina State University at Raleigh",
    "Tulane University": "Tulane University of Louisiana",
    "Columbia University": "Columbia University in the City of New York",
    "Indiana University": "Indiana University-Bloomington",
    "University of Maryland": "University of Maryland-College Park",
    "University of Minnesota": "University of Minnesota-Twin Cities",
    "University of Missouri": "University of Missouri-Columbia",
    "University of Nebraska": "University of Nebraska-Lincoln",
    "University of Oklahoma": "University of Oklahoma-Norman Campus",
    "University of Pittsburgh": "University of Pittsburgh-Pittsburgh Campus",
    "University of South Carolina": "University of South Carolina-Columbia",
    "University of Tennessee": "The University of Tennessee-Knoxville",
    "University of Washington": "University of Washington-Seattle Campus",
    "Cal Poly San Luis Obispo": "California Polytechnic State University-San Luis Obispo",
    "Cal Poly Pomona": "California State Polytechnic University-Pomona",
    "College of William & Mary": "William & Mary",
}
# Deliberately unlinked: non-US institutions (Oxford, Toronto, NUS and so on)
# are absent from a US federal dataset, and "University of Nevada" is ambiguous
# between Reno and Las Vegas.


def _norm(s: str) -> str:
    s = s.lower().replace("&", "and").replace("–", "-").replace("—", "-")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(the|of|at|main campus|campus)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def link_schools(colleges: list[dict], people_rows: list[list], apps_ix: int) -> tuple[dict, int, int]:
    """Map community school names onto Scorecard ids. Returns (name -> id)."""
    by_norm = {}
    for s in colleges:
        by_norm.setdefault(_norm(s["name"]), s["id"])
    names = {a[0] for r in people_rows for a in r[apps_ix]}
    out, unlinked = {}, []
    for n in sorted(names):
        target = SCHOOL_ALIAS.get(n, n)
        sid = by_norm.get(_norm(target))
        if sid is not None:
            out[n] = sid
        else:
            unlinked.append(n)
    return out, len(out), len(unlinked)


def norm_income(raw) -> str | None:
    """Free-text income into a coarse bracket.

    Posters write anything from "$400k+" to a paragraph about their guardians'
    finances. Publishing that verbatim is both unreadable and more personal
    detail than anyone needs. Anything that can't be bucketed confidently is
    dropped rather than shown raw.
    """
    if not raw:
        return None
    low = str(raw).lower().strip()
    if re.search(r"full[\s-]?pay|no (?:financial )?aid|didn'?t apply for aid", low):
        return "Full pay"
    if re.search(r"\bpell\b|free (?:or reduced )?lunch|low[\s-]?income|fafsa", low):
        return "Under $50k"

    m = re.search(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d{1,7})\s*(k\b)?", low)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    if m.group(2) or v < 1000:          # "70k", or a bare "70" meaning thousands
        v *= 1000
    if v < 1000 or v > 5_000_000:
        return None
    if v < 50_000:
        return "Under $50k"
    if v < 100_000:
        return "$50–100k"
    if v < 200_000:
        return "$100–200k"
    return "$200k+"


def pack_people(path: str) -> dict:
    """Pack r/collegeresults profiles. Kept entirely separate from the official
    data — the site never mixes the two or derives rates from these."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    profiles = raw["profiles"] if isinstance(raw, dict) else raw

    rows, skipped = [], 0
    for p in profiles:
        apps = [[a.get("school"), a.get("round", "RD"), a.get("result")]
                for a in (p.get("apps") or [])
                if a.get("school") and a.get("result") in ("accepted", "waitlisted", "rejected")]
        if not apps:
            skipped += 1
            continue
        row = []
        for c in PCOLS:
            if c == "apps":
                row.append(apps)
            elif c == "ecs":
                row.append([str(e)[:120] for e in (p.get("ecs") or [])][:5])
            elif c == "income":
                row.append(norm_income(p.get("income")))
            else:
                v = p.get(c)
                row.append(round(v, 3) if isinstance(v, float) else v)
        rows.append(row)

    meta = {}
    if isinstance(raw, dict):
        for k in ("source", "generated_utc", "note"):
            if raw.get(k):
                meta[k] = raw[k]
    return {"cols": PCOLS, "meta": meta, "rows": rows, "skipped": skipped}


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
    ap.add_argument("--people", default="profiles.json",
                    help="community profiles; skipped if absent")
    ap.add_argument("--no-people", action="store_true",
                    help="build without the Real applicants section")
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

    def inject(src: str, s: str, e: str, obj) -> str:
        blob = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) if obj is not None else "null"
        # </script> inside a string literal would end the script block early
        blob = blob.replace("</", "<\\/")
        return re.sub(re.escape(s) + r".*?" + re.escape(e),
                      lambda _m: s + blob + e, src, count=1, flags=re.S)

    out = inject(html, START, END, packed)

    people = None
    if not a.no_people and os.path.exists(a.people):
        people = pack_people(a.people)
        links, nlinked, nunlinked = link_schools(
            [dict(zip(COLS, r)) for r in packed["rows"]], people["rows"], PCOLS.index("apps"))
        people["links"] = links
        people["linked"], people["unlinked"] = nlinked, nunlinked
    if PSTART in out and PEND in out:
        out = inject(out, PSTART, PEND, people)

    with open(a.out, "w", encoding="utf-8") as f:
        f.write(out)

    size = os.path.getsize(a.out)
    print(f"  schools embedded   {len(packed['rows']):,}")
    print(f"  data released      {packed['meta'].get('data_updated', 'unknown')}")
    if people:
        napps = sum(len(r[PCOLS.index('apps')]) for r in people["rows"])
        print(f"  applicant profiles {len(people['rows']):,}  ({napps:,} applications)")
        if people["skipped"]:
            print(f"    skipped          {people['skipped']:,} with no usable outcomes")
        print(f"    linked to a college page: {people['linked']} school names "
              f"({people['unlinked']} unlinked — non-US or ambiguous)")
    else:
        print(f"  applicant profiles none — 'Real applicants' section hidden")
    print(f"  {a.out}   {size/1e6:.2f} MB")
    print()
    print(f"  {a.out} is now standalone. Double-click it, email it, or drop it on")
    print(f"  any static host. It needs nothing else to run.")


if __name__ == "__main__":
    main()
