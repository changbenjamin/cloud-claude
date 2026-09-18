# Instructions for asset research subagents

You are researching drug assets (mostly identified by an internal development code such as `SHR-A1811`, or by an
INN/generic name) that appear as interventions in ClinicalTrials.gov. For each asset in your batch CSV you must
determine the sponsoring / originating company and whether it is a **Chinese sponsor** (company headquartered in
mainland China, Hong Kong or Macau, or a Chinese-founded company whose R&D is primarily in China), and, for Chinese
assets, collect the profile fields below.

## Environment constraints (read carefully)
* `WebFetch` is BLOCKED for nearly all domains by the network egress policy (it returns EGRESS_BLOCKED). Do not
  rely on it. Use `WebSearch` only. Bash has no internet access to the sources either.
* WebSearch returns titles, URLs and summarized snippets. ClinicalTrials.gov result snippets usually show the
  sponsor; company press releases show target, modality, indication and data. Good query patterns:
  * `"<code>" clinicaltrials.gov sponsor`
  * `"<code>" <company> phase 2 results` / `"<code>" target antibody OR inhibitor`
  * `"<code>" 临床 试验 公司` (Chinese-language queries often work well for Chinese assets)
  * for INN names: `"<inn>" originator company China` or `"<inn>" developed by`
* Budget: about 1 search per asset for classification, plus 1-2 more for assets that turn out to be Chinese.
  Do not spend more than 3 searches on any single asset. If nothing is found after 2 searches, record
  `sponsor_country = "unknown"` and move on. Do not stop early: process EVERY row in the batch.

## Batch input
A CSV with columns: asset_key, company_name_seed (a guess from the code prefix, may be wrong or empty),
seed_confidence, inn_from_ot, drug_type_ot, ot_max_stage, raw_names (as written in trial records), top_conditions,
phases, statuses, n_trials, min_nct, max_nct, sample_titles, nct_ids, china_title_hits.
Use the sample titles / conditions to disambiguate the code (e.g. a code used by two different companies).

## Output
Write ONE JSON object per line (JSONL) to the output path given in your task, with exactly these keys:
```
asset_key            : copy from input
sponsor              : canonical English company name of the originator / lead sponsor ("" if unknown)
sponsor_country      : "CN" | "non-CN" | "unknown"
sponsor_confidence   : "high" | "medium" | "low"
sponsor_hq_city      : city if known, else ""
inn_or_name          : INN or common name if one exists (e.g. "trastuzumab rezetecan"), else ""
other_codes          : other codes / synonyms, pipe-separated (e.g. "SHR-A1811|HRS-A1811"), else ""
target               : molecular target(s), e.g. "HER2", "PD-1 x VEGF", "GLP-1R/GIPR"; "" if unknown
mechanism            : short mechanism, e.g. "TOP1i ADC", "bispecific antibody", "KRAS G12C inhibitor"
modality             : one of: small molecule | monoclonal antibody | bispecific/multispecific antibody | ADC |
                       peptide | protein/fusion protein | oligonucleotide | cell therapy | gene therapy |
                       oncolytic virus | vaccine | radiopharmaceutical | biosimilar | TCM/botanical |
                       generic/reformulation | other | unknown
indications          : pipe-separated list of indications being developed (from trials and news)
highest_phase        : "preclinical" | "phase 1" | "phase 1/2" | "phase 2" | "phase 2/3" | "phase 3" | "NDA/BLA filed" |
                       "approved (China)" | "approved (US/EU)" | "approved (China + ex-China)" | "unknown"
development_status   : "active" | "discontinued" | "unclear"
ex_china_rights      : "" | "licensed-out" | "partnered" | "retained" | "unknown" ; if licensed, name partner in notes
partner              : licensee / partner company if any, else ""
latest_data          : 1-3 sentences summarizing the most recent clinical data with date and setting
                       (e.g. "ASCO 2026: ORR 62% in 2L HER2+ mBC (n=98), median PFS 11.2 mo"). "" if none found.
first_in_class_note  : "" or a short note if it is first-in-class / best-in-class positioning
sources              : pipe-separated list of 1-4 URLs you relied on
notes                : anything else useful (name collisions, uncertainty, approvals)
```
Only the `asset_key`, `sponsor`, `sponsor_country`, `sponsor_confidence` and `sources` keys are mandatory for
non-Chinese or unknown assets; fill the rest only if it comes for free. For Chinese assets fill every key you can.

## Method
1. Read the batch CSV (use Bash `cat` or the Read tool).
2. Process assets top to bottom. Append each result line to the output file immediately (use Bash with a Python
   one-liner or `printf` with proper JSON escaping) so that nothing is lost if you run out of time.
3. At the end, verify the output has one line per input asset (`wc -l`). Report counts: total, CN, non-CN, unknown.
