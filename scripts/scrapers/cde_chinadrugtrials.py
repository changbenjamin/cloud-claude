#!/usr/bin/env python3
"""
Scraper for the NMPA/CDE Drug Clinical Trial Registration and Information Disclosure Platform
(药物临床试验登记与信息公示平台, https://www.chinadrugtrials.org.cn). Run OUTSIDE the sandbox.

This is the mandatory registry for every IND-approved drug trial in China (CTRyyyynnnn numbers), so it is the
ground truth for "in clinical development in China". It is Chinese-only, has no API, and rate-limits aggressively.

Approach (same endpoints the 2019 open-source scraper used; the site kept the .dhtml/eap structure):
  1. GET  /eap/clinicaltrials.searchlist   with currentpage/pagesize  -> list rows (reg no, state, drug, indication)
  2. POST /eap/clinicaltrials.searchlistdetail with ckm_id / ckm_index -> detail page (sponsor, title, phase, sites...)
If the plain-requests path is blocked by the site's anti-bot layer, use --playwright (Chromium) which drives the
real search page and reads the same tables.

Usage:
  python cde_chinadrugtrials.py --out cde_trials.jsonl [--start-page 1 --end-page 9999] [--playwright]
Output: JSONL, one registration per line, with raw Chinese fields; translate/normalize downstream with an LLM.
"""
import argparse, json, re, sys, time, random
import requests
from lxml import html

BASE = "https://www.chinadrugtrials.org.cn"
LIST = BASE + "/eap/clinicaltrials.searchlist"
DETAIL = BASE + "/eap/clinicaltrials.searchlistdetail"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": BASE + "/clinicaltrials.searchlist.dhtml",
}
PARAMS = dict(ckm_id="", ckm_index="", sort="desc", sort2="desc", rule="CTR", keywords="", reg_no="CTR",
              indication="", case_no="", drugs_name="", drugs_type="", appliers="", communities="",
              researchers="", agencies="", state="")

def text(el, xp):
    v = el.xpath(xp)
    return " ".join(t.strip() for t in v if isinstance(t, str) and t.strip()) if v else ""

def parse_detail(doc):
    """Pull the labelled table cells of the detail page into a dict, label -> value (Chinese labels kept)."""
    out = {}
    for td in doc.xpath("//td[contains(@class,'dw_pl') or contains(@class,'cxtj_tm')]//td | //table//td"):
        label = (td.text or "").strip()
        nxt = td.getnext()
        if label and nxt is not None and label.endswith(("：", ":")) is False and len(label) < 30:
            val = " ".join(x.strip() for x in nxt.itertext() if x.strip())
            if val and label not in out:
                out[label] = val
    out["_title"] = text(doc, '//td[contains(text(),"试验专业题目")]/following-sibling::td[1]//text()')
    out["_phase"] = text(doc, '//td[contains(text(),"试验分期")]/../../tr[2]/td[3]//text()')
    out["_classification"] = text(doc, '//td[contains(text(),"试验分类")]/../../tr[2]/td[3]//text()')
    out["_applicant"] = text(doc, '//*[contains(@class,"cxtj_tm")]//table//tr[3]/td[2]//text()')
    out["_public_date"] = text(doc, '//*[contains(@class,"cxtj_tm")]//table//tr[2]/td[4]//text()')
    out["_target_enrollment"] = text(doc, '//td[contains(text(),"目标入组人数")]/following-sibling::td[1]//text()')
    out["_first_enrolled"] = text(doc, '//div[contains(text(),"第一例受试者入组日期")]/following::table[1]//td//text()')
    return out

def scrape_requests(a):
    s = requests.Session(); s.headers.update(HEADERS)
    s.get(BASE + "/clinicaltrials.searchlist.dhtml", timeout=60)  # obtain cookies
    with open(a.out, "a", encoding="utf-8") as f:
        for page in range(a.start_page, a.end_page + 1):
            p = dict(PARAMS, currentpage=str(page), pagesize=str(a.page_size))
            r = s.get(LIST, params=p, timeout=60)
            doc = html.fromstring(r.text)
            rows = doc.xpath("//tbody//tr")
            if not rows:
                print("no rows on page", page, "- stopping"); break
            for tr in rows:
                a_el = tr.xpath("./td[2]/a")
                if not a_el: continue
                reg = (a_el[0].text or "").strip(); ckm_id = a_el[0].get("id", ""); ckm_index = a_el[0].get("name", "")
                rec = {"registration_number": reg,
                       "state": text(tr, "./td[3]//text()"), "drug_name": text(tr, "./td[4]//text()"),
                       "indication": text(tr, "./td[5]//text()")}
                d = s.post(DETAIL, data=dict(p, ckm_id=ckm_id, ckm_index=ckm_index), timeout=60)
                rec["detail"] = parse_detail(html.fromstring(d.text))
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                time.sleep(a.delay + random.random() * a.delay)
            print("page", page, "rows", len(rows)); f.flush()

def scrape_playwright(a):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw, open(a.out, "a", encoding="utf-8") as f:
        b = pw.chromium.launch(headless=True); pg = b.new_page(user_agent=HEADERS["User-Agent"])
        pg.goto(BASE + "/clinicaltrials.searchlist.dhtml", timeout=120000)
        pg.click("text=查询")  # run an empty search = everything
        page = 1
        while True:
            pg.wait_for_selector("#searchfrm tbody tr", timeout=120000)
            rows = pg.query_selector_all("#searchfrm tbody tr")
            for i in range(len(rows)):
                rows = pg.query_selector_all("#searchfrm tbody tr")
                link = rows[i].query_selector("td:nth-child(2) a")
                if not link: continue
                reg = link.inner_text().strip()
                with pg.expect_popup() as pop:
                    link.click()
                dp = pop.value; dp.wait_for_load_state("domcontentloaded")
                rec = {"registration_number": reg, "detail": parse_detail(html.fromstring(dp.content()))}
                dp.close()
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                time.sleep(a.delay)
            print("page", page); f.flush()
            nxt = pg.query_selector("a:has-text('下一页')")
            if not nxt or page >= a.end_page: break
            nxt.click(); page += 1; time.sleep(a.delay)
        b.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--end-page", type=int, default=100000)
    ap.add_argument("--page-size", type=int, default=40)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--playwright", action="store_true")
    a = ap.parse_args()
    (scrape_playwright if a.playwright else scrape_requests)(a)
