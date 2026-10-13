#!/usr/bin/env python3
"""Fetch Moroccan legislation documents from Internet Archive (Wayback Machine) copies of
official sites (adala.justice.gov.ma, www.sgg.gov.ma).

The official sites are not reachable from outside Morocco on HTTPS (TCP timeout) and
adala.justice.gov.ma is fronted by an F5 bot-defence (TSPD) layer, so only archived copies
of the official documents are used. Every document keeps its original official URL and the
Wayback capture URL used.

Usage: python ma_fetch.py [RAW_DIR]   (default ../../_raw/ma)
Writes RAW_DIR/dl/<sha1>.<ext> and RAW_DIR/manifest.jsonl
"""
import hashlib
import json
import os
import re
import sys
import time

import requests

UA = "LawCodex/1.0 (+https://github.com/LawCodex)"
RAW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "..", "_raw", "ma")
DL = os.path.join(RAW, "dl")
os.makedirs(DL, exist_ok=True)
S = requests.Session()
S.headers["User-Agent"] = UA
DELAY = 1.5

# (cdx url pattern, regex the original URL must match, source tag)
QUERIES = [
    ("adala.justice.gov.ma/reference/adala_v2/*", r"/reference/adala_v2/(ar|fr)/[0-9a-f-]{36}\.(docx|doc|pdf|PDF|htm)$", "adala_v2"),
    ("adala.justice.gov.ma/adala/new_ar_pdf/*", r"/adala/new_ar_pdf/[0-9a-f]{64}\.pdf$", "adala_new_ar"),
    ("adala.justice.gov.ma/adala/new_fr_pdf/*", r"/adala/new_fr_pdf/[0-9a-f]{64}\.pdf$", "adala_new_fr"),
    ("sgg.gov.ma/Portals/1/textesconsolides/*", r"/textesconsolides/[^/]+\.pdf$", "sgg_tc_ar"),
    ("sgg.gov.ma/Portals/0/textesconsolides/*", r"/textesconsolides/[^/]+\.pdf$", "sgg_tc_fr"),
    ("sgg.gov.ma/Portals/1/lois/constitution_2011_Ar.pdf", r"constitution_2011_Ar\.pdf$", "sgg_const_ar"),
    ("sgg.gov.ma/Portals/1/actualite/constitution_2011_Ar.pdf", r"constitution_2011_Ar\.pdf$", "sgg_const_ar"),
    ("sgg.gov.ma/constitution_2011_Ar.pdf", r"constitution_2011_Ar\.pdf$", "sgg_const_ar"),
    ("sgg.gov.ma/Portals/0/constitution/constitution_2011_Fr.pdf", r"constitution_2011_Fr\.pdf$", "sgg_const_fr"),
    ("sgg.gov.ma/Portals/0/actualite/constitution_2011_Fr.pdf", r"constitution_2011_Fr\.pdf$", "sgg_const_fr"),
    ("sgg.gov.ma/constitution_2011_Fr.pdf", r"constitution_2011_Fr\.pdf$", "sgg_const_fr"),
    ("adala.justice.gov.ma/production/constitution/Ar/constitution.pdf", r"constitution\.pdf$", "adala_const_ar"),
    ("adala.justice.gov.ma/production/constitution/fr/Constitution.pdf", r"onstitution\.pdf$", "adala_const_fr"),
    ("adala.justice.gov.ma/production/legislation/fr/Nouveautes/La%20Constitution.pdf", r"Constitution\.pdf$", "adala_const_fr2"),
]


def get(url, tries=8, **kw):
    for i in range(tries):
        try:
            r = S.get(url, timeout=180, **kw)
            if r.status_code in (429, 502, 503, 504):
                print("http", r.status_code, flush=True)
                time.sleep(20 * (i + 1))
                continue
            return r
        except requests.RequestException as e:
            print("retry", i, str(e)[-80:], flush=True)
            time.sleep(min(5 * (i + 1), 120))
    return None


def cdx(pattern):
    url = ("https://web.archive.org/cdx/search/cdx?url=%s&fl=original,timestamp,length"
           "&filter=statuscode:200" % pattern)
    if pattern.endswith("*"):
        url = url.replace("url=%s" % pattern, "url=%s" % pattern[:-1] + "&matchType=prefix")
    r = get(url, tries=40)
    time.sleep(DELAY)
    if r is None or not r.ok:
        sys.exit("CDX query failed: %s" % pattern)
    print("cdx", pattern, r.status_code if r is not None else None, flush=True)
    rows = []
    if r is not None and r.ok:
        for line in r.text.splitlines():
            p = line.split(" ")
            if len(p) == 3:
                rows.append(p)
    return rows


def norm(u):
    u = re.sub(r"^https?://", "", u.split("?")[0])
    u = u.replace(":80/", "/").replace(":443/", "/")
    return u.lower()


def fetch_one(k, g):
    caps = sorted(set(map(tuple, g["caps"])), reverse=True)
    neterr = False
    for ts, orig in caps[:6]:
        wb = "https://web.archive.org/web/%sid_/%s" % (ts, orig)
        r = get(wb, tries=20)
        time.sleep(DELAY)
        if r is None:
            neterr = True
        if r is None or r.status_code != 200:
            continue
        warn = r.headers.get("warning", "")
        olen = r.headers.get("x-archive-orig-x-crawler-content-length") or ""
        if "truncated" in warn or (olen.isdigit() and int(olen) != len(r.content)):
            continue
        if len(r.content) < 200 or r.content[:15].lower().startswith(b"<!doctype html") and not k.endswith(".htm"):
            continue
        ext = k.rsplit(".", 1)[-1].lower()
        fn = hashlib.sha1(k.encode()).hexdigest()[:16] + "." + ext
        with open(os.path.join(DL, fn), "wb") as f:
            f.write(r.content)
        return {"key": k, "tag": g["tag"], "file": fn, "original": orig.split("?")[0],
                "wayback": "https://web.archive.org/web/%s/%s" % (ts, orig), "timestamp": ts}
    if neterr:
        return None  # network trouble: retry on next run
    return {"key": k, "tag": g["tag"], "file": None, "original": caps[0][1].split("?")[0]}


def main():
    import concurrent.futures
    import threading
    man_path = os.path.join(RAW, "manifest.jsonl")
    done = {}
    if os.path.exists(man_path):
        for line in open(man_path, encoding="utf-8"):
            d = json.loads(line)
            done[d["key"]] = d
    gpath = os.path.join(RAW, "cdx_groups.json")
    if os.path.exists(gpath):
        groups = json.load(open(gpath, encoding="utf-8"))
    else:
        groups = {}
        for pat, rx, tag in QUERIES:
            for orig, ts, ln in cdx(pat):
                base = orig.split("?")[0]
                if not re.search(rx, base):
                    continue
                k = norm(base)
                g = groups.setdefault(k, {"tag": tag, "caps": []})
                g["caps"].append((ts, orig))
        json.dump(groups, open(gpath, "w", encoding="utf-8"), ensure_ascii=False)
    print("unique documents:", len(groups), flush=True)
    man = open(man_path, "a", encoding="utf-8")
    lock = threading.Lock()
    todo = [(k, g) for k, g in sorted(groups.items()) if k not in done]
    n = 0
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        for res in ex.map(lambda kg: fetch_one(*kg), todo):
            n += 1
            if res is None:
                continue
            with lock:
                man.write(json.dumps(res, ensure_ascii=False) + "\n")
                man.flush()
            if n % 25 == 0:
                print(n, "/", len(todo), flush=True)


if __name__ == "__main__":
    main()
