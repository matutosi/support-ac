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

SKILL_DIR = Path(__file__).resolve().parent.parent


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


def auto_layout(doc, lay):
    """字の大きさ・柱と脚注の位置を，この PDF の統計から決める (設定の値は既定値)．

    年代で組み方が変わる (植生学会誌: 2014 年は本文 9.9pt，2025 年は 9.2pt) ため．
    """
    lay = dict(lay)
    cnt, h1 = collections.Counter(), collections.Counter()
    pages = list(doc)[1:] or list(doc)
    for p in pages:
        for b in p.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                sp = max(l["spans"], key=lambda s: s["size"])
                t = "".join(s["text"] for s in l["spans"]).strip()
                size = round(sp["size"], 1)
                if lay["heading_font"] in sp["font"]:
                    if t.startswith(lay["heading1_prefix"]):
                        h1[size] += 1
                elif len(t) > 10:
                    cnt[size] += len(t)
    if cnt:
        lay["body_size"] = cnt.most_common(1)[0][0]
        lay["heading2_size"] = lay["body_size"]
    if h1:
        lay["heading1_size"] = h1.most_common(1)[0][0]
    last = collections.Counter(
        round(max(s["size"] for s in l["spans"]), 1)
        for b in doc[-1].get_text("dict")["blocks"] for l in b.get("lines", [])
        if len("".join(s["text"] for s in l["spans"]).strip()) > 10)
    if last and last.most_common(1)[0][0] < lay["body_size"]:
        lay["ref_size"] = last.most_common(1)[0][0]
    # 柱: 2ページ目以降の本文の最上行より上．脚注: 本文の最下行より下
    tops, bottoms = [], []
    for p in pages:
        ys = [(l["bbox"][1], l["bbox"][3]) for b in p.get_text("dict")["blocks"] for l in b.get("lines", [])
              if abs(max(s["size"] for s in l["spans"]) - lay["body_size"]) <= lay["size_tol"]
              and not re.fullmatch(r"\s*\d+\s*", "".join(s["text"] for s in l["spans"]))]
        if ys:
            tops.append(min(y[0] for y in ys))
            bottoms.append(max(y[1] for y in ys))
    if tops:
        lay["header_y_max"] = min(tops) - 1
        lay["footer_y_min"] = max(bottoms) + 1
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
        out.append(make_line(spans, lay))
    return merge_fragments(out, lay, page.rect.width / 2)


def make_line(spans, lay):
    x0 = min(s["bbox"][0] for s in spans)
    y0 = min(s["bbox"][1] for s in spans)
    x1 = max(s["bbox"][2] for s in spans)
    y1 = max(s["bbox"][3] for s in spans)
    size = max(s["size"] for s in spans)
    main = max(spans, key=lambda s: s["size"])
    return {
        "x0": x0, "y0": y0, "x1": x1, "y1": y1, "size": size, "spans": spans,
        "font": main["font"].split("+")[-1],
        "text": "".join(s["text"] for s in spans),
        "md": spans_to_md(spans, size, lay),
        "footer": y0 >= lay["footer_y_min"],
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


def spans_to_md(spans, size, lay):
    """書体と大きさから *斜体*・^上付き^・~下付き~ の印を付けた文字列にする．"""
    # 本文の大きさの字 (空白を除く) の上端と下端
    boxes = [c["bbox"] for s in spans if s["size"] >= size * 0.8 for c in s.get("chars", []) if c["c"].strip()]         or [s["bbox"] for s in spans if s["size"] >= size * 0.8]
    top = min(b[1] for b in boxes)
    bottom = max(b[3] for b in boxes)
    parts = []
    for s in spans:
        t = s["text"]
        if s["size"] < size * 0.8 and t.strip():
            # 行の中心より上にあれば上付き，下にあれば下付き
            mid = (s["bbox"][1] + s["bbox"][3]) / 2
            t = f"^{t.strip()}^" if mid < (top + bottom) / 2 else f"~{t.strip()}~"
        elif lay["italic_font"] in s["font"] and t.strip():
            lead = t[: len(t) - len(t.lstrip())]
            trail = t[len(t.rstrip()):]
            t = f"{lead}*{t.strip()}*{trail}"
        parts.append(t)
    s = "".join(parts)
    return s.replace("**", "")  # 隣り合う斜体の印をつなぐ


def near(a, b, tol):
    return abs(a - b) <= tol


# ---------------------------------------------------------------- 文字列の連結

REPORT = []
JA_CHAR = re.compile(r"[぀-ヿ㐀-鿿]")


def join(a, b):
    """行をつなぐ．和文は詰め，欧文は空白を入れ，行末のハイフンを判断する．"""
    if not a:
        return b.lstrip()
    trailing_space = a != a.rstrip()
    a = a.rstrip()
    b = b.lstrip()
    if not b:
        return a
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
    elems = []
    for img in page.get_image_info():
        elems.append(("img", pymupdf.Rect(img["bbox"])))
    for d in page.get_drawings():
        r = d["rect"]
        if r.y1 <= lay["header_y_max"] + 5 and r.width > W * 0.5:
            continue  # 柱の下の罫線
        elems.append(("draw", pymupdf.Rect(r)))
    for l in lines:
        if not is_body(l) and not l["footer"]:
            elems.append(("text", pymupdf.Rect(l["x0"], l["y0"], l["x1"], l["y1"]), l))
    # 近いもの同士をまとめる
    clusters = []
    for e in elems:
        r = pymupdf.Rect(e[1])
        hit = None
        for c in clusters:
            if (c["rect"] + (-12, -12, 12, 12)).intersects(r):
                hit = c
                break
        if hit:
            hit["rect"] |= r
            hit["elems"].append(e)
        else:
            clusters.append({"rect": r, "elems": [e]})
    # 連鎖でつながるものを繰り返しまとめる
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if (clusters[i]["rect"] + (-12, -12, 12, 12)).intersects(clusters[j]["rect"]):
                    clusters[i]["rect"] |= clusters[j]["rect"]
                    clusters[i]["elems"] += clusters[j]["elems"]
                    del clusters[j]
                    merged = True
                    break
            if merged:
                break
    return clusters


def mark_captions(lines, lay):
    """キャプション (ゴシック体の「図1.」「表1.」) とその続きの行に印を付け，本文から外す．

    2025 年の号はキャプションが本文と同じ大きさなので，大きさでは本文と分けられない．
    続きの行は，すぐ下にあり，キャプションの行頭より右から始まる (ぶら下げ字下げ) もの．
    """
    pat = re.compile(lay["caption_pattern"])
    for cap in [l for l in lines if lay["heading_font"] in l["font"] and pat.match(l["text"])]:
        cap["cap"] = True
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
    pat = re.compile(lay["caption_pattern"])
    caps = [e for e in cluster["elems"] if e[0] == "text" and lay["heading_font"] in e[2]["font"]
            and pat.match(e[2]["text"])]
    if not caps:
        return None
    cap = min(caps, key=lambda e: e[2]["y0"])[2]
    # キャプションの続きの行 (同じ大きさ・すぐ下・左端がそろう)
    text = cap["md"]
    last = cap
    for e in sorted((e for e in cluster["elems"] if e[0] == "text"), key=lambda e: e[2]["y0"]):
        l = e[2]
        if l is cap or l["y0"] <= last["y0"]:
            continue
        if near(l["size"], cap["size"], 0.2) and l["y0"] - last["y1"] < cap["size"] * 0.8 \
                and cap["x0"] - 2 <= l["x0"] <= cap["x0"] + cap["size"] * 1.5:
            text = join(text, l["md"])
            last = l
        else:
            break
    m = pat.match(cap["text"])
    kind = "fig" if m.group(1) in ("図", "Fig.") else "table"
    return {"kind": kind, "num": int(m.group(2)), "line": cap, "text": text.strip(),
            "cap_rect": pymupdf.Rect(cap["x0"], cap["y0"], last["x1"], last["y1"])}


def content_rect(c, cap):
    """まとまりから図題 (キャプションとその続きの行) を除いた範囲．"""
    r = pymupdf.Rect()
    for e in c["elems"]:
        if e[0] == "text" and (e[2].get("cap") or (cap and cap["cap_rect"].contains(e[1]))):
            continue
        r |= e[1]
    return r if not r.is_empty else c["rect"]


def trim_caption(content, cap_rects, page, margin=3):
    """余白を足したうえで，図題の手前で切る (図題が画像に写り込まないように)．"""
    clip = (content + (-margin, -margin, margin, margin)) & page.rect
    for cr in cap_rects:
        if cr.x1 < clip.x0 or cr.x0 > clip.x1:
            continue
        if cr.y0 >= content.y1 - 2:          # 図題が下
            clip.y1 = min(clip.y1, cr.y0 - 0.5)
        elif cr.y1 <= content.y0 + 2:        # 図題が上
            clip.y0 = max(clip.y0, cr.y1 + 0.5)
    return clip


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--journal", default="vegsci")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dpi-page", type=int, default=100)
    ap.add_argument("--force", action="store_true", help="既にある body.md を上書きする (手で直した分は消える)")
    ap.add_argument("--dpi-fig", type=int, default=300)
    args = ap.parse_args()

    prof = load_profile(args.journal)
    lay = prof["layout"]
    out = Path(args.out)
    for sub in ("pages", "figs", "tables"):
        (out / sub).mkdir(parents=True, exist_ok=True)
        if sub != "pages":
            # 前回の画像を消す (図表の数や続きのページが変わったとき，古い画像を build.py が拾わないように)
            for old in (out / sub).glob("*.png"):
                old.unlink()

    doc = pymupdf.open(args.pdf)
    lay = auto_layout(doc, lay)
    tol = lay["size_tol"]

    def is_h1(l):
        return lay["heading_font"] in l["font"] and near(l["size"], lay["heading1_size"], tol) \
            and l["text"].lstrip().startswith(lay["heading1_prefix"])

    def is_h2(l):
        return lay["heading_font"] in l["font"] and near(l["size"], lay["heading2_size"], tol) \
            and not re.match(lay["caption_pattern"], l["text"])

    def is_body(l):
        if l.get("cap"):
            return False
        return near(l["size"], lay["body_size"], tol) or near(l["size"], lay["ref_size"], tol) and in_refs[0] \
            or is_h1(l) or is_h2(l)

    in_refs = [False]
    started = False
    md = []          # 出力する行
    para = ""        # 組み立て中の段落
    refs = []        # 引用文献 (1件1行)
    floats_txt = []
    page1_txt = []
    fig_count = {"fig": 0, "table": 0}
    pending_floats = []
    last_float = {}   # 直前の図表 (続きのページを同じ図表に足すため)
    seen_floats = {}  # (種類, 番号) → 図表 (「表1（続き）」を見分けるため)
    captions = {}     # 図表の題 (見開きで後から伸びるので，最後に body.md へ入れる)

    def add_part(prev, page, pno, c, lines, cap, how):
        """前のページから続く図表の画像を足す．

        見開き (横に続く) かどうかは，前のページの図題と同じ高さに図題の続きの行があるかで決める
        (植生学会誌 37(1) 表2)．縦に続く表 (42(2) 表1) は，前のページと高さの範囲が同じでも見開きではない．
        """
        prev["parts"] += 1
        cap_rects = [cap["cap_rect"]] if cap else []
        spread = False
        if how is None and pno == prev["page"] + 1 and prev["cap_rows"]:
            ys = [r[0] for r in prev["cap_rows"]]
            more = [l for l in lines if min(ys) - 3 <= l["y0"] <= max(ys) + 3
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
        content = content_rect(c, cap)
        sub = "figs" if prev["kind"] == "fig" else "tables"
        name = f"{prev['kind'] if prev['kind'] == 'fig' else 'table'}{prev['num']}_{prev['parts']}.png"
        clip = trim_caption(content, cap_rects, page)
        page.get_pixmap(dpi=args.dpi_fig if prev["kind"] == "fig" else 200, clip=clip).save(out / sub / name)
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
        refs_here = in_refs[0] or any(
            is_h1(l) and l["text"].strip().lstrip(lay["heading1_prefix"]).strip() in as_list(prof["sections"]["refs"])
            for l in lines)
        def is_body_page(l):
            return is_body(l) or refs_here and near(l["size"], lay["ref_size"], tol)
        clusters = float_regions(page, lines, lay, is_body_page)
        orphans = []      # キャプションの無いまとまり (前のページの図表の続きの候補)
        for c in clusters:
            cap = caption_of(c, lay)
            txt = [e[2] for e in c["elems"] if e[0] == "text"]
            if txt:
                floats_txt.append(f"===== page {pno} {'' if not cap else cap['kind'] + str(cap['num'])}")
                floats_txt += [l["text"] for l in sorted(txt, key=lambda l: (round(l['y0']), l['x0']))]
            if cap and (cap["kind"], cap["num"]) in seen_floats:
                # 「表1（つづき）」: 同じ番号のキャプションが再び出たら続き
                add_part(seen_floats[(cap["kind"], cap["num"])], page, pno, c, lines, cap, "縦に続く (キャプションあり)")
                continue
            if not cap:
                orphans.append(c)
                continue
            kind, num = cap["kind"], cap["num"]
            fig_count[kind] += 1
            content = content_rect(c, cap)
            clip = trim_caption(content, [cap["cap_rect"]], page)
            sub, name = ("figs", f"fig{num}.png") if kind == "fig" else ("tables", f"table{num}.png")
            page.get_pixmap(dpi=args.dpi_fig if kind == "fig" else 200, clip=clip).save(out / sub / name)
            key = f"{kind}{num}"
            captions[key] = strip_label(cap["text"], lay)
            rows = [(l["y0"], l["x0"], l["md"]) for l in lines if l.get("cap") and cap["cap_rect"].intersects(
                pymupdf.Rect(l["x0"], l["y0"], l["x1"], l["y1"]))]
            last_float = {"kind": kind, "num": num, "parts": 1, "page": pno, "rect": content,
                          "cap_rows": rows, "key": key, "cap_size": cap["line"]["size"]}
            seen_floats[(kind, num)] = last_float
            if kind == "fig":
                pending_floats.append([f":::fig F{num} 図{num} {name}", f"@@CAP {key}@@", ":::"])
            else:
                pending_floats.append([f":::table T{num} 表{num}", f"@@CAP {key}@@",
                                       f"<!-- 要作成: tables/{name} と floats.txt (page {pno}) を見て表を組む -->",
                                       ":::"])
            REPORT.append(f"p{pno}: {kind}{num} の枠 {tuple(round(v) for v in clip)}")
        if orphans and last_float:
            # キャプションの無いまとまりは1つに合わせる (表の中の散らばった字が別々のまとまりになるため)．
            # 直前の図表の次のページの上端にあるか，大きければ，その図表の続き
            u = {"rect": pymupdf.Rect(), "elems": []}
            for c in orphans:
                u["rect"] |= c["rect"]
                u["elems"] += c["elems"]
            near_top = pno == last_float["page"] + 1 and u["rect"].y0 < lay["header_y_max"] + 60
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
                md.append(f"## {l['text'].strip()}")
                md.append("")
                continue
            if dx >= lay["indent_min"]:
                flush()
                para = l["md"].lstrip()
            else:
                para = join(para, l["md"])
    flush()
    md += [r.strip() for r in refs]
    md.append("")

    md = [re.sub(r"@@CAP (\w+)@@", lambda m: captions.get(m.group(1), ""), l) for l in md]
    body_path = out / "body.md"
    if body_path.exists() and not args.force:
        # 手で直した body.md (組んだ表など) を消さない
        body_path = out / "body.new.md"
        print("body.md は既にあるので上書きしない (body.new.md に書いた．手で直した所を移してから置き換える)")
    body_path.write_text("\n".join(md), encoding="utf-8")
    (out / "floats.txt").write_text("\n".join(floats_txt), encoding="utf-8")
    (out / "page1.txt").write_text("\n".join(page1_txt), encoding="utf-8")
    pdf_meta = draft_meta(doc, prof)
    (out / "meta.pdf.yaml").write_text(
        "# PDF の1ページ目から読んだ書誌 (照合用)．正は meta.yaml．\n"
        + yaml.safe_dump(pdf_meta, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    fill_meta(out / "meta.yaml", pdf_meta)
    (out / "report.txt").write_text("\n".join(REPORT), encoding="utf-8")
    print(f"本文 {len(md)} 行，引用文献 {len(refs)} 件，図 {fig_count['fig']}，表 {fig_count['table']}")
    print(f"出力: {out}")


def strip_label(text, lay):
    return re.sub(lay["caption_pattern"] + r"[.．]?\s*", "", text, count=1).strip()


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
