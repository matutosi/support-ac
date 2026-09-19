"""J-STAGE の記事ページから書誌と引用文献を取る (手順 0: 取得)．

使い方:
    python fetch_jstage.py <記事の URL> --out <作業ディレクトリ>
    python fetch_jstage.py --journal vegsci --volume 31 --issue 2 --fpage 193 --out <作業ディレクトリ>

記事ページを日本語版・英語版で1回ずつ読むだけにする (J-STAGE に負荷をかけない)．
読んだページは <作業ディレクトリ>/web/ に保存し，2回目からはそれを使う (--refresh で取り直す)．

出力:
    meta.yaml       書誌 (題名・著者・所属・巻号・日付・DOI・キーワード・英文要旨・著作権)
    refs_web.txt    J-STAGE に登録ずみの引用文献 (1件1行)
"""
import argparse
import html
import re
import sys
import time
import urllib.request
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (pdf-to-jstage-xml; +https://www.jstage.jst.go.jp)"


def fetch(url, path, refresh):
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    s = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
    path.write_text(s, encoding="utf-8")
    time.sleep(1)
    return s


def metas(s):
    """<meta name=... content=...> を (name, 値) の列で返す．"""
    return [(k, html.unescape(v).strip()) for k, v in
            re.findall(r'<meta\s+name="([^"]+)"\s+content="([^"]*)"', s)]


def first(ms, key):
    return next((v for k, v in ms if k == key), None)


def authors_with_affs(ms):
    """authors と authors_institutions の並びから，著者ごとの所属の列を作る．"""
    out = []
    for k, v in ms:
        if k == "authors":
            out.append([v, []])
        elif k == "authors_institutions" and out:
            out[-1][1].append(v)
    return out


def split_ja(name):
    parts = name.split()
    return [parts[0], " ".join(parts[1:])] if len(parts) > 1 else [name, ""]


def split_en(name):
    """「Toshikazu MATSUMURA」→ [MATSUMURA, Toshikazu]．大文字だけの語を姓とみなす．"""
    words = name.split()
    sur = [w for w in words if len(w) > 1 and w.upper() == w and re.search(r"[A-Z]", w)]
    if not sur:
        return [words[-1], " ".join(words[:-1])]
    given = [w for w in words if w not in sur]
    return [" ".join(sur), " ".join(given)]


def ymd(s):
    return s.replace("/", "-") if s else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?")
    ap.add_argument("--journal", default="vegsci")
    ap.add_argument("--volume")
    ap.add_argument("--issue")
    ap.add_argument("--fpage")
    ap.add_argument("--out", required=True)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    if args.url:
        m = re.search(r"/article/([^/]+)/([^/]+)/([^/]+)/([^/]+)/", args.url)
        if not m:
            sys.exit("記事の URL の形が違う (例: https://www.jstage.jst.go.jp/article/vegsci/31/2/31_193/_article/-char/ja)")
        journal, vol, issue, art = m.groups()
    else:
        journal, vol, issue = args.journal, args.volume, args.issue
        art = f"{vol}_{args.fpage}"
    base = f"https://www.jstage.jst.go.jp/article/{journal}/{vol}/{issue}/{art}/_article/-char/"

    out = Path(args.out)
    (out / "web").mkdir(parents=True, exist_ok=True)
    ja = metas(fetch(base + "ja", out / "web" / "article_ja.html", args.refresh))
    en = metas(fetch(base + "en", out / "web" / "article_en.html", args.refresh))
    s_ja = (out / "web" / "article_ja.html").read_text(encoding="utf-8")

    prof = yaml.safe_load((SKILL_DIR / "journals" / f"{journal}.yaml").read_text(encoding="utf-8"))

    # 著者と所属 (日英は同じ並びで載っている)
    a_ja, a_en = authors_with_affs(ja), authors_with_affs(en)
    affs, aff_ids, authors = [], {}, []
    for i, (name_ja, insts_ja) in enumerate(a_ja):
        name_en, insts_en = a_en[i] if i < len(a_en) else ("", [])
        ids = []
        for j, inst in enumerate(insts_ja):
            inst_en = insts_en[j] if j < len(insts_en) else ""
            if inst not in aff_ids:
                aff_ids[inst] = len(affs) + 1
                affs.append({"id": aff_ids[inst], "ja": inst, "en": inst_en, "country": "JP"})
            ids.append(aff_ids[inst])
        authors.append({"name": {"ja": split_ja(name_ja), "en": split_en(name_en)},
                        "aff": ids, "corresp": False, "email": None})

    # 受付日・受理日は本文の表示から取る (meta には無い)
    def date_of(label):
        m = re.search(label + r"[:：]\s*(\d{4}/\d{2}/\d{2})", re.sub(r"<[^>]+>", " ", s_ja))
        return ymd(m.group(1)) if m else None

    kw = [v for k, v in en if k == "keywords"] or [v for k, v in ja if k == "citation_keywords"]
    # キーワードの言語: 英字だけなら en
    kw_en = [k for k in kw if re.fullmatch(r"[\x00-\x7f]+", k)]
    kw_ja = [k for k in kw if k not in kw_en]

    lang = first(ja, "language") or "ja"
    cat = None  # 原稿種別は J-STAGE のページに無いので，PDF (extract.py) から入れる
    meta = {
        "source": base + "ja",
        "journal": journal,
        "article_id": art,          # J-STAGE の記事識別子 (旧号は 13_KJ00006916281 のような形)
        "article_type": "要確認 (PDF 1ページ目の種別から)",
        "category": {"ja": cat or "要確認", "en": "要確認"},
        "lang": lang,
        "doi": first(ja, "doi"),
        "volume": first(ja, "volume"), "issue": first(ja, "issue"),
        "fpage": first(ja, "firstpage"), "lpage": first(ja, "lastpage"),
        "pub_date": {"ppub": ymd(first(ja, "publication_date")), "epub": ymd(first(ja, "online_date"))},
        "history": {"received": date_of("受付日"), "accepted": date_of("受理日")},
        "title": {"ja": first(ja, "title"), "en": first(en, "title")},
        "authors": authors,
        "affiliations": affs,
        "keywords": {"en": kw_en, "ja": kw_ja},
        "abstract": {"ja": first(ja, "abstract"), "en": first(en, "abstract")},
        "copyright": {"statement": {"ja": first(ja, "copyright"), "en": first(en, "copyright")},
                      "holder": {"ja": first(ja, "copyright_owner") or prof["copyright_holder"]["ja"],
                                 "en": first(en, "copyright_owner") or prof["copyright_holder"]["en"]}},
        "issn": {"ppub": first(ja, "print_issn"), "epub": first(ja, "online_issn")},
    }
    if meta["title"]["en"] == meta["title"]["ja"]:
        meta["title"]["en"] = None
    head = ("# 書誌 (fetch_jstage.py が J-STAGE の記事ページから取ったもの)．\n"
            "# 原稿種別 (article_type・category) と連絡著者 (corresp・email) は PDF の1ページ目で埋める．\n"
            "# abstract.ja は段落の区切りが失われているので，body.md の「# 摘要」があればそちらを使う．\n")
    path = out / "meta.yaml"
    if path.exists() and not args.refresh:
        path = out / "meta.web.yaml"
        print("meta.yaml は既にあるので上書きしない (meta.web.yaml に書いた)")
    path.write_text(head + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=1000),
                    encoding="utf-8")

    refs = [v for k, v in ja if k == "references"]
    (out / "refs_web.txt").write_text("\n".join(refs) + "\n", encoding="utf-8")
    print(f"書誌: {path}  著者 {len(authors)}  所属 {len(affs)}  引用文献 {len(refs)} 件")


if __name__ == "__main__":
    sys.exit(main())
