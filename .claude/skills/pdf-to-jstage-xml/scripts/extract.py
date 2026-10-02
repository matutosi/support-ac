"""PDF から J-STAGE 用 XML の下書き一式を作る (手順 1: 抽出)．

使い方:
    python extract.py <論文.pdf> --journal vegsci --out <作業ディレクトリ>

出力 (作業ディレクトリ):
    body.md       本文の下書き (見出し・段落・図表の枠・謝辞・摘要・引用文献)
    meta.yaml     書誌の下書き (「要確認」の印が付いた項目は人か AI が確かめる)
    page1.txt     1ページ目の行 (書誌を埋めるときに見る)
    floats.txt    本文から外した行 (表の中身など．表を組み直すときに見る)
    pages/        ページ画像 (照合用)
    figs/         図の画像 (J-STAGE の Graphics に入れる候補)
    tables/       表の画像 (組み直すときに見る)
    report.txt    自動で判断したことの一覧 (ハイフンの除去など．確かめる箇所)
"""
import argparse
import collections
import re
import statistics
import sys
from pathlib import Path

import pymupdf
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_scan                                   # noqa: E402
import layout                                         # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent


def hand_over(module, args, band=None):
    """同じ引数で，もう一方の抽出スクリプトを呼ぶ．"""
    argv = [sys.argv[0], args.pdf, "--journal", args.journal, "--out", args.out,
            "--dpi-page", str(args.dpi_page), "--dpi-fig", str(args.dpi_fig)]
    if getattr(args, "force", False):
        argv.append("--force")
    if band is not None:
        argv += ["--band", str(band)]
    sys.argv = argv
    return module.main()


def as_list(v):
    """設定の節の見出しは，文字列でも並びでも書ける (「引用文献」と「文献」)．"""
    return [v] if isinstance(v, str) else list(v)


def load_profile(name):
    path = SKILL_DIR / "journals" / f"{name}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 行の取り出し

# PDF の文字の対応表が誤った字を返すもの → 正しい字 (見た目で確かめたもの)
CHAR_FIXES = {
    "₋": "-",   # 下付きのマイナス (U+208B)．植生学会誌 42(2) の文献のページ範囲「83₋96」．見た目はふつうのハイフン
}


def fix_chars(t, where):
    for bad, good in CHAR_FIXES.items():
        if bad in t:
            REPORT.append(f"字を直した: U+{ord(bad):04X} → {good!r} ({where}: {t.strip()[:30]})")
            t = t.replace(bad, good)
    return t


def lost_dashes(page):
    """dict 形式で落ちる字 (U+0336 として埋め込まれた em ダッシュ) の位置．同じ位置の重複は1つにする．"""
    rects = {}
    for sp in page.get_texttrace():
        for ch in sp["chars"]:
            if ch[0] == 0x336:
                r = pymupdf.Rect(ch[3])
                rects[(round(r.x0), round(r.y0))] = r
    return list(rects.values())


CJK = re.compile(r"[぀-ヿ㐀-鿿＀-￯]")   # かな・漢字・全角の字


def is_latin(pages):
    """英文の論文か (2ページ目以降の文字に，かな・漢字・全角の字が 15% 未満)．

    和文の論文の本文は明朝 (Ryumin など)，英文の論文の本文は Times で組まれる．
    英文の論文にも和文の書体の空白や「■」はあるが，字の数では僅かなので，書体名ではなく字で数える．
    """
    n = cjk = 0
    for p in pages:
        t = re.sub(r"\s", "", p.get_text())
        n += len(t)
        cjk += len(CJK.findall(t))
    return n > 0 and cjk / n < 0.15   # 31〜35 巻: 英文 1.2〜2.9%，和文 34〜76% (英文にも和文の摘要がある)


def head_font(font, lay):
    """見出し・キャプションの書体か (設定の heading_font は書体名に含まれる文字列．英文の論文では複数)．"""
    return any(h in font for h in as_list(lay["heading_font"]))


def cap_font(line, lay):
    """図題・表題の書体か．

    和文の論文でも，図表の題が英文 (「Fig. 1.」「Table 1.」が Times の太字) のことがある
    (32〜35 巻の和文の論文の多く．31/107 など)．このとき行の書体は見出しの書体 (Gothic) にならないので，
    行頭の字 (番号の札) の書体が英文の太字 (設定の heading_font_latin) かも見る．
    本文の中の「Table 1 に示す」は太字でないので当たらない．
    """
    if head_font(line["font"], lay):
        return True
    first = next((s for s in line["spans"] if s["text"].strip()), None)
    return bool(first) and (head_font(first["font"], lay)
                            or any(h in first["font"] for h in as_list(lay.get("heading_font_latin", "Bold"))))


def line_font(spans, lay):
    """行の書体名 (いちばん大きい span の書体)．

    英文の論文では，大見出し「■ INTRODUCTION」の「■」と空白が和文の書体 (同じ大きさ) なので，
    いちばん大きい span では見出しの書体にならない．空白と「■」を除いた字の 6 割以上が
    見出しの書体 (太字) なら，その書体とみなす (本文の行の中の太字の記号「≥」などは見出しにしない)．
    """
    main = max(spans, key=lambda s: s["size"])["font"].split("+")[-1]
    if not lay.get("latin") or head_font(main, lay):
        return main
    prefix = lay.get("heading1_prefix", "")
    n = bold = 0
    font = None
    for s in spans:
        k = len(re.sub(r"\s", "", s["text"].replace(prefix, "") if prefix else s["text"]))
        n += k
        if head_font(s["font"], lay):
            bold += k
            font = font or s["font"].split("+")[-1]
    return font if font and bold >= n * 0.6 else main


def refs_sizes(doc, lay, refs_titles):
    """引用文献の見出しから後ろ (次の大見出しか付表の題の手前まで) の，本文より小さい行の字の大きさを数える．

    引用文献の後ろに付表 (組成表など．5.7pt や 7.1pt) が続くと，最終ページの字の大きさは付表のものになる
    (31(2):179・33(2):65・35(1):1・35(1):89)．文献の字の大きさは文献の行そのものから決める．
    """
    cnt = collections.Counter()
    on = False
    app = lay.get("appendix_pattern")
    for p in doc:
        mid = p.rect.width / 2
        ls = sorted(((0 if l["bbox"][0] < mid - 10 else 1, l["bbox"][1], l)
                     for b in p.get_text("dict")["blocks"] for l in b.get("lines", [])),
                    key=lambda x: (x[0], x[1]))
        for _col, _y, l in ls:
            t = "".join(s["text"] for s in l["spans"]).strip()
            if head_font(line_font(l["spans"], lay), lay):
                if t.startswith(lay["heading1_prefix"]):
                    if on:
                        return cnt              # 文献の次の大見出し (英文の論文の「■ 要約」)
                    on = t.lstrip(lay["heading1_prefix"]).strip() in refs_titles
                elif on and app and re.match(app, t):
                    return cnt                  # 付表の題
                continue
            size = round(max(s["size"] for s in l["spans"]), 1)
            if on and len(t) > 10 and size < lay["body_size"] - lay["size_tol"]:
                cnt[size] += 1
    return cnt


def auto_layout(doc, lay, refs_titles=()):
    """字の大きさ・柱と脚注の位置を，この PDF の統計から決める (設定の値は既定値)．

    年代で組み方が変わる (植生学会誌: 2014 年は本文 9.9pt，2025 年は 9.2pt) ため．
    """
    lay = dict(lay)
    cnt, h1 = collections.Counter(), collections.Counter()
    pages = list(doc)[1:] or list(doc)
    if is_latin(pages):
        # 英文の論文: 見出しとキャプションは欧文の太字 (Times の Bold) で，大見出しの「■」だけが和文の書体
        lay["latin"] = True
        # 末尾の和文の要約の見出し「■ 要約」はゴシック体のままなので，和文の見出しの書体も残す
        lay["heading_font"] = as_list(lay.get("heading_font_latin", "Bold")) + as_list(lay["heading_font"])
        REPORT.append(f"英文の論文とみなした (本文に和文の字がほとんど無い)．見出しの書体は {lay['heading_font']} で見分ける")
    for p in pages:
        for b in p.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                sp = max(l["spans"], key=lambda s: s["size"])
                t = "".join(s["text"] for s in l["spans"]).strip()
                size = round(sp["size"], 1)
                if head_font(line_font(l["spans"], lay), lay):
                    if t.startswith(lay["heading1_prefix"]):
                        h1[size] += 1
                elif len(t) > 10 and l["bbox"][2] - l["bbox"][0] > p.rect.width * 0.3:
                    # 段の幅に近い行だけを数える (表の多い論文 (32(1):95 は表が 9 つ) で，表のセルの字の大きさを本文と取り違えない)
                    cnt[size] += len(t)
    if cnt:
        lay["body_size"] = cnt.most_common(1)[0][0]
        lay["heading2_size"] = lay["body_size"]
    if h1:
        lay["heading1_size"] = h1.most_common(1)[0][0]
    rs = refs_sizes(doc, lay, refs_titles)
    if sum(rs.values()) >= 3:
        lay["ref_size"] = rs.most_common(1)[0][0]
    else:
        # 文献の見出しが見つからない・文献が本文と同じ大きさ: 最終ページの最頻の大きさ (付表が続くと誤る)
        last = collections.Counter(
            round(max(s["size"] for s in l["spans"]), 1)
            for b in doc[-1].get_text("dict")["blocks"] for l in b.get("lines", [])
            if len("".join(s["text"] for s in l["spans"]).strip()) > 10)
        if last and last.most_common(1)[0][0] < lay["body_size"]:
            lay["ref_size"] = last.most_common(1)[0][0]
            REPORT.append("引用文献の字の大きさを最終ページから決めた (文献の節の行が数えられなかった)．確かめる")
    # 柱: 2ページ目以降の本文の最上行より上．脚注: 本文の最下行より下
    tops, bottoms, lefts, rights = [], [], [], []
    for p in pages:
        ys = [l["bbox"] for b in p.get_text("dict")["blocks"] for l in b.get("lines", [])
              if abs(max(s["size"] for s in l["spans"]) - lay["body_size"]) <= lay["size_tol"]
              and not re.fullmatch(r"\s*\d+\s*", "".join(s["text"] for s in l["spans"]))]
        if ys:
            tops.append(min(y[1] for y in ys))
            bottoms.append(max(y[3] for y in ys))
            lefts.append(min(y[0] for y in ys))
            rights.append(max(y[2] for y in ys))
    if tops:
        lay["header_y_max"] = min(tops) - 1
        lay["footer_y_min"] = max(bottoms) + 1
        # 版面の左右 (図表の画像や線がはみ出していても，見えるのは版面の中だけ．クリップされた画像の箱は版面より大きい)
        lay["text_x0"] = statistics.median(lefts)
        lay["text_x1"] = statistics.median(rights)
    REPORT.append("組み方 (自動): " + ", ".join(f"{k}={lay[k]:.1f}" if isinstance(lay[k], float) else f"{k}={lay[k]}"
                                           for k in ("body_size", "heading1_size", "ref_size",
                                                     "header_y_max", "footer_y_min")))
    return lay


def page_lines(page, lay):
    """ページの行を dict の列で返す．柱・ノンブル・脚注は除く．

    rawdict の字の位置を使い，落ちた em ダッシュを，いちばん重なる行の正しい位置に補う．
    """
    raw = [l for b in page.get_text("rawdict")["blocks"] if b["type"] == 0 for l in b["lines"]]
    for r in lost_dashes(page):
        def overlap(l):
            y0, y1 = max(r.y0, l["bbox"][1]), min(r.y1, l["bbox"][3])
            return y1 - y0 if l["bbox"][0] - 12 <= r.x0 <= l["bbox"][2] + 12 else -1
        best = max(raw, key=overlap, default=None)
        if best is None or overlap(best) <= 0:
            REPORT.append(f"em ダッシュの行が見つからない: {tuple(round(v) for v in r)}")
            continue
        for sp in best["spans"]:
            if sp["bbox"][0] - 1 <= r.x0 <= sp["bbox"][2] + 12 or sp is best["spans"][-1]:
                k = sum(1 for c in sp["chars"] if c["bbox"][0] < r.x0)
                sp["chars"].insert(k, {"c": "—", "bbox": tuple(r), "origin": (r.x0, r.y1)})
                REPORT.append(f"em ダッシュを補った: p{page.number + 1} ({r.x0:.0f},{r.y0:.0f})")
                break
    out = []
    for l in raw:
        spans = []
        for sp in l["spans"]:
            t = fix_chars("".join(c["c"] for c in sp["chars"]), f"p{page.number + 1}")
            if t:
                spans.append({**sp, "text": t})
        if not spans:
            continue
        x0, y0, x1, y1 = l["bbox"]
        if y1 <= lay["header_y_max"]:
            continue
        out.append(make_line(spans, lay, tuple(round(v) for v in l["dir"])))
    # 寝た行 (縦組みの表．dir が (1, 0) でない) は断片をつながない．merge_fragments は横組みの行の基準線で
    # 同じ行を見分けるので，寝た表の最後の行と脚注の行を 1 つの行にしてしまう (35(2):109 の表1)
    flat = [l for l in out if l["dir"] == (1, 0)]
    return merge_fragments(flat, lay, page.rect.width / 2) + [l for l in out if l["dir"] != (1, 0)]


def make_line(spans, lay, direction=(1, 0)):
    x0 = min(s["bbox"][0] for s in spans)
    y0 = min(s["bbox"][1] for s in spans)
    x1 = max(s["bbox"][2] for s in spans)
    y1 = max(s["bbox"][3] for s in spans)
    size = max(s["size"] for s in spans)
    return {
        "x0": x0, "y0": y0, "x1": x1, "y1": y1, "size": size, "spans": spans,
        "font": line_font(spans, lay),
        "text": "".join(s["text"] for s in spans),
        "md": spans_to_md(spans, size, lay),
        "footer": y0 >= lay["footer_y_min"],
        "dir": direction,   # 字の進む向き ((1, 0) は横組み，(0, -1) は左に寝た行 (下から上へ読む))
    }


def merge_fragments(lines, lay, mid):
    """上付き文字などで分かれた同じ行の断片をつなぐ．

    断片は行の底が少しずれる (0.5pt など) ので，段ごとに「高さが半分以上重なるもの」を同じ行にまとめ，
    左から並べて，すき間の小さい隣どうしをつなぐ．
    """
    def base(l):  # 行の基準線 (本文の大きさの，空白でない字の基準線の最頻値)
        ys = [round(c["origin"][1]) for s in l["spans"] if s["size"] >= l["size"] * 0.8
              for c in s.get("chars", []) if c["c"].strip()]
        return statistics.mode(ys) if ys else l["y1"]
    out = []
    for col in (False, True):
        rows = []
        for l in sorted((l for l in lines if (l["x0"] >= mid - 10) == col), key=base):
            if rows and abs(base(l) - base(rows[-1][0])) <= l["size"] * 0.3:
                rows[-1].append(l)
            else:
                rows.append([l])
        # 小さい字だけの行 (独立した上付きの「2」など) は，高さが重なり横に隣り合う行へ移す
        small = lambda r: all(l["size"] < lay["body_size"] * 0.8 for l in r)
        for r in [r for r in rows if small(r)]:
            for l in list(r):
                host = next((h for h in rows if h is not r and not small(h) and any(
                    min(l["y1"], x["y1"]) - max(l["y0"], x["y0"]) > 0 and
                    (-2 <= l["x0"] - x["x1"] <= 12 or -2 <= x["x0"] - l["x1"] <= 12) for x in h)), None)
                if host:
                    host.append(l)
                    r.remove(l)
        rows = [r for r in rows if r]
        for row in rows:
            row.sort(key=lambda l: l["x0"])
            cur = row[0]
            for l in row[1:]:
                if -2 <= l["x0"] - cur["x1"] <= 12:
                    cur = make_line(cur["spans"] + l["spans"], lay)
                else:
                    out.append(cur)
                    cur = l
            out.append(cur)
    return out


def spans_to_md(spans, size, lay, escape=False):
    """書体と大きさから *斜体*・^上付き^・~下付き~ の印を付けた文字列にする．

    escape: 字の「*」「~」を印と取り違えないよう「\\*」「\\~」と書く (表の脚注の「* The number …」)
    """
    # 本文の大きさの字 (空白を除く) の上端と下端
    boxes = [c["bbox"] for s in spans if s["size"] >= size * 0.8 for c in s.get("chars", []) if c["c"].strip()]         or [s["bbox"] for s in spans if s["size"] >= size * 0.8]
    top = min(b[1] for b in boxes)
    bottom = max(b[3] for b in boxes)
    parts = []
    for s in spans:
        t = s["text"]
        if escape:
            t = t.replace("*", "\\*").replace("~", "\\~")
        if s["size"] < size * 0.8 and t.strip():
            # 行の中心より上にあれば上付き，下にあれば下付き
            mid = (s["bbox"][1] + s["bbox"][3]) / 2
            t = f"^{t.strip()}^" if mid < (top + bottom) / 2 else f"~{t.strip()}~"
        elif any(f in s["font"] for f in as_list(lay["italic_font"])) and t.strip():
            lead = t[: len(t) - len(t.lstrip())]
            trail = t[len(t.rstrip()):]
            t = f"{lead}*{t.strip()}*{trail}"
        parts.append(t)
    s = "".join(parts)
    if escape:
        return re.sub(r"(?<!\\)\*\*", "", s)   # 逃がした「\*」の後ろの斜体の印は残す
    return s.replace("**", "")  # 隣り合う斜体の印をつなぐ


def near(a, b, tol):
    return abs(a - b) <= tol


# ---------------------------------------------------------------- 文字列の連結

REPORT = []
JA_CHAR = re.compile(r"[぀-ヿ㐀-鿿]")


def join(a, b):
    """行をつなぐ．和文は詰め，欧文は空白を入れ，行末のハイフンを判断する．"""
    # 軟ハイフン (U+00AD) は行の途中なら消す (「Matsu­mu­ra」．34(1):1)．行末のものは下で分綴として扱う
    a = re.sub("­(?!\\s*$)", "", a)
    b = re.sub("­(?!\\s*$)", "", b)
    if not a:
        return b.lstrip()
    trailing_space = a != a.rstrip()
    a = a.rstrip()
    b = b.lstrip()
    if not b:
        return a
    if a.endswith(("­", "‑")):
        # DTP の号の英文の論文は，行末の分綴を軟ハイフン (U+00AD) か U+2011 で組む (34(1):1・23)．
        # 本来のハイフンは上付きの小さい「-」なので，これらは外して詰める
        REPORT.append(f"分綴を外した: {a[-12:-1]} + {b[:10]}")
        return a[:-1] + b
    if a.endswith("*") and b.startswith("*") and not a.endswith("**"):
        # 行をまたぐ斜体 (*Lolio-Cyno-* + *suretum*) は印を外してからつなぐ
        return join(a[:-1] + (" " if trailing_space else ""), b[1:])
    if a.endswith("-") and len(a) > 1 and a[-2].isalpha() and a[-2].islower() and b[0].islower():
        word_a = re.findall(r"[\w\-]+-$", a)
        word_b = re.match(r"[\w]+", b)
        REPORT.append(f"ハイフン除去: {word_a[-1] if word_a else a[-10:]} + {word_b.group(0) if word_b else b[:10]}")
        return a[:-1] + b
    if a.endswith("-"):
        return a + b
    asc_a = re.search(r"[A-Za-z0-9.,;:)\]*]$", a)
    asc_b = re.match(r"[A-Za-z0-9(\[*&]", b)
    if (trailing_space or asc_a) and asc_b:
        return a + " " + b
    return a + b


# ---------------------------------------------------------------- 段組

def column_of(line, mid):
    return 0 if line["x0"] < mid - 10 else 1


def column_modes(lines, mid, hanging=False):
    """段ごとの行頭位置．本文は最頻値．引用文献 (ぶら下げ字下げ) は多い2つのうち左のもの．"""
    modes = {}
    for c in (0, 1):
        xs = [round(l["x0"]) for l in lines if column_of(l, mid) == c]
        if not xs:
            continue
        if hanging:
            top = [x for x, _ in collections.Counter(xs).most_common(2)]
            modes[c] = min(top)
        else:
            modes[c] = statistics.mode(xs)
    return modes


# ---------------------------------------------------------------- 図表

def float_regions(page, lines, lay, is_body):
    """本文以外の要素 (画像・罫線・本文でない行) をまとまりごとに集める．"""
    W = page.rect.width
    # 版面 (少し余裕を持たせる)．はみ出した画像や線 (クリップで隠れた部分．35(1):21 の図5，31(2):165 の図2) は版面で切る
    live = pymupdf.Rect(lay.get("text_x0", 0) - 8, lay["header_y_max"] - 10,
                        lay.get("text_x1", W) + 8, lay["footer_y_min"] + 10) & page.rect
    elems = []
    for img in page.get_image_info():
        r = pymupdf.Rect(img["bbox"]) & live
        if not r.is_empty:
            elems.append(("img", r))
    for d in page.get_drawings():
        r = d["rect"]
        if r.y1 <= lay["header_y_max"] + 5 and r.width > W * 0.5:
            continue  # 柱の下の罫線
        r = pymupdf.Rect(r)
        # 表の罫線は高さ (縦の罫線は幅) が 0 の箱で，PyMuPDF では空の箱として和 (|) にも重なりにも数えられない．
        # 表題と表の中身の間が空いた表 (32(1):1 の Table 2 など) が表題だけの枠になるので，罫線に 0.5pt の厚みを持たせる
        if r.height <= 0:
            r.y0, r.y1 = r.y0 - 0.25, r.y0 + 0.25
        if r.width <= 0:
            r.x0, r.x1 = r.x0 - 0.25, r.x0 + 0.25
        r &= live
        if r.is_empty:
            continue
        elems.append(("draw", r))
    for l in lines:
        if not is_body(l) and not l["footer"]:
            elems.append(("text", pymupdf.Rect(l["x0"], l["y0"], l["x1"], l["y1"]), l))
    # 近いもの同士 (12pt 以内) をまとめる．まとまりの外接矩形どうしが近ければ，連鎖して1つにする．
    # 線の多い図 (31(2):107 の5ページは 3 万本) でも速いよう，矩形は数の組で持ち，x0 の順に掃いて
    # 近いものを合わせることを，合わせるものが無くなるまで繰り返す (結果は 1 つずつ合わせるのと同じ)
    G = 12
    boxes = [[e[1].x0, e[1].y0, e[1].x1, e[1].y1, [k]] for k, e in enumerate(elems)]
    merged = True
    while merged:
        merged = False
        boxes.sort(key=lambda b: b[0])
        out = []
        for b in boxes:
            # 直前までのまとまりのうち，x の範囲が届くものと比べる (届かないものは以後も届かない)
            hit = None
            for c in reversed(out):
                if c[0] - G < b[2] and b[0] < c[2] + G and c[1] - G < b[3] and b[1] < c[3] + G:
                    hit = c
                    break
            if hit is None:
                out.append(b)
            else:
                hit[0], hit[1] = min(hit[0], b[0]), min(hit[1], b[1])
                hit[2], hit[3] = max(hit[2], b[2]), max(hit[3], b[3])
                hit[4] += b[4]
                merged = True
        boxes = out
    clusters = []
    for b in sorted(boxes, key=lambda b: min(b[4])):     # 元の並び (最初の要素の順) を保つ
        ks = sorted(b[4])
        clusters.append({"rect": pymupdf.Rect(b[0], b[1], b[2], b[3]), "elems": [elems[k] for k in ks]})
    return clusters


def cap_match(text, lay):
    """図題・表題・付表の題なら (種類, 番号, 付表か, 呼び名) を返す．

    付表 (「付表1」「Appendix 1」．引用文献の後ろの組成表など) は表として扱い，Table 1 と番号が重なるので
    枠を TA1，画像を appendix1.png にする (extract_scan.py と同じ)．番号の無い「付表」(31(2):179) は 1 とみる．
    """
    text = text.lstrip()   # 行頭に全角の空白の span があることがある (33(1):1 の Table 2〜4)
    m = re.match(lay["caption_pattern"], text)
    if m:
        kind = "fig" if m.group(1).startswith(("図", "Fig")) else "table"   # 「Fig 6.」(34(1):39) も図
        # 呼び名は紙面の札に合わせる (和文の論文でも図表の題が英文なら「Fig. 1」「Table 1」)
        word = m.group(1)
        label = f"{word} {int(m.group(2))}" if re.match(r"[A-Za-z]", word) else f"{word}{int(m.group(2))}"
        return kind, int(m.group(2)), False, label
    if lay.get("appendix_pattern"):
        m = re.match(lay["appendix_pattern"], text)
        if m:
            return "table", int(m.group(2) or 1), True, m.group(0).strip()
    return None


def mark_captions(lines, lay):
    """キャプション (ゴシック体の「図1.」「表1.」) とその続きの行に印を付け，本文から外す．

    2025 年の号はキャプションが本文と同じ大きさなので，大きさでは本文と分けられない．
    続きの行は，すぐ下にあり，キャプションの行頭より右から始まる (ぶら下げ字下げ) もの．
    """
    for cap in [l for l in lines if cap_font(l, lay) and cap_match(l["text"], lay)]:
        cap["cap"] = True
        cap["appx"] = cap_match(cap["text"], lay)[2]
        last = cap
        for l in sorted((l for l in lines if l["y0"] > cap["y0"]), key=lambda l: l["y0"]):
            if l.get("cap"):
                continue
            if l["y0"] - last["y1"] > cap["size"] * 0.8:
                break
            if cap["x0"] + 2 <= l["x0"] <= cap["x0"] + cap["size"] * 2 and l["x1"] <= cap["x1"] + cap["size"] * 30                     and near(l["size"], cap["size"], 0.4):
                l["cap"] = True
                last = l


def caption_of(cluster, lay):
    caps = [e for e in cluster["elems"] if e[0] == "text" and cap_font(e[2], lay)
            and cap_match(e[2]["text"], lay)]
    if not caps:
        return None
    cap = min(caps, key=lambda e: e[2]["y0"])[2]
    # キャプションの続きの行 (同じ大きさ・すぐ下・左端がそろう)
    text = cap["md"]
    last = cap
    # 図題の範囲は全行の和 (最後の行が短いと，最初の行と最後の行の角だけでは途中の長い行がはみ出し，図の枠に写り込む)
    rect = pymupdf.Rect(cap["x0"], cap["y0"], cap["x1"], cap["y1"])
    texts = [e[2] for e in cluster["elems"] if e[0] == "text"]

    def table_row(l):
        # 表の見出しの行の最初のセル (「調査地」など)．同じ高さの右に，離れた別の字がある (31(2):119 の表2)
        return any(o is not l and abs(o["y0"] - l["y0"]) < cap["size"] * 0.5
                   and o["x0"] > l["x1"] + cap["size"] * 1.5 and o["x1"] < rect.x1 - cap["size"] for o in texts)
    for e in sorted((e for e in cluster["elems"] if e[0] == "text"), key=lambda e: e[2]["y0"]):
        l = e[2]
        if l is cap or l["y0"] <= last["y0"]:
            continue
        if near(l["size"], cap["size"], 0.2) and l["y0"] - last["y1"] < cap["size"] * 0.8 \
                and cap["x0"] - 2 <= l["x0"] <= cap["x0"] + cap["size"] * 1.5 and not table_row(l):
            text = join(text, l["md"])
            last = l
            rect |= pymupdf.Rect(l["x0"], l["y0"], l["x1"], l["y1"])
        else:
            break
    kind, num, appx, label = cap_match(cap["text"], lay)
    return {"kind": kind, "num": num, "appx": appx, "label": label, "line": cap, "text": text.strip(),
            "cap_rect": rect}


def split_by_captions(cluster, lay):
    """図題が 2 つ以上入ったまとまりを，図題ごとに分ける．

    上下に接した図 (31(2):107 の Fig. 4 と Fig. 5) は 1 つのまとまりになり，上の図題の図だけが作られて
    下の図が消える．図は図題の上 (または横)，表は表題の下にあるとみて，要素を近い図題に配る．
    """
    texts = [e for e in cluster["elems"] if e[0] == "text"]
    capl, keys = [], set()
    for e in sorted(texts, key=lambda e: e[2]["y0"]):
        m = cap_font(e[2], lay) and cap_match(e[2]["text"], lay)
        if m and m[:3] not in keys:
            keys.add(m[:3])
            capl.append(e)
    if len(capl) < 2:
        return [cluster]
    others = [e for e in texts if e not in capl]
    infos = [caption_of({"elems": [e] + others}, lay) for e in capl]
    groups = [[] for _ in capl]
    for el in cluster["elems"]:
        r = el[1]
        own = next((i for i, (e, info) in enumerate(zip(capl, infos))
                    if el is e or el[0] == "text" and info["cap_rect"].contains(r)), None)
        if own is None:
            cy = (r.y0 + r.y1) / 2
            best = None
            for i, info in enumerate(infos):
                cr = info["cap_rect"]
                dx = max(cr.x0 - r.x1, r.x0 - cr.x1, 0)
                if info["kind"] == "fig" and cr.y1 >= cy - 2:
                    d = max(0, cr.y0 - cy) + dx
                elif info["kind"] == "table" and cr.y0 <= cy + 2:
                    d = max(0, cy - cr.y1) + dx
                else:
                    d = 1e6 + abs(cy - (cr.y0 + cr.y1) / 2) + dx
                if best is None or d < best[0]:
                    best = (d, i)
            own = best[1]
        groups[own].append(el)
    out = []
    for g in groups:
        if g:
            rect = pymupdf.Rect()
            for el in g:
                rect |= el[1]
            out.append({"rect": rect, "elems": g})
    REPORT.append("図題が " + "・".join(info["label"] or "" for info in infos) + " の入ったまとまりを図題ごとに分けた．確かめる")
    return out


def content_rect(c, cap):
    """まとまりから図題 (キャプションとその続きの行) を除いた範囲．"""
    r = pymupdf.Rect()
    for e in c["elems"]:
        if e[0] == "text" and e[2].get("cap"):
            continue
        if cap and e[0] != "img" and cap["cap_rect"].contains(e[1]):
            continue    # 図題の行と，図題の中に線で描かれた記号 (33(1):33 の Fig. 3 の「▲」)
        r |= e[1]
    return r if not r.is_empty else c["rect"]


def trim_caption(content, cap_rects, page, margin=3):
    """余白を足したうえで，図題の手前で切る (図題が画像に写り込まないように)．"""
    clip = (content + (-margin, -margin, margin, margin)) & page.rect
    for cr in cap_rects:
        if cr.x1 < clip.x0 or cr.x0 > clip.x1:
            continue
        # 図の白い下地や線が図題の下まで伸びていると，図題が中身と重なる (35(1):21 の図3)．
        # 中身の下半分にかかる図題は下，上半分にかかる図題は上とみて，その手前で切る
        # (横組みの図題で，中身と横に重なるときだけ．縦組みの表題 (35(1):67 の表3) は横の端にかかるだけなので除く)
        cy = (content.y0 + content.y1) / 2
        inside = cr.width > cr.height and min(cr.x1, content.x1) - max(cr.x0, content.x0) > cr.width * 0.5
        if cr.y0 >= content.y1 - 2 or inside and cr.y0 > cy:          # 図題が下
            clip.y1 = min(clip.y1, cr.y0 - 0.5)
        elif cr.y1 <= content.y0 + 2 or inside and cr.y1 < cy:        # 図題が上
            clip.y0 = max(clip.y0, cr.y1 + 0.5)
    return clip


def has_content(c, cap):
    """まとまりに図題のほかの中身があるか (図題の脇の小さい線や記号 (33(1):1 の Fig. 1) は中身とみない)．"""
    r = pymupdf.Rect()
    for e in c["elems"]:
        if not (e[0] == "text" and e[2].get("cap")) and not (e[0] != "img" and cap["cap_rect"].contains(e[1])):
            r |= e[1]
    return not r.is_empty and r.get_area() > max(1500, cap["cap_rect"].get_area())


def grow_figure(clusters, caps, c, cap):
    """図の中身のすぐ上 (または横) に，間の空いた図題の無いまとまりがあれば合わせる．

    図の凡例だけが図題とつながり，図の本体が 12pt 以上離れて別のまとまりになることがある
    (33(1):1 の Fig. 1，34(1):39 の Fig. 2)．図題より下のものは合わせない (本文や次の図)．
    """
    fig = content_rect(c, cap)
    cr = cap["cap_rect"]
    got = []
    more = True
    while more:
        more = False
        for o in clusters:
            if o is c or o in got or caps.get(id(o)) or o["rect"].get_area() < 2000:
                continue
            r = o["rect"]
            if r.y1 > cr.y1 + 5:
                continue
            gap = max(r.y0 - fig.y1, fig.y0 - r.y1)
            if gap > 30 or min(r.x1, fig.x1) - max(r.x0, fig.x0) <= 0:
                continue
            # ほかの図表 (表題のあるまとまり) のほうに近いものは，そちらの一部 (表の脚注など．31(2):107 の表1)
            if any(caps.get(id(x)) and x is not c and min(r.x1, x["rect"].x1) - max(r.x0, x["rect"].x0) > 0
                   and max(r.y0 - x["rect"].y1, x["rect"].y0 - r.y1) < gap for x in clusters):
                continue
            if True:
                got.append(o)
                fig |= r
                more = True
    for o in got:
        c["elems"] += o["elems"]
        c["rect"] |= o["rect"]
        clusters.remove(o)
    if got:
        REPORT.append(f"{cap['label']} の図に，すぐ上の図題の無いまとまりを合わせた {tuple(round(v) for v in fig)}．確かめる")


def attach_side_figures(clusters, caps):
    """図題だけのまとまりに，横 (または上下のすぐ近く) にある図題の無いまとまりを合わせる．

    図題を図の横に置く組み方 (31(2):119 の図5，31(2):165 の図1) では，図と図題の間が空いていて
    別のまとまりになり，図題の枠は図題だけ，図は図題の無いまとまり (前の図の続き扱い) になる．
    """
    for c in list(clusters):
        cap = caps.get(id(c))
        if not cap:
            continue
        if has_content(c, cap):
            if cap["kind"] == "fig":
                grow_figure(clusters, caps, c, cap)
            continue
        cr = cap["cap_rect"]
        best, best_d = None, None
        for o in clusters:
            if o is c or caps.get(id(o)) or o["rect"].get_area() < 2000:
                continue
            r = o["rect"]
            cc = c["rect"]   # 図題と，図題の脇の凡例など (34(1):39 の Fig. 2)
            dy = max(r.y0 - cc.y1, cc.y0 - r.y1, 0)      # 縦の隔たり (重なれば 0)
            dx = max(r.x0 - cc.x1, cc.x0 - r.x1, 0)
            if dy > 30 or dx > 60:
                continue
            d = dx + dy
            if best is None or d < best_d:
                best, best_d = o, d
        if best is None:
            continue
        # 合わせた図のすぐ上下に続く図題の無いまとまり (縦に並んだ小図．31(2):119 の図5) も合わせる
        got = [best]
        fig = pymupdf.Rect(best["rect"])
        more = True
        while more:
            more = False
            for o in clusters:
                if o is c or o in got or caps.get(id(o)) or o["rect"].get_area() < 2000:
                    continue
                r = o["rect"]
                if max(r.y0 - fig.y1, fig.y0 - r.y1) <= 30 and min(r.x1, fig.x1) - max(r.x0, fig.x0) > 0:
                    got.append(o)
                    fig |= r
                    more = True
        cap["side"] = True    # 図題が図の横にある (段で切らない)
        for o in got:
            c["elems"] += o["elems"]
            c["rect"] |= o["rect"]
            clusters.remove(o)
        REPORT.append(f"図題 {cap['label']} の横 (近く) の図を合わせた {tuple(round(v) for v in fig)}．確かめる")


def text_dir(elems):
    """要素の中の行の向き (字数のいちばん多い向き)．行が無ければ (1, 0)．"""
    count = collections.Counter()
    for e in elems:
        if e[0] == "text":
            count[e[2].get("dir", (1, 0))] += len(e[2]["text"].strip())
    return count.most_common(1)[0][0] if count else (1, 0)


def grow_tables(clusters, caps):
    """表の中身の下 (寝た表は起こした向きの下) に，間の空いた図題の無いまとまりがあれば合わせる．

    表の行の間が 12pt 以上空くと (小見出しの行の前など)，表は表題の付いた上の部分と，図題の無い下の部分
    (前のページの続きの候補) に分かれ，表の画像が上の部分だけになり，最後の罫線と脚注も取れない
    (31(2):119 の表2，32(2):69 の表3，33(2):53 の表5)．表の幅に収まり，すぐ下 (30pt 以内) にあるものを合わせる．
    """
    for c in list(clusters):
        cap = caps.get(id(c))
        if not cap or cap["kind"] != "table" or c not in clusters:
            continue
        direction = text_dir(c["elems"])
        T = turn_of(direction)[0]
        texts = [e[2]["size"] for e in c["elems"] if e[0] == "text"]
        size = statistics.median(texts) if texts else 8
        tr = pymupdf.Rect(T(content_rect(c, cap)))
        top = tr.y1      # 表題の付いた部分の下端 (これより下のものだけを合わせる)
        got = []
        more = True
        while more:
            more = False
            for o in clusters:
                if o is c or o in got or caps.get(id(o)):
                    continue
                r = pymupdf.Rect(T(o["rect"]))
                gap = r.y0 - tr.y1
                # 合わせた部分と横に並ぶもの (列ごとに分かれたまとまり．31(2):119 の表2) は，重なってもよい
                if r.y0 < top - 2 or gap > 30 or r.x0 < tr.x0 - size * 2 or r.x1 > tr.x1 + size * 2:
                    continue
                if any(e[0] == "text" for e in o["elems"]) and text_dir(o["elems"]) != direction:
                    continue
                # 間にほかの図表 (図題のあるまとまり) があれば合わせない
                if any(caps.get(id(x)) and x is not c and tr.y1 - 2 <= pymupdf.Rect(T(x["rect"])).y0 <= r.y0 + 2
                       and min(r.x1, pymupdf.Rect(T(x["rect"])).x1) - max(r.x0, pymupdf.Rect(T(x["rect"])).x0) > 0
                       for x in clusters):
                    continue
                got.append(o)
                tr |= r
                more = True
        for o in got:
            c["elems"] += o["elems"]
            c["rect"] |= o["rect"]
            clusters.remove(o)
        if got:
            REPORT.append(f"{cap['label']} の表に，すぐ下の図題の無いまとまり {len(got)} 個を合わせた (表の行の間が空いていた)．確かめる")


def cut_body_lines(content, cap, body_lines, mid):
    """中身の上端・下端にかかる本文の行 (段の幅の半分より長いもの) を外す．

    図の白い下地が本文の上まで伸びていると，本文の行が図の画像に写り込む (31(2):165 の図2)．
    """
    r = pymupdf.Rect(content)
    cy = (r.y0 + r.y1) / 2
    for l in body_lines:
        if l["x1"] - l["x0"] < mid * 0.4 or l["y1"] <= r.y0 or l["y0"] >= r.y1:
            continue
        if min(l["x1"], r.x1) - max(l["x0"], r.x0) < (l["x1"] - l["x0"]) * 0.8:   # 行のほとんどが中身の幅に入る
            continue
        if (l["y0"] + l["y1"]) / 2 < cy:
            r.y0 = max(r.y0, l["y1"] + 3.5)
        else:
            r.y1 = min(r.y1, l["y0"] - 3.5)
    if r.is_empty or r.height < content.height * 0.3:
        return content        # 中身の大半が消えるなら切らない (本文の大きさの字を使った図など)
    if r != content:
        REPORT.append(f"{cap['label']} の枠から本文の行を外した {tuple(round(v) for v in content)} → {tuple(round(v) for v in r)}")
    return r


def clamp_to_column(content, cap, body_lines, mid):
    """図題が片方の段にだけあり，中身がもう一方の段の本文の行に重なるときは，図題の段に切る．

    クリップで隠れた画像の箱や下地は，見えている図より広いことがある (35(1):21 の図5，31(2):165 の図2)．
    """
    cr = cap["cap_rect"]
    if cap.get("side"):
        return cut_body_lines(content, cap, body_lines, mid)
    if cr.x1 <= mid + 10:
        col, other = (None, mid - 4), lambda l: l["x0"] >= mid - 10
    elif cr.x0 >= mid - 10:
        col, other = (mid + 4, None), lambda l: l["x0"] < mid - 10
    else:
        return cut_body_lines(content, cap, body_lines, mid)
    hit = [l for l in body_lines if other(l) and l["y1"] > content.y0 and l["y0"] < content.y1
           and l["x1"] > content.x0 and l["x0"] < content.x1]
    if len(hit) < 2:
        return cut_body_lines(content, cap, body_lines, mid)
    r = pymupdf.Rect(content)
    if col[1] is not None:
        r.x1 = min(r.x1, col[1])
    else:
        r.x0 = max(r.x0, col[0])
    REPORT.append(f"{cap['label']} の枠を図題の段に切った (もう一方の段の本文に重なっていた)")
    return cut_body_lines(r, cap, body_lines, mid)


FOOT_START = re.compile(r"\s*(\\\*|＊|†|‡|§|\^)")   # 脚注の行頭の印 (md で．逃がした「\*1:」「＊:」「†」・上付きの「^1^」)
FOOT_MARK = re.compile(r"\s*([*＊†‡§]|注[:：．.\s])")   # 字の行 (md でない) の行頭の脚注の印
# 表の最後の行の「以下省略」(32(1):37 の表3 の「The rest is omitted.」，34(1):65 の表4 の「… were omitted.」)
OMITTED = re.compile(r"(?i)\brest (is|are) omitted|\bwere omitted\b|以下[省略]+")


def turn_of(direction):
    """寝た表を横組みに起こして見るための，矩形 (x0, y0, x1, y1) の変換と，起こした向きでの「下端で切る」辺．

    (0, -1) は左に寝た表 (下から上へ読む．35(2):109 の表1)．読む向きは -y，行の進む向き (起こした表の下) は +x．
    返り値は (変換, 切る辺の名前, 起こした座標の値を実際の座標に戻す関数)．
    """
    if direction == (0, -1):
        return (lambda r: (-r[3], r[0], -r[1], r[2])), "x1", (lambda v: v)
    if direction == (0, 1):
        return (lambda r: (r[1], -r[2], r[3], -r[0])), "x0", (lambda v: -v)
    if direction == (-1, 0):
        return (lambda r: (-r[2], -r[3], -r[0], -r[1])), "y0", (lambda v: -v)
    return (lambda r: tuple(r)), "y1", (lambda v: v)


def turn_line(l, T):
    """行 (字の箱も) を起こした座標に移した写し (上付きの見分けも起こした向きで行う)．"""
    def sp(s):
        return {**s, "bbox": T(s["bbox"]), "chars": [{**ch, "bbox": T(ch["bbox"])} for ch in s.get("chars", [])]}
    x0, y0, x1, y1 = T((l["x0"], l["y0"], l["x1"], l["y1"]))
    return {**l, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "spans": [sp(s) for s in l["spans"]]}


def apply_cut(clip, cut):
    """split_table_foot の返す切り位置 (辺の名前, 値) で，画像の範囲を脚注の手前までに縮める．"""
    side, v = cut
    if side in ("x1", "y1"):
        setattr(clip, side, min(getattr(clip, side), v + 1.5))
    else:
        setattr(clip, side, max(getattr(clip, side), v - 1.5))
    return clip


def split_table_foot(c, cap, label, lay, cont=False, state=None):
    """表の下の罫線より下にある脚注の行を，表の画像から外して文字で返す．

    DTP の号 (31(2) 以降) の表は，表の本体を横罫線で閉じ，その下に脚注 (「* The number of plots …」) を置く．
    公式の見本・JATS4R はどれも脚注を <table-wrap-foot> に文字で持つので，画像は最後の横罫線までで切り，
    脚注は枠の @image の後ろに書く (32(2):1 の表1)．
    90 度寝た表 (縦組みの表．行の向きが (0, -1)) は，起こした向きで同じことをする (罫線は縦の線，脚注は表の右)．
    返り値は (中身の範囲, 脚注の行 (md) の並び, 切り位置 (辺の名前, 値))．分けないときは (None, None, None)．
    罫線が無い・罫線の下に表の行らしいもの (3 つ以上のセル) や線・画像があるときは分けない (確かめるよう書く)．
    state (dict) に分けた結果を書く: foot は "split" (分けた)・"none" (罫線の下に何も無い)・"maybe" (脚注が画像に
    入っている見込み．why に理由)・"unknown" (罫線が無く脚注の印も無い)．head は表題と表の間の注の行，
    omitted は表の最後の罫線の上の「以下省略」の行．作成役への注記 (foot_notes) に使う．
    """
    state = {} if state is None else state
    capr = cap["cap_rect"] if cap else None
    real = [e for e in c["elems"] if not (e[0] == "text" and e[2].get("cap"))
            and not (capr and e[0] != "img" and capr.contains(e[1]))]
    if not any(e[0] == "text" for e in real):
        return None, None, None
    direction = text_dir(real)   # 表の向き: 字数のいちばん多い行の向き
    T, side, back = turn_of(direction)
    # 起こした座標の要素 (種類, 矩形, 行, 元の要素)．寝た表の中の横組みの行 (向きの違う行) は字の箱だけを移す
    elems = [(e[0], pymupdf.Rect(T(e[1])), turn_line(e[2], T) if e[0] == "text" else None, e) for e in real]
    texts = [e for e in elems if e[0] == "text"]
    turned = direction != (1, 0)
    # 横罫線: 高さの小さい線を，高さ (1pt 以内) ごとにまとめ，覆う横の長さを測る
    rows = []
    for e in elems:
        r = e[1]
        if e[0] != "draw" or r.height > 1.5 or r.width < 3:
            continue
        y = (r.y0 + r.y1) / 2
        g = next((g for g in rows if abs(g["y"] - y) <= 1.0), None)
        if g is None:
            rows.append({"y": y, "segs": [(r.x0, r.x1)]})
        else:
            g["segs"].append((r.x0, r.x1))
    for g in rows:
        segs = sorted(g["segs"])
        cover, cur = 0.0, None
        for a, b in segs:
            if cur is None or a > cur[1] + 1:
                if cur:
                    cover += cur[1] - cur[0]
                cur = [a, b]
            else:
                cur[1] = max(cur[1], b)
        cover += cur[1] - cur[0]
        g["cover"], g["x0"], g["x1"] = cover, segs[0][0], max(b for _a, b in segs)
    whole = pymupdf.Rect()
    for e in elems:
        whole |= e[1]
    width = whole.width
    big = max((g["cover"] for g in rows), default=0)
    full = [g for g in rows if g["cover"] >= big * 0.9] if big >= width * 0.5 else []
    size = statistics.median(e[2]["size"] for e in texts)
    where = "表 (寝た表は起こした向き) の下" if turned else "表の下"
    kind = "縦組み" if turned else "横組み"
    # 表題と表の間 (表の上の罫線より上) の注の行 (33(1):1 の表1，31(2):179 の付表)．表題の続きか脚注かは紙面による
    if cap and full and not cont:
        top = min(g["y"] for g in full)
        cr = pymupdf.Rect(T(capr))
        head = [e[2] for e in texts if cr.y1 - 1 < (e[1].y0 + e[1].y1) / 2 < top - 0.5]
        # 表の中の小見出し (35(1):21 の表1 の「（a）　DBH 5 cm 未満」) を除くため，表の幅の 4 割以上の行があるときだけ
        if head and max(cells_in_row(head, size).values()) < 3 \
                and any(l["x1"] - l["x0"] >= width * 0.4 for l in head):
            state["head"] = [l["text"].strip() for l in head]
            REPORT.append(f"{label}: 表題と表の上の罫線の間に注らしい行が {len(head)} 行あり，画像に入れたまま．確かめる")
    if len(full) == 1 and len(texts) >= 3:
        # 罫線が 1 本だけ: 表の下の罫線 (続きのページの表は上の罫線が無い．34(1):65 の表4) とみてよいのは，
        # 罫線が表の下のほうにあり，罫線より上の行がずっと多いとき
        g = full[0]
        above = [e for e in texts if (e[1].y0 + e[1].y1) / 2 < g["y"]]
        # (図の式の分数の線などを罫線とみないよう，罫線の上に 6 行以上あり，罫線が 100pt 以上のときだけ．33(2):53 の p4)
        if g["y"] < whole.y0 + whole.height * 0.5 or len(above) < max(6, 2 * (len(texts) - len(above))) \
                or g["cover"] < 100:
            full = []
    if not full:
        # 罫線で閉じていない表 (罫線の無い表など): 分けずに知らせる (脚注があれば画像に入ったまま)
        tail = sorted((e[2] for e in texts), key=lambda l: l["y1"])[-3:]
        if any(FOOT_MARK.match(l["text"]) for l in tail):
            REPORT.append(f"{label}: {where}の罫線が見つからず，脚注らしい行を画像に入れたまま (枠に書いていない)．確かめる")
            state.update(foot="maybe", why=f"{kind}・罫線なし")
        elif not cont:
            REPORT.append(f"{label}: {where}の罫線が見つからない．脚注があれば画像に入ったまま (枠に書いていない)．確かめる")
            state.update(foot="maybe" if turned else "unknown", why=f"{kind}・罫線なし")
        else:
            state.update(foot="unknown", why=f"{kind}・罫線なし")
        return None, None, None
    bottom = max(full, key=lambda g: g["y"])
    # 表の最後の罫線のすぐ上の「以下省略」の行 (32(1):37 の表3)．表の一部か脚注かは紙面による
    last = [e[2] for e in texts if (e[1].y0 + e[1].y1) / 2 < bottom["y"]]
    if last:
        y = max(l["y1"] for l in last)
        row = [l for l in last if abs(l["y1"] - y) < size * 0.5]
        if len(row) == 1 and OMITTED.search(row[0]["text"]):
            state["omitted"] = row[0]["text"].strip()
    below = [e for e in elems if (e[1].y0 + e[1].y1) / 2 > bottom["y"] + 0.5]
    foot = sorted((e[2] for e in below if e[0] == "text"), key=lambda l: (round(l["y1"]), l["x0"]))
    if not foot:
        state.update(foot="none")
        return None, None, None
    why = None
    if any(e[0] != "text" for e in below):
        why = "罫線の下に線か画像がある"
    elif any(l["x0"] < bottom["x0"] - size * 2 or l["x1"] > bottom["x1"] + size * 2 for l in foot):
        why = "罫線の下の行が表の幅からはみ出す"
    else:
        if max(cells_in_row(foot, size).values(), default=0) >= 3:
            why = "罫線の下に表の行らしいもの (3 つ以上に分かれた行) がある"
    if why:
        REPORT.append(f"{label}: {why}ので，脚注を分けず画像に入れたまま．確かめる")
        state.update(foot="maybe", why=why)
        return None, None, None
    paras = foot_paras(foot, size, lay)
    out = {id(e[3]) for e in below}
    kept = {"elems": [e for e in c["elems"] if id(e) not in out], "rect": c["rect"]}
    REPORT.append(f"{label}: {where}の罫線 ({'x' if side[0] == 'x' else 'y'}={back(bottom['y']):.0f}) より"
                  f"{'右' if side == 'x1' else '左' if side == 'x0' else '上' if side == 'y0' else '下'}の脚注 {len(foot)} 行を"
                  "画像から外し，枠に文字で書いた．確かめる")
    state.update(foot="split")
    return content_rect(kept, cap), paras, (side, back(bottom["y"]))


def cells_in_row(lines, size):
    """高さ (行) ごとの，間の空いた断片の数 (表の行ならセルの数)．

    同じ高さに 3 つ以上に分かれた行は表のセル (罫線の下にも表の行が続く表)．ただし小さい「＊」で行が切れた脚注
    (「＊: 2007 年，＊＊: 2012 年，…」．33(1):15 の表4) は断片が接しているので，間の空き (字の大きさより広い) で数える．
    """
    rows = collections.defaultdict(list)
    for l in lines:
        rows[round(l["y1"] / (size * 0.6))].append(l)
    out = {}
    for k, ls in rows.items():
        ls = sorted(ls, key=lambda l: l["x0"])
        n, end = 1, ls[0]["x1"]
        for l in ls[1:]:
            if l["x0"] - end > size:
                n += 1
            end = max(end, l["x1"])
        out[k] = n
    return out


def foot_paras(foot, size, lay):
    """脚注の行 (起こした座標．上から順) を段落にする．印で始まる行と，前の行が右端まで届かない (短い) ときに改める．"""
    right = max(l["x1"] for l in foot)
    paras = []
    prev = None
    for l in foot:
        md = spans_to_md(l["spans"], l["size"], lay, escape=True).strip()
        if prev is not None and abs(l["y1"] - prev["y1"]) < size * 0.5:
            paras[-1] = join(paras[-1] + " ", md)          # 同じ高さに並んだ脚注は 1 行につなぐ
        elif prev is None or FOOT_START.match(md) or prev["x1"] < right - size * 2:
            paras.append(md)
        else:
            paras[-1] = join(paras[-1], md)
        prev = l
    return paras


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--journal", default="vegsci")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dpi-page", type=int, default=100)
    ap.add_argument("--force", action="store_true", help="既にある body.md を上書きする (AI が手で直した分は消える)")
    ap.add_argument("--dpi-fig", type=int, default=300)
    args = ap.parse_args()

    prof = load_profile(args.journal)
    # 体裁の見分け: 紙のスキャンなら旧号用のスクリプトへ渡す (どちらを呼んでもよいようにする)
    if layout.detect(args.pdf) == "scan":
        print("紙をスキャンした PDF なので extract_scan.py で処理する", file=sys.stderr)
        return hand_over(extract_scan, args)
    lay = prof["layout"]
    out = Path(args.out)
    # body.md が既にある (AI が手を入れた) ときは，手で切り出した図表の画像を消さないよう，
    # 画像も body.new.md と同じく別の場所 (figs.new/・tables.new/) に書く (--force のときは figs/・tables/ を作り直す)
    protect = (out / "body.md").exists() and not args.force
    IMG = {"figs": "figs.new" if protect else "figs", "tables": "tables.new" if protect else "tables"}
    for sub in ("pages", IMG["figs"], IMG["tables"]):
        (out / sub).mkdir(parents=True, exist_ok=True)
        if sub != "pages":
            # 前回の画像を消す (図表の数や続きのページが変わったとき，古い画像を build.py が拾わないように)
            for old in (out / sub).glob("*.png"):
                old.unlink()
    if protect:
        REPORT.append("body.md が既にあるので，図表の画像は figs.new/・tables.new/ に書いた (figs/・tables/ は触っていない)")


    # 巻号が分かっていれば，設定の eras が言う体裁と食い違わないかを確かめる
    mp = out / "meta.yaml"
    if mp.exists():
        meta_now = yaml.safe_load(mp.read_text(encoding="utf-8")) or {}
        warns, _kind, era = layout.check(prof, args.pdf, meta_now.get("volume"), meta_now.get("issue"))
        REPORT.extend(warns)
        if era and era.get("refs_head"):
            REPORT.append(f"この巻号の引用文献の見出しは「{era['refs_head']}」のはず (設定の eras より)")
        if era and era.get("category"):
            REPORT.append(f"この巻号の原稿種別の印字は「{era['category']}」のはず (設定の eras より)")

    doc = pymupdf.open(args.pdf)
    lay = auto_layout(doc, lay, as_list(prof["sections"]["refs"]))
    tol = lay["size_tol"]

    def is_h1(l):
        return head_font(l["font"], lay) and near(l["size"], lay["heading1_size"], tol) \
            and l["text"].lstrip().startswith(lay["heading1_prefix"])

    def is_h2(l):
        return head_font(l["font"], lay) and near(l["size"], lay["heading2_size"], tol) \
            and not re.match(lay["caption_pattern"], l["text"])

    def is_body(l):
        # 寝た行 (縦組みの表・図の軸の題) は本文にしない (本文の大きさや見出しの書体の字が「## 5」のような見出しになる．34(1):65)
        if l.get("cap") or l.get("dir", (1, 0)) != (1, 0):
            return False
        return near(l["size"], lay["body_size"], tol) or near(l["size"], lay["ref_size"], tol) and in_refs[0] \
            or is_h1(l) or is_h2(l)

    in_refs = [False]
    refs_closed = [False]   # 付表の題で文献の節を終えた (以後は大見出しだけを本文とみる)
    started = False
    md = []          # 出力する行
    para = ""        # 組み立て中の段落
    refs = []        # 引用文献 (1件1行)
    last_h2 = [None]  # 直前の小見出し (英文の論文で折り返した小見出しをつなぐため)
    n_refs = [0]     # 途中で出した引用文献の数 (後ろに大見出しが続いたとき)
    floats_txt = []
    page1_txt = []
    fig_count = {"fig": 0, "table": 0}
    pending_floats = []
    appendix_floats = []   # 付表の枠 (本文の末尾，謝辞・摘要・引用文献の節の前にまとめて置く)
    last_float = {}   # 直前の図表 (続きのページを同じ図表に足すため)
    seen_floats = {}  # (種類, 番号) → 図表 (「表1（続き）」を見分けるため)
    captions = {}     # 図表の題 (見開きで後から伸びるので，最後に body.md へ入れる)
    feet = {}         # 表の脚注 (続きのページの表は最後のページのもの．最後に body.md へ入れる)
    foot_state = {}   # 表の脚注を分けた結果 (split_table_foot の state)．分けられなかった表に作成役への注記を書く

    def add_part(prev, page, pno, c, lines, cap, how):
        """前のページから続く図表の画像を足す．

        見開き (横に続く) かどうかは，前のページの図題と同じ高さに図題の続きの行があるかで決める
        (植生学会誌 37(1) 表2)．縦に続く表 (42(2) 表1) は，前のページと高さの範囲が同じでも見開きではない．
        """
        prev["parts"] += 1
        prev["last_page"] = pno   # 続きが何ページも続く付表 (35(1):89 は 8 ページ) の，次のページの上端の判定に使う
        cap_rects = [cap["cap_rect"]] if cap else []
        spread = False
        # 寝た図表 (縦組みの表) の図題は高さで見開きを決められない (表の行を図題に足してしまう．34(1):23 の表2)
        if how is None and pno == prev["page"] + 1 and prev["cap_rows"] and prev.get("cap_dir", (1, 0)) == (1, 0):
            ys = [r[0] for r in prev["cap_rows"]]
            more = [l for l in lines if min(ys) - 3 <= l["y0"] <= max(ys) + 3 and l.get("dir", (1, 0)) == (1, 0)
                    and near(l["size"], prev["cap_size"], 0.3) and not l.get("cap")]
            if more:
                spread = True
                for l in more:
                    l["cap"] = True
                    cap_rects.append(pymupdf.Rect(l["x0"], l["y0"], l["x1"], l["y1"]))
                rows = sorted(prev["cap_rows"] + [(l["y0"], 10000 + l["x0"], l["md"]) for l in more],
                              key=lambda r: (round(r[0] / 4), r[1]))
                text = ""
                for r in rows:
                    text = join(text, r[2])
                captions[prev["key"]] = strip_label(text, lay)
                REPORT.append(f"p{pno}: {prev['key']} の図題が見開きで続く ({len(more)} 行をつないだ)．確かめる")
        state = foot_state.setdefault(prev["key"], {})
        state.pop("foot", None)    # 脚注の有無は最後のページで決める (表題と表の間の注 (head) は最初のページのものを残す)
        body_rect, foot, cut_y = split_table_foot(c, cap, f"{prev['key']} の続き", lay, cont=True, state=state) \
            if prev["kind"] == "table" else (None, None, None)
        content = body_rect or content_rect(c, cap)
        sub = "figs" if prev["kind"] == "fig" else "tables"
        name = f"{prev['stem']}_{prev['parts']}.png"
        clip = trim_caption(content, cap_rects, page)
        if cut_y is not None:
            apply_cut(clip, cut_y)
            feet[prev["key"]] = foot     # ページをまたぐ表は，最後のページの脚注を書く
        page.get_pixmap(dpi=args.dpi_fig if prev["kind"] == "fig" else 200, clip=clip).save(out / IMG[sub] / name)
        REPORT.append(f"p{pno}: {prev['key']} の続き ({how or ('見開き (横に続く)' if spread else '縦に続く')})"
                      f" {tuple(round(v) for v in clip)} → {sub}/{name}")

    def flush():
        nonlocal para
        if para.strip():
            md.append(para.strip())
            md.append("")
        para = ""
        # 段落の切れ目で，そのページの図表の枠を入れる
        while pending_floats:
            md.extend(pending_floats.pop(0))
            md.append("")

    for page in doc:
        pno = page.number + 1
        page.get_pixmap(dpi=args.dpi_page).save(out / "pages" / f"p{pno:03d}.png")
        mid = page.rect.width / 2
        lines = page_lines(page, lay)

        if not started:
            # 最初の大見出しより上 (題・著者・要旨) は page1.txt へ．本文は見出しの 1.5 行上から
            h1 = [l for l in lines if is_h1(l)]
            cut = min(l["y0"] for l in h1) - lay["body_size"] * 1.5 if h1 else 1e9
            page1_txt.append(f"===== page {pno}")
            page1_txt += [f"{l['size']:4.1f} {l['font'][:18]:18s} {l['text']}" for l in
                          sorted(lines, key=lambda l: (round(l['y0']), l['x0'])) if l["y0"] < cut]
            if not h1:
                continue
            started = True
            lines = [l for l in lines if l["y0"] >= cut]

        mark_captions(lines, lay)
        # 図表 (引用文献の見出しがあるページでは，文献の字の大きさも本文として扱う)
        refs_here = not refs_closed[0] and (in_refs[0] or any(
            is_h1(l) and l["text"].strip().lstrip(lay["heading1_prefix"]).strip() in as_list(prof["sections"]["refs"])
            for l in lines))
        # 文献の後ろに付表が続くときは，付表の題で文献の節を終える (付表の種名の行を文献にしない．35(1):1 など)．
        # 付表の題より後ろ (段・高さの順) の行は本文にしない
        appx_caps = [l for l in lines if l.get("appx")]
        close_at = min(((column_of(l, mid), l["y0"]) for l in appx_caps), default=None) if refs_here else None
        if close_at:
            REPORT.append(f"p{pno}: 付表の題で引用文献の節を終えた ({min(appx_caps, key=lambda l: l['y0'])['text'][:20]})")

        def is_body_page(l):
            if refs_closed[0] and not is_h1(l):
                return False
            if close_at and (column_of(l, mid), l["y0"]) >= close_at and not is_h1(l):
                return False
            return is_body(l) or refs_here and near(l["size"], lay["ref_size"], tol)
        clusters = [sub for c in float_regions(page, lines, lay, is_body_page) for sub in split_by_captions(c, lay)]
        caps = {id(c): caption_of(c, lay) for c in clusters}
        attach_side_figures(clusters, caps)
        grow_tables(clusters, caps)
        body_now = [l for l in lines if is_body_page(l) and not l["footer"]]
        orphans = []      # キャプションの無いまとまり (前のページの図表の続きの候補)
        for c in clusters:
            cap = caps[id(c)]
            txt = [e[2] for e in c["elems"] if e[0] == "text"]
            if txt:
                floats_txt.append(f"===== page {pno} {'' if not cap else cap['kind'] + str(cap['num'])}")
                floats_txt += [l["text"] for l in sorted(txt, key=lambda l: (round(l['y0']), l['x0']))]
            if cap and (cap["kind"], cap["num"], cap["appx"]) in seen_floats:
                # 「表1（つづき）」「付表1. … （つづき）」: 同じ番号のキャプションが再び出たら続き
                add_part(seen_floats[(cap["kind"], cap["num"], cap["appx"])], page, pno, c, lines, cap,
                         "縦に続く (キャプションあり)")
                continue
            if not cap:
                orphans.append(c)
                continue
            kind, num, appx = cap["kind"], cap["num"], cap["appx"]
            fig_count[kind] += 1
            stem = "appendix" if appx else kind
            key = f"{stem}{num}"
            # 表の下の罫線より下の脚注は画像に入れず，枠に文字で書く
            foot_state[key] = {}
            body_rect, foot, cut_y = split_table_foot(c, cap, key, lay, state=foot_state[key]) \
                if kind == "table" else (None, None, None)
            content = clamp_to_column(body_rect or content_rect(c, cap), cap, body_now, mid)
            clip = trim_caption(content, [cap["cap_rect"]], page)
            if cut_y is not None:
                apply_cut(clip, cut_y)
                feet[key] = foot
            sub, name = ("figs" if kind == "fig" else "tables"), f"{stem}{num}.png"
            page.get_pixmap(dpi=args.dpi_fig if kind == "fig" else 200, clip=clip).save(out / IMG[sub] / name)
            captions[key] = strip_label(cap["text"], lay)
            rows = [(l["y0"], l["x0"], l["md"]) for l in lines if l.get("cap") and cap["cap_rect"].intersects(
                pymupdf.Rect(l["x0"], l["y0"], l["x1"], l["y1"]))]
            last_float = {"kind": kind, "num": num, "parts": 1, "page": pno, "rect": content, "stem": key,
                          "cap_rows": rows, "key": key, "cap_size": cap["line"]["size"],
                          "cap_dir": cap["line"].get("dir", (1, 0))}
            seen_floats[(kind, num, appx)] = last_float
            if appx:
                appendix_floats.append([f":::table TA{num} {cap['label']}", f"@@CAP {key}@@", "@image", f"@@FOOT {key}@@", ":::"])
            elif kind == "fig":
                pending_floats.append([f":::fig F{num} {cap['label']} {name}", f"@@CAP {key}@@", ":::"])
            else:
                pending_floats.append([f":::table T{num} {cap['label']}", f"@@CAP {key}@@",
                                       # 表は画像のまま載せるのが既定 (2026-09-29 ユーザ指示)．ただし DTP の号で組版された表が
                                       # 容易に組めるときだけは組む (table_draft.py で下書きし，@image の行を消す)
                                       "@image",
                                       f"<!-- 組版された表で容易に組めるなら: table_draft.py (page {pno}) で組み，上の @image の行を消す -->",
                                       f"@@FOOT {key}@@",   # 表の脚注 (table-wrap-foot)．無ければ消す
                                       ":::"])
            REPORT.append(f"p{pno}: {key} の枠 {tuple(round(v) for v in clip)}"
                          + (f" → tables/{name} (付表．枠は TA{num})" if appx else ""))
        if orphans and last_float:
            # キャプションの無いまとまりは1つに合わせる (表の中の散らばった字が別々のまとまりになるため)．
            # 直前の図表の次のページの上端にあるか，大きければ，その図表の続き
            u = {"rect": pymupdf.Rect(), "elems": []}
            for c in orphans:
                u["rect"] |= c["rect"]
                u["elems"] += c["elems"]
            near_top = pno == last_float.get("last_page", last_float["page"]) + 1 and u["rect"].y0 < lay["header_y_max"] + 60
            if near_top or u["rect"].get_area() > page.rect.get_area() * 0.25:
                add_part(last_float, page, pno, u, lines, None, None)

        body = [l for l in lines if is_body_page(l) and not l["footer"]]
        modes = column_modes([l for l in body if not near(l["size"], lay["ref_size"], tol)], mid)
        ref_modes = column_modes([l for l in body if near(l["size"], lay["ref_size"], tol)], mid, hanging=True)
        # 同じ行が分かれていることがあるので，行の底 (y1) で並べ，同じ高さなら左から
        body.sort(key=lambda l: (column_of(l, mid), round(l["y1"]), l["x0"]))

        for l in body:
            col = column_of(l, mid)
            dx = l["x0"] - modes.get(col, l["x0"])
            if is_h1(l):
                title = l["text"].strip().lstrip(lay["heading1_prefix"]).strip()
                flush()
                if in_refs[0] and refs:
                    # 引用文献の後ろに大見出しが続く (英文の論文の末尾の「■ 要約」) ときは，文献をその見出しの前に出す
                    md.extend(r.strip() for r in refs)
                    md.append("")
                    n_refs[0] += len(refs)
                    refs.clear()
                in_refs[0] = title in as_list(prof["sections"]["refs"])
                md.append(f"# {title}")
                md.append("")
                if in_refs[0]:
                    md.append("<!-- 引用文献は1件1行．下の行を確かめる -->")
                    md.append("")
                continue
            if in_refs[0]:
                dx = l["x0"] - ref_modes.get(col, l["x0"])
                if dx < lay["ref_indent_max"] or not refs:
                    refs.append(l["md"])
                else:
                    refs[-1] = join(refs[-1], l["md"])
                continue
            if is_h2(l):
                flush()
                if lay.get("latin"):
                    # 英文の論文: 小見出しは学名の斜体を保ち，2 行に折り返したものは 1 つにつなぐ
                    prev = last_h2[0]
                    if prev and md[-2:] == [prev["head"], ""] and column_of(prev["line"], mid) == col \
                            and -l["size"] * 0.5 <= l["y0"] - prev["line"]["y1"] < l["size"] * 0.8:  # 行の箱は 1pt ほど重なる
                        md[-2] = "## " + join(prev["head"][3:], l["md"].strip())
                    else:
                        md.extend([f"## {l['md'].strip()}", ""])
                    last_h2[0] = {"head": md[-2], "line": l}
                    continue
                md.append(f"## {l['text'].strip()}")
                md.append("")
                continue
            if dx >= lay["indent_min"]:
                flush()
                para = l["md"].lstrip()
            else:
                para = join(para, l["md"])
        if close_at:
            in_refs[0] = False
            refs_closed[0] = True
    flush()
    md += [r.strip() for r in refs]
    md.append("")
    if appendix_floats:
        # 付表は文献の後ろのページにあるが，build.py は文献の節の中の枠を拾わない．
        # 本文の末尾 (謝辞・摘要・引用文献などの節の見出しの前) に置く
        special = {t for k in ("ack", "abstract", "refs") for t in as_list(prof["sections"].get(k, []))}
        at = next((i for i, l in enumerate(md) if l.startswith("# ") and l[2:].strip() in special), len(md))
        block = ["<!-- 付表 (紙面では引用文献の後ろ)．本文の末尾に置いた．必要なら初めて引くところへ移す -->", ""]
        for f in appendix_floats:
            block += f + [""]
        md[at:at] = block

    md = [re.sub(r"@@CAP (\w+)@@", lambda m: captions.get(m.group(1), ""), l) for l in md]
    md = [f for l in md for f in (foot_lines(l[7:-2], feet, foot_state) if l.startswith("@@FOOT ") else [l])]
    body_path = out / "body.md"
    if body_path.exists() and not args.force:
        # AI が手で直した body.md (組んだ表など) を消さない
        body_path = out / "body.new.md"
        print("body.md は既にあるので上書きしない (body.new.md に書いた．AI が手で直したところを移してから置き換える)")
    body_path.write_text("\n".join(md), encoding="utf-8")
    (out / "floats.txt").write_text("\n".join(floats_txt), encoding="utf-8")
    (out / "page1.txt").write_text("\n".join(page1_txt), encoding="utf-8")
    pdf_meta = draft_meta(doc, prof)
    (out / "meta.pdf.yaml").write_text(
        "# PDF の1ページ目から読んだ書誌 (照合用)．正は meta.yaml．\n"
        + yaml.safe_dump(pdf_meta, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    fill_meta(out / "meta.yaml", pdf_meta)
    (out / "report.txt").write_text("\n".join(REPORT), encoding="utf-8")
    print(f"本文 {len(md)} 行，引用文献 {n_refs[0] + len(refs)} 件，図 {fig_count['fig']}，表 {fig_count['table']}")
    print(f"出力: {out}")


def foot_lines(key, feet, foot_state):
    """表の枠の @image の後ろに書く行: 分けた脚注と，プログラムで分けられなかったときの作成役への注記．

    注記は <!-- … --> の 1 行 (build.py は枠の中の <!-- で始まる行を捨てる)．脚注が無いと分かるとき
    (最後の罫線の下に何も無い・横組みの表で罫線も脚注の印も無い) は書かない．
    """
    st = foot_state.get(key, {})
    out = list(feet.get(key) or [])
    if not out and st.get("foot") == "maybe":
        out.append(f"<!-- 脚注: 画像に脚注が入っている見込み ({st.get('why', '')})．紙面で確かめ，"
                   "画像を脚注の手前で切り直し (crop.py)，脚注をこの下に文字で書く -->")
    if st.get("head"):
        out.append("<!-- 脚注: 表題と表の間に注の行があり，画像に入っている．紙面で確かめ，脚注なら画像を切り直し (crop.py)，"
                   "この下に文字で書く (表題の続きなら表題へ) -->")
    if st.get("omitted"):
        out.append(f"<!-- 脚注: 表の最後の罫線の上に「{st['omitted'][:40]}」の行がある (画像に入っている)．"
                   "脚注なら紙面で確かめ，画像を切り直し (crop.py)，この下に文字で書く -->")
    return out


def strip_label(text, lay):
    for pat in (lay["caption_pattern"], lay.get("appendix_pattern")):
        if pat and re.match(pat, text):
            return re.sub(pat + r"[.．]?\s*", "", text, count=1).strip()
    return text.strip()


# ---------------------------------------------------------------- 書誌 (PDF から)

def draft_meta(doc, prof):
    """1ページ目から書誌を読む．ウェブから取れない項目 (原稿種別・連絡著者) の出どころ．"""
    p1 = doc[0]
    raw = p1.get_text()
    flat = re.sub(r"\s+", "", raw)
    def rx(p, s=raw):
        m = re.search(p, s)
        return m.groups() if m else None
    vol = rx(r"(\d+)\s*:\s*(\d+)\s*[-–]\s*(\d+)\s*,\s*(\d{4})")
    issue = rx(r"No\.\s*(\d+)", doc[1].get_text()) if doc.page_count > 1 else None
    rec = rx(r"受付[:：](\d{4})年(\d+)月(\d+)日", flat)
    acc = rx(r"受理[:：](\d{4})年(\d+)月(\d+)日", flat)
    kind = next((k for k in prof["article_types"] if re.search(rf"^\s*{k}\s*$", raw, re.M)), None)
    email = rx(r"E-mail[:：]\s*(\S+@[\w.\-]+)")
    doi = rx(r"(10\.\d{4,9}/[^\s]+)")
    # 著者の行 (和文の氏名の大きさ) をつないで「＊」の付いた著者を探す
    lay = prof["layout"]
    text_of = lambda l: "".join(sp["text"] for sp in l["spans"])
    p1_lines = [l for b in p1.get_text("dict")["blocks"] for l in b.get("lines", [])]
    name_lines = [l for l in p1_lines
                  if near(max((sp["size"] for sp in l["spans"]), default=0), lay["heading1_size"], lay["size_tol"])
                  and l["bbox"][1] < 250 and not re.search(r"[A-Za-z]{2}", text_of(l)) and JA_CHAR.search(text_of(l))]
    # 同じ高さにある小さい字の行 (上付きの番号や＊だけの行) もまとめ，行ごとに左から読む
    cy = lambda l: (l["bbox"][1] + l["bbox"][3]) / 2
    def row_of(l):  # 中心の高さがいちばん近い著者の行 (重なりが無ければ None)
        hit = [n for n in name_lines if min(l["bbox"][3], n["bbox"][3]) - max(l["bbox"][1], n["bbox"][1]) > 0]
        return round(cy(min(hit, key=lambda n: abs(cy(n) - cy(l))))) if hit else None
    x_max = max((n["bbox"][2] for n in name_lines), default=0) + 20
    band = [l for l in p1_lines if row_of(l) is not None and l["bbox"][0] < x_max
            and not re.search(r"[A-Za-z]{2}|[぀-鿿]{6}", text_of(l)) or l in name_lines]
    band.sort(key=lambda l: (row_of(l), l["bbox"][0]))
    names = re.sub(r"\s+", "", "".join(text_of(l) for l in band))
    corresp = [i for i, a in enumerate(names.split("・")) if "＊" in a or "*" in a]
    fmt = lambda t: f"{t[0]}-{int(t[1]):02d}-{int(t[2]):02d}" if t else None
    at = prof["article_types"].get(kind, {})
    return {
        "article_type": at.get("type"), "category": {"ja": kind, "en": at.get("en")},
        "doi": doi[0] if doi else None,
        "volume": vol[0] if vol else None, "issue": issue[0] if issue else None,
        "fpage": vol[1] if vol else None, "lpage": vol[2] if vol else None, "year": vol[3] if vol else None,
        "history": {"received": fmt(rec), "accepted": fmt(acc)},
        "title_ja": doc.metadata.get("title"),
        "author_line": names, "corresp_index": corresp, "email": email[0] if email else None,
    }


def fill_meta(path, pm):
    """meta.yaml (ウェブから) の「要確認」を PDF の値で埋め，食い違いを報告する．"""
    if not path.exists():
        REPORT.append("meta.yaml が無い: fetch_jstage.py を先に動かすか，meta.pdf.yaml をもとに書く")
        return
    text = path.read_text(encoding="utf-8")
    head = "".join(l for l in text.splitlines(True) if l.startswith("#"))
    m = yaml.safe_load(text)
    if str(m.get("article_type", "")).startswith("要確認") and pm["article_type"]:
        m["article_type"] = pm["article_type"]
        m["category"] = pm["category"]
    for i in pm["corresp_index"]:
        if i < len(m.get("authors", [])):
            m["authors"][i]["corresp"] = True
            m["authors"][i]["email"] = m["authors"][i].get("email") or pm["email"]
    for k in ("volume", "issue", "fpage", "lpage"):
        if pm[k] and str(m.get(k)) != str(pm[k]):
            REPORT.append(f"書誌の食い違い {k}: ウェブ {m.get(k)} / PDF {pm[k]}")
    for k in ("received", "accepted"):
        if pm["history"][k] and m.get("history", {}).get(k) != pm["history"][k]:
            REPORT.append(f"書誌の食い違い {k}: ウェブ {m['history'].get(k)} / PDF {pm['history'][k]}")
    path.write_text(head + yaml.safe_dump(m, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
