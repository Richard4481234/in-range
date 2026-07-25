# InRange

**[richard4481234.github.io/in-range](https://richard4481234.github.io/in-range/)**

Where your test scores actually sit at every four-year college in the United States.

Enter an SAT or ACT score and see, for each of 1,715 schools, the real admission
rate and the actual score range of admitted students — with a marker showing
where you land inside it.

---

## Where the data comes from

The [College Scorecard](https://collegescorecard.ed.gov/data/), published by the
U.S. Department of Education. Colleges report these figures themselves through
IPEDS, the federal reporting system every accredited institution is required to use.

It covers essentially all of them, so there is no sampling and no volunteer bias.
Currently built from the **10 June 2026** release.

Admissions figures typically describe a cycle one to two years old, because
reporting takes time.

---

## What it deliberately does not do

**There is no "chance me" percentage.** A tool that multiplies your score by an
admit rate and hands back "you have a 23% chance" is inventing that number.
Admissions offices read essays, recommendations, course rigor, context, and their
own institutional needs — none of which appear in this data or any public dataset.

So the site shows two separate facts and refuses to blend them: how selective the
school is, and where your score sits among admitted students. You draw the conclusion.

**A score range is not a cutoff.** The range is the 25th to 75th percentile of
admitted students. A quarter of admitted students scored *below* the bottom number.

**Any school admitting under 20% is labelled "Reach for everyone"**, regardless of
score. At those schools most rejected applicants are academically qualified, so a
strong score buys far less than it appears to. A tool that calls Stanford a "target"
because your SAT is 1560 is lying to you.

---

## What's missing, and why

| Missing | Reason |
|---|---|
| **GPA** | The federal data doesn't collect it. Anyone showing you a GPA cutoff got it from a survey or made it up. |
| **Major-level admissions** | Engineering and nursing are often far harder than the university-wide number. These are institution-wide figures. |
| **In-state vs. out-of-state rates** | At public universities the gap is often enormous. Only the combined rate is published. |
| **Early vs. regular decision** | Not reported at this level. |

Test-optional schools' ranges now describe only students who submitted scores,
which skews them upward.

---

## Files

| File | Purpose |
|---|---|
| `index.html` | The site. Self-contained — all data embedded, no server, no dependencies. |
| `in-range.html` | Template with an empty data placeholder. |
| `get_college_data.py` | Downloads the Scorecard file and extracts `colleges.json`. |
| `build_site.py` | Bakes `colleges.json` into the template to produce the final page. |

## Rebuilding when new data is published

```bash
python get_college_data.py    # downloads ~23 MB, writes colleges.json
python build_site.py          # writes InRange.html
```

Then rename `InRange.html` to `index.html` and commit it.

Python 3.8+. Standard library only — nothing to `pip install`.

`get_college_data.py --self-test` exercises the parser offline against fixtures
covering closed schools, two-year schools, test-blind schools and reversed
percentile ranges.

---

## Notes

The whole site is one HTML file. It makes no network requests, sets no cookies,
and sends nothing anywhere. Your score and your saved list stay in your browser.

Data is a work of the U.S. federal government and is in the public domain.
