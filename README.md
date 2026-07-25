# InRange

**[richard4481234.github.io/in-range](https://richard4481234.github.io/in-range/)**

Two questions, two datasets, deliberately never mixed.

| Tab | Question | Source |
|---|---|---|
| **Colleges** | What is the real admit rate here, and where do my scores sit? | U.S. Department of Education |
| **Real applicants** | What actually happened to people with numbers like mine? | r/collegeresults posts |

The first gives you numbers you can trust. The second gives you the thing no
official dataset contains: individual stories showing that people with nearly
identical stats ended up in wildly different places.

---

## Colleges — 1,715 four-year institutions

Data from the [College Scorecard](https://collegescorecard.ed.gov/data/), which
publishes figures colleges report themselves through IPEDS, the federal system
every accredited institution must use. It covers essentially all of them, so
there is no sampling and no volunteer bias. Currently built from the
**10 June 2026** release.

Enter an SAT or ACT score and each school shows its admit rate alongside the
25th–75th percentile range of admitted students, with a marker for where you land.

### What it deliberately does not do

**There is no "chance me" percentage.** A tool that multiplies your score by an
admit rate and returns "you have a 23% chance" is inventing that number.
Admissions offices read essays, recommendations, course rigor, context, and their
own institutional needs — none of which appear in this data or any public dataset.

So the site shows two separate facts and refuses to blend them: how selective the
school is, and where your score sits among admitted students.

**A score range is not a cutoff.** A quarter of admitted students scored below
the bottom of every range shown.

**Any school admitting under 20% is labelled "Reach for everyone"**, regardless
of score. At those schools most rejected applicants are academically qualified,
so a strong score buys far less than it appears to.

### What's missing, and why

| Missing | Reason |
|---|---|
| **GPA** | The federal data doesn't collect it. Anyone showing you a GPA cutoff got it from a survey or made it up. |
| **Major-level admissions** | Engineering and nursing are often far harder than the university-wide number. |
| **In-state vs. out-of-state rates** | At public universities the gap is often enormous. Only the combined rate is published. |
| **Early vs. regular decision** | Not reported at this level. |

Test-optional schools' ranges describe only students who submitted scores, which
skews them upward.

---

## Real applicants — 1,782 posts

Harvested from **r/collegeresults** via the
[Arctic Shift](https://github.com/ArthurHeitmann/arctic_shift) archive, covering
the 2024–2026 application cycles. Usernames are never stored.

**This section contains no admit rates, anywhere, on purpose.** People who got
good news post about it far more often than people who didn't, so any percentage
computed from these profiles would be wrong in a predictable direction. For
scale: the most-selective tier computes to a 20% admit rate in this data against
a real figure near 4%. That gap *is* the bias, and no amount of parsing removes it.

What you get instead are counts and individual cases you can filter by how close
someone's stats are to yours.

Roughly 15% of posts list acceptances but no rejections — short "I got in!" posts
and early-decision commitments, averaging under three schools each. These are
flagged in the interface and can be hidden, so nobody reads them as applicants
who got in everywhere.

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
fix. `get_college_data.py --self-test` and `harvest_collegeresults.py --self-test`
exercise both parsers offline against fixtures.

---

## Notes

One HTML file. No network requests, no cookies, nothing sent anywhere. Your
score and saved list stay in your browser.

The Scorecard data is a work of the U.S. federal government and is in the public
domain. Arctic Shift honours data removal requests; anyone redistributing work
built on it should do the same.
