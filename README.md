# InRange

**[richard4481234.github.io/in-range](https://richard4481234.github.io/in-range/)**

Two questions, two datasets, deliberately never mixed.

| Tab | Question | Source |
|---|---|---|
| **Colleges** | What is the real admit rate, what will it cost, and where do my scores sit? | U.S. Department of Education |
| **Real applicants** | What actually happened to people with numbers like mine? | r/collegeresults posts |

The first gives numbers you can trust. The second gives the thing no official
dataset contains: individual stories showing that people with nearly identical
stats ended up in wildly different places.

---

## Colleges — 1,715 four-year institutions

From the [College Scorecard](https://collegescorecard.ed.gov/data/), which
publishes figures colleges report themselves through IPEDS. It covers
essentially all of them, so there is no sampling and no volunteer bias.
Currently built from the **10 June 2026** release.

Each school shows:

- **Admission rate** — the real one
- **Score range** — 25th–75th percentile of admitted students, with a marker for where you land
- **Graduation rate** — share finishing within six years, shown next to the admit rate rather than in small print
- **Cost** — the all-in annual figure: tuition *plus* housing, food, books and fees

**Similar schools** — one click surfaces the twelve most comparable institutions,
scored on selectivity, size, cost, graduation rate and public/private. No
rankings are involved; this data has no business asserting prestige.

**Compare** — put a shortlist side by side, best value in each column highlighted.

### What it deliberately does not do

**No "chance me" percentage.** A tool that multiplies your score by an admit
rate and returns "you have a 23% chance" is inventing that number. Admissions
offices read essays, recommendations, course rigor, context, and their own
institutional needs — none of which appear in any public dataset. The site shows
two separate facts and refuses to blend them.

**No default ranking.** With nothing entered, the list is alphabetical. Sorted
by selectivity it would open with the same handful of famous names everyone
already worries about. Across all 1,715 schools the median admission rate is
**77%**, and only **78** admit fewer than one in five.

**A score range is not a cutoff.** A quarter of admitted students scored below
the bottom of every range shown.

**Any school admitting under 20% is a reach for everyone**, regardless of score.

**Low graduation rates are called out.** Seventy schools here graduate under a
quarter of their students. Getting in is not the outcome that matters.

### What's missing, and why

| Missing | Reason |
|---|---|
| **GPA** | Federal data doesn't collect it. Anyone showing you a GPA cutoff got it from a survey or made it up. |
| **Major-level admissions** | Engineering and nursing are often far harder than the university-wide figure. |
| **In-state vs. out-of-state rates** | At public universities the gap is often enormous. Only the combined rate is published. |
| **Early vs. regular decision** | Not reported at this level. |

Test-optional schools' ranges describe only students who submitted scores.

---

## Real applicants — 1,782 posts

Harvested from **r/collegeresults** via the
[Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) archive, covering
the 2024–2026 cycles. Usernames are never stored.

Search across activities, intended major, background and hooks — *research*,
*debate*, *first-gen*, *QuestBridge*. Filter to a single school and split by
outcome to compare admits against rejects. Income is bucketed rather than shown
as the free text people wrote.

**This section contains no admit rates anywhere, on purpose.** People who got
good news post far more often than people who didn't. For scale: the
most-selective tier computes to a 20% admit rate here against a real figure near
4%. When you filter to one school the site shows you that gap directly — same
school, both numbers, side by side — because it's the clearest demonstration of
why these profiles can't estimate anyone's odds.

Roughly 15% of posts list acceptances but no rejections — short "I got in!"
posts and early-decision commitments, averaging under three schools each. They
are flagged and can be hidden.

---

## Files

| File | Purpose |
|---|---|
| `index.html` | The site. Self-contained — both datasets embedded, no server, no dependencies. |
| `in-range.html` | Template with empty data placeholders. |
| `get_college_data.py` | Downloads the Scorecard file, extracts `colleges.json`. |
| `harvest_collegeresults.py` | Harvests and parses r/collegeresults into `profiles.json`. |
| `csv_to_profiles.py` | Rebuilds `profiles.json` from `profiles.csv` if the JSON is lost. |
| `build_site.py` | Bakes both datasets into the template. |

## Rebuilding

```bash
python get_college_data.py        # official data  -> colleges.json
python harvest_collegeresults.py  # community data -> profiles.json  (optional, ~20 min)
python build_site.py              # -> InRange.html
```

Rename `InRange.html` to `index.html` and commit. Build without the community
section using `python build_site.py --no-people`.

Python 3.8+, standard library only — nothing to `pip install`.

**Checking your data:**

```bash
python harvest_collegeresults.py --diagnose
```

Separates genuine parser faults from properties of the sample that no parser can
fix. Both scripts have a `--self-test` that runs offline against fixtures.

---

## Notes

One HTML file, ~290 KB over the wire. No network requests, no cookies, nothing
sent anywhere. Your score and saved list stay in your browser. Every view is
linkable — filters, score and tab all live in the URL.

Scorecard data is a work of the U.S. federal government and is in the public
domain. Arctic Shift honours removal requests; anyone redistributing work built
on it should do the same.
