"""preview.py のプレビューを，J-STAGE が作った全文 HTML と単位ごとに比べる (preview.py の確かめ用)．

使い方:
    python compare.py <記事ダウンロードの zip> [--out <出力先>]

記事ダウンロード (形式「J-STAGE」) の zip には，全文 XML の記事なら J-STAGE が作った
<記事識別子>.html (全文 HTML の本体の断片) が入っている．その XML からプレビューを作り，
次の単位で J-STAGE の HTML と比べる: 大見出し・小見出し・本文の段落・本文のリンク・文献・画像・図表の id・目次．

分かっている違い (直さない):
    - 文献: J-STAGE は XML の文字ではなく，登録した文献のデータから組むので，
      「Krieger , A.M.」のように空白が入ったり，XML の「DufrêneMLegendreP1997」が
      「Dufrêne M Legendre P 1997」になったりする (43(1) の 7 本で 5 本)．文献は一致を求めない
    - 目次の「Figures (n)」: J-STAGE では JS が後から足す (保存したページには出ている)．比べない

2026-09-28 に植生学会誌 43(1) の 7 本で，文献を除く全単位が一致した
(見出し・段落・本文のリンク・画像・図表の id・目次)．
"""
import argparse
import difflib
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

from lxml import html

import preview


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def units(root):
    frag = root.xpath("//div[contains(@class,'non-sticky-content')]")[0]
    return {
        "大見出し": [norm(e.text_content()) for e in
                  frag.xpath(".//div[@class='section-title-18' and not(contains(@style,'none'))]")],
        "小見出し": [norm(e.text_content()) for e in frag.xpath(".//span[contains(@class,'global-bold-txt')]")],
        "段落": [norm(e.text_content()) for e in frag.xpath(".//p[contains(@class,'fj-sec-p')]")],
        "本文のリンク": [(e.get("href", "").split("#")[-1], norm(e.text_content())) for e in frag.xpath(
            ".//a[contains(@class,'bluelink-style') and contains(@class,'global-para-14')"
            " and not(ancestor::div[@id='figures-tables-wrap'])]")],
        "文献": [norm(e.text_content()) for e in frag.xpath(".//span[@class='reference-num-txt']")],
        "画像": [e.get("src", "").split("/")[-1] for e in
               frag.xpath(".//div[contains(@class,'global-image-holder')]/img")],
        "図表の id": [e.get("id") for e in frag.xpath(".//div[contains(@class,'global-image-holder')]")],
        "目次": [t for t in (norm(e.text_content()) for e in
                           root.xpath("//ul[@id='article-overiew-section-list']//a")) if t and not t.startswith("Figures")],
    }


def compare(ours_html, js_html, show=5):
    a = units(html.fromstring(ours_html))
    b = units(html.fromstring(js_html))
    ok = True
    for k in a:
        x, y = [str(v) for v in a[k]], [str(v) for v in b[k]]
        same = x == y
        if k != "文献":           # 文献は J-STAGE が組み直すので，一致を求めない (docstring)
            ok &= same
        print(f"  {k}: プレビュー {len(x)} / J-STAGE {len(y)}  {'一致' if same else '違いあり'}")
        if same:
            continue
        n = 0
        for t, i1, i2, j1, j2 in difflib.SequenceMatcher(None, x, y, autojunk=False).get_opcodes():
            if t == "equal":
                continue
            for p, q in zip(x[i1:i2] or [""], y[j1:j2] or [""]):
                ops = [(o, p[max(0, a1 - 15):a2 + 15], q[max(0, b1 - 15):b2 + 15]) for o, a1, a2, b1, b2 in
                       difflib.SequenceMatcher(None, p, q, autojunk=False).get_opcodes() if o != "equal"][:1]
                for o, pp, qq in ops:
                    print(f"      {o}: プレビュー「{pp}」 / J-STAGE「{qq}」")
                n += 1
                if n >= show:
                    break
            if n >= show:
                print("      ...")
                break
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("zip", help="記事ダウンロードの zip (<記事識別子>.html を含むもの)")
    ap.add_argument("--out", default=str(preview.HERE / "out" / "_compare"), help="プレビューの出力先")
    args = ap.parse_args()
    out = Path(args.out)
    base_css = (preview.HERE / "preview.css").read_text(encoding="utf-8")
    n_ok = n = 0
    with zipfile.ZipFile(args.zip) as z:
        htmls = {Path(p).stem: p for p in z.namelist() if p.endswith(".html")}
    for art in preview.read_zip(args.zip):
        if art.id not in htmls:
            print(f"{art.id}: J-STAGE の HTML が無い (全文 XML でない記事)．飛ばす")
            continue
        with zipfile.ZipFile(args.zip) as z:
            js = z.read(htmls[art.id]).decode("utf-8")
        page = preview.write_article(art, out, "ja", None, base_css)
        print(f"== {art.id}")
        n += 1
        n_ok += compare(page.read_text(encoding="utf-8"), js)
    print(f"文献を除いて一致: {n_ok} / {n} 本 (文献の違いは docstring の「分かっている違い」を見る)")
    sys.exit(0 if n and n_ok == n else 1)


if __name__ == "__main__":
    main()
