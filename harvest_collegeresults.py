#!/usr/bin/env python3
"""
harvest_collegeresults.py — build a real dataset for ApplicantTwin.

Pulls r/collegeresults posts from the Arctic Shift archive (the maintained
Pushshift successor), parses them into the schema applicant-twin.html expects,
and writes profiles.json.

    https://github.com/ArthurHeitmann/arctic_shift

Usage
-----
    python harvest_collegeresults.py                     # last two cycles
    python harvest_collegeresults.py --after 2025-01-01
    python harvest_collegeresults.py --limit-posts 200   # small trial run
    python harvest_collegeresults.py --self-test         # parser tests, no network

Outputs
-------
    profiles.json          the dataset the app loads
    profiles.csv           same data, flat
    harvest_report.txt     extraction rates + why posts were dropped
    unmatched_schools.txt  school strings that failed to resolve, by frequency
    raw_posts.jsonl        (--keep-raw) posts as fetched, for re-parsing offline

Privacy
-------
Usernames and author IDs are never written to any output file. The Reddit post
ID is kept so a suspicious row can be checked against its source. Arctic Shift
honours removal requests; if you redistribute anything built from this, honour
them too: https://github.com/ArthurHeitmann/arctic_shift#contact--removal-requests

Only stdlib. No pip install.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

API = "https://arctic-shift.photon-reddit.com/api/posts/search"
USER_AGENT = "applicant-twin-harvester/1.0 (personal research; contact via github)"
PAGE_SIZE = 100
SLEEP_BETWEEN_PAGES = 1.0   # be considerate; this is a free service

# =====================================================================
# School catalog
# ---------------------------------------------------------------------
# Canonical name -> (tier, [aliases]). Strict mode drops any decision line
# whose school does not resolve here, so extend this list rather than
# loosening the matcher. Tiers drive the app's aggregate panel.
# =====================================================================
CATALOG: dict[str, tuple[str, list[str]]] = {
    "Harvard University":        ("Most selective", ["harvard", "harvard college"]),
    "Stanford University":       ("Most selective", ["stanford"]),
    "MIT":                       ("Most selective", ["mit", "massachusetts institute of technology"]),
    "Princeton University":      ("Most selective", ["princeton"]),
    "Yale University":           ("Most selective", ["yale"]),
    "Caltech":                   ("Most selective", ["caltech", "california institute of technology"]),
    "Columbia University":       ("Most selective", ["columbia"]),
    "University of Pennsylvania":("Most selective", ["upenn", "penn", "u penn", "wharton", "university of pennsylvania"]),
    "Duke University":           ("Most selective", ["duke"]),
    "Brown University":          ("Most selective", ["brown"]),
    "University of Chicago":     ("Most selective", ["uchicago", "u chicago", "university of chicago"]),
    "Dartmouth College":         ("Most selective", ["dartmouth"]),
    "Northwestern University":   ("Most selective", ["northwestern", "nu"]),
    "Johns Hopkins University":  ("Most selective", ["jhu", "johns hopkins", "hopkins"]),
    "Cornell University":        ("Most selective", ["cornell"]),
    "Rice University":           ("Highly selective", ["rice"]),
    "Vanderbilt University":     ("Highly selective", ["vanderbilt", "vandy"]),
    "Washington University in St. Louis": ("Highly selective", ["washu", "wustl", "washington university in st louis", "washington university in st. louis"]),
    "Carnegie Mellon University":("Highly selective", ["cmu", "carnegie mellon"]),
    "Georgetown University":     ("Highly selective", ["georgetown", "gtown"]),
    "University of Notre Dame":  ("Highly selective", ["notre dame", "nd"]),
    "UC Berkeley":               ("Highly selective", ["ucb", "uc berkeley", "berkeley", "cal"]),
    "UCLA":                      ("Highly selective", ["ucla", "uc los angeles"]),
    "University of Michigan":    ("Highly selective", ["umich", "u michigan", "michigan", "university of michigan ann arbor"]),
    "Emory University":          ("Highly selective", ["emory"]),
    "University of Southern California": ("Highly selective", ["usc", "southern cal"]),
    "Tufts University":          ("Highly selective", ["tufts"]),
    "New York University":       ("Highly selective", ["nyu", "new york university"]),
    "University of Virginia":    ("Highly selective", ["uva", "university of virginia"]),
    "Georgia Tech":              ("Highly selective", ["gatech", "gt", "georgia tech", "georgia institute of technology"]),
    "UNC Chapel Hill":           ("Highly selective", ["unc", "unc chapel hill", "university of north carolina", "north carolina"]),
    "UC San Diego":              ("Selective", ["ucsd", "uc san diego"]),
    "Boston University":         ("Selective", ["bu", "boston university"]),
    "Northeastern University":   ("Selective", ["northeastern", "neu"]),
    "Case Western Reserve University": ("Selective", ["case western", "cwru", "case western reserve"]),
    "UIUC":                      ("Selective", ["uiuc", "illinois urbana champaign", "university of illinois"]),
    "UT Austin":                 ("Selective", ["ut austin", "ut", "university of texas", "university of texas at austin", "texas austin"]),
    "UC Irvine":                 ("Selective", ["uci", "uc irvine"]),
    "UC Davis":                  ("Selective", ["ucd", "uc davis"]),
    "UC Santa Barbara":          ("Selective", ["ucsb", "uc santa barbara"]),
    "University of Wisconsin–Madison": ("Selective", ["uw madison", "wisconsin madison", "wisc", "university of wisconsin madison", "university of wisconsin", "uw-madison"]),
    "University of Maryland":    ("Selective", ["umd", "maryland", "university of maryland college park"]),
    "Purdue University":         ("Selective", ["purdue"]),
    "Boston College":            ("Selective", ["bc", "boston college"]),
    "University of Washington":  ("Selective", ["uw", "udub", "university of washington"]),
    "University of Florida":     ("Selective", ["uf", "university of florida"]),
    "Ohio State University":     ("Likely", ["osu", "ohio state"]),
    "Penn State University":     ("Likely", ["psu", "penn state"]),
    "Rutgers University":        ("Likely", ["rutgers"]),
    "University of Pittsburgh":  ("Likely", ["pitt", "university of pittsburgh"]),
    "UMass Amherst":             ("Likely", ["umass", "umass amherst"]),
    "Indiana University":        ("Likely", ["iu", "indiana university", "indiana"]),
    "Michigan State University": ("Likely", ["msu", "michigan state"]),
    "UC Santa Cruz":             ("Likely", ["ucsc", "uc santa cruz"]),
    "UC Riverside":              ("Likely", ["ucr", "uc riverside"]),
    "UC Merced":                 ("Likely", ["ucm", "uc merced"]),
    "Arizona State University":  ("Very likely", ["asu", "arizona state"]),
    "University of Alabama":     ("Very likely", ["bama", "university of alabama", "alabama"]),
    "University of Arizona":     ("Very likely", ["u of a", "university of arizona", "arizona"]),
    "Iowa State University":     ("Very likely", ["iowa state"]),
    "University of Kansas":      ("Very likely", ["ku", "university of kansas", "kansas"]),

    # ---- liberal arts colleges ----
    "Williams College":          ("Most selective", ["williams"]),
    "Amherst College":           ("Most selective", ["amherst college", "amherst"]),
    "Swarthmore College":        ("Most selective", ["swarthmore", "swat"]),
    "Pomona College":            ("Most selective", ["pomona"]),
    "Bowdoin College":           ("Most selective", ["bowdoin"]),
    "Claremont McKenna College": ("Most selective", ["claremont mckenna", "cmc"]),
    "Wellesley College":         ("Highly selective", ["wellesley"]),
    "Middlebury College":        ("Highly selective", ["middlebury", "midd"]),
    "Carleton College":          ("Highly selective", ["carleton"]),
    "Haverford College":         ("Highly selective", ["haverford"]),
    "Vassar College":            ("Highly selective", ["vassar"]),
    "Hamilton College":          ("Highly selective", ["hamilton college"]),
    "Colby College":             ("Highly selective", ["colby"]),
    "Bates College":             ("Highly selective", ["bates"]),
    "Colgate University":        ("Highly selective", ["colgate"]),
    "Grinnell College":          ("Highly selective", ["grinnell"]),
    "Harvey Mudd College":       ("Highly selective", ["harvey mudd", "mudd"]),
    "Barnard College":           ("Highly selective", ["barnard"]),
    "Wesleyan University":       ("Highly selective", ["wesleyan"]),
    "Davidson College":          ("Highly selective", ["davidson"]),
    "Smith College":             ("Selective", ["smith college"]),
    "Oberlin College":           ("Selective", ["oberlin"]),
    "Macalester College":        ("Selective", ["macalester", "mac"]),
    "Bryn Mawr College":         ("Selective", ["bryn mawr"]),
    "Kenyon College":            ("Selective", ["kenyon"]),
    "Scripps College":           ("Selective", ["scripps"]),
    "Pitzer College":            ("Selective", ["pitzer"]),
    "Occidental College":        ("Selective", ["occidental", "oxy"]),
    "Skidmore College":          ("Selective", ["skidmore"]),
    "Trinity College":           ("Selective", ["trinity college"]),
    "Dickinson College":         ("Likely", ["dickinson"]),
    "Denison University":        ("Likely", ["denison"]),

    # ---- more privates ----
    "Tulane University":         ("Highly selective", ["tulane"]),
    "Wake Forest University":    ("Highly selective", ["wake forest", "wake"]),
    "Brandeis University":       ("Selective", ["brandeis"]),
    "Lehigh University":         ("Selective", ["lehigh"]),
    "Villanova University":      ("Selective", ["villanova", "nova"]),
    "Rensselaer Polytechnic Institute": ("Selective", ["rpi", "rensselaer"]),
    "Worcester Polytechnic Institute":  ("Selective", ["wpi", "worcester polytechnic"]),
    "Stevens Institute of Technology":  ("Selective", ["stevens", "stevens institute"]),
    "Fordham University":        ("Selective", ["fordham"]),
    "Syracuse University":       ("Selective", ["syracuse", "cuse"]),
    "George Washington University": ("Selective", ["gwu", "george washington", "gw"]),
    "American University":       ("Selective", ["american university", "au"]),
    "Rochester Institute of Technology": ("Selective", ["rit", "rochester institute"]),
    "University of Rochester":   ("Selective", ["u rochester", "university of rochester", "urochester"]),
    "Santa Clara University":    ("Selective", ["santa clara", "scu"]),
    "Pepperdine University":     ("Selective", ["pepperdine"]),
    "Southern Methodist University": ("Selective", ["smu", "southern methodist"]),
    "Baylor University":         ("Likely", ["baylor"]),
    "Marquette University":      ("Likely", ["marquette"]),
    "Drexel University":         ("Likely", ["drexel"]),
    "Hofstra University":        ("Likely", ["hofstra"]),
    "Loyola Marymount University": ("Likely", ["lmu", "loyola marymount"]),
    "DePaul University":         ("Very likely", ["depaul"]),
    "Arizona Christian":         ("Very likely", ["arizona christian"]),

    # ---- more publics / flagships ----
    "College of William & Mary": ("Highly selective", ["william and mary", "william & mary", "wm"]),
    "University of Georgia":     ("Selective", ["uga", "university of georgia"]),
    "University of Texas at Dallas": ("Selective", ["utd", "ut dallas"]),
    "Virginia Tech":             ("Selective", ["vt", "virginia tech", "vtech"]),
    "North Carolina State University": ("Selective", ["nc state", "ncsu"]),
    "University of Minnesota":   ("Selective", ["umn", "university of minnesota", "minnesota"]),
    "University of Connecticut": ("Selective", ["uconn"]),
    "Binghamton University":     ("Selective", ["binghamton", "suny binghamton"]),
    "Stony Brook University":    ("Selective", ["stony brook", "suny stony brook"]),
    "University of Colorado Boulder": ("Likely", ["cu boulder", "colorado boulder", "cu"]),
    "University of Utah":        ("Likely", ["university of utah", "utah"]),
    "University of Oregon":      ("Likely", ["university of oregon", "uoregon"]),
    "Oregon State University":   ("Likely", ["oregon state"]),
    "University of Iowa":        ("Likely", ["university of iowa"]),
    "University of Missouri":    ("Likely", ["mizzou", "university of missouri"]),
    "University of Tennessee":   ("Likely", ["ut knoxville", "university of tennessee", "tennessee"]),
    "University of Kentucky":    ("Likely", ["university of kentucky", "kentucky"]),
    "University of South Carolina": ("Likely", ["university of south carolina", "south carolina"]),
    "Clemson University":        ("Likely", ["clemson"]),
    "Auburn University":         ("Likely", ["auburn"]),
    "Texas A&M University":      ("Likely", ["texas a&m", "tamu", "texas am"]),
    "University of Delaware":    ("Likely", ["udel", "university of delaware"]),
    "University of Vermont":     ("Likely", ["uvm", "university of vermont"]),
    "University of New Hampshire": ("Likely", ["unh"]),
    "San Jose State University": ("Likely", ["sjsu", "san jose state"]),
    "Cal Poly San Luis Obispo":  ("Selective", ["cal poly slo", "cal poly", "calpoly"]),
    "Cal Poly Pomona":           ("Likely", ["cal poly pomona", "cpp"]),
    "San Diego State University":("Likely", ["sdsu", "san diego state"]),
    "University of Nevada":      ("Very likely", ["unr", "university of nevada", "unlv"]),
    "University of Cincinnati":  ("Very likely", ["university of cincinnati", "cincinnati"]),
    "Temple University":         ("Very likely", ["temple"]),
    "University of Houston":     ("Very likely", ["university of houston", "uh"]),
    "Florida State University":  ("Likely", ["fsu", "florida state"]),
    "University of Central Florida": ("Very likely", ["ucf", "central florida"]),
    "University of South Florida":   ("Very likely", ["usf", "south florida"]),
    "Rutgers Newark":            ("Very likely", ["rutgers newark"]),
    "Oklahoma State University": ("Very likely", ["oklahoma state", "okstate"]),
    "University of Oklahoma":    ("Very likely", ["university of oklahoma", "oklahoma"]),
    "Kansas State University":   ("Very likely", ["kansas state", "k state"]),
    "University of Nebraska":    ("Very likely", ["university of nebraska", "nebraska"]),

    # ---- non-US commonly listed ----
    "University of Toronto":     ("Selective", ["uoft", "u of t", "university of toronto", "toronto"]),
    "University of Waterloo":    ("Selective", ["waterloo"]),
    "McGill University":         ("Selective", ["mcgill"]),
    "University of British Columbia": ("Selective", ["ubc"]),
    "University of Oxford":      ("Most selective", ["oxford"]),
    "University of Cambridge":   ("Most selective", ["cambridge"]),
    "Imperial College London":   ("Highly selective", ["imperial college", "imperial"]),
    "London School of Economics":("Highly selective", ["lse", "london school of economics"]),
    "University College London": ("Highly selective", ["ucl", "university college london"]),
    "King's College London":     ("Selective", ["kcl", "kings college london", "king's college london"]),
    "National University of Singapore": ("Highly selective", ["nus"]),
}

ALIAS_TO_CANON: dict[str, str] = {}
for canon, (_tier, aliases) in CATALOG.items():
    ALIAS_TO_CANON[canon.lower()] = canon
    for a in aliases:
        ALIAS_TO_CANON[a] = canon
TIER_OF = {c: t for c, (t, _a) in CATALOG.items()}

# =====================================================================
# Normalisation tables
# =====================================================================
GENDER_MAP = [
    (r"\b(non[- ]?binary|nonbinary|enby|nb)\b", "Non-binary"),
    (r"\b(female|f|girl|woman|women|gal|lady|cis ?female)\b", "Female"),
    (r"\b(male|m|guy|dude|boy|man|men|cis ?male)\b", "Male"),
]
ETHNICITY_MAP = [
    (r"south[- ]?asian|indian|desi|pakistani|bangladeshi|sri ?lankan|nepali", "South Asian"),
    (r"east[- ]?asian|chinese|korean|japanese|taiwanese", "East Asian"),
    (r"southeast[- ]?asian|vietnamese|filipin|thai|hmong|cambodian|indonesian|malaysian", "Southeast Asian"),
    (r"hispanic|latin[oax]|mexican|colombian|peruvian|cuban|puerto ?rican", "Hispanic or Latino"),
    (r"black|african[- ]?american|nigerian|ghanaian|kenyan|ethiopian", "Black or African American"),
    (r"middle[- ]?eastern|arab|persian|iranian|lebanese|egyptian|mena|turkish", "Middle Eastern"),
    (r"native[- ]?american|indigenous|american indian|alaska native", "Native American"),
    (r"pacific islander|native hawaiian|samoan", "Pacific Islander"),
    (r"white|caucasian|european", "White"),
]
MAJOR_MAP = [
    (r"computer sci|\bcs\b|software|computing|informatics", "Computer Science"),
    (r"engineer|\bece\b|\bmech ?e\b|aerospace|civil eng|chemical eng", "Engineering"),
    (r"pre[- ]?med|biolog|biochem|neurosci|life sci|molecular", "Biology / Pre-med"),
    (r"business|finance|marketing|accounting|wharton|management", "Business"),
    (r"econ", "Economics"),
    (r"\bmath|statistic|data sci", "Mathematics / Statistics"),
    (r"physics|astronom|astrophys", "Physics"),
    (r"political sci|\bpoli ?sci\b|government|international relations|global stud|public policy", "Political Science / IR"),
    (r"psycholog", "Psychology"),
    (r"nursing", "Nursing"),
    (r"english|history|philosoph|literature|classics|humanities|linguistic", "Humanities"),
    (r"art|design|architect|music|film|theat", "Art & Design"),
    (r"undecided|undeclared|open major|exploratory", "Undecided"),
]
US_STATES = {
 "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in","ia","ks","ky","la","me","md",
 "ma","mi","mn","ms","mo","mt","ne","nv","nh","nj","nm","ny","nc","nd","oh","ok","or","pa","ri","sc",
 "sd","tn","tx","ut","vt","va","wa","wv","wi","wy","dc",
 "alabama","alaska","arizona","arkansas","california","colorado","connecticut","delaware","florida",
 "georgia","hawaii","idaho","illinois","indiana","iowa","kansas","kentucky","louisiana","maine",
 "maryland","massachusetts","michigan","minnesota","mississippi","missouri","montana","nebraska",
 "nevada","new hampshire","new jersey","new mexico","new york","north carolina","north dakota","ohio",
 "oklahoma","oregon","pennsylvania","rhode island","south carolina","south dakota","tennessee","texas",
 "utah","vermont","virginia","washington","west virginia","wisconsin","wyoming",
}
US_METROS = ["bay area","socal","norcal","nyc","new england","midwest","new york city","la ","tristate",
             "tri-state","dmv","silicon valley","chicagoland","usa","u.s.","us ","united states"]

# Order matters only for tie-breaks; classification uses whichever keyword
# appears FIRST in the header, so "Waitlists -> Rejected" is a waitlist block.
RESULT_HEADERS = [
    ("waitlisted", r"wait\s*-?\s*list|\bwl\b"),
    ("accepted",   r"accept|admit|committed|\bwins?\b"),
    ("rejected",   r"reject|denied|denial|\bdenies\b"),
    ("deferred",   r"defer"),
]
# Whole-header shorthands some posters use instead of a word ("In:", "Outs:", "L's")
RESULT_EXACT = {
    "in": "accepted", "ins": "accepted", "yes": "accepted", "yeses": "accepted",
    "w": "accepted", "ws": "accepted", "the good": "accepted", "good news": "accepted",
    "out": "rejected", "outs": "rejected", "no": "rejected", "nos": "rejected",
    "l": "rejected", "ls": "rejected", "l s": "rejected", "the bad": "rejected",
    "bad news": "rejected", "the ugly": "rejected",
}
# Inline form: "Rejections: Harvard, Yale, Princeton" on a single line rather
# than as a section header with bullets beneath it.
INLINE_RESULT_RE = re.compile(
    r"^[\s>*\-•#]*\**\s*(accept\w*|admits?|reject\w*|denials?|denied|waitlists?|waitlisted)\s*\**\s*:\s*(.+)$",
    re.I | re.M)


def result_of_word(word: str) -> str | None:
    w = word.lower()
    if w.startswith(("waitlist",)):
        return "waitlisted"
    if w.startswith(("accept", "admit")):
        return "accepted"
    if w.startswith(("reject", "denial", "denied")):
        return "rejected"
    return None


ROUND_TOKEN_RE = [
    (r"\bed\s*(?:2|ii|two)\b", "ED"), (r"\bed\s*(?:1|i|one)?\b", "ED"),
    (r"\b(?:rea|scea|restrictive early|single choice)\b", "EA"),
    (r"\bearly action\b", "EA"), (r"\bea\s*(?:2|ii)?\b", "EA"),
    (r"\bearly decision\b", "ED"),
    (r"\b(?:rd|regular decision|regular)\b", "RD"),
    (r"\brolling\b", "RD"), (r"\bpriority\b", "RD"),
]


def header_round(title: str) -> str | None:
    """A round for a whole section, but only when the header names exactly one."""
    low = title.lower()
    found = {label for pat, label in ROUND_TOKEN_RE if re.search(pat, low)}
    return found.pop() if len(found) == 1 else None

# =====================================================================
# Text helpers
# =====================================================================
def clean_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"\\([#*_\[\]()~`>+\-.!\\])", r"\1", s)   # markdown escapes
    s = s.replace("→", " -> ").replace("–", "-").replace("—", "-")
    return s


def strip_md(s: str) -> str:
    return re.sub(r"[*_`#]+", "", s or "").strip()


def field(text: str, *labels: str) -> str | None:
    """Find `Label ...: value` on a line, tolerating bold markers and parentheticals."""
    for lab in labels:
        pat = r"^[\s>*\-•#\d.]*\**\s*" + lab + r"[^:\n]{0,80}?:\s*\**\s*(.+)$"
        m = re.search(pat, text, re.I | re.M)
        if m:
            v = strip_md(m.group(1))
            if v and v.lower() not in {"n/a", "na", "none", "-", "--", "tbd"}:
                return v
    return None


HEADER_RE = re.compile(r"^\s{0,3}(?:#{1,6}\s*(.+?)|\*{2,}(.+?)\*{2,}\s*|\*(.+?)\*\s*)$", re.M)


def headers(text: str) -> list[tuple[int, int, str]]:
    """(start_of_body, header_start, header_title) for every header-looking line."""
    out = []
    for m in HEADER_RE.finditer(text):
        title = next((g for g in m.groups() if g), "")
        title = strip_md(title).strip(": ").strip()
        if title and len(title) < 120:
            out.append((m.end(), m.start(), title))
    return out


def section(text: str, *name_pats: str) -> str | None:
    """Body text under the first header matching any pattern, up to the next header."""
    hs = headers(text)
    for i, (body_start, _hstart, title) in enumerate(hs):
        for pat in name_pats:
            if re.search(pat, title, re.I):
                end = hs[i + 1][1] if i + 1 < len(hs) else len(text)
                return text[body_start:end]
    return None


BULLET_RE = re.compile(r"^\s{0,4}(?:[-*•]|\d+[.)])\s+(.*\S)\s*$", re.M)


def bullets(block: str) -> list[str]:
    if not block:
        return []
    out = [strip_md(m.group(1)) for m in BULLET_RE.finditer(block)]
    if not out:  # some posts use bare lines
        out = [strip_md(l) for l in block.split("\n") if l.strip() and not l.strip().startswith(">")]
    return [b for b in out if b]


# =====================================================================
# Field parsers
# =====================================================================
def parse_gpa(text: str) -> float | None:
    raw = field(text, "GPA", "Unweighted GPA", "UW GPA")
    if not raw:
        return None
    m = re.search(r"([0-4](?:\.\d{1,3})?)\s*(?:/\s*4(?:\.0+)?)?\s*(?:uw|unweighted)", raw, re.I)
    if m:
        v = float(m.group(1))
        return v if 0 < v <= 4.0 else None
    for tok in re.findall(r"\d+(?:\.\d+)?", raw):
        v = float(tok)
        if 0 < v <= 4.0:
            return round(v, 3)
    return None


def parse_sat(text: str) -> int | None:
    raw = field(text, "SAT I", "SAT", "SAT Total", "New SAT")
    if not raw or re.search(r"n/?a|none|not submit|test.?optional|didn'?t|no sat", raw, re.I):
        return None
    for tok in re.findall(r"\d{3,4}", raw):
        v = int(tok)
        if 400 <= v <= 1600 and v % 10 == 0:
            return v
    return None


def parse_act(text: str) -> int | None:
    raw = field(text, "ACT")
    if not raw or re.search(r"n/?a|none|not submit|test.?optional|didn'?t|no act", raw, re.I):
        return None
    m = re.search(r"\b([1-9]|[12]\d|3[0-6])\b", raw)
    return int(m.group(1)) if m else None


def norm_from_map(value: str | None, table) -> str | None:
    if not value:
        return None
    low = value.lower()
    hits = [label for pat, label in table if re.search(pat, low)]
    return hits[0] if hits else None


def parse_ethnicity(text: str) -> str | None:
    raw = field(text, "Race/Ethnicity", "Race", "Ethnicity")
    if not raw:
        return None
    low = raw.lower()
    if re.search(r"multi[- ]?racial|biracial|mixed", low):
        return "Multiracial"
    hits = []
    for pat, label in ETHNICITY_MAP:
        if re.search(pat, low) and label not in hits:
            hits.append(label)
    if len(hits) > 1:
        return "Multiracial"
    if hits:
        return hits[0]
    # Fallback only — a bare "Asian" with no region given. Deliberately a
    # separate bucket rather than being folded into East or South Asian,
    # which would invent a distinction the poster didn't make.
    if re.search(r"\basian\b", low):
        return "Asian (unspecified)"
    return None


def parse_gender(text: str) -> str | None:
    raw = field(text, "Gender", "Sex")
    return norm_from_map(raw, GENDER_MAP)


def parse_residency(text: str) -> tuple[str | None, str | None]:
    raw = field(text, "Residence", "Location", "State", "Country")
    if not raw:
        return None, None
    low = raw.lower().strip()
    if re.search(r"\binternational\b|\bintl\b", low):
        return "international", raw
    tokens = re.split(r"[,/()]", low)
    for t in tokens:
        t = t.strip().strip(".")
        if t in US_STATES:
            return "domestic", raw
    if any(k in low for k in US_METROS):
        return "domestic", raw
    # a bare word we don't recognise as a US state is most likely a country
    return ("international", raw) if len(low) > 1 else (None, raw)


def parse_major(text: str) -> str | None:
    raw = field(text, "Intended Major", "Major", "Intended Majors", "Prospective Major")
    if not raw:
        blk = section(text, r"intended major", r"^majors?$", r"prospective major")
        if blk:
            raw = " ".join(bullets(blk))[:200] or blk.strip()[:200]
    return norm_from_map(raw, MAJOR_MAP) or ("Other" if raw else None)


def parse_hook(text: str) -> str | None:
    raw = field(text, "Hooks", "Hook")
    if not raw:
        return None
    if re.fullmatch(r"(n/?a|none|no|nope|nothing|-|lol none)\.?", raw.strip(), re.I):
        return None
    return raw[:120]


def parse_ecs(text: str) -> list[str]:
    blk = section(text, r"extracurricular", r"^activities$", r"^ecs?$")
    return [b[:160] for b in bullets(blk)][:8] if blk else []


def parse_round(line: str) -> str:
    low = line.lower()
    for pat, label in ROUND_TOKEN_RE:
        if re.search(pat, low):
            return label
    return "RD"


def resolve_school(raw: str) -> str | None:
    s = strip_md(raw)
    s = re.sub(r"\([^)]*\)", " ", s)                       # drop parentheticals
    s = re.sub(r"\[[^\]]*\]", " ", s)
    s = s.split(" - ")[0].split(" — ")[0]
    s = re.sub(r"\b(?:committed?|attending|enrolling|deferred?|waitlisted?|rejected?|accepted?)\b.*$", "", s, flags=re.I)
    s = re.sub(r"[^a-z0-9&.–\- ]", " ", s.lower())
    s = re.sub(r"\s+", " ", s).strip(" .,-–")
    if not s:
        return None
    if s in ALIAS_TO_CANON:
        return ALIAS_TO_CANON[s]
    s2 = re.sub(r"^(the)\s+", "", s)
    if s2 in ALIAS_TO_CANON:
        return ALIAS_TO_CANON[s2]
    # longest alias that matches on word boundaries
    best = None
    for alias, canon in ALIAS_TO_CANON.items():
        if len(alias) < 3:
            continue
        if re.search(r"\b" + re.escape(alias) + r"\b", s):
            if best is None or len(alias) > len(best[0]):
                best = (alias, canon)
    return best[1] if best else None


def school_candidates(line: str) -> list[str]:
    """
    One decision line can name several schools ("Harvard, Yale, Princeton").
    Resolving only the whole line loses all but one, which silently deletes
    rejections — people bullet their acceptances but lump their rejections.

    Splitting is done carefully: some names legitimately contain a comma
    ("University of California, Berkeley") or the word "and" ("William and
    Mary"), so a split is only accepted when it resolves more schools than
    treating the line as a whole.
    """
    def segment(seg: str) -> list[str]:
        """Resolve one segment, deciding whether to split it on 'and'.

        Rule: take whichever reading yields more schools. "College of William
        and Mary" resolves to one school whole and none split, so it stays
        whole. "Harvard and Yale" resolves to one whole and two split, so it
        splits. This avoids needing a list of names that contain 'and'."""
        whole_hit = resolve_school(seg)
        if re.search(r"\s+\band\b\s+", seg):
            split_hits: list[str] = []
            for half in re.split(r"\s+\band\b\s+", seg):
                h = resolve_school(half)
                if h and h not in split_hits:
                    split_hits.append(h)
            if len(split_hits) > (1 if whole_hit else 0):
                return split_hits
        return [whole_hit] if whole_hit else []

    got: list[str] = []
    for seg in re.split(r"\s*[,;]\s+|\s+/\s+|\s+\+\s+", line):
        for c in segment(seg):
            if c not in got:
                got.append(c)
    if got:
        return got
    whole = resolve_school(line)
    return [whole] if whole else []


def add_apps(block: str, result: str, ctx_round: str | None,
             apps: list[dict], seen: set[str], unmatched: Counter) -> None:
    for line in bullets(block):
        if len(line) > 300:
            continue
        cands = school_candidates(line)
        if not cands:
            cleaned = re.sub(r"\([^)]*\)", "", strip_md(line)).strip()
            if 2 < len(cleaned) < 60:
                unmatched[cleaned.lower()] += 1
            continue
        line_round = parse_round(line)
        # an explicit tag on the line wins; otherwise inherit the section's round
        rnd = line_round if line_round != "RD" else (ctx_round or "RD")
        for canon in cands:
            if canon in seen:
                continue
            seen.add(canon)
            apps.append({"school": canon, "tier": TIER_OF[canon],
                         "round": rnd, "result": result})


def parse_decisions(text: str, unmatched: Counter) -> list[dict]:
    """Scan the whole post for result-block headers and collect their bullets."""
    hs = headers(text)
    apps: list[dict] = []
    seen: set[str] = set()
    ctx_round: str | None = None      # round named by an enclosing section header
    for i, (body_start, _hstart, title) in enumerate(hs):
        hr = header_round(title)
        if hr:
            ctx_round = hr
        low = title.lower()
        bare = re.sub(r"['’]", "", low).strip(" :.-")   # "L's" -> "ls"
        if bare in RESULT_EXACT:
            result = RESULT_EXACT[bare]
        else:
            # classify by whichever result keyword appears FIRST in the header,
            # so "Waitlists -> Rejected" is a waitlist block, not a rejection block
            best: tuple[int, str] | None = None
            for res, pat in RESULT_HEADERS:
                m = re.search(pat, low)
                if m and (best is None or m.start() < best[0]):
                    best = (m.start(), res)
            if not best:
                continue
            result = best[1]
        if result == "deferred":
            result = "rejected"          # a bare deferral block = no admit
        end = hs[i + 1][1] if i + 1 < len(hs) else len(text)
        add_apps(text[body_start:end], result, header_round(title) or ctx_round,
                 apps, seen, unmatched)

    # Second pass: inline "Rejections: Harvard, Yale" lines that are not
    # section headers with bullets underneath.
    for m in INLINE_RESULT_RE.finditer(text):
        result = result_of_word(m.group(1))
        if not result:
            continue
        add_apps(m.group(2), result, None, apps, seen, unmatched)

    return apps


ACT_TO_SAT = {36:1590,35:1540,34:1500,33:1460,32:1430,31:1400,30:1370,29:1340,28:1310,27:1280,
              26:1240,25:1210,24:1180,23:1140,22:1110,21:1070,20:1030,19:990,18:950}


def parse_post(post: dict, unmatched: Counter, drops: Counter) -> dict | None:
    text = clean_text(post.get("selftext", ""))
    if len(text) < 200:
        drops["body too short / removed"] += 1
        return None

    gpa = parse_gpa(text)
    if gpa is None:
        drops["no parseable unweighted GPA"] += 1
        return None

    apps = parse_decisions(text, unmatched)
    if not apps:
        drops["no resolvable decisions"] += 1
        return None
    if not any(a["result"] in ("accepted", "rejected", "waitlisted") for a in apps):
        drops["no usable outcomes"] += 1
        return None

    sat, act = parse_sat(text), parse_act(text)

    # "SAT: 800 (Math)" parses as a valid-looking total. When someone reports
    # both tests and the two disagree by more than ~250 points, the SAT figure
    # is almost always a section score, so trust the ACT instead of inventing
    # a profile with a 800 SAT and a 32 ACT.
    if sat and act:
        act_equiv = ACT_TO_SAT.get(act)
        if act_equiv and abs(act_equiv - sat) > 250:
            drops["SAT/ACT disagree — section score assumed"] += 1
            sat = None

    unified = sat if sat else (ACT_TO_SAT.get(act) if act else None)
    residency, residence_raw = parse_residency(text)

    created = post.get("created_utc") or 0
    dt = datetime.fromtimestamp(created, tz=timezone.utc)
    cycle = dt.year if dt.month <= 8 else dt.year + 1

    return {
        "id": "CR-" + str(post.get("id", "")),      # post id kept; username never stored
        "cycle": cycle,
        "gpa": gpa,
        "sat": sat,
        "act": act,
        "unified": unified,
        "ethnicity": parse_ethnicity(text),
        "gender": parse_gender(text),
        "residency": residency,
        "residence_raw": residence_raw,
        "major": parse_major(text),
        "income": field(text, "Income Bracket", "Income"),
        "school_type": field(text, "Type of School", "School Type"),
        "ecs": parse_ecs(text),
        "hook": parse_hook(text),
        "flair": post.get("link_flair_text"),
        "apps": apps,
    }


# =====================================================================
# Fetching
# =====================================================================
def fetch_page(after: int, before: str | None) -> list[dict]:
    params = {
        "subreddit": "collegeresults",
        "after": str(after),
        "limit": str(PAGE_SIZE),
        "sort": "asc",
        "fields": "id,created_utc,selftext,title,link_flair_text",
    }
    if before:
        params["before"] = before
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r).get("data", [])
        except Exception as e:                                  # noqa: BLE001
            wait = 3 * (attempt + 1)
            print(f"  ! {type(e).__name__}: {e} — retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    print("  ! giving up on this page", file=sys.stderr)
    return []


def to_epoch(datestr: str) -> int:
    return int(datetime.strptime(datestr, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def harvest(after: str, before: str | None, max_posts: int | None, keep_raw: bool):
    cursor, seen_ids = to_epoch(after), set()
    profiles, raw_out = [], []
    unmatched, drops = Counter(), Counter()
    fetched = 0

    print(f"Harvesting r/collegeresults from {after}" + (f" to {before}" if before else "") + " …")
    while True:
        page = fetch_page(cursor, before)
        if not page:
            break
        new = [p for p in page if p.get("id") not in seen_ids]
        if not new:
            break
        for p in new:
            seen_ids.add(p["id"])
            fetched += 1
            if keep_raw:
                raw_out.append({k: p.get(k) for k in ("id", "created_utc", "title", "link_flair_text", "selftext")})
            prof = parse_post(p, unmatched, drops)
            if prof:
                profiles.append(prof)
        cursor = max(p.get("created_utc", cursor) for p in new) + 1
        print(f"  fetched {fetched:>5}  parsed {len(profiles):>5}  "
              f"({datetime.fromtimestamp(cursor, tz=timezone.utc).date()})")
        if max_posts and fetched >= max_posts:
            break
        if len(page) < PAGE_SIZE:
            break
        time.sleep(SLEEP_BETWEEN_PAGES)

    return profiles, fetched, unmatched, drops, raw_out


# =====================================================================
# Output
# =====================================================================
def write_outputs(profiles, fetched, unmatched, drops, raw_out):
    with open("profiles.json", "w", encoding="utf-8") as f:
        json.dump({
            "source": "r/collegeresults via Arctic Shift",
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(profiles),
            "note": "Self-reported, volunteer sample. Usernames removed. Real admit rates are lower than these.",
            "profiles": profiles,
        }, f, ensure_ascii=False, indent=1)

    cols = ["id","cycle","gpa","sat","act","unified","ethnicity","gender","residency",
            "major","income","school_type","hook","ecs","accepted","waitlisted","rejected"]
    with open("profiles.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(cols)
        for p in profiles:
            g = lambda r: "; ".join(f"{a['school']} ({a['round']})" for a in p["apps"] if a["result"] == r)
            w.writerow([p["id"], p["cycle"], p["gpa"], p["sat"] or "", p["act"] or "", p["unified"] or "",
                        p["ethnicity"] or "", p["gender"] or "", p["residency"] or "", p["major"] or "",
                        p["income"] or "", p["school_type"] or "", p["hook"] or "", "; ".join(p["ecs"]),
                        g("accepted"), g("waitlisted"), g("rejected")])

    apps = [a for p in profiles for a in p["apps"]]
    def rate(field_name):
        vals = sum(1 for p in profiles if p.get(field_name) is not None)
        return f"{vals:>5} / {len(profiles):<5} ({100*vals/max(len(profiles),1):.0f}%)"

    lines = [
        "ApplicantTwin harvest report",
        f"generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        f"posts fetched      {fetched}",
        f"profiles kept      {len(profiles)}  ({100*len(profiles)/max(fetched,1):.0f}% of fetched)",
        f"applications       {len(apps)}  (avg {len(apps)/max(len(profiles),1):.1f} per profile)",
        "",
        "-- why posts were dropped --",
        *[f"  {reason:<32} {n}" for reason, n in drops.most_common()],
        "",
        "-- field extraction rates --",
        *[f"  {fld:<14} {rate(fld)}" for fld in
          ("gpa","sat","act","unified","ethnicity","gender","residency","major","income","hook")],
        "",
        "-- outcomes --",
        *[f"  {r:<12} {sum(1 for a in apps if a['result']==r)}" for r in ("accepted","waitlisted","rejected")],
        "",
        "-- rounds --",
        *[f"  {r:<12} {sum(1 for a in apps if a['round']==r)}" for r in ("ED","EA","RD")],
        "",
        "-- admit rate by tier --",
    ]
    for tier in ["Most selective","Highly selective","Selective","Likely","Very likely"]:
        t = [a for a in apps if a["tier"] == tier]
        acc = sum(1 for a in t if a["result"] == "accepted")
        if t:
            lines.append(f"  {tier:<18} {100*acc/len(t):>5.1f}%   n={len(t)}")
    lines += ["", f"unmatched school strings: {len(unmatched)} distinct "
                  f"({sum(unmatched.values())} lines dropped) — see unmatched_schools.txt"]
    open("harvest_report.txt", "w", encoding="utf-8").write("\n".join(lines) + "\n")

    with open("unmatched_schools.txt", "w", encoding="utf-8") as f:
        f.write("# Decision lines whose school did not resolve, most frequent first.\n"
                "# Add the common ones to CATALOG in this script and re-run.\n\n")
        for name, n in unmatched.most_common(400):
            f.write(f"{n:>5}  {name}\n")

    if raw_out:
        with open("raw_posts.jsonl", "w", encoding="utf-8") as f:
            for p in raw_out:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print("\n".join(lines))
    print("\nwrote profiles.json, profiles.csv, harvest_report.txt, unmatched_schools.txt"
          + (", raw_posts.jsonl" if raw_out else ""))


# =====================================================================
# Self-test — runs the parser against fixture posts, no network
# =====================================================================
def self_test(paths: list[str]) -> int:
    unmatched, drops = Counter(), Counter()
    failures = 0
    for path in paths:
        text = open(path, encoding="utf-8").read()
        prof = parse_post({"id": path, "selftext": text, "created_utc": 1745000000}, unmatched, drops)
        print(f"\n=== {path} ===")
        if not prof:
            print("  DROPPED:", dict(drops)); failures += 1; continue
        for k in ("gpa","sat","act","unified","ethnicity","gender","residency","major","income","hook"):
            print(f"  {k:<11} {prof[k]!r}")
        print(f"  ecs         {len(prof['ecs'])} items, first={prof['ecs'][0][:60]!r}" if prof["ecs"] else "  ecs         none")
        for r in ("accepted","waitlisted","rejected"):
            got = [a["school"] + "/" + a["round"] for a in prof["apps"] if a["result"] == r]
            print(f"  {r:<11} {len(got)}: {', '.join(got)}")
    if unmatched:
        print("\nunmatched school strings:")
        for n, c in unmatched.most_common(20):
            print(f"  {c:>3}  {n}")
    return failures


def diagnose(path: str = "profiles.json") -> None:
    """Health check on a finished profiles.json. Flags the failure modes that
    make a dataset look fine while being quietly wrong."""
    P = json.load(open(path, encoding="utf-8"))
    P = P["profiles"] if isinstance(P, dict) else P
    A = [a for p in P for a in p["apps"]]
    print(f"profiles {len(P)}   applications {len(A)}   avg {len(A)/max(len(P),1):.1f}/profile\n")

    warn, note = [], []
    no_neg = [p for p in P if any(a["result"] == "accepted" for a in p["apps"])
              and not any(a["result"] in ("rejected", "waitlisted") for a in p["apps"])]
    pctneg = 100 * len(no_neg) / max(len(P), 1)
    avg_listed = sum(len(p["apps"]) for p in no_neg) / max(len(no_neg), 1)
    print(f"acceptances but no rejections/waitlists : {len(no_neg)} ({pctneg:.0f}%), "
          f"listing {avg_listed:.1f} schools on average")
    # A missed rejection block leaves a normal-length acceptance list with a gap.
    # A short "I got in!" post lists one or two schools total. The average tells
    # them apart, so don't blame the parser for what is really post length.
    if pctneg > 8 and avg_listed >= 5:
        warn.append("Whole result blocks are being missed — these profiles list a normal "
                    "number of schools but no negative outcomes.")
    elif pctneg > 8:
        note.append(f"{len(no_neg)} profiles report only acceptances, but they list just "
                    f"{avg_listed:.1f} schools each — short posts and early-decision "
                    f"commitments, not missed parsing. Flag them in any UI so nobody reads "
                    f"them as applicants who got in everywhere.")

    rounds = Counter(a["round"] for a in A)
    tot = max(sum(rounds.values()), 1)
    print(f"rounds  RD {100*rounds['RD']/tot:.0f}%  EA {100*rounds['EA']/tot:.0f}%  ED {100*rounds['ED']/tot:.0f}%")
    if 100 * rounds["RD"] / tot > 75:
        warn.append("Round detection is weak — most applications defaulted to RD. "
                    "Treat the early-vs-regular comparison as unreliable.")

    one_rej = sum(1 for p in P if sum(1 for a in p["apps"] if a["result"] == "rejected") == 1
                  and sum(1 for a in p["apps"] if a["result"] == "accepted") >= 5)
    print(f"profiles with 1 rejection but 5+ acceptances : {one_rej}")
    if one_rej > len(P) * 0.02:
        warn.append("Multi-school lines may still be collapsing to a single school.")

    print("\nadmit rate by tier")
    for t in ["Most selective", "Highly selective", "Selective", "Likely", "Very likely"]:
        T = [a for a in A if a["tier"] == t]
        if T:
            print(f"  {t:<18}{100*sum(1 for a in T if a['result']=='accepted')/len(T):>6.1f}%   n={len(T)}")
    elite = [a for a in A if a["tier"] == "Most selective"]
    if elite:
        r = 100 * sum(1 for a in elite if a["result"] == "accepted") / len(elite)
        if r > 12:
            note.append(f"Most-selective admit rate computes to {r:.0f}%, against a real figure "
                        f"near 4%. This is the volunteer bias, not a bug: people who got into "
                        f"these schools post about it. No amount of parsing fixes it, which is "
                        f"why this data should never be used to show admit rates.")

    print("\nfield coverage")
    for k in ("sat", "act", "unified", "ethnicity", "gender", "residency", "major", "income", "ecs"):
        n = sum(1 for p in P if p.get(k) not in (None, "", []))
        print(f"  {k:<10}{100*n/max(len(P),1):>4.0f}%")

    import textwrap
    wrap = lambda s: textwrap.fill(s, 72, initial_indent="  * ", subsequent_indent="    ")
    print("\n" + ("-" * 60))
    if warn:
        print("PARSER PROBLEMS  (fixable — the script is losing data)")
        for w in warn:
            print(wrap(w))
    else:
        print("PARSER PROBLEMS  none detected")
    if note:
        print("\nPROPERTIES OF THE SAMPLE  (not fixable — handle in the UI)")
        for n in note:
            print(wrap(n))
    print("\nEither way: this data shows what happened to individual people.")
    print("It cannot tell you anyone's odds. Use official figures for rates.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--after", default="2024-01-01", help="start date YYYY-MM-DD (default 2024-01-01)")
    ap.add_argument("--before", default=None, help="end date YYYY-MM-DD")
    ap.add_argument("--limit-posts", type=int, default=None, help="stop after N posts fetched")
    ap.add_argument("--keep-raw", action="store_true", help="also write raw_posts.jsonl")
    ap.add_argument("--self-test", nargs="*", metavar="FIXTURE", help="parse local files instead of fetching")
    ap.add_argument("--diagnose", nargs="?", const="profiles.json", metavar="FILE",
                    help="health-check an existing profiles.json and exit")
    a = ap.parse_args()

    if a.diagnose:
        diagnose(a.diagnose); sys.exit(0)
    if a.self_test is not None:
        sys.exit(self_test(a.self_test or []))

    profiles, fetched, unmatched, drops, raw_out = harvest(a.after, a.before, a.limit_posts, a.keep_raw)
    if not profiles:
        print("No profiles parsed. Try --keep-raw and inspect raw_posts.jsonl.", file=sys.stderr)
        sys.exit(1)
    write_outputs(profiles, fetched, unmatched, drops, raw_out)


if __name__ == "__main__":
    main()
