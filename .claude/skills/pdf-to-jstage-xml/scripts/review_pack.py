"""別のエージェントに検証してもらうための資料を作る (手順 5: 独立検証の準備)．

使い方:
    python review_pack.py <作業ディレクトリ>/out/<記事識別子.xml> --work <作業ディレクトリ> --pdf <論文.pdf>

出力: <作業ディレクトリ>/review/review.md
    XML を人が読める形にしたもの．検証役はこれと PDF のページ画像 (pages/p*.png) だけを見比べる．
    - 本文のリンクは「表示」[→B12 先頭の文字] の形で行き先を示す
    - 引用文献は，分解した結果 (著者・年・題名・誌名・巻・号・ページ・出版社) を並べる
    - 図と表は，番号・図題・画像ファイルの場所・表の中身を示す

検証役には XML を作る途中の資料 (body.md・meta.yaml・report.txt) を渡さない．
作った側の判断に引きずられないようにするため．
"""
import argparse
import re
from pathlib import Path

from lxml import etree

import manifest

XML_NS = "{http://www.w3.org/XML/1998/namespace}"
XLINK = "{http://www.w3.org/1999/xlink}href"


def lang(e):
    return e.get(XML_NS + "lang") or ""


def inline(e, refs):
    """要素の中身を，修飾の印とリンクの行き先つきの文字列にする．"""
    out = [e.text or ""]
    for c in e:
        tag = c.tag
        inner = inline(c, refs)
        if tag == "italic":
            out.append(f"*{inner}*")
        elif tag == "bold":
            out.append(f"**{inner}**")
        elif tag == "sup":
            out.append(f"^{inner}^")
        elif tag == "sub":
            out.append(f"~{inner}~")
        elif tag == "break":
            out.append(" / ")
        elif tag == "xref":
            rid = c.get("rid", "")
            target = refs.get(rid, "")
            out.append(f"「{inner}」[→{rid}{' ' + target if target else ''}]")
        else:
            out.append(inner)
        out.append(c.tail or "")
    return "".join(out)


def ref_summary(ref):
    mc = ref.find("mixed-citation")
    # 著者 (個人と団体) を元の並び順のまま．著者と編者は分けて示す
    def people(kind):
        out = []
        for pg in mc.iter("person-group"):
            if pg.get("person-group-type") != kind:
                continue
            for n in pg:
                if n.tag == "string-name":
                    out.append(" ".join(t for t in (n.findtext("surname"), n.findtext("given-names")) if t))
                elif n.tag == "collab":
                    out.append(f"〔団体〕{n.text or ''}")
        return out
    names = people("author")
    editors = people("editor")
    parts = {
        "区分": mc.get("publication-type", ""),
        "著者": " / ".join(names),
        "編者": " / ".join(editors),
        "年": mc.findtext("year") or "",
        "題名": "".join(mc.find("article-title").itertext()) if mc.find("article-title") is not None else "",
        "誌名・書名": "".join(mc.find("source").itertext()) if mc.find("source") is not None else "",
        "巻": mc.findtext("volume") or "", "号": mc.findtext("issue") or "",
        "ページ": "-".join(t for t in (mc.findtext("fpage"), mc.findtext("lpage")) if t),
        "出版社": " ".join(t for t in (mc.findtext("publisher-name"), mc.findtext("publisher-loc")) if t),
    }
    return "".join(mc.itertext()).strip(), parts


def table_text(tw, refs):
    rows = []
    for tr in tw.iter("tr"):
        cells = []
        for td in tr:
            span = ""
            if td.get("colspan", "1") != "1":
                span += f"〔横{td.get('colspan')}〕"
            if td.get("rowspan", "1") != "1":
                span += f"〔縦{td.get('rowspan')}〕"
            cells.append(span + inline(td, refs).strip())
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xml")
    ap.add_argument("--work", required=True)
    ap.add_argument("--pdf", help="論文の PDF．渡すと検証用に 200dpi のページ画像を review/pages/ に作る")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()
    xml = Path(args.xml).resolve()
    work = Path(args.work).resolve()
    doc = etree.parse(str(xml), etree.XMLParser(load_dtd=False, no_network=True))
    r = doc.getroot()
    # 図表の画像は写していないので，対応表 (manifest.json) で元のファイル (figs/・tables/) を示す
    src = {name: work / f for name, f in manifest.read(work)["graphics"]}
    def img(href):
        return src.get(href, f"(対応表に無い: {href})")

    # リンクの行き先の表示 (文献は先頭 40 字，図表は番号と図題の先頭)
    refs = {}
    for ref in r.iter("ref"):
        refs[ref.get("id")] = "".join(ref.find("mixed-citation").itertext()).strip()[:40]
    for f in list(r.iter("fig")) + list(r.iter("table-wrap")):
        cap = f.find("caption")
        refs[f.get("id")] = (f.findtext("label") or "") + " " + ("".join(cap.itertext())[:20] if cap is not None else "")
    for f in r.iter("disp-formula"):
        refs[f.get("id")] = "式 " + (f.findtext("label") or "")

    pages = work / "pages"
    if args.pdf:
        # 検証役が小さい字まで読めるように，照合用 (100dpi) より細かいページ画像を作る
        import pymupdf
        pages = work / "review" / "pages"
        pages.mkdir(parents=True, exist_ok=True)
        for pg in pymupdf.open(args.pdf):
            pg.get_pixmap(dpi=args.dpi).save(pages / f"p{pg.number + 1:03d}.png")
    o = [f"# 検証用資料: {xml.name}", "",
         f"- PDF のページ画像: `{pages}` (p001.png, p002.png, …)",
         f"- 図表の画像: `{work / 'figs'}`・`{work / 'tables'}`，式の画像: `{work / 'formulas'}`"
         " (図表・式ごとの場所は下に書いた)", ""]

    am = r.find("front/article-meta")
    o += ["## 書誌", ""]
    o.append(f"- 種別: {r.get('article-type')} / " + " / ".join(
        "".join(s.itertext()) for s in am.iter("subject")))
    o.append("- DOI: " + (am.findtext("article-id[@pub-id-type='doi']") or ""))
    tg = am.find("title-group")
    o.append(f"- 題名 ({lang(tg.find('article-title'))}): {inline(tg.find('article-title'), refs)}")
    for tt in tg.iter("trans-title"):
        o.append(f"- 題名 (訳): {inline(tt, refs)}")
    affs = {a.get("id"): " ／ ".join(f"[{lang(x)}] {''.join(x.find('institution').itertext())}"
                                   for x in a.iter("aff")) for a in am.iter("aff-alternatives")}
    for c in am.iter("contrib"):
        names = " ／ ".join(f"[{lang(n)}] {n.findtext('surname')} {n.findtext('given-names')}" for n in c.iter("name"))
        xs = ", ".join(x.get("rid") for x in c.iter("xref"))
        extra = (" 連絡著者" if c.get("corresp") == "yes" else "") + (
            f" {c.findtext('address/email')}" if c.find("address/email") is not None else "")
        o.append(f"- 著者: {names} (所属 {xs}){extra}")
    for k, v in affs.items():
        o.append(f"- 所属 {k}: {v}")
    for pd in am.iter("pub-date"):
        ymd = "-".join(t for t in (pd.findtext("year"), pd.findtext("month"), pd.findtext("day")) if t)
        o.append(f"- 発行日 ({pd.get('pub-type')}): {ymd}")
    o.append(f"- 巻号ページ: {am.findtext('volume')}({am.findtext('issue')}): {am.findtext('fpage')}-{am.findtext('lpage')}")
    for d in am.iter("date"):
        o.append(f"- {d.get('date-type')}: {d.findtext('year')}-{d.findtext('month')}-{d.findtext('day')}")
    for kg in am.iter("kwd-group"):
        # キーワードに <italic> が入ると .text が空になるので，中の字をすべてつなぐ
        o.append(f"- キーワード ({lang(kg)}): " + ", ".join("".join(k.itertext()) for k in kg.iter("kwd")))
    for cs in am.iter("copyright-statement"):
        o.append(f"- 著作権 ({lang(cs)}): {''.join(cs.itertext())}")
    for tag in ("abstract", "trans-abstract"):
        for ab in am.iter(tag):
            o += ["", f"### 要旨 ({lang(ab)})", ""]
            o += [inline(p, refs) + "\n" for p in ab.iter("p")]

    o += ["", "## 本文", ""]

    def walk(e, depth):
        for c in e:
            if c.tag == "sec":
                o.append("#" * (depth + 2) + " " + inline(c.find("title"), refs) if c.find("title") is not None
                         else "#" * (depth + 2) + " (見出しなし)")
                o.append("")
                walk(c, depth + 1)
            elif c.tag == "p":
                o.append(inline(c, refs))
                o.append("")
            elif c.tag == "list":
                for it in c.iter("list-item"):
                    o.append("- " + inline(it.find("p"), refs))
                o.append("")
            elif c.tag == "fig":
                g = c.find("graphic")
                o.append(f"**[図 {c.get('id')}] {c.findtext('label')}** {inline(c.find('caption/p'), refs)}")
                o.append(f"  画像: `{img(g.get(XLINK))}`")
                o.append("")
            elif c.tag == "disp-formula":
                o.append(f"**[式 {c.get('id')}] {c.findtext('label') or '(番号なし)'}**")
                for g in c.findall("graphic"):
                    o.append(f"  画像で掲載: `{img(g.get(XLINK))}`")
                o.append("")
            elif c.tag == "table-wrap":
                o.append(f"**[表 {c.get('id')}] {c.findtext('label')}** {inline(c.find('caption/p'), refs)}")
                for g in c.findall("graphic"):
                    o.append(f"  画像で掲載: `{img(g.get(XLINK))}`")
                if c.find("table") is not None:
                    o.extend([""] + table_text(c.find("table"), refs))
                for p in c.iter("table-wrap-foot"):
                    o.append("  注: " + " ".join(inline(x, refs) for x in p.iter("p")))
                o.append("")
    walk(r.find("body"), 0)

    back = r.find("back")
    if back.find("ack") is not None:
        o += ["## 謝辞", ""] + [inline(p, refs) for p in back.find("ack").iter("p")] + [""]
    o += ["## 引用文献 (元の文と，分解した結果)", ""]
    for ref in back.iter("ref"):
        text, parts = ref_summary(ref)
        o.append(f"- **{ref.get('id')}** {text}")
        o.append("  - " + " ／ ".join(f"{k}: {v}" for k, v in parts.items() if v))
    n_x = len(list(r.iter("xref")))
    o += ["", "## 数", "",
          f"- 段落 {len(list(r.find('body').iter('p')))}，図 {len(list(r.iter('fig')))}，表 {len(list(r.iter('table-wrap')))}，"
          f"式 {len(list(r.iter('disp-formula')))}，"
          f"文献 {len(list(back.iter('ref')))}，リンク {n_x}"]

    out = work / "review"
    out.mkdir(exist_ok=True)
    (out / "review.md").write_text("\n".join(o) + "\n", encoding="utf-8")
    print(f"検証用資料: {out / 'review.md'}")


if __name__ == "__main__":
    main()
