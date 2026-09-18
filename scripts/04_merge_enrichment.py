#!/usr/bin/env python3
"""
Step 4: Merge subagent research results (data/interim/enrichment/results/*.jsonl) with the registry-derived
asset candidates, resolve synonyms (code <-> INN <-> other codes), attach trial-level detail and Open Targets
mechanism data, and write the processed dataset.

Outputs (data/processed/):
  chinese_clinical_assets.csv / .json   one row per Chinese-sponsored asset (entity-resolved)
  chinese_clinical_trials.csv           one row per (asset, ClinicalTrials.gov study)
  asset_classification_all.csv          every candidate asset with its classification + evidence (QA / transparency)
  summary.json                          counts for the README
"""
import json, re, glob, pathlib, collections
import pandas as pd, duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
INTER = ROOT / 'data/interim'; RAW = ROOT / 'data/raw/opentargets_26.06'; PROC = ROOT / 'data/processed'
PROC.mkdir(parents=True, exist_ok=True)

CODE_RE = re.compile(r'(?<![A-Za-z0-9])([A-Za-z]{1,6}[- ]?[A-Za-z]?\d{2,6}[A-Za-z]?\d{0,4}|\d[A-Za-z]{1,3}\d{3,6})(?![A-Za-z0-9])')
def norm_code(s):
    m = CODE_RE.search(s or '')
    return m.group(1).upper().replace(' ', '-') if m else None
def norm_name(s):
    return re.sub(r'\s+', ' ', (s or '').strip().lower())

cand = pd.read_parquet(INTER / 'asset_candidates.parquet')
cand_keys = set(cand.asset_key)

# ---- 1. load research results -------------------------------------------------------------------
CONF = {'high': 3, 'medium': 2, 'low': 1, '': 0, None: 0}
res = {}
n_lines = 0
for f in sorted(glob.glob(str(INTER / 'enrichment/results/*.jsonl'))):
    for line in open(f, encoding='utf-8'):
        line = line.strip()
        if not line: continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        n_lines += 1
        k = r.get('asset_key')
        if not k: continue
        r['_batch'] = pathlib.Path(f).stem
        if k not in res or CONF.get(r.get('sponsor_confidence'), 0) > CONF.get(res[k].get('sponsor_confidence'), 0):
            res[k] = r

# ---- 2. entity resolution: union-find over asset keys ---------------------------------------------
parent = {}
def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb: parent[rb] = ra

con = duckdb.connect()
mol = con.sql(f"select id, name, drugType, maximumClinicalStage, [s.label for s in synonyms] syns from '{RAW}/drug_molecule/*.parquet'").fetchall()
mol_by_id = {m[0]: m for m in mol}
# link via ChEMBL synonyms (OT already unified code<->INN for ChEMBL-known drugs)
for _, row in cand.iterrows():
    k = row.asset_key
    find(k)
    for cid in (row.chembl_ids or '').split('|'):
        m = mol_by_id.get(cid)
        if not m: continue
        for s in [m[1]] + list(m[4] or []):
            for alt in (norm_code(s), norm_name(s)):
                if alt and alt in cand_keys and alt != k:
                    union(k, alt)
# link via research results (inn_or_name, other_codes)
for k, r in res.items():
    if k not in cand_keys: continue
    alts = [r.get('inn_or_name') or ''] + (r.get('other_codes') or '').split('|')
    for s in alts:
        for alt in (norm_code(s), norm_name(s)):
            if alt and alt in cand_keys and alt != k:
                # only merge if the other key is not classified as a different sponsor
                ro = res.get(alt)
                if ro and ro.get('sponsor') and r.get('sponsor') and norm_name(ro['sponsor']) != norm_name(r['sponsor']) and ro.get('sponsor_country') != r.get('sponsor_country'):
                    continue
                union(k, alt)

cand['cluster'] = [find(k) for k in cand.asset_key]

# ---- 3. classification per asset ----------------------------------------------------------------
def classify(row):
    r = res.get(row.asset_key)
    if r:
        c = r.get('sponsor_country') or 'unknown'
        return c, r.get('sponsor') or '', r.get('sponsor_confidence') or '', 'web-research'
    if row.origin_seed == 'cn':
        return 'CN', row.company_name_seed, row.seed_confidence, 'code-prefix-seed (unverified)'
    if row.origin_seed == 'non_cn':
        return 'non-CN', row.company_name_seed, row.seed_confidence, 'code-prefix-seed (unverified)'
    return 'unknown', '', '', 'unclassified'
cls = cand.apply(lambda r: pd.Series(classify(r), index=['sponsor_country', 'sponsor', 'sponsor_confidence', 'classification_basis']), axis=1)
cand = pd.concat([cand, cls], axis=1)
cand.drop(columns=['nct_ids']).to_csv(PROC / 'asset_classification_all.csv', index=False)

# cluster-level: a cluster is Chinese if any member is CN (web-research beats seed)
def cluster_country(g):
    basis_rank = {'web-research': 2, 'code-prefix-seed (unverified)': 1, 'unclassified': 0}
    g = g.assign(rank=g.classification_basis.map(basis_rank) * 10 + g.sponsor_confidence.map(CONF).fillna(0))
    best = g.sort_values('rank', ascending=False).iloc[0]
    return best
best_by_cluster = cand.groupby('cluster', group_keys=False).apply(cluster_country)
cn_clusters = set(best_by_cluster[best_by_cluster.sponsor_country == 'CN'].cluster)

# ---- 4. trial detail + OT mechanism -------------------------------------------------------------
trials = con.sql(f"select nct_id, url, phase, overall_status, study_type, primary_purpose, start_date, brief_title, official_title, why_stopped, intervention_names, conditions from '{INTER}/ctgov_trials.parquet'").df()
trials = trials.set_index('nct_id')
moa = con.sql(f"select actionType, mechanismOfAction, chemblIds, targetName from '{RAW}/drug_mechanism_of_action/*.parquet'").fetchall()
moa_by_chembl = collections.defaultdict(list)
for at, m, ids, tn in moa:
    for cid in ids or []:
        moa_by_chembl[cid].append(f"{m} [{tn}]" if tn else m)

PHASE_LABEL = {0.5: 'early phase 1', 1: 'phase 1', 1.5: 'phase 1/2', 2: 'phase 2', 2.5: 'phase 2/3', 3: 'phase 3', 4: 'phase 4', 0: 'not stated'}
assets_out, trial_rows = [], []
for cl, g in cand[cand.cluster.isin(cn_clusters)].groupby('cluster'):
    keys = list(g.asset_key)
    rs = [res[k] for k in keys if k in res]
    primary = max(rs, key=lambda r: CONF.get(r.get('sponsor_confidence'), 0)) if rs else {}
    ncts = sorted(set(n for s in g.nct_ids for n in s.split('|') if n))
    chembl = sorted(set(c for s in g.chembl_ids for c in s.split('|') if c))
    ot_moa = sorted(set(x for c in chembl for x in moa_by_chembl.get(c, [])))
    ot_names = sorted(set(mol_by_id[c][1] for c in chembl if c in mol_by_id))
    ot_stage = sorted(set(mol_by_id[c][3] for c in chembl if c in mol_by_id and mol_by_id[c][3]))
    ot_type = sorted(set(mol_by_id[c][2] for c in chembl if c in mol_by_id and mol_by_id[c][2]))
    tsub = trials.loc[[n for n in ncts if n in trials.index]]
    phase_rank = g.max_phase_rank.max()
    conds = collections.Counter()
    for cs in tsub.conditions:
        for c in (cs or []):
            if c: conds[c] += 1
    statuses = collections.Counter(tsub.overall_status.fillna('NA'))
    # pick a display name: INN if known, else the code with most trials
    code_keys = [k for k in keys if re.search(r'\d', k)]
    display = (primary.get('inn_or_name') or (ot_names[0].lower() if ot_names else '') or (g.sort_values('n_trials', ascending=False).asset_key.iloc[0]))
    rec = {
        'asset_id': cl,
        'display_name': display,
        'codes_and_names': '|'.join(sorted(set(keys + [x for r in rs for x in (r.get('other_codes') or '').split('|') if x]))),
        'inn': primary.get('inn_or_name') or (ot_names[0].lower() if ot_names else ''),
        'sponsor': primary.get('sponsor') or g.company_name_seed.iloc[0],
        'sponsor_hq_city': primary.get('sponsor_hq_city', ''),
        'sponsor_confidence': primary.get('sponsor_confidence') or g.seed_confidence.iloc[0],
        'classification_basis': 'web-research' if rs else 'code-prefix-seed (unverified)',
        'target': primary.get('target', ''),
        'mechanism': primary.get('mechanism', ''),
        'modality': primary.get('modality', '') or (ot_type[0] if ot_type else ''),
        'ot_mechanism_of_action': ' | '.join(ot_moa),
        'ot_drug_type': '|'.join(ot_type),
        'ot_max_clinical_stage': '|'.join(ot_stage),
        'chembl_ids': '|'.join(chembl),
        'indications_researched': primary.get('indications', ''),
        'conditions_in_trials': ' | '.join(c for c, _ in conds.most_common(10)),
        'highest_phase_researched': primary.get('highest_phase', ''),
        'highest_phase_in_ctgov': PHASE_LABEL.get(phase_rank, 'not stated'),
        'development_status': primary.get('development_status', ''),
        'ex_china_rights': primary.get('ex_china_rights', ''),
        'partner': primary.get('partner', ''),
        'latest_data': primary.get('latest_data', ''),
        'first_in_class_note': primary.get('first_in_class_note', ''),
        'n_trials_ctgov': len(ncts),
        'n_trials_recruiting_or_active': int(sum(v for k, v in statuses.items() if k in ('RECRUITING', 'ACTIVE_NOT_RECRUITING', 'NOT_YET_RECRUITING', 'ENROLLING_BY_INVITATION'))),
        'trial_statuses': json.dumps(statuses),
        'earliest_nct': ncts[0] if ncts else '', 'latest_nct': ncts[-1] if ncts else '',
        'nct_ids': '|'.join(ncts),
        'sources': primary.get('sources', ''),
        'notes': primary.get('notes', ''),
    }
    assets_out.append(rec)
    for n, t in tsub.iterrows():
        trial_rows.append({'asset_id': cl, 'display_name': display, 'nct_id': n, 'phase': t.phase, 'overall_status': t.overall_status,
                           'study_type': t.study_type, 'primary_purpose': t.primary_purpose, 'start_date': t.start_date,
                           'brief_title': t.brief_title, 'official_title': t.official_title, 'why_stopped': t.why_stopped,
                           'interventions': ' | '.join(t.intervention_names or []), 'conditions': ' | '.join(c for c in (t.conditions or []) if c), 'url': t.url})

A = pd.DataFrame(assets_out).sort_values(['sponsor', 'display_name'])
A.to_csv(PROC / 'chinese_clinical_assets.csv', index=False)
T = pd.DataFrame(trial_rows).sort_values(['sponsor' if 'sponsor' in trial_rows[0] else 'asset_id', 'nct_id']) if trial_rows else pd.DataFrame()
T.to_csv(PROC / 'chinese_clinical_trials.csv', index=False)
with open(PROC / 'chinese_clinical_assets.json', 'w', encoding='utf-8') as f:
    tr_by = collections.defaultdict(list)
    for r in trial_rows: tr_by[r['asset_id']].append({k: (str(v) if v is not None else '') for k, v in r.items() if k not in ('asset_id', 'display_name')})
    json.dump([dict(a, trials=tr_by.get(a['asset_id'], [])) for a in assets_out], f, ensure_ascii=False, indent=1, default=str)

summary = {
    'candidate_assets_total': int(len(cand)), 'research_result_lines': n_lines, 'assets_with_research': int(len(res)),
    'classified': cand.sponsor_country.value_counts().to_dict(),
    'chinese_assets_after_entity_resolution': int(len(A)),
    'chinese_assets_by_basis': A.classification_basis.value_counts().to_dict() if len(A) else {},
    'chinese_assets_by_highest_phase_ctgov': A.highest_phase_in_ctgov.value_counts().to_dict() if len(A) else {},
    'chinese_assets_by_modality': A.modality.value_counts().head(20).to_dict() if len(A) else {},
    'top_sponsors': A.sponsor.value_counts().head(40).to_dict() if len(A) else {},
    'chinese_trials_rows': int(len(T)),
}
json.dump(summary, open(PROC / 'summary.json', 'w'), indent=1)
print(json.dumps(summary, indent=1)[:3000])
