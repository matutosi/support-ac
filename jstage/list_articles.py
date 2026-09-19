"""J-STAGE から学会誌の論文の一覧を取る．

jstage.py (号の目次) と xmltest.py・xmltest_en.py (サイト用の論文リスト) をまとめたもの．

使い方:
    # 号の目次 (記事種別・題名・著者・書誌) を表示する
    python list_articles.py toc vegsci 41 2
    # サイト用の論文リスト (<li> の HTML) を出す．巻・号で絞れる
    python list_articles.py html --lang ja --out list_ja.html
    python list_articles.py html --lang en --vol 41 --no 2

J-STAGE に負荷をかけないよう，1 回の実行で読むページは最小にする
(目次は 1 ページ．一覧は 1000 件ごとに 1 回で，間に 1 秒おく)．
"""
import argparse
import html
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (support-ac list_articles; +https://github.com/matutosi/support-ac)"
API = "https://api.jstage.jst.go.jp/searchapi/do"
NS = {"a": "http://www.w3.org/2005/Atom",
      "os": "http://a9.com/-/spec/opensearch/1.1/",
      "prism": "http://prismstandard.org/namespaces/basic/2.0/"}
PER_PAGE = 1000  # API の上限


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8")


def squash(s):
    """改行・タブ・連続する空白を 1 つの空白にする．"""
    return re.sub(r"\s+", " ", s).strip()


# ---- toc: 号の目次 -------------------------------------------------------

def toc(journal, vol, no, lang):
    from bs4 import BeautifulSoup
    url = f"https://www.jstage.jst.go.jp/browse/{journal}/{vol}/{no}/_contents/-char/{lang}"
    soup = BeautifulSoup(fetch(url), "html.parser")
    for el in soup.select(".section-level1, #search-resultslist-wrap li"):
        if "section-level1" in (el.get("class") or []):
            print(f"\n## {squash(el.get_text())}")
            continue
        def text(sel):
            t = el.select_one(sel)
            return squash(t.get_text(" ")) if t else ""
        print(f"- {text('.searchlist-title')}")
        print(f"  {text('.searchlist-authortags')}")
        print(f"  {text('.searchlist-additional-info')}")


# ---- html: サイト用の論文リスト ------------------------------------------

def entries(issn, vol=None, no=None):
    start = 1
    while True:
        q = {"service": 3, "issn": issn, "count": PER_PAGE, "start": start}
        if vol: q["vol"] = vol
        if no: q["no"] = no
        root = ET.fromstring(fetch(f"{API}?{urllib.parse.urlencode(q)}"))
        status = root.findtext("a:result/a:status", namespaces=NS)
        if status not in (None, "0"):
            sys.exit(f"J-STAGE API のエラー: {status} {root.findtext('a:result/a:message', namespaces=NS)}")
        yield from root.findall("a:entry", NS)
        total = int(root.findtext("os:totalResults", "0", NS))
        start += PER_PAGE
        if start > total:
            break
        time.sleep(1)


def item(e, lang):
    def t(path):
        return squash(e.findtext(path, "", NS))
    title = t(f"a:article_title/a:{lang}")
    if not title:
        return None
    authors = ", ".join(squash(n.text or "") for n in e.findall(f"a:author/a:{lang}/a:name", NS))
    journal = t(f"a:material_title/a:{lang}")
    link = t(f"a:article_link/a:{lang}")
    vol, no, yr = t("prism:volume"), t("prism:number"), t("a:pubyear")
    sp, ep = t("prism:startingPage"), t("prism:endingPage")
    if lang == "ja":
        parts = [f"{title}. {journal}", yr, f"{vol}巻", f"{no}号", f"p.{sp}-{ep}"]
    else:
        parts = [f"{title}. {journal}", yr, f"Volume {vol}", f"Issue {no}", f"Pages {sp}-{ep}"]
    text = ", ".join(([authors] if authors else []) + parts)
    return ('<li style="margin-left: 40px; padding-bottom: 15px;">\n'
            f' <a href="{html.escape(link)}">\n     {html.escape(text)}\n </a>\n</li>')


def html_list(issn, vol, no, lang, out):
    items = [s for s in (item(e, lang) for e in entries(issn, vol, no)) if s]
    body = "\n".join(items) + "\n"
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(body)
        print(f"{len(items)} 件を {out} に書いた", file=sys.stderr)
    else:
        sys.stdout.write(body)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("toc", help="号の目次を表示する")
    p.add_argument("journal", help="資料コード (例: vegsci)")
    p.add_argument("vol"); p.add_argument("no")
    p.add_argument("--lang", choices=["ja", "en"], default="ja")
    p = sub.add_parser("html", help="サイト用の論文リスト (<li>) を出す")
    p.add_argument("--issn", default="2189-4809", help="ISSN (既定: 植生学会誌の電子版)")
    p.add_argument("--vol"); p.add_argument("--no")
    p.add_argument("--lang", choices=["ja", "en"], default="ja")
    p.add_argument("--out", help="書き出すファイル (省略すると標準出力)")
    a = ap.parse_args()
    if a.cmd == "toc":
        toc(a.journal, a.vol, a.no, a.lang)
    else:
        html_list(a.issn, a.vol, a.no, a.lang, a.out)


if __name__ == "__main__":
    main()
