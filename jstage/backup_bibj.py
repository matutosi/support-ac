"""J-STAGE にいま載っている状態を，書誌 XML (BIB-J) の登載用 zip として控える．

全文 XML (FULL-J) で記事を更新する前に，もとに戻せるようにするためのもの．
中身は J-STAGE の記事ページ (日英) と J-STAGE の全文 PDF だけから作り，手元の原稿や AI の直しは混ぜない．

    python jstage/backup_bibj.py jstage/work/13/* --out jstage/work/_backup/13

入力 (作業ディレクトリごと):
    web/article_ja.html・web/article_en.html   J-STAGE の記事ページ (fetch_jstage.py が保存したもの)
    <記事識別子>.pdf                            J-STAGE の全文 PDF
    記事ページは新たに読まない (保存ずみのものだけを使う．J-STAGE に負荷をかけない)．

出力 (--out):
    vegsci.zip      編集登載の一括アップロード用 (別紙2 の BIB-J．資料コード/巻/号/記事識別子/ に
                    XML・PDF・全文テキスト)．アップロード画面で選ぶ種類は「本公開記事」
    web/            元にした記事ページの写し (<記事識別子>_ja.html・_en.html)
    README.md       記事の一覧と戻し方

XML に入れるもの: 題名・著者・所属・原稿種別・巻号ページ・日付・DOI・キーワード・抄録 (日英)・
引用文献 (J-STAGE の登録どおりの文字列を <mixed-citation> に)．本文 (<body>) は持たない．
"""
import argparse
import datetime
import hashlib
import html
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pymupdf as fitz
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / ".claude" / "skills" / "pdf-to-jstage-xml" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build  # noqa: E402  (書誌の組み方は全文 XML と同じものを使う)

DOCTYPE = ('<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.1 20151215//EN" '
           '"https://www.jstage.jst.go.jp/dtds/1.1/JATS-journalpublishing1.dtd">')


def web_meta(work, tmp):
    """保存ずみの記事ページから fetch_jstage.py で書誌を作る (ネットワークには出ない)．"""
    ja = (work / "web" / "article_ja.html").read_text(encoding="utf-8")
    url = re.search(r'<meta\s+name="citation_pdf_url"\s+content="([^"]+)/_pdf"', ja).group(1)
    m = re.search(r"/article/([^/]+)/([^/]+)/([^/]+)/([^/]+)$", url)
    shutil.copytree(work / "web", tmp / "web")
    r = subprocess.run([sys.executable, str(SCRIPTS / "fetch_jstage.py"),
                        f"https://www.jstage.jst.go.jp/article/{'/'.join(m.groups())}/_article/-char/ja",
                        "--out", str(tmp)], capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        sys.exit(f"{work}: fetch_jstage.py が失敗した\n{r.stderr}")
    meta = yaml.safe_load((tmp / "meta.yaml").read_text(encoding="utf-8"))
    refs = [x for x in (tmp / "refs_web.txt").read_text(encoding="utf-8").splitlines() if x.strip()]
    return meta, refs, r.stderr.strip()


def realign_authors(work, meta):
    """和文と英文で著者の数が違うときに組み直す．

    J-STAGE の登録では，外国人の著者は英語名だけで和文の並びに無いことがある
    (13(1):51 は和文が「菊池」1人，英文が SUBEDI・KIKUCHI)．fetch_jstage.py は先頭から組にするので
    別人を1人にしてしまう．ここでは和文名を英文の並びの**後ろ**にそろえる (13 巻の2本はこれで合う)．
    合わせたことは戻り値で知らせ，README に残す．
    """
    import fetch_jstage as fj
    a_ja = fj.authors_with_affs(fj.metas((work / "web" / "article_ja.html").read_text(encoding="utf-8")))
    a_en = fj.authors_with_affs(fj.metas((work / "web" / "article_en.html").read_text(encoding="utf-8")))
    if len(a_ja) == len(a_en) or len(a_ja) > len(a_en):
        return None
    off = len(a_en) - len(a_ja)
    affs, aff_ids, authors = [], {}, []
    for i, (name_en, insts_en) in enumerate(a_en):
        name_ja, insts_ja = a_ja[i - off] if i >= off else ("", [])
        ids = []
        for j, inst in enumerate(insts_en or insts_ja):
            inst_en = inst if insts_en else ""
            inst_ja = (insts_ja[j] if j < len(insts_ja) else "") if insts_en else inst
            key = inst_en or inst_ja
            if key not in aff_ids:
                aff_ids[key] = len(affs) + 1
                affs.append({"id": aff_ids[key], "ja": inst_ja, "en": inst_en, "country": "JP"})
            ids.append(aff_ids[key])
        name = {"en": fj.split_en(name_en)}
        if name_ja:
            name["ja"] = fj.split_ja(name_ja)
        authors.append({"name": name, "aff": ids, "corresp": False, "email": None})
    meta["authors"], meta["affiliations"] = authors, affs
    pairs = ", ".join(f"{a_ja[i - off][0]} = {a_en[i][0]}" for i in range(off, len(a_en)))
    only_en = ", ".join(a_en[i][0] for i in range(off))
    return f"和文 {len(a_ja)} 人・英文 {len(a_en)} 人．{pairs}．英語名だけ: {only_en}"


def subtitle(work, lang):
    s = (work / "web" / f"article_{lang}.html").read_text(encoding="utf-8")
    m = re.search(r'class="global-article-subtitle">([^<]*)<', s)
    return html.unescape(m.group(1)).strip() if m and m.group(1).strip() else None


def build_xml(work, meta, refs, prof):
    cat = subtitle(work, "ja")
    types = prof.get("article_types") or {}
    t = types.get(cat) or {}
    meta["category"] = {"ja": cat, "en": subtitle(work, "en") or t.get("en")}
    meta["article_type"] = t.get("type", "other")
    front = build.build_front(meta, prof, [], [], {})
    # 所属の国は記事ページに無い (build_front は既定で「日本」を入れる)．控えには入れない
    front = re.sub(r"<country [^>]*>[^<]*</country>", "", front)
    back = ""
    if refs:
        # 題は紙面の見出しでなく J-STAGE の記事ページの呼び名 (「参考文献」) に合わせる
        back = ("<back>\n<ref-list><title>参考文献</title>\n"
                + "\n".join(f'<ref id="B{i}"><mixed-citation>{build.esc(x)}</mixed-citation></ref>'
                            for i, x in enumerate(refs, 1))
                + "\n</ref-list>\n</back>")
    lang = meta.get("lang", "ja")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n' + DOCTYPE + "\n"
            '<article xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:mml="http://www.w3.org/1998/Math/MathML" xmlns:xlink="http://www.w3.org/1999/xlink" '
            'xmlns:ali="http://www.niso.org/schemas/ali/1.0/" '
            f'xml:lang="{lang}" dtd-version="1.1" article-type="{build.attr(meta["article_type"])}">\n'
            f"{front}\n{back}\n</article>\n")


def pdf_text(pdf):
    with fitz.open(pdf) as d:
        return "\n".join(p.get_text() for p in d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("works", nargs="+", help="作業ディレクトリ (web/ と <記事識別子>.pdf があるもの)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = Path(args.out)
    (out / "web").mkdir(parents=True, exist_ok=True)

    arts = []
    for w in map(Path, args.works):
        if not (w / "web" / "article_ja.html").exists():
            continue
        with tempfile.TemporaryDirectory() as t:
            meta, refs, _ = web_meta(w, Path(t))
        warn = realign_authors(w, meta)
        prof = yaml.safe_load((SCRIPTS.parent / "journals" / f"{meta['journal']}.yaml").read_text(encoding="utf-8"))
        art = meta["article_id"]
        pdf = w / f"{art}.pdf"
        if not pdf.exists():
            sys.exit(f"{w}: J-STAGE の全文 PDF {pdf.name} が無い")
        xml = build_xml(w, meta, refs, prof)
        txt = pdf_text(pdf)
        for lg in ("ja", "en"):
            shutil.copy2(w / "web" / f"article_{lg}.html", out / "web" / f"{art}_{lg}.html")
        arts.append(dict(meta=meta, art=art, xml=xml, txt=txt, pdf=pdf, n_refs=len(refs), warn=warn))

    arts.sort(key=lambda a: (int(a["meta"]["volume"]), int(a["meta"]["issue"]), int(a["meta"]["fpage"])))
    code = {a["meta"]["journal"] for a in arts}
    if len(code) != 1:
        sys.exit(f"資料コードが1つでない: {sorted(code)}")
    code = code.pop()
    zpath = out / f"{code}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for a in arts:
            m = a["meta"]
            p = f"{code}/{m['volume']}/{m['issue']}/{a['art']}/{a['art']}"
            z.writestr(p + ".xml", a["xml"])
            z.writestr(p + ".txt", a["txt"])
            z.write(a["pdf"], p + ".pdf")

    rows, notes = [], []
    for a in arts:
        if a["warn"]:
            notes.append(f"- {a['art']}: {a['warn']}")
        m = a["meta"]
        md5 = hashlib.md5(a["pdf"].read_bytes()).hexdigest()[:8]
        rows.append(f"| {a['art']} | {m['volume']}({m['issue']}): {m['fpage']}-{m['lpage']} | "
                    f"{m['category']['ja']} | {m['title']['ja'] or m['title']['en']} | {a['n_refs']} | "
                    f"{len(a['txt'].strip())} | {md5} |")
        if a["warn"]:
            print(f"{a['art']}: {a['warn']}")
    today = datetime.date.today().isoformat()
    readme = f"""# J-STAGE の現状の控え ({code}．{today} に作成)

全文 XML で記事を更新する前の，J-STAGE に載っている状態の控え．
`jstage/backup_bibj.py` が，保存ずみの J-STAGE の記事ページ (`web/`) と J-STAGE の全文 PDF だけから作った．

- `{code}.zip` … 編集登載の一括アップロード用 (別紙2 の BIB-J)．記事ごとに XML (書誌のみ)・PDF・全文テキスト
- `web/` … 元にした記事ページ (日英) の写し

| 記事識別子 | 巻号ページ | 種別 | 題名 | 文献 | 全文テキストの字数 | PDF の md5 |
|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## 和文と英文で著者の数が違った記事

J-STAGE の登録では外国人の著者が英語名だけのため，和文名を英文の並びの後ろにそろえて組にした．

{chr(10).join(notes) or "- なし"}

## もとに戻すとき (人間が行う)

1. 編集登載システムの「一括記事アップロード」で `{code}.zip` を上げる．記事の種類は「本公開記事」
   (公開中の記事の更新)．zip の名前は `{code}.zip` のまま変えない．
2. 上げる前に，XML を全文 XML 作成ツールの「XML 検証」で確かめておくとよい．

## 限界

- 記事ページに出ていない項目 (J-STAGE の内部の管理項目など) は控えられない．
  完全な控えが要るなら，編集登載システムに登録データを書き出す機能があるかを確かめる．
- 引用文献は J-STAGE の登録どおりの文字列 (`<mixed-citation>`) で，著者・年などに分けていない．
- 全文テキストは PDF の文字の層から取った (スキャンの PDF は OCR の結果)．
"""
    (out / "README.md").write_text(readme, encoding="utf-8")
    print(f"zip: {zpath}  記事 {len(arts)} 本，{zpath.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
