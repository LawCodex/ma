#!/usr/bin/env python3
"""Regenerate README.md counts for the Morocco repository. Usage: python ma_readme.py REPO_DIR"""
import collections
import datetime
import os
import sys

REPO = sys.argv[1]
counts = collections.Counter()
for lang in ("ar", "fr"):
    base = os.path.join(REPO, lang)
    if not os.path.isdir(base):
        continue
    for root, _, files in os.walk(base):
        for f in files:
            if f.endswith(".md"):
                cat = os.path.relpath(root, base).split(os.sep)[0]
                counts[(lang, cat)] += 1
rows = "\n".join("| `%s/%s/` | %d |" % (l, c, n) for (l, c), n in sorted(counts.items()))
total = sum(counts.values())
today = datetime.date.today().isoformat()

README = f"""# Morocco (MA) — legislation as Markdown

Part of [LawCodex](https://github.com/LawCodex): the legislation of every country as plain Markdown in git.

Moroccan constitution, codes, organic laws, laws, dahirs and some decrees, in **Arabic** (`ar/`)
and **French** (`fr/`), as published by the Ministry of Justice legal portal *Adala*
(adala.justice.gov.ma) and the Secrétariat Général du Gouvernement (www.sgg.gov.ma).
Most texts are **consolidated versions** ("صيغة محينة بتاريخ …" / "version consolidée") prepared
by the Ministry of Justice; the consolidation date is in `last_amended`.

**Total: {total} texts** (retrieved {today}).

| Directory | Files |
|---|---|
{rows}

## Structure

```
ar/ constitution/  codes/  organic-laws/  laws/<year>/  dahirs/<year>/  decree-laws/  decrees/<year>/
fr/ constitution/  codes/  lois-organiques/  lois/<year>/  dahirs/<year>/  decrets-lois/  decrets/<year>/
```

* `laws` = laws (قانون رقم / loi n°) promulgated by dahir; file `law-<number>.md` (e.g. `law-103-13.md` = law 103.13).
* `dahirs` = dahirs (ظهير شريف) not tied to a numbered law (incl. dahirs "portant loi"); `dahir-<number>.md`, or the date when unnumbered.
* `codes` = codes (مدونة / مجموعة القانون / Code …), named after the law or dahir number that enacted them.
* `decree-laws` = royal decrees having force of law (مرسوم ملكي بمثابة قانون) and decree-laws.
* Year directories use the Gregorian date of the promulgating dahir/decree (`undated` when it could not be parsed).
* Headings: الكتاب/الجزء (Livre) `##`, القسم (Titre) `###`, الباب (Chapitre) `####`, الفرع/Section `#####`,
  articles (المادة / الفصل / Article) `######`. In texts that number their articles "المادة", "الفصل" is a
  chapter heading; in texts that use "الفصل" for articles (e.g. the Penal Code, the D.O.C.), it is the article.

Front matter: `identifier` is the law/dahir/decree number; `date` the Gregorian date of the promulgating act;
`last_amended` the consolidation date stated by the source; `status` is `unknown` for all texts except the
Constitution, because the sources do not state repeal status; `source` is the official URL and
`archived_source` the Internet Archive capture actually used.

## Sources

The official sites are not reachable from outside Morocco over HTTPS (TCP connection time-outs to
www.sgg.gov.ma:443 and adala.justice.gov.ma) and adala.justice.gov.ma is fronted by an F5 bot-defence
challenge (TSPD). No attempt was made to get around either. Instead, **Internet Archive (Wayback Machine)
captures of the official documents** were used (each file records the original URL and the capture):

* Adala (Ministry of Justice): `reference/adala_v2/ar|fr/*.docx|pdf|doc|htm` (2022 portal) and
  `adala/new_ar_pdf|new_fr_pdf/*.pdf` (consolidated texts, "نصوص قانونية محينة", 2023–2025 portal);
  constitution PDFs (`production/constitution/…`).
* SGG: consolidated texts (`Portals/1|0/textesconsolides/*.pdf`) and the 2011 Constitution PDFs.

## Not covered / known gaps

* Only documents that the Internet Archive captured could be used. The Adala consolidated-texts tree
  lists ~1,545 Arabic documents, of which only a small part is archived; the full Bulletin officiel
  (Arabic/French) is not processed.
* Documents whose text layer is unusable were **skipped rather than published**: scanned PDFs (no OCR),
  PDFs with broken Arabic font encodings (wrong glyph-to-Unicode maps, `afii…` glyph names,
  reversed word order, duplicated "bold" glyph runs). See `scripts/ma_text.py:acceptable()`.
* Jurisprudence, circulars, treaties not attached to an approving dahir/law, and individual regulatory
  decisions (arrêtés) are out of scope.
* Arabic PDF extraction: text comes from pypdf (logical order, correct ligatures); missing word
  separators are restored using poppler's tokenisation of the same page. Minor bidi artefacts
  (e.g. punctuation placement around numbers) remain in some PDF-derived files.
* Status (in force / repealed) is not provided by the sources and is recorded as `unknown`.

## Licence

Moroccan legislation is official text published by the State; Moroccan copyright law (law 2.00,
art. 8) excludes official texts of a legislative, administrative or judicial nature from protection.
The Markdown conversion is published under CC0.

## Regenerate

```
python scripts/ma_fetch.py ../_raw/ma          # Wayback CDX + downloads (resumable)
python scripts/ma_convert.py ../_raw/ma .       # extraction + Markdown
python scripts/ma_readme.py .
```
Requires Python 3 (`scripts/requirements.txt`), poppler-utils (`pdftotext`) and macOS `textutil` for legacy `.doc`.
"""
open(os.path.join(REPO, "README.md"), "w", encoding="utf-8").write(README)
print(total)
