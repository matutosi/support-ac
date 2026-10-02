"""済んだ全文 XML の引用文献の和名を，姓と名に分け直す (登載用の zip の中の XML を直接直す)．

使い方:
    python fix_ja_names.py <zip か xml> ... --root <作業の根>            # 直す件数を出すだけ
    python fix_ja_names.py <zip か xml> ... --root <作業の根> --write    # 書き換える

決めごと (2026-09-28 ユーザ確定．2026-10-03 に 13(1) 以外へ広げた):
引用文献の和名は，姓と名が分かれば <surname>・<given-names> に分け，後ろの句読点は名前に入れない．
紙面の文字は変えない (空白を足さない)．build.py の tag_ja_name と同じ規則で，
- 名前の中に空白があれば，そこで分ける (「宮脇　昭」)
- 空白が無ければ，著者の和名の辞書にあるものだけ分ける (「遠山三樹夫」→ 遠山 / 三樹夫)
- 和名の後ろの「.」「,」(「飯泉茂.」) は名前の外に出す
辞書は，作業の根の _backup (J-STAGE の控え．13〜43 巻) と _bundle の XML の著者欄，
各作業ディレクトリの meta.yaml の著者欄から作る．
作業ディレクトリが手元に無い号 (13〜20・22・23 巻) は build.py で組み直せないので，これで直す．
"""
import argparse
import glob
import re
import zipfile
from pathlib import Path

import yaml

JA = re.compile(r"[ぁ-ゖァ-ヺ一-鿿々]")
AUTHOR = re.compile(r'<name name-style="eastern" xml:lang="ja">\s*<surname>([^<]+)</surname>\s*'
                    r'<given-names>([^<]+)</given-names>')
SINGLE = re.compile(r'<string-name name-style="eastern" xml:lang="ja"><surname>([^<]*)</surname></string-name>')


def xml_in_zip(path):
    with zipfile.ZipFile(path) as z:
        n = next(k for k in z.namelist() if k.endswith(".xml"))
        return n, z.read(n).decode("utf-8")


def load_known(root):
    """和名の辞書 {姓名: (姓, 名)}．build.py の KNOWN_JA と同じ形．"""
    known = {}
    root = Path(root)
    for z in glob.glob(str(root / "_backup" / "*" / "*.zip")) + glob.glob(str(root / "_bundle" / "*" / "*.zip")):
        try:
            _, x = xml_in_zip(z)
        except Exception:
            continue
        for s, g in AUTHOR.findall(x):
            s, g = s.strip(), g.strip()
            if s and g:
                known.setdefault(s + g, (s, g))
    for p in root.glob("*/*/meta.yaml"):
        try:
            m = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        for a in m.get("authors") or []:
            nj = (a.get("name") or {}).get("ja")
            if nj and len(nj) == 2 and nj[0] and nj[1]:
                known.setdefault(nj[0] + nj[1], (nj[0], nj[1]))
    return known


def fix_name(m, known, log):
    name = m.group(1)
    trail = ""
    t = re.match(r"^(.*?)([．.，,]+)$", name)
    # 和名の後ろの句読点だけ外に出す．英文のイニシャル「B.A.」「ブラウン-ブランケ，J．」の点は名前の一部なので触らない
    if t and JA.search(t.group(1)) and not re.search(r"[A-Za-zＡ-Ｚａ-ｚ]$", t.group(1)):
        name, trail = t.group(1), t.group(2)
    core = name.strip()
    parts = re.split(r"[\s　]+", core, maxsplit=1)
    if JA.search(core) and len(parts) == 2:
        sur, giv = parts
        sep = core[len(sur):len(core) - len(giv)]
    elif core in known:
        sur, giv = known[core]
        sep = ""
    elif trail:
        log.append(f"句読点: {m.group(1)}")
        return f'<string-name name-style="eastern" xml:lang="ja"><surname>{name}</surname></string-name>{trail}'
    else:
        return m.group(0)
    log.append(f"{m.group(1)} → {sur} / {giv}" + (f" ({trail} を外へ)" if trail else ""))
    return (f'<string-name name-style="eastern" xml:lang="ja"><surname>{sur}</surname>{sep}'
            f'<given-names>{giv}</given-names></string-name>{trail}')


def fix_xml(x, known, log):
    head, sep, refs = x.partition("<ref-list")
    if not sep:
        return x
    return head + sep + SINGLE.sub(lambda m: fix_name(m, known, log), refs)


def text_of(x):
    return re.sub(r"<[^>]+>", "", x)


def rewrite_zip(path, name, new):
    path = Path(path)
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for info in zin.infolist():
            data = new.encode("utf-8") if info.filename == name else zin.read(info.filename)
            zout.writestr(info, data)
    tmp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--root", required=True, help="作業の根 (_backup・_bundle・<巻>/<開始ページ>/ のある所)")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    known = load_known(a.root)
    print(f"和名の辞書: {len(known)} 人")
    total = 0
    for f in a.files:
        is_zip = f.lower().endswith(".zip")
        name, x = xml_in_zip(f) if is_zip else (None, Path(f).read_text(encoding="utf-8"))
        log = []
        new = fix_xml(x, known, log)
        assert text_of(new) == text_of(x), f"文字が変わった: {f}"
        total += len(log)
        print(f"{f}: {len(log)} 件")
        if a.write and new != x:
            if is_zip:
                rewrite_zip(f, name, new)
            else:
                Path(f).write_text(new, encoding="utf-8")
    print(f"計 {total} 件" + ("．書き換えた" if a.write else "．--write で書き換える"))


if __name__ == "__main__":
    main()
