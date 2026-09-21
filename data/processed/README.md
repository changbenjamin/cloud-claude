# Chinese clinical-stage drug asset dataset

A list of clinical-stage (and a few just-approved) drug assets originating from Chinese sponsors,
built entirely from data sources reachable inside this session's sandboxed network policy, plus
model research. It is a **research starting point, not a purchasing-grade source of truth** — see
Limitations below before using it to screen licensing targets.

## Files

| file | contents |
|---|---|
| `chinese_clinical_assets.csv` / `.json` | one row per drug asset: sponsor, target, mechanism, modality, indications, phase, trial counts, verification tier |
| `chinese_clinical_trials.csv` | one row per (asset, ClinicalTrials.gov study): phase, status, dates, title, why-stopped |
| `summary.json` | counts behind every number in this README |

`chinese_clinical_assets.json` also nests each asset's trial rows under a `trials` key, so it's a
single file if you want the whole thing.

## Why this exists and what changed from the original ask

The original request was for a scrape of *every* Chinese-sponsored clinical-stage asset from live
registries (ClinicalTrials.gov, the CDE platform, ChiCTR, PatSnap Synapse, etc.). This session's
network egress policy blocks essentially all of those domains — only GitHub, PyPI, npm, Docker Hub
metadata, and public AWS S3 buckets are reachable; `WebFetch` is blocked for every registry and
company-site domain tried. `WebSearch` (summarized web results, not raw page fetches) does work,
but is metered — the session exhausted its WebSearch budget partway through the first research
pass. What follows documents how the dataset was actually built under those constraints, and where
it falls short of "every asset, live-verified."

## Method

1. **Trial universe.** The [Open Targets Platform](https://platform.opentargets.org) release 26.06,
   pulled from its public AWS Open Data bucket (`s3://open-targets-public-data-releases`, no
   credentials needed — see `scripts/00_download_opentargets.sh`), turned out to carry a near-current
   mirror of ClinicalTrials.gov's full study registry (231,000 studies, registrations through mid-2026,
   via its underlying AACT source) as its `clinical_report` table. This became the trial universe
   in place of a live ClinicalTrials.gov scrape.
2. **Candidate extraction** (`scripts/01_extract_ctgov_trials_from_opentargets.py`,
   `02_build_asset_candidates.py`). Every trial's intervention names were parsed for an internal
   development code (e.g. `SHR-A1811`, `IBI363`) or normalized as a free-text drug name, then grouped
   into ~49,000 candidate assets by code/name.
3. **Seed classification.** A hand-built map of ~340 known Chinese (and, for contrast, non-Chinese)
   company code prefixes (`data/reference/code_prefix_map_seed.csv`) flagged 1,937 candidate assets
   as *possibly* Chinese-sponsored purely from the prefix of their code. **This seed map is a rough
   prior, not a source of truth** — see Limitations.
4. **Research pass.** Every one of the 1,937 seed-flagged assets was independently reviewed by a
   research subagent, tasked with confirming or correcting the seed's sponsor guess and filling in
   target, mechanism, modality, indications, phase, and (where known) licensing status:
   - **298 assets** were reviewed with live `WebSearch` access ("web_verified" — cites at least one URL).
   - **1,639 assets** were reviewed after the session's WebSearch budget ran out, from the model's
     trained knowledge only, with explicit instructions not to fabricate specifics and to flag low
     confidence rather than guess ("prior_knowledge").
   Agents were told to override the seed guess whenever their own knowledge disagreed, and to say so.
   This caught a large number of seed errors: **246 of the 1,937** seed-flagged assets turned out to
   belong to non-Chinese companies (code-prefix collisions like `AN-` matching both Adlai Nortye and
   Anacor Pharmaceuticals, or `CS-` matching both CStone and Daiichi Sankyo legacy compounds), and
   **76 more** were left as "sponsor unknown."
5. **Entity resolution.** The same drug often appears under a code, an INN, and sometimes a second
   partner's code (e.g. `AK112` / ivonescimab, `DB-1303` / `BNT323`). A four-pass merge collapsed
   1,615 CN-classified candidates into **1,399 unique assets**: explicit synonym claims from the
   research pass, shared ClinicalTrials.gov trial sets under the same sponsor, dehyphenated code
   matches, and fuzzy name matches for free-text formulation names.
6. **Canonicalization and cleaning.** Sponsor names were mapped to one canonical spelling per company
   (~120 companies); modality and phase were normalized to a fixed vocabulary; a handful of
   free-text fields that leaked into structured columns were caught and re-normalized.

## What's in the final dataset

- **1,399 unique Chinese-sponsored clinical-stage assets**, from **124 distinct sponsors**.
- **10,577 underlying ClinicalTrials.gov trial records** linked to those assets.
- Phase distribution: 557 phase 1, 244 phase 2, 258 phase 3, 208 phase 1/2, 18 phase 2/3, 85 approved
  in China only, 13 approved in China and ex-China, 6 NDA/BLA filed, 5 early phase 1, 4 approved
  US/EU, 5 preclinical/not stated.
- Modality: 441 small molecule, 204 monoclonal antibody, 110 ADC, 71 bispecific/multispecific
  antibody, 41 protein/fusion protein, 35 cell therapy, 29 biosimilar, 19 peptide, 16 oligonucleotide,
  11 vaccine, 9 generic/reformulation, 6 gene therapy, 5 radiopharmaceutical, 4 oncolytic virus,
  1 TCM/botanical, and 397 not confidently classified.
- Top sponsors by asset count: Jiangsu Hengrui Pharmaceuticals (185), Chia Tai Tianqing / Sino
  Biopharmaceutical (87), Innovent Biologics (59), Hansoh Pharma (55), Qilu Pharmaceutical (54),
  CSPC Pharmaceutical (44), Bio-Thera Solutions (43), Shanghai Henlius Biotech (40), Akeso (28),
  Kelun-Biotech (27) — full ranking in `summary.json`.
- **`verification_tier` on every row**: 237 assets are `web_verified` (at least one cited source),
  1,162 are `prior_knowledge` (model recall only, no live check this run). Use `sponsor_confidence`
  (high/medium/low) alongside it — a `prior_knowledge` row can still be high-confidence recall of a
  well-known drug, and a `web_verified` row can still be low-confidence about a specific detail.

## Limitations — read before relying on this for a licensing screen

1. **Coverage is a slice, not "every asset."** Tier A (the 1,937 seed-flagged, fully-researched
   candidates behind this dataset) came from code-prefix pattern matching, which only catches
   companies whose code convention was in the seed map and misses candidates named only by generic
   drug name with no distinctive code. Three more candidate tiers were built but **not** researched
   this session, for a combined ~7,580 additional candidate assets that may include real Chinese
   sponsors:
   - Tier B1 (4,804 candidates): code-like intervention names with a 2024+ trial, no code-prefix match.
   - Tier C (1,701 candidates): non-code names with a China signal (China mentioned in the trial
     title, "recombinant ... injection"-style naming, or an INN-like name in early clinical phases).
   - Tier B2 (1,078 candidates): code-like names whose newest trial is from 2022-2023.
   Their batch files already exist under `data/interim/enrichment/batches/` (prefixes `B1_`, `C_`,
   `B2_`) for a future research pass with the same subagent instructions in
   `data/interim/enrichment/AGENT_INSTRUCTIONS.md` / `NO_SEARCH_INSTRUCTIONS.md`.
2. **83% of rows were classified from model recall, not a live check.** `prior_knowledge` rows can
   be wrong in ways a live source would have caught — a renamed company, a discontinued program, a
   deal that happened after the model's training cutoff. Treat `sponsor_confidence: low` rows as
   "needs verification" rather than fact, and re-verify anything before using it for a real decision
   (a licensing screen, an investment memo, outreach).
3. **The seed map itself is unreliable on its own** — it exists only to narrow the search space, and
   research agents overrode it in roughly 1 case out of 6. A code prefix that only appears in the
   raw `data/interim/enrichment/results*/` files (i.e. was never independently confirmed) should not
   be trusted.
4. **"Latest data" fields are sparse and unverified.** Agents were told to leave `latest_data` blank
   rather than guess at trial results, so most rows have no efficacy data. Where filled, it is the
   model's recollection, not a citation to a specific abstract or press release, unless a URL is
   present in `sources`.
5. **Licensing status (`ex_china_rights`, `partner`) is incomplete.** Many of the assets in this list
   have already been licensed out (which would make them unavailable to a new licensee) — the
   dataset generally does not know this unless an agent happened to recall the deal.
6. **Entity resolution is heuristic and can both over- and under-merge.** A handful of true
   duplicates likely remain unmerged (e.g. one Huabo Biopharm docetaxel-micelle formulation still
   appears as two rows, one by internal code and one by descriptive name, because neither the
   trial-set-overlap nor the fuzzy-name-match threshold caught that particular pair). Conversely, a
   code-prefix collision that fooled the seed map could in principle also fool the entity-resolution
   pass if two different companies' assets were both (wrongly) attributed to the same sponsor name.
7. **China-founded but now multi-hub companies** (BeiGene/BeOne Medicines, Zai Lab, Gracell post
   AstraZeneca acquisition, I-Mab, HUTCHMED) are classified `CN` by origin. If your definition of
   "Chinese sponsor" is stricter (mainland-HQ'd only), filter these out using the `notes` field, which
   flags every such judgment call explicitly.
8. **Taiwan, Hong Kong and Macau.** Agents were instructed to classify mainland China, Hong Kong, and
   Macau as `CN` and Taiwan as `non-CN`; spot-check `sponsor_hq_city` if this distinction matters to you.

## Getting the ground truth this dataset couldn't reach

`scripts/scrapers/` has four ready-to-run scripts for the registries this session could not access
(see `scripts/scrapers/README.md`):

- `ctgov_api_v2.py` — the free ClinicalTrials.gov Data API v2 (no key needed): pull every study with
  a China site, every study from a named Chinese sponsor, or every study mentioning a given code.
  This gives you the one field this dataset is missing at the trial level: the actual **lead sponsor
  name** ClinicalTrials.gov has on file, which would let you QA or fully replace the code-prefix
  classification step.
- `cde_chinadrugtrials.py` — the mandatory CDE registration platform (药物临床试验登记与信息公示平台):
  every IND-approved trial in China, in Chinese, with sponsor and phase.
- `cde_implied_approval.py` — the CDE's implied-IND-approval list, the closest thing to a master
  list of every new drug cleared to start a trial in China.
- `chictr.py` — ChiCTR, for investigator-initiated and China-only industry trials not on
  ClinicalTrials.gov.

Running `ctgov_api_v2.py sponsors --sponsor-csv <a Chinese company list>` and cross-checking its
output against `chinese_clinical_assets.csv` would upgrade every `prior_knowledge` row that matches
to a genuinely source-verified one.

## Reproducing / extending

```
scripts/00_download_opentargets.sh                       # pull Open Targets 26.06 from public S3
scripts/01_extract_ctgov_trials_from_opentargets.py       # explode trials x interventions
scripts/02_build_asset_candidates.py                      # group into candidate assets, apply seed map
scripts/03_make_enrichment_batches.py                     # (re)split candidates into research batches
scripts/05_finalize_dataset.py                            # merge research + entity-resolve + clean
```

`scripts/04_merge_enrichment.py` is the superseded first-draft merge (kept for reference); `05` is
the one that produced the files in this directory.
