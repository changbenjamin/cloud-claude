#!/usr/bin/env python3
"""
Step 3: Split candidate assets into batches for web-research subagents.
Tiers:
  A  = seed-classified Chinese assets (enrich)                 batch size 60
  B1 = unknown code-like assets with a trial registered NCT05+ batch size 90
  C  = unknown non-code assets that look Chinese-originated (China in title, 'recombinant ... injection' style names,
       INN-like names with phase 1-3 stage or no ChEMBL link)  batch size 90
  B2 = unknown code-like assets whose newest trial is NCT04    batch size 90
"""
import pandas as pd, re, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
INTER = ROOT / 'data/interim'
BD = INTER / 'enrichment/batches'; BD.mkdir(parents=True, exist_ok=True)
df = pd.read_parquet(INTER / 'asset_candidates.parquet')
df['cn_style_name'] = df.raw_names.str.lower().str.contains(r'\brecombinant\b', regex=True) | df.raw_names.str.lower().str.contains('injection', regex=False)
stems = 'mab|nib|tide|cel|gene|vec|ase|stat|parin|tercept|relin|orsen|siran|leucel|cabtagene|vir|mer'
inn_like = df.asset_key.str.match(r'^[a-z]+(' + stems + r')$')
ph = ['PHASE_1','PHASE_2','PHASE_3','PHASE_1_2','PHASE_2_3','EARLY_PHASE_1','']
unk = df.origin_seed == 'unknown'
tiers = {
  'A':  df[df.origin_seed == 'cn'].sort_values(['n_trials_nct04plus','n_trials'], ascending=False),
  'B1': df[unk & df.is_code & (df.max_nct >= 'NCT05')].sort_values('n_trials', ascending=False),
  'C':  df[unk & ~df.is_code & (df.max_nct >= 'NCT04') & ((df.china_title_hits > 0) | df.cn_style_name | (inn_like & df.ot_max_stage.isin(ph)))].sort_values('n_trials', ascending=False),
  'B2': df[unk & df.is_code & (df.max_nct >= 'NCT04') & (df.max_nct < 'NCT05')].sort_values('n_trials', ascending=False),
}
sizes = {'A': 60, 'B1': 90, 'C': 90, 'B2': 90}
cols = ['asset_key','company_name_seed','seed_confidence','inn_from_ot','drug_type_ot','ot_max_stage','raw_names','top_conditions','phases','statuses','n_trials','min_nct','max_nct','sample_titles','nct_ids','china_title_hits']
manifest = []
for tier, t in tiers.items():
    t = t.copy()
    t['sample_titles'] = t.sample_titles.str.slice(0, 350)
    t['nct_ids'] = t.nct_ids.apply(lambda s: '|'.join(s.split('|')[:6]))
    t['raw_names'] = t.raw_names.str.slice(0, 200)
    n = sizes[tier]
    for i in range(0, len(t), n):
        bid = f"{tier}_{i//n+1:03d}"
        chunk = t.iloc[i:i+n][cols]
        chunk.to_csv(BD / f"{bid}.csv", index=False)
        manifest.append({'batch_id': bid, 'tier': tier, 'n_assets': len(chunk), 'file': str((BD / f'{bid}.csv').relative_to(ROOT))})
json.dump(manifest, open(INTER / 'enrichment/manifest.json', 'w'), indent=1)
import collections
print({k: len(v) for k, v in tiers.items()}, 'batches:', collections.Counter(m['tier'] for m in manifest))
