"""記事識別子の対応表を作り，引く (「巻_開始ページ」↔ J-STAGE の記事識別子)．

2000 年代より前の号は，J-STAGE の記事識別子が `13_KJ00006916281` のような NII 由来の形で，
新しい号の `31_193` (巻_開始ページ) と違う．**登載のときは既存の識別子を使う**ので，
こちらを正とし，人が言いやすい「巻_開始ページ」から引けるようにこの対応表を置く．

使い方:
    python article_ids.py update --vol 13        # J-STAGE の API から取り，article_ids.csv を更新する
    python article_ids.py update                 # 巻を指定しなければ全巻 (1000 件ごとに 1 回読む)
    python article_ids.py get 13_1               # 13_KJ00006916281 (巻_開始ページ → 記事識別子)
    python article_ids.py get 13_KJ00006916281   # 13_1 (逆引き)
    python article_ids.py list --vol 13          # その巻の一覧 (短縮形・識別子・ページ・題名)

対応表 `article_ids.csv` の列:
    short (巻_開始ページ), article_id (記事識別子), volume, issue, fpage, lpage, url, title
"""
import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from list_articles import entries, squash, NS   # noqa: E402  (同じディレクトリの取得部を使う)

CSV = Path(__file__).resolve().parent / "article_ids.csv"
COLS = ["short", "article_id", "volume", "issue", "fpage", "lpage", "url", "title"]


def rows_from_api(issn, vol=None):
    for e in entries(issn, vol):
        link = squash(e.findtext("a:article_link/a:ja", "", NS)) or squash(
            e.findtext("a:article_link/a:en", "", NS))
        m = re.search(r"/article/[^/]+/[^/]+/[^/]+/([^/]+)/", link)
        if not m:
            continue
        v = squash(e.findtext("prism:volume", "", NS))
        fp = squash(e.findtext("prism:startingPage", "", NS))
        yield {
            "short": f"{v}_{fp}",
            "article_id": m.group(1),
            "volume": v,
            "issue": squash(e.findtext("prism:number", "", NS)),
            "fpage": fp,
            "lpage": squash(e.findtext("prism:endingPage", "", NS)),
            "url": link,
            "title": squash(e.findtext("a:article_title/a:ja", "", NS))
                     or squash(e.findtext("a:article_title/a:en", "", NS)),
        }


def load():
    if not CSV.exists():
        return {}
    with CSV.open(encoding="utf-8", newline="") as f:
        return {r["article_id"]: r for r in csv.DictReader(f)}


def save(rows):
    with CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, COLS)
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: (int(r["volume"] or 0), int(r["fpage"] or 0))))


def update(issn, vol):
    rows = load()
    n_new = 0
    for r in rows_from_api(issn, vol):
        n_new += r["article_id"] not in rows
        rows[r["article_id"]] = r
    save(rows)
    print(f"{CSV.name}: {len(rows)} 件 (新しく足したもの {n_new} 件)")


def get(key):
    rows = load()
    if key in rows:
        print(rows[key]["short"])
        return
    hit = [r for r in rows.values() if r["short"] == key]
    if not hit:
        sys.exit(f"対応表に無い: {key} (先に `update --vol <巻>` を実行する)")
    if len(hit) > 1:
        sys.exit(f"同じ「巻_開始ページ」が {len(hit)} 件ある: " + ", ".join(r["article_id"] for r in hit))
    print(hit[0]["article_id"])


def show(vol):
    for r in sorted(load().values(), key=lambda r: (int(r["volume"] or 0), int(r["fpage"] or 0))):
        if vol and r["volume"] != str(vol):
            continue
        print(f"{r['short']:>10s}  {r['article_id']:<20s} {r['volume']}({r['issue']}): "
              f"{r['fpage']}-{r['lpage']}  {r['title']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("update", help="J-STAGE の API から対応表を更新する")
    p.add_argument("--issn", default="2189-4809", help="ISSN (既定: 植生学会誌の電子版)")
    p.add_argument("--vol")
    p = sub.add_parser("get", help="短縮形 ↔ 記事識別子を引く")
    p.add_argument("key")
    p = sub.add_parser("list", help="対応表を表示する")
    p.add_argument("--vol")
    a = ap.parse_args()
    if a.cmd == "update":
        update(a.issn, a.vol)
    elif a.cmd == "get":
        get(a.key)
    else:
        show(a.vol)


if __name__ == "__main__":
    main()
