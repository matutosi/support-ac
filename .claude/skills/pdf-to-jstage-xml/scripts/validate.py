"""J-STAGE 用の全文 XML を検証する (手順 4: 検証)．

使い方:
    python validate.py <作業ディレクトリ>/out/<記事識別子.xml>

build.py が作った out/manifest.json と <記事識別子>.zip も見る (画像・PDF が zip に入っているか)．

1. DTD (J-STAGE の JATS 1.1) で妥当性を見る．
   DTD 一式は初回だけ https://www.jstage.jst.go.jp/dtds/1.1/ から取り，スキルの dtd/ に置く
   (git では追跡しない．取り直すときは dtd/ を消す)．
2. J-STAGE の独自規則 (「XML データフォーマットガイドライン (JATS1.1 版)」第 2.4 版と
   「メタデータ項目一覧」) のうち，DTD では分からないものを見る．

どちらも通っても，最後は全文 XML 作成ツールの「XML 検証」と「プレビュー」で確かめる．
"""
import posixpath
import re
import time
import sys
import urllib.error
import urllib.request
from pathlib import Path

from lxml import etree

import manifest

SKILL_DIR = Path(__file__).resolve().parent.parent
DTD_DIR = SKILL_DIR / "dtd"
DTD_BASE = "https://www.jstage.jst.go.jp/dtds/1.1/"
DTD_MAIN = "JATS-journalpublishing1.dtd"
NS = {"xlink": "http://www.w3.org/1999/xlink"}


def fetch_dtd(url, tries=4):
    """DTD の一部を取る．404 は None (条件付きで参照されるだけのもの)．
    それ以外の失敗は間を空けて試し直し，最後まで駄目なら止める
    (黙って飛ばすと DTD が欠けたまま残り，次回以降も取り直されないため)．"""
    for i in range(tries):
        try:
            return urllib.request.urlopen(url, timeout=60).read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:  # 通信の失敗
            last = e
        if i < tries - 1:
            time.sleep(2 ** i)
    raise SystemExit(
        f"DTD を取れなかった: {url} ({last})\n"
        "  ネットワークが J-STAGE に出られない環境かもしれない (串やプロキシの遮断)．\n"
        f"  出られるところで一度 validate.py を走らせ，できた {DTD_DIR} をそのまま持ち込めば，\n"
        "  以後は取得せずに検証できる (dtd/ は git では追跡しない)．")


def ensure_dtd():
    pat = re.compile(r'(?:SYSTEM|PUBLIC\s+"[^"]*")\s*"([^"]+\.(?:ent|dtd|mod))"', re.S)
    todo, seen, got, missing = [DTD_MAIN], set(), 0, []
    said = False
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        path = DTD_DIR / f
        if not path.exists():
            data = fetch_dtd(DTD_BASE + f)
            if data is None:
                missing.append(f)   # 404．条件付きで参照されるだけのものは無くてよい
                continue
            if not said:
                print("DTD を J-STAGE から取得する (足りない分だけ)")
                said = True
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            got += 1
        d = posixpath.dirname(f)
        for m in pat.findall(path.read_text(encoding="utf-8", errors="replace")):
            if not m.startswith("http"):
                todo.append(posixpath.normpath(posixpath.join(d, m)))
    if got:
        print(f"  {got} ファイルを取得 (一式 {len(seen) - len(missing)} ファイル)")


def text_len(el):
    return len("".join(el.itertext())) if el is not None else 0


def check_rules(doc, xml_path):
    """DTD で分からない J-STAGE の規則．(重大度, 内容) の列を返す．"""
    errs = []
    r = doc.getroot()
    def need(xpath, msg):
        if not r.xpath(xpath, namespaces=NS):
            errs.append(("エラー", msg))
    need('front/journal-meta/journal-id[@journal-id-type="j-stage"]', "journal-id (j-stage) が無い")
    need("front/journal-meta/issn", "issn が無い")
    need("front/article-meta/title-group/article-title", "記事の表題が無い")
    need("front/article-meta/volume", "巻が無い")
    need("front/article-meta/issue", "号が無い")
    need("front/article-meta/pub-date/year", "発行年が無い")
    if not r.xpath("front/article-meta/fpage|front/article-meta/article-id[@pub-id-type='manuscript']"):
        errs.append(("エラー", "開始ページも論文番号も無い"))
    if r.get("article-type") is None or "要確認" in (r.get("article-type") or ""):
        errs.append(("エラー", "article-type が決まっていない"))

    # 文字数の上限 (メタデータ項目一覧)
    limits = [("front/article-meta/title-group/article-title", 2000, "記事表題"),
              ("front/article-meta/abstract", 4000, "抄録"),
              ("front/article-meta/trans-abstract", 4000, "抄録 (多言語)"),
              ("back/ack", 4000, "謝辞")]
    for xp, n, name in limits:
        for el in r.xpath(xp):
            if text_len(el) > n:
                errs.append(("エラー", f"{name}が {text_len(el)} 字 (上限 {n})"))
    for el in r.xpath("//kwd"):
        if text_len(el) > 1000:
            errs.append(("エラー", f"キーワードが長すぎる: {text_len(el)} 字"))
    for el in r.xpath("back/ref-list/ref/mixed-citation"):
        if text_len(el) > 4000:
            errs.append(("エラー", f"引用文献が 4000 字を超える: {el.getparent().get('id')}"))
    for el in r.xpath("//surname"):
        if re.search(r"[0-9]", el.text or ""):
            errs.append(("エラー", f"姓に半角数字: {el.text}"))

    # body.md・meta.yaml の印 (^上付き^・~下付き~・{{リンク}}) が閉じられず文字のまま残っていないか．
    # J-STAGE の登録版の要旨は上付きを「m^2」と書くので，写すと画面に「^2」が出る
    # (21(2):65 の英文要旨．13(2):87・14(1):61・15(2):125 にもあった．DTD では分からない)
    for el in r.xpath("//front//*[not(*)]|//body//*|//back//*"):
        for s in [el.text or "", el.tail or ""]:
            # URL の中の「~」(「http://www13.ocn.ne.jp/~minnagis/」．22(1):25) は印ではない
            s = re.sub(r"https?://\S+", "", s)
            for mm in re.finditer(r".{0,20}(\^|\{\{|\}\}|(?<![~〜\d])~(?![~〜]))\S{0,20}", s):
                errs.append(("エラー", f"印が文字のまま残っている (閉じ忘れ): …{mm.group(0).strip()}…"))

    # 著作権は日英両方か，どちらも無いか
    for tag in ("copyright-statement", "copyright-holder"):
        langs = {e.get("{http://www.w3.org/XML/1998/namespace}lang") for e in r.xpath(f"//permissions/{tag}")}
        if langs and langs != {"ja", "en"}:
            errs.append(("エラー", f"{tag} は日英両方が要る (いま {sorted(l for l in langs if l)})"))

    # ID の参照
    ids = {e.get("id") for e in r.xpath("//*[@id]")}
    for x in r.xpath("//xref"):
        for rid in (x.get("rid") or "").split():
            if rid not in ids:
                errs.append(("エラー", f"xref の参照先が無い: {rid}"))
    # 画像
    # 画像のありかは build.py の対応表 (manifest.json) で分かる．zip の中の Graphics/ にあるかも見る
    work = manifest.find_work(xml_path)
    m = manifest.read(work) if work and (work / manifest.OUT / manifest.NAME).exists() else None
    if m is None:
        errs.append(("エラー", "out/manifest.json が無い (build.py で組み直す)"))
    srcs = {name: work / src for name, src in m["graphics"]} if m else {}
    in_zip = manifest.zip_names(work, m) if m else None
    if m and in_zip is None:
        errs.append(("エラー", f"{m['article']}.zip が無い (build.py で組み直す)"))
    for g in r.xpath("//graphic|//inline-graphic", namespaces=NS):
        href = g.get("{http://www.w3.org/1999/xlink}href")
        stem = xml_path.stem
        if href and href.startswith(stem + "."):
            errs.append(("エラー", f"本文の画像名は「記事識別子.」で始められない: {href}"))
        # 編集登載編 別紙2: 画像・メディアファイルは「{記事識別子}_{連番}.{拡張子}」(連番は0埋めを勧める)
        if href and not href.startswith("abst-") and g.getparent().tag != "supplementary-material" \
                and not re.fullmatch(re.escape(stem) + r"_\d+\.(jpe?g|gif|png|mp4)", href, re.I):
            errs.append(("エラー", f"画像名が「{stem}_連番.拡張子」の形でない (別紙2): {href}"))
        if g.getparent().tag != "supplementary-material" and href and m:
            if href not in srcs:
                errs.append(("エラー", f"対応表 (manifest.json) に画像が無い: {href}"))
            elif not srcs[href].exists():
                errs.append(("エラー", f"画像の元のファイルが無い: {href} ← {srcs[href]}"))
            if in_zip is not None and f"Graphics/{href}" not in in_zip:
                errs.append(("エラー", f"zip の Graphics/ に画像が無い: {href}"))
        if href and not re.search(r"\.(jpe?g|gif|png)$", href, re.I):
            errs.append(("エラー", f"画像の拡張子は jpg・gif・png だけ: {href}"))
    # 使われていない文献・図表
    cited = {rid for x in r.xpath("//xref") for rid in (x.get("rid") or "").split()}
    for ref in r.xpath("back/ref-list/ref"):
        if ref.get("id") not in cited:
            errs.append(("注意", f"本文から参照されていない文献: {ref.get('id')} "
                         + "".join(ref.itertext())[:50].strip()))
    for f in r.xpath("//fig|//table-wrap"):
        if f.get("id") not in cited:
            errs.append(("注意", f"本文から参照されていない図表: {f.get('id')}"))
    # 番号の付いた式は本文から参照されるはず (番号の無い式は参照されないのがふつう)
    for f in r.xpath("//disp-formula[label]"):
        if f.get("id") not in cited:
            errs.append(("注意", f"本文から参照されていない式: {f.get('id')} {f.findtext('label')}"))
    # ファイル名と zip の中身 (zip の中の記事フォルダ名 = XML のファイル名 = 記事識別子)
    if m:
        if m["article"] != xml_path.stem:
            errs.append(("エラー", f"対応表の記事識別子と XML のファイル名が違う: {m['article']} / {xml_path.stem}"))
        if not m["pdf"]:
            errs.append(("注意", f"全文 PDF が無い (作業ディレクトリに {xml_path.stem}.pdf を置いて組み直す)"))
        if in_zip is not None:
            for need in [f"{xml_path.stem}.xml"] + ([f"{xml_path.stem}.pdf"] if m["pdf"] else []):
                if need not in in_zip:
                    errs.append(("エラー", f"zip の {manifest.prefix(m)}/ に {need} が無い"))
    return errs


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    xml_path = Path(sys.argv[1])
    ensure_dtd()
    dtd = etree.DTD(str(DTD_DIR / DTD_MAIN))
    parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
    try:
        doc = etree.parse(str(xml_path), parser)
    except etree.XMLSyntaxError as e:
        sys.exit(f"XML として読めない: {e}")
    ok = dtd.validate(doc)
    n_err = 0
    if ok:
        print("DTD: 妥当")
    else:
        errs = list(dtd.error_log.filter_from_errors())
        print(f"DTD: {len(errs)} 件のエラー")
        for e in errs[:50]:
            print(f"  {e.line}: {e.message}")
        n_err += len(errs)
    rules = check_rules(doc, xml_path)
    e_rules = [m for s, m in rules if s == "エラー"]
    w_rules = [m for s, m in rules if s == "注意"]
    print(f"J-STAGE の規則: エラー {len(e_rules)} 件，注意 {len(w_rules)} 件")
    for m in e_rules:
        print(f"  エラー: {m}")
    for m in w_rules[:40]:
        print(f"  注意: {m}")
    if len(w_rules) > 40:
        print(f"  (注意はあと {len(w_rules) - 40} 件)")
    n_err += len(e_rules)
    sys.exit(1 if n_err else 0)


if __name__ == "__main__":
    main()
