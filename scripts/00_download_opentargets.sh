#!/usr/bin/env bash
# Downloads the Open Targets Platform 26.06 tables used by this project from the public AWS bucket
# (registry.opendata.aws/opentargets). No credentials needed.
set -euo pipefail
REL=${1:-26.06}
B="https://open-targets-public-data-releases.s3.eu-west-1.amazonaws.com"
OUT="$(dirname "$0")/../data/raw/opentargets_${REL}"
mkdir -p "$OUT"
for ds in clinical_report clinical_indication clinical_target drug_molecule drug_mechanism_of_action drug_warning disease target; do
  mkdir -p "$OUT/$ds"
  curl -sS "$B/?prefix=platform/${REL}/output/${ds}/&max-keys=1000" \
    | grep -o '<Key>[^<]*\.parquet</Key>' | sed 's/<Key>//;s/<\/Key>//' \
    | while read -r key; do
        echo "fetching $key"; curl -sS -o "$OUT/$ds/$(basename "$key")" "$B/$key"
      done
done
echo "done -> $OUT"
