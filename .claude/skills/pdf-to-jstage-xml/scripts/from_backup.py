"""J-STAGE の現状の控え (記事ダウンロードの zip) から，作業ディレクトリの書誌と PDF を用意する (手順 0: 控えから)．

使い方:
    python from_backup.py <控えの zip> [<控えの zip> ...] [--out <作業ディレクトリ>] [--force]

    例: python from_backup.py jstage/work/_backup/24_1/24_KJ00005989683.zip
        python from_backup.py jstage/work/_backup/32_1/*.zip

控えの zip は `jstage/work/_backup/<巻>_<号>/<記事識別子>.zip` (手順は jstage/backup.md)．
fetch_jstage.py (記事ページから) と merge_backup.py (控えの登録ずみの書誌) の代わりに，これ1本で済む．
**ウェブを読まない** (控えに書誌も引用文献も入っている．2026-09-28 ユーザ指示で 24 巻以降はこちら)．

作業ディレクトリは既定で jstage/work/<巻>/<開始ページ 3 桁>/ (zip が複数のときは --out を使えない)．
書くもの:
    <記事識別子>.pdf  控えの全文 PDF (J-STAGE に載っているもの)．既にあれば触らない
    meta.yaml        書誌．fetch_jstage.py と同じ形に，merge_backup.py の `registered:` の節を足したもの．
                     既にあれば上書きせず meta.backup.yaml に書く (--force で上書き)
    refs_web.txt     J-STAGE に登録ずみの引用文献 (1件1行．末尾の doi: を build.py が文献に付ける)

控えの XML に本文 (<body>) があれば，全文 XML が既に登載されているので止める (--force で続ける)．

meta.yaml に入れないもの (ガイドライン第 2.4 版による．merge_backup.py と同じ):
- 著作権表示の先頭の &copy; (上げ直すと二重になる)・公開日の epub-j-stage (仕様の値は epub)・
  ISSN-L と誌名の略称 (システムが足す)・custom-meta (仕様に無い)
- 所属の <addr-line> (控えでは機関名の写しなどが入っていることがある．住所は PDF を見て addr: に書く)
"""
import argparse
import re
import sys
import zipfile
from pathlib import Path

import yaml
from lxml import etree

import merge_backup

SKILL_DIR = Path(__file__).resolve().parent.parent
REPO = SKILL_DIR.parent.parent.parent          # support-ac
XL = "{http://www.w3.org/XML/1998/namespace}lang"
INLINE = {"italic": "*", "bold": "**", "sup": "^", "sub": "~"}


def parse(xml):
    # 控えは &copy; &nbsp; などの実体参照を DTD なしで使う．読めるように先に文字へ置き換える
    s = xml.decode("utf-8")
    s = s.replace("&copy;", "").replace("&nbsp;", " ")
    p = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, recover=False)
    return etree.fromstring(s.encode("utf-8"), p)


def md(e):
    """要素の中身を body.md と同じ印の文字にする (<italic> → *…*，<break/> → 改行)．"""
    if e is None:
        return None
    out = [e.text or ""]
    for c in e:
        tag = etree.QName(c).localname if isinstance(c.tag, str) else ""
        if tag == "break":
            out.append("\n")
        elif tag in INLINE:
            out.append(INLINE[tag] + md(c) + INLINE[tag])
        else:
            out.append(md(c))
        out.append(c.tail or "")
    return "".join(out)


def clean(s):
    if s is None:
        return None
    lines = [re.sub(r"[ \t　]+", " ", ln).strip() for ln in s.split("\n")]
    s = "\n".join(ln for ln in lines if ln)
    return s or None


def date(e):
    if e is None:
        return None
    y, m, d = (e.findtext(x, "").strip() for x in ("year", "month", "day"))
    if not y:
        return None
    return "-".join([y] + [f"{int(v):02d}" for v in (m, d) if v])


def build_meta(root, prof, source):
    am = root.find("front/article-meta")
    lang = root.get(XL) or am.find("title-group/article-title").get(XL) or "ja"
    tg = am.find("title-group")
    title = {lang: clean(md(tg.find("article-title")))}
    for t in tg.findall("trans-title-group"):
        title[t.get(XL)] = clean(md(t.find("trans-title")))
    title = {"ja": title.get("ja"), "en": title.get("en")}

    # 所属 (機関名だけ．id は控えの aff1 → 1)
    affs, idmap = [], {}
    for aa in am.findall("contrib-group/aff-alternatives") + am.findall("contrib-group/aff"):
        rid = aa.get("id")
        inst = {}
        for a in ([aa] if aa.tag == "aff" else aa.findall("aff")):
            inst[a.get(XL) or lang] = clean(md(a.find("institution")) or md(a))
        idmap[rid] = len(affs) + 1
        affs.append({"id": len(affs) + 1, "ja": inst.get("ja") or "", "en": inst.get("en") or "", "country": "JP"})

    authors = []
    for c in am.findall("contrib-group/contrib"):
        name = {}
        for n in c.findall("name-alternatives/name") + c.findall("name"):
            lg = n.get(XL)
            if lg in ("ja", "en"):
                name[lg] = [clean(md(n.find("surname"))) or "", clean(md(n.find("given-names"))) or ""]
        email = c.findtext("address/email") or c.findtext("email")
        authors.append({"name": name,
                        "aff": [idmap[x.get("rid")] for x in c.findall("xref[@ref-type='aff']") if x.get("rid") in idmap],
                        "corresp": c.get("corresp") == "yes", "email": email.strip() if email else None})

    hist = {d.get("date-type"): date(d) for d in am.findall("history/date")}
    pdates = {d.get("pub-type"): date(d) for d in am.findall("pub-date")}
    kws = {"en": [], "ja": []}
    for g in am.findall("kwd-group"):
        kws.setdefault(g.get(XL) or lang, []).extend(clean(md(k)) for k in g.findall("kwd"))
    abstract = {"ja": None, "en": None}
    for a in am.findall("abstract") + am.findall("trans-abstract"):
        abstract[a.get(XL) or lang] = clean("\n".join(md(p) for p in a.findall("p")))
    cps = {c.get(XL): clean(md(c)) for c in am.findall("permissions/copyright-statement")}
    cph = {c.get(XL): clean(md(c)) for c in am.findall("permissions/copyright-holder")}

    return {
        "source": source,
        "journal": root.findtext("front/journal-meta/journal-id") or prof["journal_id"],
        "article_id": None,                       # 呼ぶ側で入れる
        "article_type": "要確認 (PDF 1ページ目の種別から)",
        "category": {"ja": "要確認", "en": "要確認"},   # 控えの値は registered.category (build.py はそちらを使う)
        "lang": lang,
        "doi": am.findtext("article-id[@pub-id-type='doi']"),
        "volume": am.findtext("volume"), "issue": am.findtext("issue"),
        "fpage": am.findtext("fpage"), "lpage": am.findtext("lpage"),
        "pub_date": {"ppub": pdates.get("ppub"), "epub": pdates.get("epub") or pdates.get("epub-j-stage")},
        "history": {"received": hist.get("received"), "accepted": hist.get("accepted")},
        "title": title,
        "authors": authors,
        "affiliations": affs,
        "keywords": {"en": kws.get("en", []), "ja": kws.get("ja", [])},
        "abstract": abstract,
        "copyright": {"statement": {"ja": cps.get("ja"), "en": cps.get("en")},
                      "holder": {"ja": cph.get("ja") or prof["copyright_holder"]["ja"],
                                 "en": cph.get("en") or prof["copyright_holder"]["en"]}},
        "issn": {"ppub": prof["issn"]["ppub"], "epub": prof["issn"]["epub"]},
    }


def refs_text(root):
    out = []
    for m in root.iter("mixed-citation"):
        t = re.sub(r"\s+", " ", "".join(m.itertext())).strip()
        if t:
            out.append(t)
    return out


def one(zpath, out, force):
    zpath = Path(zpath)
    art = zpath.stem
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
        xn = next((n for n in names if n.endswith(f"/{art}.xml")), None)
        pn = next((n for n in names if n.endswith(f"/{art}.pdf")), None)
        if xn is None:
            sys.exit(f"{zpath}: {art}.xml が無い (記事ごとの控えの zip を渡す)")
        raw = z.read(xn)
        pdf = z.read(pn) if pn else None
    root = parse(raw)
    if root.find("body") is not None and not force:
        print(f"{art}: 控えに本文 (<body>) がある．全文 XML は登載ずみなので飛ばす (--force で続ける)")
        return
    journal = xn.split("/")[0]
    prof = yaml.safe_load((SKILL_DIR / "journals" / f"{journal}.yaml").read_text(encoding="utf-8"))
    rel = zpath.resolve().relative_to(REPO).as_posix() if zpath.resolve().is_relative_to(REPO) else zpath.name
    meta = build_meta(root, prof, rel)
    meta["article_id"] = art
    if out is None:
        out = REPO / "jstage" / "work" / str(meta["volume"]) / f"{int(meta['fpage']):03d}"
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    if pdf is not None and not (out / f"{art}.pdf").exists():
        (out / f"{art}.pdf").write_bytes(pdf)

    head = ("# 書誌 (from_backup.py が J-STAGE の控え (記事ダウンロード) から取ったもの)．\n"
            "# 原稿種別 (article_type) と連絡著者 (corresp・email) は PDF の1ページ目で埋める．\n"
            "# 所属の住所は控えに無いので，紙面にあれば addr: に書く．\n")
    path = out / "meta.yaml"
    if path.exists() and not force:
        path = out / "meta.backup.yaml"
        print(f"{art}: meta.yaml は既にあるので上書きしない (meta.backup.yaml に書いた)")
    path.write_text(head + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")

    # 登録ずみの書誌 (原稿種別・論文番号・カナ・approved・license) は merge_backup.py と同じ節に書く
    block, missing = merge_backup.registered(raw, meta)
    merge_backup.write_block(path, block, rel)

    refs = refs_text(root)
    (out / "refs_web.txt").write_text("\n".join(refs) + "\n", encoding="utf-8")
    ndoi = sum("doi:" in r.lower() for r in refs)
    print(f"{art}: {out}  著者 {len(meta['authors'])}  所属 {len(meta['affiliations'])}  "
          f"引用文献 {len(refs)} 件 (DOI {ndoi})  " + ", ".join(f"{k}" for k in block))
    if missing:
        print(f"  注意: 著者 {missing} のカナが控えと対応しない")
    if len(meta["affiliations"]) and not all(a["ja"] or a["en"] for a in meta["affiliations"]):
        print("  注意: 機関名の空な所属がある．PDF の1ページ目で確かめる")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("zips", nargs="+", help="控えの zip (_backup/<巻>_<号>/<記事識別子>.zip)")
    ap.add_argument("--out", help="作業ディレクトリ (zip が1つのときだけ．既定は jstage/work/<巻>/<開始ページ>/)")
    ap.add_argument("--force", action="store_true", help="meta.yaml を上書きする・本文のある控えも扱う")
    args = ap.parse_args()
    if args.out and len(args.zips) > 1:
        sys.exit("--out は zip が1つのときだけ使える")
    for z in args.zips:
        one(z, args.out, args.force)


if __name__ == "__main__":
    sys.exit(main())
