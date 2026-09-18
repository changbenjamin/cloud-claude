# Registry scrapers (run outside the sandbox)

The session that built this repo could not reach clinicaltrials.gov, chinadrugtrials.org.cn, chictr.org.cn, cde.org.cn,
PatSnap Synapse, PubMed or company websites (all blocked by the environment's egress policy; only GitHub, PyPI,
npm, Docker Hub metadata, and public AWS S3 buckets were reachable). The committed dataset was therefore built
from the Open Targets Platform mirror of ClinicalTrials.gov (public S3 bucket) plus web-search based research.

These scripts are the "ground truth" refresh path once you run them from a normal machine:

| script | source | what it gives you |
|---|---|---|
| `ctgov_api_v2.py` | ClinicalTrials.gov Data API v2 (free, no key) | every study with China sites / Chinese sponsors / given codes, including **lead sponsor**, locations, dates, results flags |
| `cde_chinadrugtrials.py` | CDE 药物临床试验登记与信息公示平台 | every IND-approved drug trial in China (CTR numbers), sponsor, phase, indication, sites (Chinese) |
| `cde_implied_approval.py` | CDE 临床试验默示许可 list | every implied IND approval (acceptance no., drug, applicant, indication, date) |
| `chictr.py` | ChiCTR | investigator-initiated and some China-only industry trials |

Suggested order: run `ctgov_api_v2.py locn` and `sponsors`, then the two CDE scripts, then re-run
`scripts/02_build_asset_candidates.py` style grouping over the union (the CT.gov records now carry sponsor names,
so the code-prefix heuristics become a QA step rather than the primary classifier).

Install: `pip install requests lxml playwright && playwright install chromium`
