"""複数の論文を，編集登載の「記事一括アップロード」用の1つの zip にまとめる (手順 6 の準備)．

使い方:
    python bundle.py <作業ディレクトリ> [<作業ディレクトリ> ...] --out <出力先フォルダ>

    例: python bundle.py jstage/work/31_193 jstage/work/42_59 jstage/work/37_37 --out jstage/work/_bundle

出力: <出力先フォルダ>/<資料コード>.zip
    中身は「資料コード/巻/号/記事識別子/」(J-STAGE 操作マニュアル 編集登載編 別紙2)．
    各作業ディレクトリの jstage/ の下 (build.py の出力) を集める．

マニュアルで確かめたこと (編集登載編「13. 記事アップロード」と別紙2．2026-09-19):
    - 1回のアップロードは1つの資料．zip の名前は {資料コード}.zip
    - 巻のフォルダには1つまたは複数の号，号のフォルダには1つまたは複数の記事を入れてよい
    - 複数の巻を1つの zip に入れてよいかは明記が無い．入れると警告を出す (最初は少ない本数で試す)
    - 記事の種類 (通常公開・早期公開・本公開) はアップロード1回につき1つ．公開中の記事の更新は「本公開記事」．
      新しく載せる記事と，公開中の記事の更新は，同じ zip に混ぜない (--kind で区別して別々に作る)
    - アップロードの前に，巻・号を編集登載システムで作っておく
"""
import argparse
import collections
import sys
import zipfile
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("works", nargs="+", help="作業ディレクトリ (build.py を実行ずみのもの)")
    ap.add_argument("--out", required=True, help="zip を書き出すフォルダ")
    ap.add_argument("--kind", choices=["new", "update"], default="update",
                    help="new: 新しく載せる記事 (通常公開)．update: 公開中の記事の更新 (本公開記事)．"
                         "アップロード画面で選ぶ種類の控え．zip の中身は同じ")
    args = ap.parse_args()

    articles = []          # (資料コード, 巻, 号, 記事識別子, 記事フォルダ)
    problems = []
    for w in args.works:
        root = Path(w) / "jstage"
        found = [p for p in root.glob("*/*/*/*") if p.is_dir()]
        if not found:
            problems.append(f"{w}: jstage/ の下に記事が無い (build.py を先に実行する)")
            continue
        for d in found:
            code, vol, iss, art = d.relative_to(root).parts
            if not (d / f"{art}.xml").exists():
                problems.append(f"{d}: {art}.xml が無い")
            if not (d / f"{art}.pdf").exists():
                problems.append(f"{d}: {art}.pdf が無い (build.py に --pdf を渡す)")
            articles.append((code, vol, iss, art, d))

    codes = {a[0] for a in articles}
    if len(codes) > 1:
        problems.append(f"資料コードが複数ある {sorted(codes)}．1つの zip には1つの資料だけを入れる")
    ids = collections.Counter((a[0], a[3]) for a in articles)
    for k, n in ids.items():
        if n > 1:
            problems.append(f"同じ記事識別子が {n} 個ある: {k[1]}")
    if problems:
        print("まとめられない:")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)

    code = codes.pop()
    vols = sorted({a[1] for a in articles}, key=lambda v: (len(v), v))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    zpath = out / f"{code}.zip"
    n_files = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for code_, vol, iss, art, d in sorted(articles, key=lambda a: (int(a[1]), int(a[2]), a[3])):
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    z.write(f, Path(code_, vol, iss, art, f.relative_to(d)))
                    n_files += 1

    print(f"zip: {zpath}  記事 {len(articles)} 本，ファイル {n_files} 個，{zpath.stat().st_size / 1e6:.1f} MB")
    by = collections.defaultdict(list)
    for a in articles:
        by[(a[1], a[2])].append(a[3])
    for (vol, iss), arts in sorted(by.items(), key=lambda kv: (int(kv[0][0]), int(kv[0][1]))):
        print(f"  {vol}巻 {iss}号: {', '.join(sorted(arts))}")
    if len(vols) > 1:
        print(f"注意: 複数の巻 ({', '.join(vols)}) が入っている．マニュアルに明記が無いので，"
              "最初は1巻ずつに分けるか少ない本数で試す")
    kind = "本公開記事 (公開中の記事の更新)" if args.kind == "update" else "通常公開記事 (新しく載せる記事)"
    print(f"アップロード画面で選ぶ種類: {kind}．巻・号は編集登載システムで先に作っておく")


if __name__ == "__main__":
    main()
