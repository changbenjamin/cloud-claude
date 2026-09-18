#!/usr/bin/env python3
"""
ChiCTR (Chinese Clinical Trial Registry, www.chictr.org.cn) scraper. Run OUTSIDE the sandbox.

ChiCTR detail pages are addressable by a numeric project id:  https://www.chictr.org.cn/showprojEN.html?proj=<id>
(Chinese version: showproj.html?proj=<id>). Ids are dense integers (roughly 1 .. 300000 as of 2026), so the
simplest complete crawl is to iterate ids. ChiCTR is mostly investigator-initiated studies; industry-sponsored
drug trials are usually ALSO on ClinicalTrials.gov, but some China-only Phase 1/2 studies are only here.

Usage:
  python chictr.py --start 1 --end 300000 --out chictr.jsonl --workers 4 --delay 0.5
Output: JSONL with the labelled fields of each registration (English labels where the EN page provides them).
"""
import argparse, json, time, random, concurrent.futures as cf
import requests
from lxml import html

URL = "https://www.chictr.org.cn/showprojEN.html?proj={}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
           "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"}

def parse(doc):
    rec = {}
    # Every field on a ChiCTR page is a <td class="left_title">label</td><td>value</td> pair (nested cn/en spans).
    for lt in doc.xpath("//td[contains(@class,'left_title')]"):
        label = " ".join(t.strip() for t in lt.itertext() if t.strip())
        val_td = lt.getnext()
        if val_td is None: continue
        val = " ".join(t.strip() for t in val_td.itertext() if t.strip())
        if label and val and label not in rec:
            rec[label] = val
    return rec

def fetch(pid, delay):
    for attempt in range(4):
        try:
            r = requests.get(URL.format(pid), headers=HEADERS, timeout=60)
            if r.status_code == 200 and "Registration number" in r.text:
                d = parse(html.fromstring(r.text)); d["_proj_id"] = pid
                time.sleep(delay + random.random() * delay)
                return d
            if r.status_code in (404,) or "Registration number" not in r.text:
                return None
        except Exception:
            time.sleep(2 ** attempt)
    return None

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1); ap.add_argument("--end", type=int, default=300000)
    ap.add_argument("--out", required=True); ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.5)
    a = ap.parse_args()
    n = 0
    with open(a.out, "a", encoding="utf-8") as f, cf.ThreadPoolExecutor(a.workers) as ex:
        for rec in ex.map(lambda i: fetch(i, a.delay), range(a.start, a.end + 1)):
            if rec:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n"); n += 1
                if n % 500 == 0: print("saved", n); f.flush()
    print("done", n)
