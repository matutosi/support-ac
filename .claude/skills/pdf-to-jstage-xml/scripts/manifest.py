"""登載用の zip に入れるものの対応表 (build.py が書き，bundle.py・validate.py・review_pack.py が読む)．

J-STAGE が求める「資料コード/巻/号/記事識別子/」の入れ子は zip の中の名前にだけ付け，
ディスク上には作らない．PDF と図表の画像も写さず，元のファイルから直接 zip へ入れる．

    <作業ディレクトリ>/out/<記事識別子>.xml   ... 全文 XML
    <作業ディレクトリ>/out/manifest.json      ... この対応表
    <作業ディレクトリ>/<記事識別子>.pdf       ... 全文 PDF (元のファイル．写さない)
    <作業ディレクトリ>/figs/・tables/          ... 図表の画像 (元のファイル．zip の中で改名する)

manifest.json の中身:
    {"journal": "vegsci", "volume": "37", "issue": "1", "article": "37_37",
     "pdf": "37_37.pdf",                                  (作業ディレクトリからの相対パス．無ければ null)
     "graphics": [["37_37_01.png", "figs/fig1.png"], ...]}  (zip の中の名前と元のファイル)
"""
import json
import zipfile
from pathlib import Path

OUT = "out"
NAME = "manifest.json"


def write(work, journal, volume, issue, article, pdf, graphics):
    work = Path(work)
    m = {"journal": journal, "volume": str(volume), "issue": str(issue), "article": article,
         "pdf": rel(work, pdf) if pdf else None,
         "graphics": [[name, rel(work, src)] for name, src in graphics]}
    (work / OUT / NAME).write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return m


def read(work):
    return json.loads((Path(work) / OUT / NAME).read_text(encoding="utf-8"))


def rel(work, p):
    """作業ディレクトリの中なら相対パス，外なら絶対パスで持つ．"""
    p = Path(p).resolve()
    try:
        return p.relative_to(Path(work).resolve()).as_posix()
    except ValueError:
        return str(p)


def prefix(m):
    """zip の中の記事フォルダ「資料コード/巻/号/記事識別子」．"""
    return f"{m['journal']}/{m['volume']}/{m['issue']}/{m['article']}"


def members(work, m=None):
    """zip に入れるもの (元のファイル, 記事フォルダからの名前) を並べる．"""
    work = Path(work)
    m = m or read(work)
    art = m["article"]
    out = [(work / OUT / f"{art}.xml", f"{art}.xml")]
    if m["pdf"]:
        out.append((work / m["pdf"], f"{art}.pdf"))
    out += [(work / src, f"Graphics/{name}") for name, src in m["graphics"]]
    return out


def add_to_zip(z, work, m=None):
    """1本の記事を zip に書く．書いたファイルの数を返す．"""
    m = m or read(work)
    items = members(work, m)
    for src, name in items:
        z.write(src, f"{prefix(m)}/{name}")
    return len(items)


def find_work(xml_path):
    """out/<記事識別子>.xml から作業ディレクトリを返す．"""
    xml_path = Path(xml_path).resolve()
    return xml_path.parent.parent if xml_path.parent.name == OUT else None


def zip_names(work, m):
    """作業ディレクトリの <記事識別子>.zip にある名前 (記事フォルダからの相対)．zip が無ければ None．"""
    zpath = Path(work) / f"{m['article']}.zip"
    if not zpath.exists():
        return None
    pre = prefix(m) + "/"
    with zipfile.ZipFile(zpath) as z:
        return {n[len(pre):] for n in z.namelist() if n.startswith(pre)}
