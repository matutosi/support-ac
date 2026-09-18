"""PDF の表の範囲から，文字の位置で行と列を推定して JATS の <table> の下書きを作る．

使い方:
    python table_draft.py <論文.pdf> <ページ番号> [--clip x0,y0,x1,y1] [--skip-top N]
                          [--no-merge] [--cols x,x,...] [--key-col K]

    --clip      表の範囲 (pt)．extract.py の report.txt の「tableN の枠」をもとに，見出しを除いて渡す
    --skip-top  上から N 行を捨てる (キャプションや見出しの行．見出しは手で組むほうが早い)
    --no-merge  左端の列が空の行を前の行につながない (統計表のように左端を空けた行があるとき)
    --cols      列の始まり (pt) を手で与える．まばらな列 (最初の行にだけ湖名がある列など) を拾えないとき
    --key-col   この列 (0 始まり) の値ごとに1行とする．その値の高さの範囲にある語を集め，
                短い値の2段 (表層/底層など) は <break/> で1セルに収め，長い文は1行につなぐ
    --next-clip 見開きの表: 次のページのこの範囲も読み，同じ高さの行を右につなぐ
                (植生学会誌 37(1) 表2 は，左ページに行の見出しと6湖，右ページに残りの15湖がある)

出力は標準出力．見出し (thead) と脚注は，tables/tableN.png を見て手で直す．
斜体の書体の字の並びは *…* にする (学名のため)．
"""
import argparse
import html
import re

import pymupdf

JA = re.compile(r"[　-鿿＀-￯]")


def words_with_italic(page, clip):
    """語の列 (x0, y0, x1, y1, 文字列) を返す．斜体の字の並びは *…* で囲む．"""
    out = []
    for b in page.get_text("rawdict", clip=clip)["blocks"]:
        for l in b.get("lines", []):
            chars = []   # (字, 斜体か, bbox)

            def flush():
                if not chars:
                    return
                s, prev = "", False
                for c, it, _ in chars:
                    if it != prev:
                        s += "*"
                        prev = it
                    s += c
                if prev:
                    s += "*"
                x0 = min(c[2][0] for c in chars)
                y0 = min(c[2][1] for c in chars)
                x1 = max(c[2][2] for c in chars)
                y1 = max(c[2][3] for c in chars)
                out.append((x0, y0, x1, y1, s))
                chars.clear()

            for sp in l["spans"]:
                it = "Italic" in sp["font"] or "Oblique" in sp["font"]
                for c in sp["chars"]:
                    if not c["c"].strip():
                        flush()
                        continue
                    if pymupdf.Rect(c["bbox"]).intersects(clip):
                        chars.append((c["c"], it, c["bbox"]))
            flush()
    return out


def join_text(a, b):
    """セルの中の折り返しをつなぐ (和文は詰める，行末のハイフンは外す，欧文は空白)．"""
    if not a:
        return b
    a2 = a.rstrip("*") if a.endswith("*") and b.startswith("*") else a
    b2 = b[1:] if a2 != a else b
    if a2.endswith("-") and len(a2) > 1 and a2[-2].islower() and b2[:1].islower():
        return a2[:-1] + b2
    if JA.search(a2[-1:]) or JA.search(b2[:1]):
        return a2 + b2
    return a2 + " " + b2


def detect_columns(rows, clip, col_gap):
    """多くの行で文字の無い縦の帯を列の切れ目とみなす (横に長い行は数えない)．"""
    x0, x1 = int(clip.x0), int(clip.x1) + 1
    body = [r for r in rows if (r[-1][2] - r[0][0]) < (clip.width * 0.9) or len(r) > 3]
    cover = [0] * (x1 - x0 + 1)
    for r in body:
        for w in r:
            for x in range(int(w[0]) - x0, int(w[2]) - x0 + 1):
                if 0 <= x < len(cover):
                    cover[x] += 1
    limit = max(1, len(body) * 0.08)
    cols, in_gap, gap_w = [], True, 0
    for k, c in enumerate(cover):
        if c <= limit:
            in_gap, gap_w = True, gap_w + 1
        else:
            if in_gap and (gap_w >= col_gap / 2 or not cols):
                cols.append(x0 + k)
            in_gap, gap_w = False, 0
    return cols or [x0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("page", type=int)
    ap.add_argument("--clip")
    ap.add_argument("--skip-top", type=int, default=0)
    ap.add_argument("--col-gap", type=float, default=10, help="列の切れ目とみなす空白の幅 (pt) の2倍")
    ap.add_argument("--row-tol", type=float, default=3)
    ap.add_argument("--no-merge", action="store_true")
    ap.add_argument("--cols")
    ap.add_argument("--key-col", type=int)
    ap.add_argument("--next-clip")
    args = ap.parse_args()
    doc = pymupdf.open(args.pdf)
    left = draft(doc[args.page - 1], args.clip, args)
    if not args.next_clip:
        emit([c for _, c in left[1]], left[0])
        return
    right = draft(doc[args.page], args.next_clip, args)
    # 同じ高さの行どうしを横につなぐ (片方にしか無い行は空のセルで埋める)
    nl, nr = len(left[0]), len(right[0])
    rows, used = [], set()
    for y, cells in left[1]:
        j = min(range(len(right[1])), key=lambda k: abs(right[1][k][0] - y), default=None)
        if j is not None and abs(right[1][j][0] - y) <= args.row_tol and j not in used:
            used.add(j)
            rows.append((y, cells + right[1][j][1]))
        else:
            rows.append((y, cells + [""] * nr))
    for j, (y, cells) in enumerate(right[1]):
        if j not in used:
            rows.append((y, [""] * nl + cells))
            print(f"<!-- 右ページにだけある行 (y={y:.0f})．位置を確かめる -->")
    rows.sort(key=lambda r: r[0])
    emit([c for _, c in rows], left[0] + [f"次 {c}" for c in right[0]])


def emit(table, cols):
    print(f"<!-- 列の始まり (pt): {[c if isinstance(c, str) else round(c) for c in cols]} -->")
    print("<table>")
    print("<tbody>")
    for cells in table:
        print("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    print("</tbody>")
    print("</table>")


def draft(page, clip_s, args):
    """1ページ分の下書き．(列の始まり, [(行の高さ, セルの列)]) を返す．"""

    clip = pymupdf.Rect(*map(float, clip_s.split(","))) if clip_s else page.rect
    words = words_with_italic(page, clip)
    # 行: 語の底 (y1) が近いものをまとめる
    rows = []
    for w in sorted(words, key=lambda w: (w[3], w[0])):
        if rows and abs(rows[-1][0] - w[3]) <= args.row_tol:
            rows[-1][1].append(w)
        else:
            rows.append([w[3], [w]])
    rows = [sorted(r[1], key=lambda w: w[0]) for r in rows][args.skip_top:]
    if not rows:
        return [], []
    cols = [float(c) for c in args.cols.split(",")] if args.cols else detect_columns(rows, clip, args.col_gap)

    def col_of(w):
        x = (w[0] + w[2]) / 2   # 中央ぞろえのセルがあるので，語の中心で列を決める
        return max((i for i, c in enumerate(cols) if c <= x + 2), default=0)

    if args.key_col is not None:
        table = by_key(rows, cols, col_of, args.key_col)
    else:
        table = by_line(rows, cols, col_of, args.no_merge)
    return cols, table


def cell_text(ws):
    """セルの語を行ごとにつなぐ．"""
    lines = []
    for w in sorted(ws, key=lambda w: (round(w[3]), w[0])):
        if lines and abs(lines[-1][0] - w[3]) <= 3:
            lines[-1][1].append(w)
        else:
            lines.append([w[3], [w]])
    out = []
    for _, lw in lines:
        s = ""
        for w in sorted(lw, key=lambda w: w[0]):
            s = join_text(s, w[4]) if s else w[4]
        out.append(s)
    return out


def mark(c):
    """「〇」(漢数字のゼロ，U+3007) だけのセルは「○」(U+25CB) にそろえる．
    植生学会誌 37(1) 表2 は同じ記号が PDF の文字情報で2種類に分かれていた (独立検証の指摘)．"""
    return "○" if c.strip() == "〇" else c


def by_line(rows, cols, col_of, no_merge):
    table = []
    for r in rows:
        cells = [""] * len(cols)
        for w in r:
            i = col_of(w)
            cells[i] = join_text(cells[i], w[4]) if cells[i] else w[4]
        y = r[0][3]
        if table and not cells[0].strip() and not no_merge:
            for i, c in enumerate(cells):   # 複数行にわたるセルの続き
                if c:
                    table[-1][1][i] = join_text(table[-1][1][i], c) if table[-1][1][i] else c
        else:
            table.append((y, cells))
    return [(y, [html.escape(mark(c).replace("* *", " "), quote=False) for c in cells]) for y, cells in table]


def by_key(rows, cols, col_of, key):
    """key 列の値ごとに1行．値の中心の高さの中間で行の範囲を区切る．"""
    words = [w for r in rows for w in r]
    keys = sorted((w for w in words if col_of(w) == key), key=lambda w: (w[1] + w[3]) / 2)
    if not keys:
        return by_line(rows, cols, col_of, True)
    cy = [(k[1] + k[3]) / 2 for k in keys]
    bounds = [-1e9] + [(a + b) / 2 for a, b in zip(cy, cy[1:])] + [1e9]
    recs = [[[] for _ in cols] for _ in keys]
    for w in words:
        y = (w[1] + w[3]) / 2
        i = max(j for j in range(len(keys)) if bounds[j] <= y)
        recs[i][col_of(w)].append(w)
    table = []
    for k, rec in zip(keys, recs):
        cells = []
        for ws in rec:
            ls = cell_text(ws)
            if len(ls) > 1 and all(len(re.sub(r"\*", "", l)) <= 8 for l in ls):
                cells.append("<break/>".join(html.escape(l, quote=False) for l in ls))   # 表層/底層 など
            else:
                s = ""
                for l in ls:
                    s = join_text(s, l)
                cells.append(html.escape(mark(s).replace("* *", " "), quote=False))
        table.append((k[3], cells))
    return table


if __name__ == "__main__":
    main()
