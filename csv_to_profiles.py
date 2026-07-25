#!/usr/bin/env python3
"""
csv_to_profiles.py — rebuild profiles.json from profiles.csv.

The harvester writes both files. If the JSON is lost or corrupted, the CSV
carries the same information and this reconstructs the JSON from it, so a
long harvest never has to be repeated.

    python csv_to_profiles.py                      # profiles.csv -> profiles.json
    python csv_to_profiles.py --in x.csv --out y.json

School tiers are not stored in the CSV, so they're looked up from the catalog
in harvest_collegeresults.py, which must sit in the same folder.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import io
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone


def load_catalog(script: str = "harvest_collegeresults.py") -> dict:
    if not os.path.exists(script):
        print(f"Missing {script} — needed for school tiers. Keep the files together.",
              file=sys.stderr)
        sys.exit(1)
    spec = importlib.util.spec_from_file_location("h", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.TIER_OF


APP_RE = re.compile(r"^(.*?)(?:\s*\(([^)]*)\))?$")


def parse_apps(cell: str, result: str, tiers: dict, unknown: Counter) -> list[dict]:
    out = []
    for chunk in (cell or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = APP_RE.match(chunk)
        school = (m.group(1) or "").strip()
        rnd = (m.group(2) or "RD").strip().upper()
        if rnd not in ("ED", "EA", "RD"):
            rnd = "RD"
        if not school:
            continue
        if school not in tiers:
            unknown[school] += 1
            continue
        out.append({"school": school, "tier": tiers[school], "round": rnd, "result": result})
    return out


def num(v, cast=float):
    v = (v or "").strip()
    if not v:
        return None
    try:
        return cast(float(v))
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", default="profiles.csv")
    ap.add_argument("--out", dest="dst", default="profiles.json")
    ap.add_argument("--script", default="harvest_collegeresults.py")
    a = ap.parse_args()

    if not os.path.exists(a.src):
        print(f"Missing {a.src}", file=sys.stderr)
        sys.exit(1)

    tiers = load_catalog(a.script)
    unknown: Counter = Counter()
    profiles, skipped = [], 0

    with io.open(a.src, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            apps = (parse_apps(r.get("accepted"), "accepted", tiers, unknown)
                    + parse_apps(r.get("waitlisted"), "waitlisted", tiers, unknown)
                    + parse_apps(r.get("rejected"), "rejected", tiers, unknown))
            gpa = num(r.get("gpa"))
            if gpa is None or not apps:
                skipped += 1
                continue
            profiles.append({
                "id": r.get("id") or None,
                "cycle": num(r.get("cycle"), int),
                "gpa": round(gpa, 3),
                "sat": num(r.get("sat"), int),
                "act": num(r.get("act"), int),
                "unified": num(r.get("unified"), int),
                "ethnicity": r.get("ethnicity") or None,
                "gender": r.get("gender") or None,
                "residency": r.get("residency") or None,
                "major": r.get("major") or None,
                "income": r.get("income") or None,
                "school_type": r.get("school_type") or None,
                "hook": r.get("hook") or None,
                "ecs": [e.strip() for e in (r.get("ecs") or "").split(";") if e.strip()],
                "apps": apps,
            })

    if not profiles:
        print("Nothing recovered — is this the right CSV?", file=sys.stderr)
        sys.exit(1)

    payload = {
        "source": "r/collegeresults via Arctic Shift",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(profiles),
        "note": ("Self-reported, volunteer sample. Usernames removed. Real admit rates "
                 "are lower than these. Rebuilt from profiles.csv."),
        "profiles": profiles,
    }
    # write to a temp file first, then replace, so a failure part-way through
    # can't leave a half-written file behind
    tmp = a.dst + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, a.dst)

    apps = sum(len(p["apps"]) for p in profiles)
    print(f"  recovered   {len(profiles):,} profiles")
    print(f"               {apps:,} applications")
    if skipped:
        print(f"  skipped     {skipped:,} rows with no GPA or no decisions")
    if unknown:
        print(f"  unmatched   {len(unknown)} school names not in the catalog "
              f"({sum(unknown.values())} lines)")
        for s, n in unknown.most_common(5):
            print(f"                {n:>4}  {s}")
    print(f"  wrote       {a.dst}  ({os.path.getsize(a.dst)/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
