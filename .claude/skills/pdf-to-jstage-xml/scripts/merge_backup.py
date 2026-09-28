"""J-STAGE の現状の控え (記事ダウンロードの zip) から，登録ずみの書誌を meta.yaml に引き継ぐ (手順 0 の続き)．

使い方:
    python merge_backup.py <作業ディレクトリ> <控えの zip>

控えの zip は，編集登載システムの「記事ダウンロード」(形式「J-STAGE」) で落としたもの
(`jstage/work/_backup/<巻>/<号>/download_<日時>.zip`．手順は jstage/backup.md)．
meta.yaml の article_id で記事を探し，次を meta.yaml の末尾の `registered:` に書く
(何度走らせても，その節を置き換えるだけ)．build.py がこの節を XML に出す．

- category    原稿種別 (<subject>)．**控えの値を正とする** (2026-09-28 ユーザ確定)．meta.yaml の category より優先
- manuscript  論文番号 (<article-id pub-id-type="manuscript">．旧号は NII 由来の KJ… の形)
- kana        著者名のカナ (<name xml:lang="ja-Kana">)．meta.yaml の authors と同じ並び．無い著者は null
- approved    最終査読日 (<date date-type="approved">)．'' は「査読済み・日付なし」(日付を空で出す)
- license     認証の状態 (<license license-type>．free・open-access・authentication)

引き継がないもの (J-STAGE の「XML データフォーマットガイドライン (JATS1.1 版)」第 2.4 版による):
- ISSN-L・誌名・略称: ダウンロード時にシステムが自動で書き足すもの (3.1.7)
- custom-meta (els-ncid など): アップロードの仕様 (メタデータ項目一覧) に無い
- 公開日の pub-type="epub-j-stage": 仕様の値は ppub と epub だけ．手元は epub のまま
- 著作権表示の先頭の &copy: ダウンロード時に自動で付くもの．上げ直すときは削除する (3.1.27)
- 引用文献: 正は PDF 版 (控えは件数が少なく，分解も数件だけ)
"""
import argparse
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

import yaml
from lxml import etree

XL = "{http://www.w3.org/XML/1998/namespace}lang"


def text(e):
    return re.sub(r"\s+", " ", "".join(e.itertext())).strip() if e is not None else ""


def norm(s):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "")).lower()


def find_article(src, art_id):
    """控え (zip か展開したディレクトリ) から <記事識別子>.xml の中身を返す．"""
    name = f"{art_id}.xml"
    src = Path(src)
    if src.is_dir():
        hits = list(src.rglob(name))
        return hits[0].read_bytes() if hits else None
    with zipfile.ZipFile(src) as z:
        hits = [n for n in z.namelist() if n.endswith("/" + name) or n == name]
        return z.read(hits[0]) if hits else None


def registered(xml, meta):
    # 控えは &copy; を実体参照のまま使う (DTD を読まないと解決できない) ので，解決せずに読む
    p = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
    am = etree.fromstring(xml, p).find("front/article-meta")
    out = {}

    cat = {s.get(XL): text(s.find("subject")) for s in am.findall("article-categories/subj-group")
           if s.get("subj-group-type") == "article"}
    if cat:
        out["category"] = {lg: cat[lg] for lg in ("ja", "en") if cat.get(lg)}

    ms = am.find("article-id[@pub-id-type='manuscript']")
    if ms is not None and text(ms):
        out["manuscript"] = text(ms)

    # 著者: 控えのカナは姓と名が別々の <name> に分かれている．1人ぶんにまとめて，
    # meta.yaml の著者と和名 (無ければ英語の姓) で対応させる
    bk = []
    for c in am.findall("contrib-group/contrib"):
        d = {"ja": "", "en": "", "kana": ["", ""]}
        # 名前が1言語だけの著者は <name-alternatives> で包まず <name> を直に持つ (13(1):51 の SUBEDI)
        for n in c.findall("name-alternatives/name") + c.findall("name"):
            lg, sur, giv = n.get(XL), text(n.find("surname")), text(n.find("given-names"))
            if lg == "ja-Kana":
                d["kana"] = [sur or d["kana"][0], giv or d["kana"][1]]
            elif lg in ("ja", "en"):
                d[lg] = norm(sur + giv) if lg == "ja" else norm(sur)
        bk.append(d)
    kana, missing = [], []
    for i, a in enumerate(meta.get("authors") or []):
        nj, ne = a["name"].get("ja"), a["name"].get("en")
        hit = next((d for d in bk if nj and d["ja"] and d["ja"] == norm("".join(nj))), None) \
            or next((d for d in bk if ne and d["en"] and d["en"] == norm(ne[0])), None)
        k = hit["kana"] if hit and any(hit["kana"]) else None
        kana.append(k)
        if hit is None:
            missing.append(i + 1)
    if any(kana):
        out["kana"] = kana

    ap = am.find("history/date[@date-type='approved']")
    if ap is not None:
        ymd = [text(ap.find(x)) for x in ("year", "month", "day")]
        out["approved"] = "-".join(f"{int(v):02d}" if j else v for j, v in enumerate(ymd) if v) if ymd[0] else ""

    lic = am.find("permissions/license")
    if lic is not None and lic.get("license-type"):
        out["license"] = lic.get("license-type")
    return out, missing


def write_block(meta_path, block, source):
    """meta.yaml の `registered:` の節を置き換える (無ければ末尾に足す)．ほかの行とコメントは触らない．"""
    raw = meta_path.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"   # 元の改行を保つ (Windows で既定の改行にすると全行が変わる)
    lines = raw.splitlines()
    keep, skip = [], False
    for ln in lines:
        if re.match(r"^registered:", ln) or ln.startswith("# J-STAGE の登録ずみの書誌 (merge_backup.py"):
            skip = True
            continue
        if skip and re.match(r"^\S", ln) and not ln.startswith("#"):
            skip = False
        if not skip:
            keep.append(ln)
    while keep and not keep[-1].strip():
        keep.pop()
    body = yaml.safe_dump({"registered": block}, allow_unicode=True, sort_keys=False, default_flow_style=None)
    keep += ["", f"# J-STAGE の登録ずみの書誌 (merge_backup.py が控え {source} から書いた．build.py が XML に出す)",
             body.rstrip()]
    meta_path.write_bytes((nl.join(keep) + nl).encode("utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("work", help="作業ディレクトリ (meta.yaml のあるところ)")
    ap.add_argument("backup", help="控えの zip (記事ダウンロードで落としたもの) か，それを展開したディレクトリ")
    args = ap.parse_args()
    work = Path(args.work)
    meta_path = work / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    art_id = str(meta.get("article_id") or "")
    xml = find_article(args.backup, art_id)
    if xml is None:
        sys.exit(f"控え {args.backup} に {art_id}.xml が無い (巻号の違う控えではないか)")
    block, missing = registered(xml, meta)
    write_block(meta_path, block, Path(args.backup).name)
    print(f"{art_id}: " + ", ".join(f"{k}={v}" for k, v in block.items()))
    if missing:
        print(f"  注意: 著者 {missing} は控えの著者と対応が取れなかった (カナは null)．PDF と控えで著者が違わないか見る")


if __name__ == "__main__":
    main()
