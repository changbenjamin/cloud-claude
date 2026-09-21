#!/usr/bin/env python3
"""
Step 5 (final): Build the finished Chinese clinical-stage asset dataset from Tier A research results.

Tier A = the 1,937 candidate assets whose ClinicalTrials.gov intervention code matched the seed
code-prefix map as Chinese-sponsored (data/reference/code_prefix_map_seed.csv). Every one of these
1,937 assets was independently reviewed by a research subagent (298 via live WebSearch = "web_verified",
1,639 from the model's trained knowledge only = "prior_knowledge", after the WebSearch budget for this
session was exhausted). Agents were told to correct the seed guess whenever their own knowledge disagreed,
so the sponsor/country in each research record already reflects those corrections, not the raw seed.

This script:
  1. Builds one research record per asset_key (preferring web_verified over prior_knowledge, then higher
     confidence, then more populated fields) from data/interim/enrichment/results/ + results_pk/.
  2. Keeps only assets classified sponsor_country == "CN".
  3. Entity-resolves duplicate codes / INN names of the same drug into one row (union-find over shared
     ChEMBL id, explicit inn_or_name / other_codes claims, and asset_key substring-normalized match),
     refusing to merge across two different confidently-identified sponsors.
  4. Canonicalizes sponsor company names (spelling/casing variants -> one canonical name).
  5. Normalizes modality and highest_phase to a controlled vocabulary.
  6. Attaches ClinicalTrials.gov trial-level detail (phase, status, dates, titles) and Open Targets
     drug/mechanism data for every underlying NCT id and ChEMBL id in the cluster.
  7. Writes data/processed/chinese_clinical_assets.csv/.json, chinese_clinical_trials.csv, and summary.json.

Every asset row carries `verification_tier` (web_verified | prior_knowledge) and `sponsor_confidence`,
so a reader can immediately see how much to trust each row. See data/processed/README.md for the full
methodology and known limitations.
"""
import json, re, glob, csv, collections, pathlib
import pandas as pd, duckdb

ROOT = pathlib.Path(__file__).resolve().parents[1]
INTER = ROOT / 'data/interim'; RAW = ROOT / 'data/raw/opentargets_26.06'; PROC = ROOT / 'data/processed'
PROC.mkdir(parents=True, exist_ok=True)

CONF = {'high': 3, 'medium': 2, 'low': 1, '': 0, None: 0}
CODE_RE = re.compile(r'(?<![A-Za-z0-9])([A-Za-z]{1,6}[- ]?[A-Za-z]?\d{2,6}[A-Za-z]?\d{0,4}|\d[A-Za-z]{1,3}\d{3,6})(?![A-Za-z0-9])')

def norm_code(s):
    m = CODE_RE.search(s or '')
    return m.group(1).upper().replace(' ', '-').replace('_', '-') if m else None

def norm_name(s):
    return re.sub(r'\s+', ' ', (s or '').strip().lower())

# ---------------------------------------------------------------------------------------------------
# 1. Unify research results (results/ = wave 1 web-research, results_pk/ = wave 2 prior-knowledge)
# ---------------------------------------------------------------------------------------------------
res = {}
n_lines = 0
for d in ['results', 'results_pk']:
    for f in glob.glob(str(INTER / f'enrichment/{d}/*.jsonl')):
        for line in open(f, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            n_lines += 1
            try:
                r = json.loads(line)
            except Exception:
                continue
            k = r.get('asset_key')
            if not k:
                continue
            src = (r.get('sources') or '').strip()
            # A record only counts as web_verified if it actually cites a URL. Records where the wave-1
            # agent ran out of WebSearch budget mid-batch and fell back to memory (empty sources) are
            # treated as prior_knowledge regardless of which directory they live in.
            r['_tier'] = 'web_verified' if ('http' in src) else 'prior_knowledge'
            def score(rec):
                return (1 if rec['_tier'] == 'web_verified' else 0, CONF.get(rec.get('sponsor_confidence'), 0),
                        sum(1 for v in rec.values() if v))
            if k not in res or score(r) > score(res[k]):
                res[k] = r

cn = {k: r for k, r in res.items() if r.get('sponsor_country') == 'CN'}
print(f"research records: {n_lines} lines -> {len(res)} unique assets -> {len(cn)} classified CN")

# ---------------------------------------------------------------------------------------------------
# 2. Sponsor name canonicalization
# ---------------------------------------------------------------------------------------------------
CANON = [
    (r'beigene|beone', 'BeiGene (BeOne Medicines)'),
    (r'hengrui', 'Jiangsu Hengrui Pharmaceuticals'),
    (r'chia\s*tai\s*tianqing|\bcttq\b|sino\s*biopharm', 'Chia Tai Tianqing (Sino Biopharmaceutical)'),
    (r'innovent', 'Innovent Biologics'),
    (r'\bakeso\b', 'Akeso'),
    (r'qilu', 'Qilu Pharmaceutical'),
    (r'henlius', 'Shanghai Henlius Biotech'),
    (r'hansoh', 'Hansoh Pharma'),
    (r'\bcspc\b', 'CSPC Pharmaceutical'),
    (r'junshi', 'Shanghai Junshi Biosciences'),
    (r'cstone', 'CStone Pharmaceuticals'),
    (r'hutchmed|hutchison\s*medi', 'HUTCHMED'),
    (r'haisco', 'Haisco Pharmaceutical'),
    (r'simcere', 'Simcere Zaiming'),
    (r'sinocelltech', 'Sinocelltech'),
    (r'remegen', 'RemeGen'),
    (r'jemincare', 'Jemincare'),
    (r'alebund|anpu\s*pharma', 'Alebund Pharmaceuticals'),
    (r'alphamab', 'Alphamab Oncology'),
    (r'\bbiocity\b', 'BioCity Biopharma'),
    (r'genescience|changchun\s*high', 'GeneScience (Changchun High-Tech)'),
    (r'genor', 'Genor Biopharma'),
    (r'lanova', 'LaNova Medicines'),
    (r'shouyao', 'Shouyao Holdings'),
    (r'huabo|huaota', 'Huabo Biopharm (Huaota)'),
    (r'immuneonco', 'ImmuneOnco'),
    (r'mabwell', 'Mabwell'),
    (r'ascletis', 'Ascletis Pharma'),
    (r'kanghong', 'Chengdu Kanghong'),
    (r'ascentage', 'Ascentage Pharma'),
    (r'carsgen', 'CARsgen Therapeutics'),
    (r'genrix', 'Genrix Bio'),
    (r'\bi-?mab\b', 'I-Mab'),
    (r'kelun-?biotech|kelun\s*biotech', 'Kelun-Biotech'),
    (r'baili-?bio|systimmune', 'Baili-Bio / SystImmune'),
    (r'bio-?thera', 'Bio-Thera Solutions'),
    (r'\b3sbio\b|sunshine\s*guojian', '3SBio'),
    (r'keymed', 'Keymed Biosciences'),
    (r'hec\s*pharm|sunshine\s*lake', 'HEC Pharm (Sunshine Lake)'),
    (r'betta', 'Betta Pharmaceuticals'),
    (r'duality\s*bio', 'Duality Biologics'),
    (r'zelgen', 'Suzhou Zelgen'),
    (r'miracogen', 'Shanghai Miracogen (Lepu)'),
    (r'medilink', 'MediLink Therapeutics'),
    (r'harbour\s*bio', 'Harbour BioMed'),
    (r'biotheus', 'Biotheus'),
    (r'abbisko', 'Abbisko Therapeutics'),
    (r'innocare', 'InnoCare Pharma'),
    (r'jacobio', 'Jacobio Pharma'),
    (r'inventisbio', 'InventisBio'),
    (r'fochon', 'Fochon Pharmaceuticals'),
    (r'transthera', 'TransThera Sciences'),
    (r'elpiscience', 'Elpiscience'),
    (r'evopoint', 'Evopoint Biosciences'),
    (r'gan\s*&\s*lee|ganlee', 'Gan & Lee Pharmaceuticals'),
    (r'sciwind', 'Sciwind Biosciences'),
    (r'dizal', 'Dizal Pharmaceutical'),
    (r'regor', 'Regor Therapeutics'),
    (r'luye', 'Luye Pharma'),
    (r'allist', 'Allist Pharmaceuticals'),
    (r'kintor', 'Kintor Pharmaceutical'),
    (r'genfleet', 'GenFleet Therapeutics'),
    (r'xuanzhu', 'Xuanzhu Biopharma'),
    (r'brii\s*bio', 'Brii Biosciences'),
    (r'belite', 'Belite Bio'),
    (r'ribo\s*life|suzhou\s*ribo', 'Suzhou Ribo Life Science'),
    (r'sirnaomics', 'Sirnaomics'),
    (r'argo\s*bio', 'Argo Biopharma'),
    (r'legend\s*bio', 'Legend Biotech'),
    (r'clover\s*bio', 'Clover Biopharmaceuticals'),
    (r'recbio', 'Jiangsu Recbio'),
    (r'ablbio', 'ABL Bio'),
    (r'zhongsheng|raynovent', 'Guangdong Zhongsheng (Raynovent)'),
    (r'\bkbp\b', 'KBP Biosciences'),
    (r'hinova', 'Hinova Pharmaceuticals'),
    (r'minghui', 'Minghui Pharmaceutical'),
    (r'leads\s*biolabs', 'Leads Biolabs'),
    (r'everest\s*medi', 'Everest Medicines'),
    (r'antengene', 'Antengene'),
    (r'shanghai\s*pharma', 'Shanghai Pharmaceuticals'),
    (r'haihe', 'Haihe Biopharma'),
    (r'askgene', 'AskGene Pharma'),
    (r'aosaikang', 'Jiangsu Aosaikang Pharmaceutical'),
    (r'advenchen', 'Advenchen Laboratories'),
    (r'\bhitgen\b', 'HitGen'),
    (r'huidagene', 'HuidaGene Therapeutics'),
    (r'gracell', 'Gracell Biotechnologies (AstraZeneca)'),
    (r'iaso\s*bio', 'IASO Biotherapeutics'),
    (r'\bjw\s*(therapeutics|bio)', 'JW Therapeutics'),
    (r'immunochina', 'Immunochina'),
    (r'juventas', 'Juventas Cell Therapy'),
    (r'coherent\s*bio', 'Coherent Biopharma'),
    (r'connect\s*bio', 'Connect Biopharma'),
    (r'huadong', 'Huadong Medicine'),
    (r'united\s*laboratories', 'The United Laboratories'),
    (r'salubris', 'Salubris Biotherapeutics'),
    (r'ascletis', 'Ascletis Pharma'),
    (r'bebetter', 'BeBetter Medicine'),
    (r'kechow', 'Kechow Pharma'),
    (r'\bzai\s*lab\b', 'Zai Lab'),
    (r'\bdualitybio\b', 'Duality Biologics'),
    (r'escugen', 'Escugen Biotechnology'),
    (r'qyuns', 'Qyuns Therapeutics'),
    (r'genequantum', 'GeneQuantum Healthcare'),
    (r'zhejiang\s*doer|doer\s*bio', 'Zhejiang Doer Biologics'),
    (r'bioray', 'Bioray Laboratories'),
    (r'anhui\s*zhifei|zhifei\s*longcom', 'Anhui Zhifei Longcom'),
    (r'epimab', 'EpimAb Biotherapeutics'),
    (r'mabspace|transcenta', 'Transcenta'),
    (r'immvira', 'ImmVira'),
    (r'virogin', 'Virogin Biotech'),
    (r'wuhan\s*binhui|binhui\s*bio', 'Wuhan Binhui Biotechnology'),
    (r'gloria\s*bio|harbin\s*gloria', 'Harbin Gloria Pharmaceuticals'),
    (r'\bhec88\b|hec\s*pharm', 'HEC Pharm (Sunshine Lake)'),
    (r'apogee', 'Apogee Therapeutics'),
    (r'allakos', 'Allakos'),
    (r'sagimet', 'Sagimet Biosciences'),
    (r'syros', 'Syros Pharmaceuticals'),
    (r'bergenbio', 'BerGenBio'),
    (r'celltrion', 'Celltrion'),
    (r'daiichi\s*sankyo', 'Daiichi Sankyo'),
    (r'\bnovartis\b', 'Novartis'),
    (r'\balcon\b', 'Alcon'),
    (r'crispr\s*therapeutics', 'CRISPR Therapeutics'),
    (r'anacor', 'Anacor Pharmaceuticals'),
    (r'bioline-?rx', 'BioLineRx'),
    (r'recursion', 'Recursion Pharmaceuticals'),
    (r'us\s*worldmeds', 'US WorldMeds'),
]
CANON = [(re.compile(p, re.I), n) for p, n in CANON]

def canonicalize(name):
    if not name:
        return name
    for rx, canon in CANON:
        if rx.search(name):
            return canon
    return name.strip()

MODALITY_MAP = {
    'small molecule': 'small molecule', 'monoclonal antibody': 'monoclonal antibody', 'antibody': 'monoclonal antibody',
    'bispecific/multispecific antibody': 'bispecific/multispecific antibody', 'bispecific antibody': 'bispecific/multispecific antibody',
    'bispecific': 'bispecific/multispecific antibody', 'multispecific antibody': 'bispecific/multispecific antibody',
    'adc': 'ADC', 'antibody drug conjugate': 'ADC', 'antibody-drug conjugate': 'ADC',
    'peptide': 'peptide', 'protein/fusion protein': 'protein/fusion protein', 'fusion protein': 'protein/fusion protein',
    'protein': 'protein/fusion protein', 'oligonucleotide': 'oligonucleotide', 'sirna': 'oligonucleotide', 'asо': 'oligonucleotide',
    'cell therapy': 'cell therapy', 'car-t': 'cell therapy', 'cart': 'cell therapy',
    'gene therapy': 'gene therapy', 'aav': 'gene therapy', 'oncolytic virus': 'oncolytic virus',
    'vaccine': 'vaccine', 'radiopharmaceutical': 'radiopharmaceutical', 'radioligand': 'radiopharmaceutical',
    'biosimilar': 'biosimilar', 'tcm/botanical': 'TCM/botanical', 'generic/reformulation': 'generic/reformulation',
    'generic': 'generic/reformulation',
}

MODALITY_VOCAB = ['small molecule', 'bispecific/multispecific antibody', 'monoclonal antibody', 'ADC',
                   'peptide', 'protein/fusion protein', 'oligonucleotide', 'cell therapy', 'gene therapy',
                   'oncolytic virus', 'vaccine', 'radiopharmaceutical', 'biosimilar', 'TCM/botanical',
                   'generic/reformulation']

def norm_modality(m, ot_type=''):
    m = (m or '').strip().lower()
    if m in MODALITY_MAP:
        return MODALITY_MAP[m]
    if len(m) <= 40:
        for canon in MODALITY_VOCAB:
            if canon.lower() in m:
                return canon
    elif m:
        # a long free-text string (an agent's hedge/tentative note) rather than a controlled-vocab value
        for canon in MODALITY_VOCAB:
            if canon.lower() in m:
                return canon
        return 'unknown'
    ot = (ot_type or '').strip().lower()
    return MODALITY_MAP.get(ot, ot if ot else 'unknown')

PHASE_MAP = {
    'preclinical': 'preclinical', 'ind-enabling': 'preclinical', 'early phase 1': 'early phase 1',
    'phase 1': 'phase 1', 'phase i': 'phase 1', 'phase 1/2': 'phase 1/2', 'phase i/ii': 'phase 1/2',
    'phase 2': 'phase 2', 'phase ii': 'phase 2', 'phase 2/3': 'phase 2/3', 'phase ii/iii': 'phase 2/3',
    'phase 3': 'phase 3', 'phase iii': 'phase 3', 'nda/bla filed': 'NDA/BLA filed',
    'approved (china)': 'approved (China)', 'approved (us/eu)': 'approved (US/EU)',
    'approved (china + ex-china)': 'approved (China + ex-China)',
}
# ordered so the more specific phrase (e.g. "phase 1/2") is checked before its substring ("phase 1")
PHASE_VOCAB_ORDER = ['approved (china + ex-china)', 'approved (china)', 'approved (us/eu)', 'nda/bla filed',
                      'phase 2/3', 'phase ii/iii', 'phase 1/2', 'phase i/ii', 'phase 3', 'phase iii',
                      'phase 2', 'phase ii', 'early phase 1', 'phase 1', 'phase i', 'preclinical']

def norm_phase(p):
    p = (p or '').strip().lower()
    if not p:
        return 'unknown'
    if p in PHASE_MAP:
        return PHASE_MAP[p]
    if len(p) <= 40:
        for v in PHASE_VOCAB_ORDER:
            if v in p:
                return PHASE_MAP[v]
        return p
    for v in PHASE_VOCAB_ORDER:
        if v in p:
            return PHASE_MAP[v]
    return 'unknown'

con = duckdb.connect()
cand = pd.read_parquet(INTER / 'asset_candidates.parquet').set_index('asset_key')

# ---------------------------------------------------------------------------------------------------
# 3. Entity resolution: merge duplicate codes/INN for the same sponsor into one cluster
# ---------------------------------------------------------------------------------------------------
parent = {}
def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[rb] = ra

keys = list(cn.keys())
for k in keys:
    find(k)
norm_sponsor_of = {k: canonicalize(cn[k].get('sponsor', '')) for k in keys}
key_by_norm = collections.defaultdict(list)
for k in keys:
    key_by_norm[norm_name(k)].append(k)

for k, r in cn.items():
    candidates = [r.get('inn_or_name') or ''] + [c for c in (r.get('other_codes') or '').split('|') if c]
    for c in candidates:
        for alt in (norm_code(c), norm_name(c)):
            if alt and alt in cn and alt != k:
                sa, sb = norm_sponsor_of[k], norm_sponsor_of[alt]
                if sa and sb and sa != sb:
                    continue  # different confidently-named sponsors -> do not merge, likely a code collision
                union(k, alt)

clusters = collections.defaultdict(list)
for k in keys:
    clusters[find(k)].append(k)
print(f"entity resolution pass 1 (explicit synonym claims): {len(keys)} keys -> {len(clusters)} clusters")

# pass 2: two keys under the same canonical sponsor whose ClinicalTrials.gov trial sets are near-identical
# are almost certainly the same drug under a code name vs an INN (e.g. AK112 / ivonescimab) that the
# research agents never explicitly cross-referenced. Merge on >=70% Jaccard overlap of NCT ids.
nct_sets = {k: set((cand.loc[k, 'nct_ids'] or '').split('|')) - {''} for k in keys if k in cand.index}
by_sponsor = collections.defaultdict(list)
for k in keys:
    if k in nct_sets and nct_sets[k]:
        by_sponsor[norm_sponsor_of[k]].append(k)
merged_pairs = 0
for sponsor, ks in by_sponsor.items():
    if not sponsor or len(ks) < 2:
        continue
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            a, b = ks[i], ks[j]
            if find(a) == find(b):
                continue
            sa, sb = nct_sets[a], nct_sets[b]
            inter = len(sa & sb)
            union_sz = len(sa | sb)
            if union_sz and inter / union_sz >= 0.7:
                union(a, b)
                merged_pairs += 1

clusters = collections.defaultdict(list)
for k in keys:
    clusters[find(k)].append(k)
print(f"entity resolution pass 2 (shared-trial-set, same sponsor): merged {merged_pairs} more pairs -> {len(clusters)} clusters")

# pass 3: two keys that are the exact same code once hyphens/spaces are stripped (e.g. "SHR-2554" vs
# "SHR2554") are the same asset by construction.
def dehyphenate(k):
    return re.sub(r'[\s\-_]', '', k).upper()
by_dehyph = collections.defaultdict(list)
for k in keys:
    by_dehyph[dehyphenate(k)].append(k)
merged_p3 = 0
for dk, ks in by_dehyph.items():
    if len(ks) < 2:
        continue
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            a, b = ks[i], ks[j]
            if find(a) == find(b):
                continue
            sa, sb = norm_sponsor_of[a], norm_sponsor_of[b]
            if sa and sb and sa != sb:
                continue
            union(a, b)
            merged_p3 += 1

# pass 4: fuzzy name match among same-sponsor, non-code (free-text) keys, e.g. "docetaxel polymeric
# micelles" vs "docetaxel polymer micelles" describing the same formulation from the same company.
from rapidfuzz import fuzz
clusters = collections.defaultdict(list)
for k in keys:
    clusters[find(k)].append(k)
name_keys_by_sponsor = collections.defaultdict(list)
for k in keys:
    if not norm_code(k) and norm_sponsor_of[k]:
        name_keys_by_sponsor[norm_sponsor_of[k]].append(k)
merged_p4 = 0
for sponsor, ks in name_keys_by_sponsor.items():
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            a, b = ks[i], ks[j]
            if find(a) == find(b):
                continue
            if fuzz.token_sort_ratio(a, b) >= 90:
                union(a, b)
                merged_p4 += 1

clusters = collections.defaultdict(list)
for k in keys:
    clusters[find(k)].append(k)
print(f"entity resolution pass 3 (dehyphenated code match): merged {merged_p3} pairs; "
      f"pass 4 (fuzzy name match, same sponsor): merged {merged_p4} pairs -> {len(clusters)} final clusters")

# ---------------------------------------------------------------------------------------------------
# 4. Attach ClinicalTrials.gov trial detail + Open Targets mechanism data
# ---------------------------------------------------------------------------------------------------
trials = con.sql(f"select nct_id, url, phase, overall_status, study_type, primary_purpose, start_date, "
                  f"brief_title, official_title, why_stopped, intervention_names, conditions "
                  f"from '{INTER}/ctgov_trials.parquet'").df().set_index('nct_id')
mol = con.sql(f"select id, name, drugType, maximumClinicalStage, [s.label for s in synonyms] syns "
              f"from '{RAW}/drug_molecule/*.parquet'").fetchall()
mol_by_id = {m[0]: m for m in mol}
moa = con.sql(f"select chemblIds, mechanismOfAction, targetName from '{RAW}/drug_mechanism_of_action/*.parquet'").fetchall()
moa_by_chembl = collections.defaultdict(list)
for ids, m, tn in moa:
    for cid in ids or []:
        moa_by_chembl[cid].append(f"{m} [{tn}]" if tn else m)

def aslist(x):
    if x is None:
        return []
    try:
        if x is pd.NA:
            return []
    except Exception:
        pass
    try:
        return [v for v in list(x) if v is not None]
    except TypeError:
        return []

PHASE_RANK = {'unknown': -2, 'not stated': -1, 'preclinical': 0, 'early phase 1': 0.5, 'phase 1': 1,
              'phase 1/2': 1.5, 'phase 2': 2, 'phase 2/3': 2.5, 'phase 3': 3, 'NDA/BLA filed': 3.5,
              'approved (China)': 4, 'approved (US/EU)': 4, 'approved (China + ex-China)': 4}
CTGOV_PHASE_LABEL = {0.5: 'early phase 1', 1: 'phase 1', 1.5: 'phase 1/2', 2: 'phase 2', 2.5: 'phase 2/3',
                      3: 'phase 3', 4: 'phase 4', 0: 'not stated'}

rows_out, trial_rows = [], []
for cl, member_keys in clusters.items():
    members = [cn[k] for k in member_keys]
    best = max(members, key=lambda r: (1 if r['_tier'] == 'web_verified' else 0, CONF.get(r.get('sponsor_confidence'), 0)))
    tier = 'web_verified' if any(r['_tier'] == 'web_verified' for r in members) else 'prior_knowledge'
    sponsor = canonicalize(best.get('sponsor', '')) or ''
    # aggregate candidate-table info across all member keys present in cand
    present = [k for k in member_keys if k in cand.index]
    chembl_ids = sorted(set(c for k in present for c in (cand.loc[k, 'chembl_ids'] or '').split('|') if c))
    ncts = sorted(set(n for k in present for n in (cand.loc[k, 'nct_ids'] or '').split('|') if n))
    max_phase_rank_ctgov = max((cand.loc[k, 'max_phase_rank'] for k in present), default=0)
    ot_names = sorted(set(mol_by_id[c][1] for c in chembl_ids if c in mol_by_id))
    ot_types = sorted(set(mol_by_id[c][2] for c in chembl_ids if c in mol_by_id and mol_by_id[c][2]))
    ot_stage = sorted(set(mol_by_id[c][3] for c in chembl_ids if c in mol_by_id and mol_by_id[c][3]))
    ot_moa = sorted(set(x for c in chembl_ids for x in moa_by_chembl.get(c, [])))
    tsub = trials.loc[[n for n in ncts if n in trials.index]] if ncts else trials.iloc[0:0]
    conds = collections.Counter()
    for cs in tsub.conditions:
        for c in aslist(cs):
            if c:
                conds[c] += 1
    statuses = collections.Counter(tsub.overall_status.fillna('NA')) if len(tsub) else collections.Counter()
    display = norm_name(best.get('inn_or_name')) or (ot_names[0].lower() if ot_names else '') or \
              sorted(member_keys, key=lambda k: -len(cand.loc[k, 'nct_ids'] or '') if k in cand.index else 0)[0]
    modality = norm_modality(best.get('modality', ''), ot_types[0] if ot_types else '')
    highest_phase_researched = norm_phase(best.get('highest_phase', ''))
    highest_phase_ctgov = CTGOV_PHASE_LABEL.get(max_phase_rank_ctgov, 'not stated')
    overall_phase = max([highest_phase_researched, highest_phase_ctgov], key=lambda p: PHASE_RANK.get(p, -1))
    rows_out.append({
        'asset_id': cl,
        'display_name': display,
        'codes_and_names': '|'.join(sorted(set(member_keys) | {c for r in members for c in (r.get('other_codes') or '').split('|') if c})),
        'inn': best.get('inn_or_name', '') or (ot_names[0].lower() if ot_names else ''),
        'sponsor': sponsor,
        'sponsor_hq_city': best.get('sponsor_hq_city', ''),
        'sponsor_confidence': best.get('sponsor_confidence', ''),
        'verification_tier': tier,
        'target': best.get('target', ''),
        'mechanism': best.get('mechanism', ''),
        'modality': modality,
        'ot_mechanism_of_action': ' | '.join(ot_moa),
        'ot_drug_type': '|'.join(ot_types),
        'chembl_ids': '|'.join(chembl_ids),
        'indications_researched': best.get('indications', ''),
        'conditions_in_trials': ' | '.join(c for c, _ in conds.most_common(8)),
        'highest_phase': overall_phase,
        'highest_phase_researched': highest_phase_researched,
        'highest_phase_in_ctgov': highest_phase_ctgov,
        'development_status': best.get('development_status', ''),
        'ex_china_rights': best.get('ex_china_rights', ''),
        'partner': best.get('partner', ''),
        'latest_data': best.get('latest_data', ''),
        'first_in_class_note': best.get('first_in_class_note', ''),
        'n_trials_ctgov': len(ncts),
        'n_trials_recruiting_or_active': int(sum(v for k, v in statuses.items() if k in
                                                  ('RECRUITING', 'ACTIVE_NOT_RECRUITING', 'NOT_YET_RECRUITING', 'ENROLLING_BY_INVITATION'))),
        'trial_statuses': json.dumps(statuses),
        'earliest_nct': ncts[0] if ncts else '', 'latest_nct': ncts[-1] if ncts else '',
        'nct_ids': '|'.join(ncts),
        'sources': best.get('sources', ''),
        'notes': ' || '.join(sorted(set(r.get('notes', '') for r in members if r.get('notes')))),
    })
    for n in ncts:
        if n in trials.index:
            t = trials.loc[n]
            trial_rows.append({
                'asset_id': cl, 'display_name': display, 'sponsor': sponsor, 'nct_id': n, 'phase': t.phase,
                'overall_status': t.overall_status, 'study_type': t.study_type, 'primary_purpose': t.primary_purpose,
                'start_date': t.start_date, 'brief_title': t.brief_title, 'official_title': t.official_title,
                'why_stopped': t.why_stopped, 'interventions': ' | '.join(aslist(t.intervention_names)),
                'conditions': ' | '.join(c for c in aslist(t.conditions) if c), 'url': t.url,
            })

A = pd.DataFrame(rows_out).sort_values(['sponsor', 'display_name'])
A.to_csv(PROC / 'chinese_clinical_assets.csv', index=False)
T = pd.DataFrame(trial_rows).sort_values(['sponsor', 'nct_id']) if trial_rows else pd.DataFrame()
T.to_csv(PROC / 'chinese_clinical_trials.csv', index=False)
tr_by = collections.defaultdict(list)
for r in trial_rows:
    tr_by[r['asset_id']].append({k: (str(v) if v is not None else '') for k, v in r.items() if k not in ('asset_id',)})
with open(PROC / 'chinese_clinical_assets.json', 'w', encoding='utf-8') as f:
    json.dump([dict(a, trials=tr_by.get(a['asset_id'], [])) for a in rows_out], f, ensure_ascii=False, indent=1, default=str)

summary = {
    'tier_a_candidates_researched': len(res),
    'classified_cn': len(cn), 'classified_non_cn': sum(1 for r in res.values() if r.get('sponsor_country') == 'non-CN'),
    'classified_unknown': sum(1 for r in res.values() if r.get('sponsor_country') not in ('CN', 'non-CN')),
    'web_verified_records': sum(1 for r in res.values() if r['_tier'] == 'web_verified'),
    'prior_knowledge_records': sum(1 for r in res.values() if r['_tier'] == 'prior_knowledge'),
    'final_unique_assets_after_entity_resolution': len(A),
    'assets_web_verified': int((A.verification_tier == 'web_verified').sum()),
    'assets_prior_knowledge': int((A.verification_tier == 'prior_knowledge').sum()),
    'by_highest_phase': A.highest_phase.value_counts().to_dict(),
    'by_modality': A.modality.value_counts().to_dict(),
    'top_sponsors': A.sponsor.value_counts().head(40).to_dict(),
    'total_ctgov_trial_rows': len(T),
}
json.dump(summary, open(PROC / 'summary.json', 'w'), indent=1)
print(json.dumps(summary, indent=1)[:2500])
