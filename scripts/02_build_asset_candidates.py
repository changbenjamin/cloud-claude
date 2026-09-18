#!/usr/bin/env python3
"""
Step 2: Group ClinicalTrials.gov trial x intervention rows into candidate *assets* and apply
the seed drug-code-prefix -> sponsor map to flag likely Chinese-sponsored assets.

Inputs : data/interim/ctgov_trial_interventions.parquet (from step 1)
         data/raw/opentargets_26.06/drug_molecule/*.parquet
         data/reference/code_prefix_map_seed.csv
Outputs: data/interim/asset_candidates.parquet / .csv  (one row per asset key)
"""
import re, csv, json, pathlib, collections
import duckdb, pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
INTER = ROOT / "data/interim"
RAW = ROOT / "data/raw/opentargets_26.06"
REF = ROOT / "data/reference"

CODE_RE = re.compile(r'(?<![A-Za-z0-9])([A-Za-z]{1,6}[- ]?[A-Za-z]?\d{2,6}[A-Za-z]?\d{0,4}|\d[A-Za-z]{1,3}\d{3,6})(?![A-Za-z0-9])')
# tokens that look like codes but are not drug codes
STOP = {'COVID-19','COVID19','SARS-COV-2','CD19','CD20','CD22','CD30','CD33','CD38','CD3','CD4','CD7','CD8','CD123','CD70','CD47','HER2','PD-1','PD-L1','IL-2','IL2','IL-6','IL-17','IL-15','IL-12','IL-1','IL-23','IL-4','IL-13','IL-10','IL-18','IL-21','IL-7','MMR','H1N1','H5N1','H7N9','H3N2','B7-H3','B7H3','CAR-T','CART','TCR','MRD','DNA','RNA','T-CELL','P53','K-RAS','KRAS','G12C','EGFR','ALK','ROS1','FGFR2','FGFR3','HPV16','HPV18','HPV','B12','D3','K2','K1','E2','E1','B6','B1','B2','B3','B5','B9','C3','C5','A1','A2','O2','H2','HIV-1','HIV1','HCV','HBV','HPV9','MAB-1','MAB1','KD','CD19-CAR','BCMA','GD2','NY-ESO-1','TCR-T','AAV9','AAV8','AAV2','AAV5','AAV1','Y-90','Y90','I-131','I131','LU-177','LU177','GA-68','GA68','F-18','F18','TC-99M','TC99M','IN-111','AC-225','AC225','CU-64','CU64','ZR-89','ZR89','RA-223','RA223','C-11','C11','N-13','O-15','SM-153','SR-89','RE-188','PB-212','TH-227','AT-211','BI-213','I-124','I-123','I-125','MG132','H2O2','O3','CO2','NO2','PM2.5','PGE1','PGE2','PGF2','TNF-A','TGF-B','VEGF-A','FVIII','FIX','FVII','FXIII','FX','FXI','FXII','CD3E','MUC1','MUC16','ART-01','T4','T3','TSH','FSH','LH','HCG','GLP-1','GLP1','GLP-2','GIP','PTH','PTH1','IGF-1','IGF1','MRSA','PCV13','PCV20','PCV15','PCV10','MENACWY','DTAP','TDAP','IPV','OPV','MMRV','HEPB','HEPA','VZV','RSV','BCG','MTB','TB','H1','H3','H9','N9','N1','N2','A-Z','V-1','TYPE-2','TYPE2','TYPE-1','TYPE1','GRADE-3','GRADE3','STAGE-3','STAGE3','STAGE-4','STAGE4','STAGE-2','STAGE2','STAGE-1','STAGE1','WEEK-12','DAY-1','DAY1','ARM-1','ARM1','ARM-2','ARM2','COHORT-1','GROUP-1','GROUP1','PHASE-1','PHASE1','PHASE-2','PHASE2','PHASE-3','PHASE3','DOSE-1','LEVEL-1','MG-1','ML-1','CYCLE-1','X-1','X1','X2','X-2','FACTOR-VIII','FACTOR-IX','OMEGA-3','OMEGA3','VITAMIN-D3','VITAMIN-B12','VITAMIN-K2','VITAMIN-C','VITAMIN-E','VITAMIN-A','VIT-D3','CD34','CD56','CD4-T','AB-1','AB1','ETC-1','MAB-2','H-1','HD-1','P-1','P1','P2','P-2','Q-1','R-1','S-1','S1','S-2','T-1','T1','T2','U-1','V1','V2','W-1','Z-1','GEN-1','GEN-2','GEN2','GEN1','G-1','G1','G2','G-2','M-1','M1','M2','M-2','N-1','L-1','L1','L2','L-2','K-1','J-1','I-1','F-1','F1','F2','E-1','D-1','D1','D2','D-2','C-1','C1','C2','C-2','B-1','B-2','A-1','A-2','0-1','1-1','2-1','3-1','4-1'}

def extract_code(name: str):
    if not name:
        return None
    for m in CODE_RE.finditer(name):
        tok = m.group(1).upper().replace(' ', '-')
        if tok in STOP or re.fullmatch(r'\d+', tok):
            continue
        # skip pure disease/target-like tokens
        if re.fullmatch(r'(CD|IL|HER|PD|TNF|TGF|VEGF|FGFR|HPV|AAV|CAR)-?\d+[A-Z]?', tok):
            continue
        if re.fullmatch(r'[A-Z]\d', tok):  # e.g. B2, D3
            continue
        return tok
    return None

def norm_name(name: str):
    n = (name or '').strip().lower()
    n = re.sub(r'\s+', ' ', n)
    n = re.sub(r'\b(injection|tablets?|capsules?|for injection|solution|oral|iv|intravenous|subcutaneous|sc)\b', '', n).strip(' ,;-')
    return n

con = duckdb.connect()
rows = con.sql(f"""
    select nct_id, intervention_name, chembl_id, phase, overall_status, study_type, primary_purpose,
           start_date, brief_title, official_title, why_stopped, conditions
    from '{INTER}/ctgov_trial_interventions.parquet'
""").fetchall()

# seed prefix map
seed = []
with open(REF / 'code_prefix_map_seed.csv', newline='') as f:
    for r in csv.DictReader(f):
        seed.append((re.compile(r['regex']), r))

def classify(code):
    if not code:
        return None
    for rx, r in seed:
        if rx.search(code):
            return r
    return None

PHASE_RANK = {'EARLY_PHASE1': 0.5, 'PHASE1': 1, 'PHASE1/PHASE2': 1.5, 'PHASE2': 2, 'PHASE2/PHASE3': 2.5, 'PHASE3': 3, 'PHASE4': 4}

assets = {}
for (nct, name, chembl, phase, status, stype, purpose, start, btitle, otitle, why, conds) in rows:
    code = extract_code(name)
    key = code if code else norm_name(name)
    if not key:
        continue
    a = assets.setdefault(key, {
        'asset_key': key, 'is_code': bool(code), 'raw_names': collections.Counter(), 'chembl_ids': set(),
        'trials': set(), 'phases': collections.Counter(), 'statuses': collections.Counter(),
        'conditions': collections.Counter(), 'titles': [], 'china_title_hits': 0, 'why_stopped': [],
        'study_types': collections.Counter(), 'max_phase_rank': 0.0, 'min_nct': None, 'max_nct': None,
    })
    a['raw_names'][name] += 1
    if chembl: a['chembl_ids'].add(chembl)
    a['trials'].add(nct)
    a['phases'][phase or 'NA'] += 1
    a['statuses'][status or 'NA'] += 1
    a['study_types'][stype or 'NA'] += 1
    for c in (conds or []):
        if c: a['conditions'][c] += 1
    t = (btitle or otitle or '')
    if len(a['titles']) < 3: a['titles'].append(t)
    if re.search(r'\bchin(a|ese)\b', (t + ' ' + (otitle or '')), re.I): a['china_title_hits'] += 1
    if why and len(a['why_stopped']) < 3: a['why_stopped'].append(why)
    a['max_phase_rank'] = max(a['max_phase_rank'], PHASE_RANK.get(phase or '', 0))
    a['min_nct'] = min(a['min_nct'] or nct, nct)
    a['max_nct'] = max(a['max_nct'] or nct, nct)

# OT drug_molecule lookup (chembl_id -> name/type/stage/synonyms)
mol = con.sql(f"""
    select id, name, drugType, maximumClinicalStage, [s.label for s in synonyms] syns
    from '{RAW}/drug_molecule/*.parquet'
""").fetchall()
mol_by_id = {m[0]: m for m in mol}

out = []
for key, a in assets.items():
    seedrow = classify(key if a['is_code'] else None)
    # if not code, try to find a code in the OT synonyms of any linked ChEMBL molecule
    syn_code = None
    inn = None; dtype = None; ot_stage = None
    for cid in a['chembl_ids']:
        m = mol_by_id.get(cid)
        if not m: continue
        inn = inn or m[1]; dtype = dtype or m[2]; ot_stage = ot_stage or m[3]
        for s in (m[4] or []):
            c = extract_code(s)
            if c and classify(c):
                syn_code = c; break
        if syn_code: break
    if not seedrow and syn_code:
        seedrow = classify(syn_code)
    origin = seedrow['origin'] if seedrow else 'unknown'
    out.append({
        'asset_key': key,
        'is_code': a['is_code'],
        'origin_seed': origin,
        'company_key_seed': seedrow['company_key'] if seedrow else '',
        'company_name_seed': seedrow['company_name'] if seedrow else '',
        'seed_confidence': seedrow['confidence'] if seedrow else '',
        'seed_via_synonym': syn_code or '',
        'inn_from_ot': inn or '',
        'drug_type_ot': dtype or '',
        'ot_max_stage': ot_stage or '',
        'chembl_ids': '|'.join(sorted(a['chembl_ids'])),
        'n_trials': len(a['trials']),
        'n_trials_nct04plus': sum(1 for t in a['trials'] if t >= 'NCT04'),
        'n_trials_nct06plus': sum(1 for t in a['trials'] if t >= 'NCT06'),
        'max_phase_rank': a['max_phase_rank'],
        'phases': json.dumps(a['phases']),
        'statuses': json.dumps(a['statuses']),
        'study_types': json.dumps(a['study_types']),
        'top_conditions': ' | '.join(c for c, _ in a['conditions'].most_common(6)),
        'raw_names': ' | '.join(n for n, _ in a['raw_names'].most_common(5)),
        'sample_titles': ' || '.join(a['titles']),
        'china_title_hits': a['china_title_hits'],
        'why_stopped_sample': ' || '.join(a['why_stopped']),
        'min_nct': a['min_nct'], 'max_nct': a['max_nct'],
        'nct_ids': '|'.join(sorted(a['trials'])),
    })

df = pd.DataFrame(out)
df.to_parquet(INTER / 'asset_candidates.parquet', index=False)
df.drop(columns=['nct_ids']).to_csv(INTER / 'asset_candidates_summary.csv', index=False)
print("assets:", len(df), "| code-like:", int(df.is_code.sum()))
print(df.groupby('origin_seed').size())
recent = df[df.n_trials_nct04plus > 0]
print("assets with NCT04+ trials:", len(recent))
print(recent.groupby('origin_seed').size())
print("code-like unknown with NCT04+:", int(((recent.origin_seed == 'unknown') & recent.is_code).sum()))
print("non-code unknown with NCT04+:", int(((recent.origin_seed == 'unknown') & ~recent.is_code).sum()))
print("cn seed assets by confidence:\n", df[df.origin_seed == 'cn'].groupby('seed_confidence').size())
print("cn seed assets by company (top 40):\n", df[df.origin_seed == 'cn'].groupby('company_name_seed').size().sort_values(ascending=False).head(40))
