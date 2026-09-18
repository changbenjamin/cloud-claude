#!/usr/bin/env python3
"""
Step 1: Explode the Open Targets 26.06 `clinical_report` table (AACT/ClinicalTrials.gov derived)
into one row per (trial, intervention), and aggregate per normalized intervention name.

Inputs : data/raw/opentargets_26.06/clinical_report/*.parquet
Outputs: data/interim/ctgov_trial_interventions.parquet   (trial x intervention rows)
         data/interim/ctgov_trials.parquet                (one row per trial)
"""
import re, duckdb, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/opentargets_26.06"
OUT = ROOT / "data/interim"
OUT.mkdir(parents=True, exist_ok=True)

con = duckdb.connect()
con.sql(f"""
CREATE OR REPLACE TABLE trials AS
SELECT upper(id) AS nct_id,
       url,
       coalesce(trialPhase, phaseFromSource) AS phase,
       clinicalStage AS clinical_stage,
       trialOverallStatus AS overall_status,
       trialStudyType AS study_type,
       trialPrimaryPurpose AS primary_purpose,
       trialNumberOfArms AS n_arms,
       trialStartDate AS start_date,
       title AS brief_title,
       trialOfficialTitle AS official_title,
       trialDescription AS description,
       trialWhyStopped AS why_stopped,
       trialStopReasonCategories AS stop_reason_categories,
       hasExpertReview AS has_expert_review,
       qualityControls AS quality_controls,
       drugs, diseases
FROM read_parquet('{RAW}/clinical_report/*.parquet')
WHERE source = 'AACT'
""")
con.sql(f"COPY (SELECT * EXCLUDE (drugs, diseases), [d.drugFromSource for d in drugs] AS intervention_names, [d.drugId for d in drugs] AS chembl_ids, [x.diseaseFromSource for x in diseases] AS conditions, [x.diseaseId for x in diseases] AS disease_ids FROM trials) TO '{OUT}/ctgov_trials.parquet' (FORMAT PARQUET)")

con.sql(f"""
COPY (
  SELECT t.nct_id, t.phase, t.clinical_stage, t.overall_status, t.study_type, t.primary_purpose, t.start_date,
         t.brief_title, t.official_title, t.why_stopped,
         d.drugFromSource AS intervention_name, d.drugId AS chembl_id,
         [x.diseaseFromSource for x in t.diseases] AS conditions,
         [x.diseaseId for x in t.diseases] AS disease_ids
  FROM trials t, unnest(t.drugs) AS u(d)
) TO '{OUT}/ctgov_trial_interventions.parquet' (FORMAT PARQUET)
""")
n1 = con.sql(f"select count(*) from '{OUT}/ctgov_trials.parquet'").fetchone()[0]
n2 = con.sql(f"select count(*) from '{OUT}/ctgov_trial_interventions.parquet'").fetchone()[0]
print(f"trials={n1} trial_x_intervention={n2}")
