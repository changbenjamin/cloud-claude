#!/usr/bin/env python3
"""
CDE "implied IND approval" list (临床试验默示许可) scraper, https://www.cde.org.cn/main/xxgk/listpage/9f9c74c73e0f8f56a8bfbc646055026d
Run OUTSIDE the sandbox. The page is a JS application that loads rows from an internal JSON endpoint protected by a
rotating signature header, so the robust approach is Playwright: open the page, capture the XHR responses that feed
the table while paging through it, and dump every row (受理号 acceptance no., 药物名称 drug name, 药物类型 type,
适应症 indication, 申请人 applicant, 承办日期/许可日期 dates).

Usage:  python cde_implied_approval.py --out cde_implied_approvals.jsonl [--max-pages 5000]
"""
import argparse, json, time
from playwright.sync_api import sync_playwright

PAGE = "https://www.cde.org.cn/main/xxgk/listpage/9f9c74c73e0f8f56a8bfbc646055026d"

def main(a):
    rows, seen = [], set()
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        pg = b.new_page()
        def on_response(resp):
            try:
                if resp.request.method == "POST" and "xxgk" in resp.url and "json" in (resp.headers.get("content-type") or ""):
                    data = resp.json()
                    for r in (data.get("records") or data.get("data", {}).get("records") or data.get("rows") or []):
                        key = json.dumps(r, sort_keys=True, ensure_ascii=False)
                        if key not in seen:
                            seen.add(key); rows.append(r)
            except Exception:
                pass
        pg.on("response", on_response)
        pg.goto(PAGE, timeout=120000)
        pg.wait_for_timeout(4000)
        for i in range(a.max_pages):
            nxt = pg.query_selector("button.btn-next, .btn-next, li.next a, a:has-text('下一页')")
            if not nxt or nxt.get_attribute("disabled") is not None:
                break
            nxt.click(); pg.wait_for_timeout(1200 + 300 * (i % 3))
            if i % 50 == 0: print("page", i, "rows so far", len(rows))
        b.close()
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("saved", len(rows), "rows ->", a.out)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--max-pages", type=int, default=5000)
    main(ap.parse_args())
