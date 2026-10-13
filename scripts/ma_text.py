"""Text extraction helpers for Moroccan documents (docx, doc, htm, pdf).

Arabic PDFs: poppler's pdftotext gives the right logical order and word spacing, but writes
multi-character ligature glyphs (lam-alef, "allah") reversed (e.g. "اآلخرة" for "الآخرة",
"هللا" for "الله"). pypdf gets those ligatures right but sometimes drops inter-word spaces.
We take pdftotext's tokens and, for tokens containing a suspicious pattern, pick the variant
(un-reversed ligature) that occurs in pypdf's text of the same page.
"""
import itertools
import re
import subprocess
import unicodedata
import zipfile

from lxml import etree, html as LH

BIDI = re.compile("[‎‏‪-‮⁦-⁩﻿]")
AR = re.compile("[؀-ۿ]")
SUSP = re.compile("[اأإآ]ل|هللا|هلل")


def clean_line(s):
    s = BIDI.sub("", s)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("ـ", "")  # tatweel (justification only)
    s = s.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", s).strip()


# ---------------------------------------------------------------- docx
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_lines(path):
    z = zipfile.ZipFile(path)
    root = etree.fromstring(z.read("word/document.xml"))
    out = []
    for p in root.iter(W + "p"):
        parts = []
        for el in p.iter():
            if el.tag == W + "t" and el.text:
                parts.append(el.text)
            elif el.tag in (W + "tab",):
                parts.append(" ")
            elif el.tag in (W + "br", W + "cr"):
                parts.append("\n")
        for seg in "".join(parts).split("\n"):
            out.append(clean_line(seg))
        out.append("")
    return out


def doc_lines(path):
    r = subprocess.run(["textutil", "-convert", "txt", "-stdout", path], capture_output=True)
    if r.returncode != 0:
        return []
    return [clean_line(x) for x in r.stdout.decode("utf-8", "replace").splitlines()]


def htm_lines(path):
    raw = open(path, "rb").read()
    m = re.search(rb'charset=([\w-]+)', raw[:3000])
    enc = m.group(1).decode() if m else "utf-8"
    try:
        txt = raw.decode("utf-8")  # some pages declare windows-1256 but are UTF-8
    except UnicodeDecodeError:
        try:
            txt = raw.decode(enc, "replace")
        except LookupError:
            txt = raw.decode("utf-8", "replace")
    doc = LH.fromstring(txt)
    for bad in doc.xpath("//script|//style|//head"):
        bad.getparent().remove(bad)
    out = []
    for el in doc.iter("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
        t = el.text_content()
        for seg in t.split("\n"):
            out.append(clean_line(seg))
        out.append("")
    return out


# ---------------------------------------------------------------- pdf
def pdf_pages_poppler(path):
    r = subprocess.run(["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True)
    return r.stdout.decode("utf-8", "replace").split("\f")


def pdf_pages_pypdf(path):
    import pypdf
    try:
        rd = pypdf.PdfReader(path)
        return [(p.extract_text() or "") for p in rd.pages]
    except Exception:
        return None


def _variants(tok):
    spots = [m for m in re.finditer(r"هللا|هلل|[اأإآ]ل", tok)]
    for k in range(len(spots), 0, -1):
        for combo in itertools.combinations(spots, k):
            s = tok
            for m in sorted(combo, key=lambda m: -m.start()):
                g = m.group(0)
                rep = {"هللا": "الله", "هلل": "لله"}.get(g, g[::-1])
                s = s[:m.start()] + rep + s[m.end():]
            yield s


def fix_tokens(text, ref):
    ref = re.sub(r"\s+", "", unicodedata.normalize("NFKC", BIDI.sub("", ref)))

    def fix(m):
        tok = m.group(0)
        if not SUSP.search(tok):
            return tok
        core = re.sub(r"[^\u0621-\u064a]", "", tok)
        if core in ref:
            return tok
        for v in _variants(tok):
            vc = re.sub(r"[^\u0621-\u064a]", "", v)
            if vc and vc in ref:
                return v
        return tok
    return re.sub(r"\S+", fix, text)


ARW = re.compile(r"[\u0621-\u064a\u0671-\u06d3]+")


def _vocab(ptext):
    v = set()
    for tok in ARW.findall(unicodedata.normalize("NFKC", BIDI.sub("", ptext))):
        v.add(tok)
        if SUSP.search(tok):
            for x in _variants(tok):
                v.add(x)
    return v


def _split(tok, V):
    if tok in V or len(tok) < 4:
        return tok
    for i in range(2, len(tok) - 1):
        a, b = tok[:i], tok[i:]
        if a in V and b in V:
            return a + " " + b
    return tok


def repair_ar(line, V):
    line = re.sub(r"([\u0621-\u064a])(\d)", r"\1 \2", line)
    line = re.sub(r"(\d)([\u0621-\u064a])", r"\1 \2", line)
    if V:
        line = ARW.sub(lambda m: _split(m.group(0), V), line)
    return line


def pdf_lines(path, arabic=True):
    """Arabic: pypdf text (correct logical order, ligatures and numbers) with word-boundary
    repair against the pdftotext vocabulary of the same page. French: pdftotext."""
    pop = pdf_pages_poppler(path)
    out = []
    if arabic:
        pages = pdf_pages_pypdf(path)
        if pages is None:
            pages = pop
        for i, pg in enumerate(pages):
            V = _vocab(pop[i]) if i < len(pop) else set()
            for line in pg.split("\n"):
                line = clean_line(line)
                if AR.search(line):
                    line = repair_ar(line, V)
                out.append(line)
            out.append("\f")
    else:
        for pg in pop:
            for line in pg.split("\n"):
                out.append(clean_line(line))
            out.append("\f")
    return out


COMMON = set("في من على أو إلى التي الذي رقم أن عن هذا هذه المادة الفصل القانون بتاريخ لا ما مع كل الظهير الشريف وزير".split())


def common_share(lines):
    words = [re.sub(r"[^\u0621-\u064a]", "", w) for l in lines for w in l.split()]
    words = [w for w in words if w]
    if not words:
        return 0.0
    return sum(1 for w in words if w in COMMON or (w[:1] == "و" and w[1:] in COMMON)) / len(words)


def quality(lines):
    """Rough garble score for Arabic text: share of Arabic words with Latin letters inside,
    replacement chars, or isolated single letters."""
    words = [w for l in lines for w in l.split() if AR.search(w)]
    if not words:
        return 0.0, 0
    bad = sum(1 for w in words if re.search(r"[A-Za-z�]", w) or len(w) == 1 and w not in "وأ")
    return bad / len(words), len(words)


def ma_text_is_word(w):
    return len(w) > 1 and AR.search(w) is not None


def acceptable(lines):
    """Heuristic garble detector for Arabic text extracted from PDFs/Word files.
    Returns (ok, reason)."""
    text = "\n".join(lines)
    q, nw = quality(lines)
    if nw < 30:
        return False, "too few Arabic words"
    if re.search(r"afii\d|/g\d{2,}|\ufffd|\ufffc", text):
        return False, "glyph names / replacement chars"
    if q > 0.03:
        return False, "latin/isolated letters %.3f" % q
    cs = common_share(lines)
    if cs < 0.10:
        return False, "common-word share %.3f" % cs
    parens = text.count("(") + text.count(")")
    if parens > 0.08 * nw:
        return False, "parenthesis noise"
    toks = text.split()
    rep = sum(1 for a, b in zip(toks, toks[1:]) if a == b and ma_text_is_word(a))
    if rep > 0.02 * max(1, len(toks)):
        return False, "duplicated tokens (bold overprint)"
    fwd = len(re.findall(r"هذا القانون|المنصوص عليها|الحمد لله|بناء على", text))
    rev = len(re.findall(r"القانون هذا|عليها المنصوص|لله الحمد|على بناء", text))
    if rev > fwd:
        return False, "reversed word order"
    return True, ""
