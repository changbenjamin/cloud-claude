# Instructions for asset research subagents — PRIOR-KNOWLEDGE-ONLY PASS

This is a follow-up pass. An earlier wave of agents exhausted a shared, session-wide WebSearch quota partway
through, and a shared-scratchpad collision caused some agents' output to land in the wrong file. Both problems
are fixed for this pass by working differently:

## Hard rules for this pass

1. **Do NOT call WebSearch or WebFetch at all.** The shared quota is exhausted; calling it will fail or steal
   budget from sibling agents running in parallel. Answer every row from your own trained knowledge only.
2. **Do NOT use any shared/generic temp file path** (no `/tmp/scratch.jsonl`, no shared scratchpad file). Build
   your full output **in memory** as you go, and write it **once, at the end**, using the Write tool, to the
   exact output path you were given in your task prompt. If you must checkpoint partway, use a path that
   embeds your own batch id (given in the task prompt) so it cannot collide with a sibling agent's file.
3. Process **every row** of your input CSV. For a code or name you do not recognize at all, do not guess a
   company — write the row with `sponsor_confidence: "low"` (or omit sponsor/blank) and
   `notes: "not recognized from training data; needs live verification"`. Do not fabricate specifics (trial
   results, dates, deal terms) you are not confident about — leave those fields blank rather than invent them.
4. Because there is no live search, mark every record's provenance honestly: set
   `verification_tier` to `"prior_knowledge"` for everything in this pass (a merge step downstream will use
   this to distinguish these rows from the earlier, web-verified wave). Never claim high confidence you don't
   have; "I recall this being Hengrui's ADC program" is medium at best, not high.

## What you're classifying

Same task as before: for each asset (an internal drug development code like `SHR-A1811`, or an INN/generic
name) that appears as an intervention in ClinicalTrials.gov, determine the sponsor / originating company and
whether it is Chinese (headquartered in mainland China / Hong Kong / Macau, or Chinese-founded with R&D
primarily in China).

## Input CSV columns

asset_key, company_name_seed (a guess from the code prefix — may be wrong or blank), seed_confidence,
inn_from_ot, drug_type_ot, ot_max_stage, raw_names, top_conditions, phases, statuses, n_trials, min_nct,
max_nct, sample_titles, nct_ids, china_title_hits. Use the sample titles / conditions to disambiguate a code
used by more than one company.

## Output: JSONL, one object per line, in your assigned output file

```
asset_key            : copy from input
sponsor              : canonical English company name, or "" if unknown
sponsor_country      : "CN" | "non-CN" | "unknown"
sponsor_confidence   : "high" | "medium" | "low"
sponsor_hq_city      : city if known, else ""
inn_or_name          : INN or common name if known, else ""
other_codes          : other codes/synonyms you recall, pipe-separated, else ""
target               : molecular target(s), e.g. "HER2", "PD-1 x VEGF"; "" if unknown
mechanism            : short mechanism, e.g. "TOP1i ADC", "bispecific antibody"
modality             : small molecule | monoclonal antibody | bispecific/multispecific antibody | ADC | peptide |
                       protein/fusion protein | oligonucleotide | cell therapy | gene therapy | oncolytic virus |
                       vaccine | radiopharmaceutical | biosimilar | TCM/botanical | generic/reformulation |
                       other | unknown
indications          : pipe-separated indications, from memory / from top_conditions in the input
highest_phase        : "preclinical" | "phase 1" | "phase 1/2" | "phase 2" | "phase 2/3" | "phase 3" |
                       "NDA/BLA filed" | "approved (China)" | "approved (US/EU)" |
                       "approved (China + ex-China)" | "unknown"
development_status   : "active" | "discontinued" | "unclear"
ex_china_rights      : "" | "licensed-out" | "partnered" | "retained" | "unknown"
partner              : licensee/partner if you recall one, else ""
latest_data          : 1-2 sentences ONLY if you have specific, confident recall (with rough date). Leave "" if
                       you would be guessing.
first_in_class_note  : "" or a short note if genuinely first/best-in-class
sources              : "" (no live source checked in this pass)
verification_tier    : "prior_knowledge" (always, for this pass)
notes                : anything useful; flag name collisions or low confidence explicitly
```

Only `asset_key`, `sponsor_country`, `sponsor_confidence`, `verification_tier` are mandatory for every row.
Fill the rest only to the extent you actually recall it.

## Method

1. Read your batch CSV (Bash `cat` or the Read tool).
2. Go through rows top to bottom, from memory only.
3. Build the JSONL content in memory; write it once at the end via the Write tool to your exact output path.
4. Verify line count matches input row count, then report: total / CN / non-CN / unknown, and the output path.
