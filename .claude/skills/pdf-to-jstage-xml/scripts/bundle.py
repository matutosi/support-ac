"""複数の論文を，編集登載の「記事一括アップロード」用の1つの zip にまとめる (手順 6 の準備)．

使い方:
    python bundle.py <作業ディレクトリ> [<作業ディレクトリ> ...] --out <出力先フォルダ>

    例: python bundle.py jstage/work/31/193 jstage/work/42/059 jstage/work/37/037 --out jstage/work/_bundle/trial
        python bundle.py jstage/work/15/* --out jstage/work/_bundle/15

    出力先は巻ごとに jstage/work/_bundle/<巻>/ とする．zip の名前は {資料コード}.zip に決まっている
    ので，同じフォルダへ出すと前の zip を上書きする．

出力: <出力先フォルダ>/<資料コード>.zip
    中身は「資料コード/巻/号/記事識別子/」(J-STAGE 操作マニュアル 編集登載編 別紙2)．
    各作業ディレクトリの out/manifest.json (build.py の出力) をもとに，元のファイルから直接集める．
    まとめた zip は登載が済んだら消してよい (いつでも作り直せる)．

マニュアルで確かめたこと (編集登載編「13. 記事アップロード」と別紙2．2026-09-19):
    - 1回のアップロードは1つの資料．zip の名前は {資料コード}.zip
    - 巻のフォルダには1つまたは複数の号，号のフォルダには1つまたは複数の記事を入れてよい
    - 複数の巻を1つの zip に入れてよいかは明記が無い．入れると警告を出す (最初は少ない本数で試す)
    - 記事の種類 (通常公開・早期公開・本公開) はアップロード1回につき1つ．新しく載せる記事は「通常公開記事」．
      「本公開記事」は早期公開した記事と対になる種類で，植生学会誌では使わない
    - アップロードの前に，巻・号を編集登載システムで作っておく

**公開中の記事は，一括アップロードでは更新できない** (2026-09-28 に 13(1):1 で確かめた)．
「本公開記事」でも「通常公開記事」でも EMSGM183E (対応する記事種別の未公開状態ではありません) で止まる．
公開中の記事は，記事管理の「記事訂正 (履歴なし)」から1本ずつ上げる (SKILL.md の手順 6)．
そのときは各作業ディレクトリの <記事識別子>.zip (build.py の出力) を使えばよく，この zip は要らない．
"""
import argparse
import collections
import sys
import zipfile
from pathlib import Path

import manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("works", nargs="+", help="作業ディレクトリ (build.py を実行ずみのもの)")
    ap.add_argument("--out", required=True, help="zip を書き出すフォルダ")
    ap.add_argument("--kind", choices=["new", "update"], default="new",
                    help="new: 新しく載せる記事 (通常公開記事)．update: 公開中の記事 "
                         "(一括アップロードでは更新できないので，記事訂正で1本ずつ上げるよう案内する)．zip の中身は同じ")
    args = ap.parse_args()

    articles = []          # (資料コード, 巻, 号, 記事識別子, 作業ディレクトリ, 対応表)
    problems = []
    for w in args.works:
        w = Path(w)
        if not (w / manifest.OUT / manifest.NAME).exists():
            problems.append(f"{w}: out/manifest.json が無い (build.py を先に実行する)")
            continue
        m = manifest.read(w)
        art = m["article"]
        if not m["pdf"]:
            problems.append(f"{w}: 全文 PDF が無い (作業ディレクトリに {art}.pdf を置いて build.py をやり直す)")
        for src, name in manifest.members(w, m):
            if not src.exists():
                problems.append(f"{w}: {name} の元のファイルが無い: {src}")
        articles.append((m["journal"], m["volume"], m["issue"], art, w, m))

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
        for code_, vol, iss, art, w, m in sorted(articles, key=lambda a: (int(a[1]), int(a[2]), a[3])):
            n_files += manifest.add_to_zip(z, w, m)

    print(f"zip: {zpath}  記事 {len(articles)} 本，ファイル {n_files} 個，{zpath.stat().st_size / 1e6:.1f} MB")
    by = collections.defaultdict(list)
    for a in articles:
        by[(a[1], a[2])].append(a[3])
    for (vol, iss), arts in sorted(by.items(), key=lambda kv: (int(kv[0][0]), int(kv[0][1]))):
        print(f"  {vol}巻 {iss}号: {', '.join(sorted(arts))}")
    if len(vols) > 1:
        print(f"注意: 複数の巻 ({', '.join(vols)}) が入っている．マニュアルに明記が無いので，"
              "最初は1巻ずつに分けるか少ない本数で試す")
    if args.kind == "update":
        print("注意: 公開中の記事は一括アップロードでは更新できない (EMSGM183E)．この zip は使わず，"
              "記事管理の「記事訂正 (履歴なし)」→ファイルアップロード→「全文XML (ZIP 形式)」で，"
              "各作業ディレクトリの <記事識別子>.zip を1本ずつ上げる．公開日は翌日以降に設定する")
    else:
        print("アップロード画面で選ぶ種類: 通常公開記事 (新しく載せる記事)．巻・号は編集登載システムで先に作っておく")


if __name__ == "__main__":
    main()
