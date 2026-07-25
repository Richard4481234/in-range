#!/usr/bin/env python3
"""
get_college_data.py — download official U.S. college admissions data.

Source: the U.S. Department of Education's College Scorecard, which publishes
admission rates and admitted-student test score ranges for every accredited
college in the country. Schools report these figures themselves through IPEDS.

    https://collegescorecard.ed.gov/data/

This is a census, not a survey. There is no volunteer bias, no sampling, and
nothing to parse out of prose. It is the authoritative source for "what is the
admit rate at X" and "what scores did X's admitted students actually have."

Usage
-----
    python get_college_data.py                # download and build colleges.json
    python get_college_data.py --keep-zip     # leave the raw download in place
    python get_college_data.py --zip FILE     # use an already-downloaded zip
    python get_college_data.py --self-test    # exercise the parser, no network

Outputs
-------
    colleges.json      the file the web app loads
    colleges.csv       same data, opens in Excel
    college_report.txt what was found, what was missing, and the data vintage

Only stdlib. No pip install.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

DATA_PAGE = "https://collegescorecard.ed.gov/data/"
# Used only if the data page can't be read. The date in the filename changes
# with each release, which is exactly why we try to discover it first.
FALLBACK_ZIP = ("https://ed-public-download.scorecard.network/downloads/"
                "Most-Recent-Cohorts-Institution_03232026.zip")
USER_AGENT = "college-range-tool/1.0 (personal use)"

# Scorecard column -> what we call it. These names have been stable for years.
COLUMNS = {
    "UNITID":         "id",
    "INSTNM":         "name",
    "CITY":           "city",
    "STABBR":         "state",
    "CONTROL":        "control",         # 1 public, 2 private nonprofit, 3 private for-profit
    "ADM_RATE":       "admit_rate",
    "SATVR25":        "sat_read_25",
    "SATVR75":        "sat_read_75",
    "SATMT25":        "sat_math_25",
    "SATMT75":        "sat_math_75",
    "SAT_AVG":        "sat_avg",
    "ACTCM25":        "act_25",
    "ACTCM75":        "act_75",
    "ACTCMMID":       "act_mid",
    "UGDS":           "size",
    "TUITIONFEE_IN":  "tuition_in",
    "TUITIONFEE_OUT": "tuition_out",
    "COSTT4_A":       "cost_total",
    "C150_4":         "grad_rate",
    "PREDDEG":        "pred_degree",     # 3 = predominantly bachelor's
    "HIGHDEG":        "high_degree",     # 3 = bachelor's, 4 = graduate
    "CURROPER":       "operating",
    "ICLEVEL":        "level",           # 1 = 4-year
    "REGION":         "region",
}
NUMERIC = {
    "id", "admit_rate", "sat_read_25", "sat_read_75", "sat_math_25", "sat_math_75",
    "sat_avg", "act_25", "act_75", "act_mid", "size", "tuition_in",
    "tuition_out", "cost_total", "grad_rate", "control", "pred_degree",
    "high_degree", "operating", "level", "region",
}
CONTROL_LABEL = {1: "Public", 2: "Private nonprofit", 3: "Private for-profit"}
REGION_LABEL = {
    0: "U.S. Service Schools", 1: "New England", 2: "Mid East", 3: "Great Lakes",
    4: "Plains", 5: "Southeast", 6: "Southwest", 7: "Rocky Mountains",
    8: "Far West", 9: "Outlying Areas",
}


# ======================================================================
# download
# ======================================================================
def vintage_from_url(url: str) -> str | None:
    """The release date is in the filename (…_06102026.zip = 10 June 2026),
    which is a more reliable source than scraping it off the page."""
    m = re.search(r"_(\d{2})(\d{2})(\d{4})\.zip", url)
    if not m:
        return None
    try:
        mm, dd, yyyy = (int(x) for x in m.groups())
        return datetime(yyyy, mm, dd).strftime("%B %-d, %Y")
    except (ValueError, TypeError):
        try:
            return datetime(yyyy, mm, dd).strftime("%B %d, %Y").replace(" 0", " ")
        except Exception:                                              # noqa: BLE001
            return None


def discover_zip_url() -> tuple[str, str | None]:
    """Find the current 'Most Recent Institution-Level Data' link."""
    try:
        req = urllib.request.Request(DATA_PAGE, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode("utf-8", "replace")
        m = re.search(r'https://[^"\'\s]*Most-Recent-Cohorts-Institution[^"\'\s]*\.zip', html)
        upd = re.search(r"last updated[^A-Z]{0,40}([A-Z][a-z]+ \d{1,2},? \d{4})", html)
        if m:
            return m.group(0), (upd.group(1) if upd else vintage_from_url(m.group(0)))
        print("  ! could not find the link on the data page; using the built-in URL")
    except Exception as e:                                            # noqa: BLE001
        print(f"  ! could not read the data page ({type(e).__name__}); using the built-in URL")
    return FALLBACK_ZIP, None


def download(url: str, dest: str) -> str:
    print(f"  downloading {url.rsplit('/', 1)[-1]}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = 100 * done / total
                print(f"\r  {done/1e6:6.1f} MB of {total/1e6:.1f} MB  ({pct:4.1f}%)", end="")
            else:
                print(f"\r  {done/1e6:6.1f} MB", end="")
    print()
    return dest


# ======================================================================
# parse
# ======================================================================
def num(v):
    if v is None:
        return None
    v = v.strip()
    if v in ("", "NULL", "PrivacySuppressed", "PS"):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return int(f) if f == int(f) else f


def rows_from_csv(fh) -> tuple[list[dict], set[str], int]:
    reader = csv.DictReader(fh)
    have = set(reader.fieldnames or [])
    missing = set(COLUMNS) - have
    out, seen_total = [], 0
    for raw in reader:
        seen_total += 1
        rec = {}
        for src, dst in COLUMNS.items():
            val = raw.get(src)
            rec[dst] = num(val) if dst in NUMERIC else (val.strip() if val else None)
        out.append(rec)
    return out, missing, seen_total


def build(rows: list[dict]) -> tuple[list[dict], dict]:
    """Keep four-year, currently-operating undergraduate institutions."""
    stats = {"total": len(rows), "four_year": 0, "with_admit": 0,
             "with_sat": 0, "with_act": 0, "kept": 0}
    out = []
    for r in rows:
        if not r.get("name"):
            continue
        if r.get("operating") == 0:
            continue
        four_year = (r.get("level") == 1) or (r.get("pred_degree") == 3) or (r.get("high_degree") or 0) >= 3
        if not four_year:
            continue
        stats["four_year"] += 1

        adm = r.get("admit_rate")
        if adm is not None and not (0 < adm <= 1):
            adm = None
        if adm is not None:
            stats["with_admit"] += 1

        # Composite SAT range from the section percentiles when present,
        # otherwise fall back to the reported average.
        s25 = s75 = None
        if r.get("sat_read_25") and r.get("sat_math_25"):
            s25 = int(r["sat_read_25"] + r["sat_math_25"])
        if r.get("sat_read_75") and r.get("sat_math_75"):
            s75 = int(r["sat_read_75"] + r["sat_math_75"])
        if s25 and s75 and s25 > s75:
            s25, s75 = s75, s25
        if s25 or s75 or r.get("sat_avg"):
            stats["with_sat"] += 1
        a25, a75 = r.get("act_25"), r.get("act_75")
        if a25 or a75 or r.get("act_mid"):
            stats["with_act"] += 1

        # nothing useful to say about a school with no admissions data at all
        if adm is None and not (s25 or s75 or a25 or a75):
            continue

        out.append({
            "id": r["id"],
            "name": r["name"],
            "city": r.get("city"),
            "state": r.get("state"),
            "control": CONTROL_LABEL.get(r.get("control")),
            "region": REGION_LABEL.get(r.get("region")),
            "admit_rate": round(adm, 4) if adm is not None else None,
            "sat25": s25, "sat75": s75,
            "sat_avg": int(r["sat_avg"]) if r.get("sat_avg") else None,
            "act25": int(a25) if a25 else None,
            "act75": int(a75) if a75 else None,
            "act_mid": int(r["act_mid"]) if r.get("act_mid") else None,
            "size": int(r["size"]) if r.get("size") else None,
            "tuition_in": int(r["tuition_in"]) if r.get("tuition_in") else None,
            "tuition_out": int(r["tuition_out"]) if r.get("tuition_out") else None,
            "cost": int(r["cost_total"]) if r.get("cost_total") else None,
            "grad_rate": round(r["grad_rate"], 3) if r.get("grad_rate") else None,
        })
    stats["kept"] = len(out)
    out.sort(key=lambda x: (x["admit_rate"] if x["admit_rate"] is not None else 2, x["name"]))
    return out, stats


# ======================================================================
# output
# ======================================================================
def write_outputs(schools: list[dict], stats: dict, missing: set[str],
                  source_url: str, vintage: str | None) -> None:
    meta = {
        "source": "U.S. Department of Education, College Scorecard",
        "source_url": source_url,
        "data_updated": vintage or "see collegescorecard.ed.gov/data",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(schools),
        "note": ("Admission rates and score ranges are reported by the institutions "
                 "themselves via IPEDS and typically describe an admissions cycle one "
                 "to two years old. A score range describes admitted students; it is "
                 "not a cutoff and not a probability."),
    }
    with open("colleges.json", "w", encoding="utf-8") as f:
        json.dump({**meta, "schools": schools}, f, ensure_ascii=False, separators=(",", ":"))

    cols = ["id", "name", "city", "state", "control", "admit_rate", "sat25", "sat75",
            "sat_avg", "act25", "act75", "size", "tuition_in", "tuition_out", "cost", "grad_rate"]
    with open("colleges.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for s in schools:
            w.writerow([s.get(c, "") if s.get(c) is not None else "" for c in cols])

    def pc(n):
        return f"{n} ({100*n/max(stats['four_year'],1):.0f}% of four-year schools)"

    lines = [
        "College Scorecard extract",
        f"generated {meta['generated_utc']}",
        f"data last updated by ED: {meta['data_updated']}",
        f"source: {source_url}",
        "",
        f"rows in file            {stats['total']}",
        f"four-year institutions  {stats['four_year']}",
        f"  with an admit rate    {pc(stats['with_admit'])}",
        f"  with SAT data         {pc(stats['with_sat'])}",
        f"  with ACT data         {pc(stats['with_act'])}",
        "",
        f"schools written         {stats['kept']}",
        "",
        "Schools are kept when they are four-year, currently operating, and report",
        "either an admission rate or a test score range. Open-admission schools and",
        "test-blind schools legitimately have blanks; the app shows those as",
        "'not reported' rather than guessing.",
    ]
    if missing:
        lines += ["", "WARNING - expected columns not present in the file:",
                  "  " + ", ".join(sorted(missing)),
                  "  The file layout may have changed. Send this report to Claude."]
    open("college_report.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\nwrote colleges.json, colleges.csv, college_report.txt")


# ======================================================================
# self test
# ======================================================================
SAMPLE = """UNITID,INSTNM,CITY,STABBR,CONTROL,ADM_RATE,SATVR25,SATVR75,SATMT25,SATMT75,SAT_AVG,ACTCM25,ACTCM75,ACTCMMID,UGDS,TUITIONFEE_IN,TUITIONFEE_OUT,COSTT4_A,C150_4,PREDDEG,HIGHDEG,CURROPER,ICLEVEL,REGION
1,Selective Tech,Cambridge,MA,2,0.0396,740,780,780,800,1557,35,36,35,4600,60000,60000,82000,0.948,3,4,1,1,1
2,Big State U,Ann Arbor,MI,1,0.1766,690,760,700,790,1460,32,35,34,33000,17000,57000,35000,0.933,3,4,1,1,3
3,Open Door College,Phoenix,AZ,1,,,,,,,,,,12000,4000,9000,15000,0.28,2,3,1,1,6
4,Closed School,Nowhere,TX,3,0.55,500,600,500,600,1100,18,24,21,300,9000,9000,20000,0.2,3,3,0,1,6
5,Community College,Anytown,OH,1,,,,,,,,,,8000,3000,6000,12000,0.31,1,2,1,2,3
6,Test Blind LAC,Portland,OR,2,0.7712,,,,,,,,,2200,58000,58000,74000,0.79,3,3,1,1,8
7,Backwards Range U,Reno,NV,1,0.85,700,650,690,640,1340,,,,9000,8000,24000,21000,0.55,3,4,1,1,7
"""


def self_test() -> int:
    rows, missing, total = rows_from_csv(io.StringIO(SAMPLE))
    schools, stats = build(rows)
    print(f"parsed {total} rows, missing columns: {sorted(missing) or 'none'}")
    print(f"stats: {stats}\n")
    for s in schools:
        rng = f"SAT {s['sat25']}-{s['sat75']}" if s["sat25"] and s["sat75"] else "SAT n/a"
        act = f"ACT {s['act25']}-{s['act75']}" if s["act25"] and s["act75"] else "ACT n/a"
        adm = f"{100*s['admit_rate']:.1f}%" if s["admit_rate"] is not None else "n/a"
        print(f"  {s['name']:<20} admit {adm:>6}  {rng:<16} {act:<12} {s['control']}")

    names = {s["name"] for s in schools}
    problems = []
    if "Closed School" in names:
        problems.append("closed school was not filtered out")
    if "Community College" in names:
        problems.append("two-year school was not filtered out")
    if "Open Door College" in names:
        problems.append("school with no admissions data at all was kept")
    if "Test Blind LAC" not in names:
        problems.append("test-blind school with an admit rate should be kept")
    bw = next((s for s in schools if s["name"] == "Backwards Range U"), None)
    if bw and bw["sat25"] > bw["sat75"]:
        problems.append("reversed SAT percentiles were not corrected")
    st = next((s for s in schools if s["name"] == "Selective Tech"), None)
    if not st or st["sat25"] != 1520 or st["sat75"] != 1580:
        problems.append(f"composite SAT wrong: {st and (st['sat25'], st['sat75'])}")
    if schools and schools[0]["name"] != "Selective Tech":
        problems.append("not sorted by selectivity")

    print("\n" + ("FAILURES:\n  " + "\n  ".join(problems) if problems else "all checks passed"))
    return 1 if problems else 0


# ======================================================================
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zip", help="use an already-downloaded zip instead of fetching")
    ap.add_argument("--keep-zip", action="store_true", help="don't delete the download when done")
    ap.add_argument("--self-test", action="store_true", help="test the parser offline")
    a = ap.parse_args()

    if a.self_test:
        sys.exit(self_test())

    tmp = "Most-Recent-Cohorts-Institution.zip"
    vintage, url = None, a.zip or ""
    if a.zip:
        path = a.zip
        print(f"Using {path}")
    else:
        print("Locating the current data file ...")
        url, vintage = discover_zip_url()
        if vintage:
            print(f"  College Scorecard data last updated {vintage}")
        print("  this is about 23 MB, one time only")
        path = download(url, tmp)

    print("\nReading ...")
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not names:
            print("No CSV inside the zip. Send college_report.txt to Claude.", file=sys.stderr)
            sys.exit(1)
        inner = max(names, key=lambda n: z.getinfo(n).file_size)
        print(f"  {inner}")
        with z.open(inner) as fh:
            rows, missing, total = rows_from_csv(io.TextIOWrapper(fh, encoding="utf-8-sig", errors="replace"))

    print(f"  {total} institutions in file\n")
    schools, stats = build(rows)
    if not schools:
        print("Nothing usable was extracted. Send college_report.txt to Claude.", file=sys.stderr)
        sys.exit(1)
    write_outputs(schools, stats, missing, url or a.zip, vintage)

    if not a.zip and not a.keep_zip:
        try:
            os.remove(tmp)
            print("(removed the temporary download)")
        except OSError:
            pass


if __name__ == "__main__":
    main()
