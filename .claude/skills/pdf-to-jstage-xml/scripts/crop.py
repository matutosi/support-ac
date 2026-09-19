"""PDF の一部を切り出して画像にする (別行立ての式を `formulas/` に入れるときに使う)．

使い方:
    python crop.py <作業ディレクトリ> --page 3 --rect 70,320,300,345 --out formulas/eq1.png

    --page   PDF のページ番号 (1 から数える．`pages/p003.png` の 3)
    --rect   切り出す枠 x0,y0,x1,y1 (pt．PDF の座標．`floats.txt`・`report.txt` の値と同じ)
    --dpi    既定 300 (式は小さいので図 (200) より細かくする)
    --out    作業ディレクトリからの相対パス (無ければ親のフォルダを作る)

式番号 (1) は画像に入れず，body.md の枠に書いて XML の <label> に持たせる
(図題・表題を画像に入れないのと同じ理由．J-STAGE が画像の横に表示する)．
枠の右端を式番号の手前までにすると入らない．
"""
import argparse
from pathlib import Path

import pymupdf



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--pdf", help="既定は <作業ディレクトリ>/<作業ディレクトリ名>.pdf")
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--rect", required=True, help="x0,y0,x1,y1 (pt)")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    work = Path(args.work)
    pdf = Path(args.pdf) if args.pdf else work / f"{work.name}.pdf"
    out = work / args.out
    out.parent.mkdir(parents=True, exist_ok=True)

    rect = pymupdf.Rect(*[float(v) for v in args.rect.split(",")])
    with pymupdf.open(pdf) as doc:
        page = doc[args.page - 1]
        clip = rect & page.rect
        if clip.is_empty:
            raise SystemExit(f"枠がページの外: {tuple(rect)} (ページは {tuple(page.rect)})")
        page.get_pixmap(dpi=args.dpi, clip=clip).save(out)
    print(f"p{args.page} {tuple(round(v) for v in clip)} → {out.relative_to(work)}")


if __name__ == "__main__":
    main()
