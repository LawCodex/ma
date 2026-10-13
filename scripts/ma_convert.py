#!/usr/bin/env python3
"""Convert downloaded Moroccan documents (see ma_fetch.py) into LawCodex Markdown.

Usage: python ma_convert.py RAW_DIR OUT_REPO_DIR
"""
import collections
import datetime
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ma_text  # noqa: E402

RAW, OUT = sys.argv[1], sys.argv[2]
TODAY = datetime.date.today().isoformat()

AR_MONTHS = {"يناير": 1, "فبراير": 2, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "إبريل": 4, "ماي": 5,
             "مايو": 5, "يونيو": 6, "يوليو": 7, "يوليوز": 7, "غشت": 8, "أغسطس": 8, "شتنبر": 9, "سبتمبر": 9,
             "أكتوبر": 10, "اكتوبر": 10, "نونبر": 11, "نوفمبر": 11, "دجنبر": 12, "ديسمبر": 12}
FR_MONTHS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
             "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
             "décembre": 12, "decembre": 12}

TYPES = {  # type -> (ar dir, fr dir, filename prefix)
    "constitution": ("constitution", "constitution", "constitution"),
    "code": ("codes", "codes", "code"),
    "organic_law": ("organic-laws", "lois-organiques", "organic-law"),
    "law": ("laws", "lois", "law"),
    "dahir": ("dahirs", "dahirs", "dahir"),
    "decree_law": ("decree-laws", "decrets-lois", "decree-law"),
    "decree": ("decrees", "decrets", "decree"),
    "order": ("orders", "arretes", "order"),
}
YEARLY = {"law", "dahir", "decree", "order"}
PRIO = {"sgg_const_ar": 9, "sgg_const_fr": 9, "adala_new_ar": 5, "adala_new_fr": 5, "adala_v2": 4,
        "sgg_tc_ar": 3, "sgg_tc_fr": 3, "adala_const_ar": 1, "adala_const_fr": 1, "adala_const_fr2": 2}

log = open(os.path.join(RAW, "convert.log"), "w", encoding="utf-8")


def extract(path):
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "docx":
        return ma_text.docx_lines(path), False
    if ext == "doc":
        return ma_text.doc_lines(path), False
    if ext == "htm":
        return ma_text.htm_lines(path), False
    head = open(path, "rb").read(5)
    if head != b"%PDF-":
        return [], True
    lines = ma_text.pdf_lines(path, arabic=True)
    if not any(ma_text.AR.search(x) for x in lines[:400]):
        lines = ma_text.pdf_lines(path, arabic=False)
    return lines, True


def parse_date(text, lang):
    if lang == "ar":
        for m in re.finditer(r"\(\s*(\d{1,2}|فاتح)\s+([ء-ي]+)\s+(\d{4})\s*\)", text):
            mo = AR_MONTHS.get(m.group(2))
            if mo:
                d = 1 if m.group(1) == "فاتح" else int(m.group(1))
                try:
                    return datetime.date(int(m.group(3)), mo, d).isoformat()
                except ValueError:
                    pass
    else:
        for m in re.finditer(r"\(\s*(\d{1,2})(?:er)?\s+([a-zéèûô]+)\s+(\d{4})\s*\)", text, re.I):
            mo = FR_MONTHS.get(m.group(2).lower())
            if mo:
                try:
                    return datetime.date(int(m.group(3)), mo, int(m.group(1))).isoformat()
                except ValueError:
                    pass
    return None


def consolidated(text, lang):
    if lang == "ar":
        m = re.search(r"صيغة محينة بتاريخ\s*(\d{1,2})\s+([ء-ي]+)\s+(\d{4})", text)
        if m and AR_MONTHS.get(m.group(2)):
            try:
                return datetime.date(int(m.group(3)), AR_MONTHS[m.group(2)], int(m.group(1))).isoformat()
            except ValueError:
                return None
    else:
        m = re.search(r"[Vv]ersion consolidée (?:en date )?du\s*(\d{1,2})(?:er)?\s+([a-zéèûô]+)\s+(\d{4})", text)
        if m and FR_MONTHS.get(m.group(2).lower()):
            try:
                return datetime.date(int(m.group(3)), FR_MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
            except ValueError:
                return None
    return None


NUM = r"(\d{1,3}[\.\-]\d{1,3}(?:[\.\-]\d{1,4})?)"


def base_segment(nonempty):
    """Lines describing the base act (skipping the amendment list of consolidated versions)."""
    start = 1
    for i, l in enumerate(nonempty[:6]):
        if re.search(r"صيغة محينة|[Vv]ersion consolidée|[Vv]ersion mise à jour", l):
            start = i + 1
            break
    seg = []
    for l in nonempty[start:start + 8]:
        if re.match(r"^\d{1,2}\s*[-\.\)]\s", l) or re.match(r"^\d{1,2}\s*[-\.\)]\s*[\u0621-\u064a]", l):
            break
        seg.append(l)
        if re.search(r"كما (?:تم|وقع)|كما عدل|tel(?:le)? qu'(?:il|elle)", l):
            break
    return "\n".join(seg)


def dahir_heading(nonempty):
    for l in nonempty[:200]:
        if re.match(r"^(ظهير شريف|Dahir)", l):
            return l
    return ""


def classify(head, title, lang, tag):
    """Return (type, number)."""
    h = head
    if "const" in tag or re.match(r"^(الدستور|دستور المملكة|Constitution)", title):
        return "constitution", "2011"
    if lang == "ar":
        law = re.search(r"(?:ال)?قانون\s+(?:ال)?(?:تنظيمي|إطار|الإطار)?\s*رقم\s*" + NUM, h)
        org = re.search(r"(?:ال)?قانون\s+(?:ال)?تنظيمي\s+رقم\s*" + NUM, h)
        dl = re.search(r"مرسوم\s+بقانون\s+رقم\s*" + NUM, h) or re.search(
            r"مرسوم\s+ملكي\s+(?:بمثابة\s+قانون\s+)?رقم\s*" + NUM, h)
        dec = re.search(r"مرسوم\s+رقم\s*" + NUM, h)
        dah = re.search(r"ظهير\s+شريف\s+(?:بمثابة\s+قانون\s+)?رقم\s*" + NUM, h)
        order = re.search(r"قرار\s+[^\n]{0,80}?رقم\s*" + NUM, h)
        is_code = re.search(r"مدونة|مجموعة القانون|قانون المسطرة|الالتزامات والعقود", title)
    else:
        law = re.search(r"\bloi(?:-cadre)?\s+(?:organique\s+)?n[°o]\s*" + NUM, h, re.I)
        org = re.search(r"\bloi\s+organique\s+n[°o]\s*" + NUM, h, re.I)
        dl = re.search(r"décret-loi\s+n[°o]\s*" + NUM, h, re.I) or re.search(
            r"décret\s+royal\s+(?:portant\s+loi\s+)?n[°o]\s*" + NUM, h, re.I)
        dec = re.search(r"\bdécret\s+n[°o]\s*" + NUM, h, re.I)
        dah = re.search(r"\bdahir\s+(?:portant loi\s+)?n[°o]\s*" + NUM, h, re.I)
        order = re.search(r"\barrêté\s+[^\n]{0,80}?n[°o]\s*" + NUM, h, re.I)
        is_code = re.search(r"\bcode\b", title, re.I)
    first = min([m for m in (law, dl, dec, dah, order) if m], key=lambda m: m.start(), default=None)
    if org:
        return ("code" if is_code else "organic_law"), org.group(1)
    if is_code and (law or dah):
        return "code", (law or dah).group(1)
    if law:
        return "law", law.group(1)
    if dl:
        return "decree_law", dl.group(1)
    if first is dec and dec:
        return "decree", dec.group(1)
    if dah:
        return "dahir", dah.group(1)
    if dec:
        return "decree", dec.group(1)
    if order:
        return "order", order.group(1)
    return None, None


# ------------------------------------------------------------------ structure
AR_HEAD = [(r"^(الكتاب|الجزء)\s", 2), (r"^القسم\s", 3), (r"^الباب\s", 4), (r"^الفرع\s", 5)]
FR_HEAD = [(r"^(LIVRE|Livre|PARTIE|Partie)\s", 2), (r"^(TITRE|Titre)\s", 3), (r"^(CHAPITRE|Chapitre)\s", 4),
           (r"^(Section|SECTION)\s", 5)]
AR_ART = re.compile(r"^(المادة|الفصل)\s+((?:\d+[\-\.]?\d*\s*(?:مكرر(?:ة)?(?:\s+مرتين)?)?)|(?:ال)?[ء-ي]+(?:\s+(?:بعد\s+)?(?:العشرون|عشرة|عشر|مكرر(?:ة)?))?)\s*[:\-–\.]*\s*(.*)$")
FR_ART = re.compile(r"^(Article|ARTICLE|Art\.)\s+(premier|unique|\d+[\-\.]?\d*(?:\s*(?:bis|ter|quater))?(?:er)?)\s*[\.:\-–]*\s*(.*)$")
PAGE = re.compile(r"^[\-–\s]*\d{1,4}[\-–\s]*$|^\f$")


def is_heading(line, lang, fasl_is_chapter):
    if len(line) > 140:
        return None
    pats = AR_HEAD if lang == "ar" else FR_HEAD
    for rx, lvl in pats:
        if re.match(rx, line):
            return lvl
    if lang == "ar" and fasl_is_chapter and re.match(r"^الفصل\s", line):
        return 5
    return None


def build_body(lines, lang, from_pdf):
    text = "\n".join(lines)
    n_madda = len(re.findall(r"(?m)^المادة\s", text))
    n_fasl = len(re.findall(r"(?m)^الفصل\s", text))
    fasl_is_chapter = lang == "ar" and n_madda > 3 and n_madda >= n_fasl
    out = []
    para = []

    def flush():
        if para:
            out.append(" ".join(para).strip())
            out.append("")
            para.clear()

    for raw in lines:
        line = raw.strip()
        if not line or PAGE.match(line):
            if not from_pdf or not line:
                flush()
            continue
        lvl = is_heading(line, lang, fasl_is_chapter)
        if lvl:
            flush()
            out.append("#" * lvl + " " + line.replace("#", ""))
            out.append("")
            continue
        m = (AR_ART if lang == "ar" else FR_ART).match(line)
        if m and not (lang == "ar" and m.group(1) == "الفصل" and fasl_is_chapter) and len(m.group(2)) < 40:
            flush()
            out.append("###### " + (m.group(1) + " " + m.group(2)).strip())
            out.append("")
            if m.group(3).strip():
                para.append(m.group(3).strip())
            continue
        if from_pdf:
            if para and (re.search(r"[\.:؛;!؟\?]$", para[-1]) or re.match(r"^[\-–•\*]|^\d+[\.\)\-]\s|^[ء-ي][\)\-]\s", line)):
                flush()
            para.append(line)
        else:
            para.append(line)
            flush()
    flush()
    md = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def yaml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    man = [json.loads(x) for x in open(os.path.join(RAW, "manifest.jsonl"), encoding="utf-8")]
    seen = {}
    for d in man:
        if d.get("file"):
            seen[d["key"]] = d
    docs = []
    for d in seen.values():
        path = os.path.join(RAW, "dl", d["file"])
        try:
            lines, from_pdf = extract(path)
        except Exception as e:  # noqa
            print("ERR extract", d["key"], e, file=log)
            continue
        nonempty = [x for x in lines if x.strip() and not PAGE.match(x.strip())]
        if len(nonempty) < 3:
            print("SKIP empty/scanned", d["key"], file=log)
            continue
        alltext = "\n".join(nonempty)
        n_ar = len(ma_text.AR.findall(alltext))
        lang = "ar" if n_ar > 0.3 * len(re.findall(r"\w", alltext)) else "fr"
        if lang == "ar":
            ok, why = ma_text.acceptable(nonempty)
            if not ok:
                print("SKIP quality", why, d["key"], file=log)
                continue
        while nonempty and (len(nonempty[0]) < 3 or re.match(r"^[\-–\s\d]+$", nonempty[0])
                            or re.match(r"^(?i:الجريدة الرسمية|Bulletin officiel|المملكة المغربية|Royaume du Maroc|وزارة العدل)", nonempty[0])):
            nonempty = nonempty[1:]
        if lang == "fr":
            fw = re.findall(r"[A-Za-zÀ-ÿ]+", alltext)
            share = sum(1 for w in fw if w.lower() in ("de", "la", "le", "et", "les", "des", "du", "à", "en", "par", "au")) / max(1, len(fw))
            if share < 0.12 or len(fw) < 50:
                print("SKIP quality fr", round(share, 3), d["key"], file=log)
                continue
        head = "\n".join(nonempty[:25])
        title = re.sub(r"\s+", " ", nonempty[0]).strip(" -–")
        title = re.sub(r"\s*(صيغة محينة.*|[Vv]ersion consolidée.*)$", "", title).strip() or title
        seg = base_segment(nonempty)
        typ, num = classify(seg, title, lang, d["tag"]) if seg else (None, None)
        if not typ:
            m = re.search(r"^\s*(\d\.\d{2}\.\d{1,4})\s*$", seg, re.M)
            if m:
                typ, num = ("code" if re.search(r"مدونة|مجموعة القانون|قانون المسطرة|Code", title) else "dahir"), m.group(1)
        if not typ:
            dh = dahir_heading(nonempty)
            if dh:
                typ, num = classify(dh, title, lang, d["tag"])
                seg = seg or dh
        if not typ and re.search(r"(?:ال)?ظهير (?:ال)?شريف|Dahir", seg + "\n" + title):
            dt = parse_date(seg, lang) or parse_date(head, lang)
            if dt:
                typ = "code" if re.search(r"مدونة|مجموعة القانون|قانون المسطرة|Code", title) else "dahir"
                num = dt
        if not typ:
            typ, num = classify(head, title, lang, d["tag"])
        datesrc = seg or head
        if not typ:
            print("SKIP unclassified", d["key"], title[:80], file=log)
            continue
        if re.search(r"اتفاق|اتفاقية|Convention|Accord", title) and typ not in ("constitution",):
            # treaties are out of scope; keep only if the heading is a law/dahir approving it
            pass
        docs.append({"d": d, "lines": lines, "from_pdf": from_pdf, "lang": lang, "type": typ, "num": num,
                     "title": title, "date": parse_date(datesrc, lang) or parse_date(dahir_heading(nonempty), lang), "cons": consolidated(head, lang)})
    # dedupe
    for x in docs:
        if x["type"] == "dahir" and re.match(r"^\d{2,4}\.\d{2}\.1$", x["num"] or ""):
            x["num"] = ".".join(reversed(x["num"].split(".")))  # digits run reversed by bidi
    best = {}
    for x in docs:
        k = (x["lang"], x["type"], x["num"]) if x["type"] != "code" else (x["lang"], "code", re.sub(r"\W", "", x["title"]))
        score = (x["cons"] or "", PRIO.get(x["d"]["tag"], 0), x["d"].get("timestamp", ""))
        if k not in best or score > best[k][0]:
            best[k] = (score, x)
    counts = collections.Counter()
    index = []
    for (_, x) in best.values():
        typ, lang, num = x["type"], x["lang"], x["num"]
        dirs = TYPES[typ]
        sub = dirs[0] if lang == "ar" else dirs[1]
        year = (x["date"] or "")[:4]
        rel = os.path.join(lang, sub)
        if typ in YEARLY:
            rel = os.path.join(rel, year or "undated")
        slug = dirs[2] + "-" + re.sub(r"[^0-9a-z]+", "-", num.lower()).strip("-")
        if typ == "constitution":
            slug = "constitution-2011"
        fn = os.path.join(OUT, rel, slug + ".md")
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        body = build_body(x["lines"], lang, x["from_pdf"])
        d = x["d"]
        fm = ["---", "title: " + yaml_str(x["title"]), "identifier: " + yaml_str(num), "type: " + typ,
              "jurisdiction: ma", "language: " + lang]
        if x["date"]:
            fm.append("date: " + x["date"])
        if x["cons"]:
            fm.append("last_amended: " + x["cons"])
            fm.append("consolidated: true")
        fm.append("status: " + ("in_force" if typ == "constitution" else "unknown"))
        fm.append("source: " + yaml_str(d["original"]))
        fm.append("archived_source: " + yaml_str(d["wayback"]))
        ts = d.get("timestamp", "")
        if ts:
            fm.append("archived: %s-%s-%s" % (ts[:4], ts[4:6], ts[6:8]))
        fm.append("retrieved: " + TODAY)
        fm.append("---")
        h1 = "# " + x["title"]
        with open(fn, "w", encoding="utf-8") as f:
            f.write("\n".join(fm) + "\n\n" + h1 + "\n\n" + body)
        counts[(lang, typ)] += 1
        index.append((lang, typ, os.path.relpath(fn, OUT)))
    json.dump(sorted(index), open(os.path.join(RAW, "index.json"), "w"), ensure_ascii=False, indent=0)
    for k, v in sorted(counts.items()):
        print(k, v)
    print("total", sum(counts.values()))


if __name__ == "__main__":
    main()
