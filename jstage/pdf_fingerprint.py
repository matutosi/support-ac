"""巻・号の PDF の「体裁」を調べる (どの巻号で組み方が変わったかを二分探索で探すための道具)．

使い方:
    python pdf_fingerprint.py 13 1          # 13 巻 1 号の先頭の論文を調べる
    python pdf_fingerprint.py 31 2 --n 2    # 先頭から 2 本を調べる (号の中のばらつきを見る)
    python pdf_fingerprint.py 13 1 --json   # 機械で読む形で出す

出力 (1 行 1 項目):
    article      記事識別子
    pages        ページ数
    paper        紙の大きさ (mm)．スキャンの PDF はスキャナの紙なので判型とは限らない
    text_area    版面 (本文の入る範囲．mm)
    scanned      yes/no  紙をスキャンした PDF か (ページ全体が1枚の画像で，書体が1種類)
    fonts        使われている書体 (多い順に 5 つまで)
    body_size    本文の字の大きさ (pt)
    columns      段組み (1/2)
    refs_head    引用文献の見出しの文言 (「文献」「引用文献」など)
    category     1ページ目にある原稿種別の文言 (原著論文・総説など．無ければ -)
    doi          1ページ目に DOI が刷られているか
    received     受付日・受理日の書き方 (「1996年6月24日受理」など)

PDF は `jstage/work/_fingerprint/` に取っておき，2回目からは読み直さない (J-STAGE に負荷をかけない)．
"""
import argparse
import json
import re
import statistics
import sys
import urllib.request
from collections import Counter
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from list_articles import entries, squash, NS   # noqa: E402

CACHE = Path(__file__).resolve().parent / "work" / "_fingerprint"
UA = "Mozilla/5.0 (support-ac pdf_fingerprint; +https://github.com/matutosi/support-ac)"
CATEGORIES = ["原著論文", "原著", "総説", "短報", "資料", "特集", "報告", "寄稿", "解説"]
REFS_HEADS = ["引用文献", "文献", "参考文献"]


def article_ids(issn, vol, no, n):
    """その巻号の記事識別子を，先頭から n 件返す．"""
    out = []
    for e in entries(issn, vol, no):
        link = squash(e.findtext("a:article_link/a:ja", "", NS)) or squash(
            e.findtext("a:article_link/a:en", "", NS))
        m = re.search(r"/article/([^/]+)/([^/]+)/([^/]+)/([^/]+)/", link)
        if m:
            out.append(m.groups())        # (資料コード, 巻, 号, 記事識別子)
        if len(out) >= n:
            break
    return out


def fetch_pdf(journal, vol, no, art):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{art}.pdf"
    if not path.exists():
        url = f"https://www.jstage.jst.go.jp/article/{journal}/{vol}/{no}/{art}/_pdf"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        path.write_bytes(urllib.request.urlopen(req, timeout=120).read())
    return path


def fingerprint(path):
    doc = pymupdf.open(path)
    fonts, sizes = Counter(), Counter()
    xs = []
    text_all = []
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for l in b["lines"]:
                t = "".join(s["text"] for s in l["spans"])
                text_all.append(t)
                if len(t.strip()) > 10:
                    xs.append(round(l["bbox"][0]))
                for s in l["spans"]:
                    fonts[s["font"].split("+")[-1]] += len(s["text"])
                    if len(t.strip()) > 20:
                        sizes[round(s["size"], 1)] += len(s["text"])
    text = "\n".join(text_all)
    page1 = doc[0]
    imgs = page1.get_images()
    big = any(w * h > page1.rect.width * page1.rect.height * 0.5
              for w, h in [(i["width"], i["height"]) for i in page1.get_image_info()]) if page1.get_image_info() else False
    scanned = len(fonts) <= 2 and bool(imgs) and big

    # 段組み: 行頭の位置が紙面の左半分と右半分の両方に固まっていれば2段
    mid = page1.rect.width / 2
    cols = 2 if xs and sum(1 for x in xs if x > mid - 10) > len(xs) * 0.2 else 1

    def find(words, where=None):
        """行がまるごとその言葉のものを探す (字間を空けて組まれることがあるので空白は無視)．"""
        src = where if where is not None else text
        for w in words:
            if re.search(r"^\s*" + r"\s*".join(w) + r"\s*$", src, re.M):
                return w
        return "-"

    p1 = page1.get_text().replace("　", "").replace(" ", "")
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日(受理|受付|受領|採用)", p1)
    m2 = re.search(r"(受付|受理|受領|採用)[::]?(\d{4})[-./年]", p1)
    received = (m.group(0) if m else m2.group(0) if m2 else
                ("記載の形が違う" if re.search(r"受理|受付", p1) else "1ページ目に記載なし"))
    # 紙の大きさと版面 (本文の入る範囲)．mm で丸めて返す．スキャンの PDF は
    # 紙の大きさが「スキャナの紙」なので，印刷物の判型とは限らない
    pg = doc[1] if doc.page_count > 1 else doc[0]
    xs, ys = [], []
    for b in pg.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            if len("".join(s["text"] for s in l["spans"]).strip()) < 8:
                continue
            x0, y0, x1, y1 = l["bbox"]
            if y1 < 30 or y0 > pg.rect.height - 30:
                continue
            xs += [x0, x1]
            ys += [y0, y1]
    mm = lambda v: round(v * 25.4 / 72, 1)

    return {
        "pages": doc.page_count,
        "paper": f"{mm(pg.rect.width)}x{mm(pg.rect.height)}mm",
        "text_area": f"{mm(max(xs) - min(xs))}x{mm(max(ys) - min(ys))}mm" if xs else "-",
        "scanned": "yes" if scanned else "no",
        "fonts": ", ".join(f for f, _ in fonts.most_common(5)),
        "n_fonts": len(fonts),
        "body_size": sizes.most_common(1)[0][0] if sizes else None,
        "columns": cols,
        "refs_head": find(REFS_HEADS),
        "category": find(CATEGORIES, page1.get_text()),
        "doi": "yes" if re.search(r"10\.\d{4,5}/", text) else "no",
        "received": received,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("vol")
    ap.add_argument("no", nargs="?")
    ap.add_argument("--issn", default="2189-4809")
    ap.add_argument("--n", type=int, default=1, help="調べる論文の数 (既定 1)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    out = []
    for journal, vol, no, art in article_ids(a.issn, a.vol, a.no, a.n):
        fp = fingerprint(fetch_pdf(journal, vol, no, art))
        fp["article"] = art
        fp["vol"], fp["no"] = vol, no
        out.append(fp)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    for fp in out:
        print(f"=== {fp['vol']}({fp['no']}) {fp['article']}")
        for k in ("pages", "paper", "text_area", "scanned", "fonts", "n_fonts", "body_size", "columns",
                  "refs_head", "category", "doi", "received"):
            print(f"  {k:10s} {fp[k]}")


if __name__ == "__main__":
    main()
