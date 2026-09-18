#!/usr/bin/env python3
"""
ClinicalTrials.gov Data API v2 fetcher (run this OUTSIDE the sandbox: clinicaltrials.gov was blocked by the
session's egress policy, which is why the committed dataset was built from the Open Targets mirror instead).

Three modes, all write JSONL (one study per line) to --out:

  # every study with at least one site in China (the ground truth for "trial run in China")
  python ctgov_api_v2.py locn --out ctgov_china_sites.jsonl

  # every study whose lead sponsor / collaborator matches names in the Chinese sponsor list
  python ctgov_api_v2.py sponsors --sponsor-csv ../../data/reference/chinese_sponsors.csv --out ctgov_cn_sponsors.jsonl

  # every study mentioning given intervention codes (one per line in a text file)
  python ctgov_api_v2.py interventions --codes codes.txt --out ctgov_by_code.jsonl

No API key is needed. Be polite: the script sleeps 0.3 s between pages. Full China-site pull is ~40k studies.
"""
import argparse, csv, json, sys, time, urllib.parse, urllib.request

BASE = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = ",".join([
    "NCTId", "BriefTitle", "OfficialTitle", "LeadSponsorName", "LeadSponsorClass", "CollaboratorName",
    "Phase", "OverallStatus", "StudyType", "DesignPrimaryPurpose", "StartDate", "PrimaryCompletionDate",
    "CompletionDate", "LastUpdatePostDate", "ResultsFirstPostDate", "Condition", "Keyword",
    "InterventionName", "InterventionType", "InterventionDescription", "ArmGroupLabel", "ArmGroupType",
    "LocationCountry", "LocationCity", "LocationFacility", "EnrollmentCount", "WhyStopped", "SecondaryId",
    "BriefSummary", "PrimaryOutcomeMeasure", "EligibilityCriteria", "ResponsiblePartyInvestigatorAffiliation",
])

def fetch(params, sleep=0.3):
    token = None
    while True:
        p = dict(params, format="json", pageSize=1000, fields=FIELDS)
        if token:
            p["pageToken"] = token
        url = BASE + "?" + urllib.parse.urlencode(p, quote_via=urllib.parse.quote)
        for attempt in range(5):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "asset-scan/1.0"}), timeout=120) as r:
                    data = json.load(r)
                break
            except Exception as e:  # noqa
                wait = 2 ** attempt
                print(f"retry {attempt+1} after error {e}; sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
        else:
            raise SystemExit("giving up on " + url)
        for s in data.get("studies", []):
            yield s
        token = data.get("nextPageToken")
        if not token:
            return
        time.sleep(sleep)

def write(gen, out, seen):
    n = 0
    with open(out, "a") as f:
        for s in gen:
            nct = s.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
            if nct in seen:
                continue
            seen.add(nct)
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
            n += 1
    return n

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["locn", "sponsors", "interventions"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--sponsor-csv")
    ap.add_argument("--codes")
    a = ap.parse_args()
    seen = set()
    if a.mode == "locn":
        # query.locn searches location facility/city/state/country; combine with China + Hong Kong + Macau
        for term in ["China", "Hong Kong", "Macau", "Taiwan"]:
            n = write(fetch({"query.locn": term}), a.out, seen)
            print(term, n)
    elif a.mode == "sponsors":
        names = []
        with open(a.sponsor_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                names.append(r["english_name"])
                names += [v for v in (r.get("name_variants") or "").split("|") if v.strip()]
        for name in sorted(set(n.strip() for n in names if n.strip())):
            n = write(fetch({"query.spons": f'"{name}"'}), a.out, seen)
            print(name, n)
    else:
        with open(a.codes) as f:
            codes = [l.strip() for l in f if l.strip()]
        for c in codes:
            n = write(fetch({"query.intr": f'"{c}"'}), a.out, seen)
            print(c, n)
    print("total unique studies:", len(seen))

if __name__ == "__main__":
    main()
