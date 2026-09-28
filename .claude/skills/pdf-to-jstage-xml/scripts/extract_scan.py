"""スキャン + OCR の古い号の PDF から下書き一式を作る (手順 1 の旧号版)．

使い方:
    python extract_scan.py <論文.pdf> --journal vegsci --out <作業ディレクトリ>

新しい号の PDF (InDesign で組んだもの) は extract.py を使う．こちらは 2000 年代より前の
「紙をスキャンして OCR をかけた PDF」(J-STAGE の NII-ELS 由来のもの) 向け．次の点が違う．

- 書体が1種類しかない (例: MS-Gothic) ので，**見出し・斜体・キャプションを書体で見分けられない**．
  代わりに行の幅・位置 (中央揃えか) と，キャプションの文言で見分ける．
- **斜体の情報が無い**．学名や誌名の斜体は AI がページ画像を見て付ける (report.txt に注意を出す)．
- 1行が細かい断片に分かれ，y がそろわない．**y の帯でまとめて x 順に並べ直す**と読み順が戻る．
- 図・表は画像や罫線として取れない (ページ全体が1枚の画像)．**キャプションの位置から枠を決めて**
  ページから切り出す．
- OCR の誤りが残る (`10crn`・`Sooiety`・`至`/`孟` など)．直すのは AI の仕事で，
  ここでは**怪しい字を report.txt に並べる**だけにする．

出力 (作業ディレクトリ):
    body.md       本文の下書き (AI がページ画像と見比べて直す前提の「たたき台」)
    ocr.md        ページ・段ごとの行 (座標つき．body.md を直すときの原文)
    page1.txt     1ページ目の行 (書誌を埋めるときに見る)
    floats.txt    図表の枠の中の行 (表を組むときに見る)
    pages/        ページ画像 (照合用．既定 100dpi = 画素 × 0.72 が pt．細かい字は PDF を高い解像度で描き直して見る)
    figs/・tables/ 図・表の画像 (キャプションは入れない)
    report.txt    自動で判断したことと，確かめるところの一覧
"""
import argparse
import collections
import difflib
import re
import statistics
import sys
from pathlib import Path

import pymupdf
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout                                         # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
REPORT = []

# スキャンの透かし (NII-ELS が全ページの上下に入れたもの)．字が崩れた形も拾う．
# ここは雑誌によらない分だけ．学会名などの雑誌固有の分は設定の scan.junk から足す (main)
JUNK_COMMON = r"NII[- ]?Electronic|NII-|Eleotronio|Library Service|N 工工|工工一"
JUNK = re.compile(JUNK_COMMON)
JA = r"ぁ-んァ-ヶ一-龥々ー"
# 図表の題．OCR は約物を全角にし，字も崩すので (「Tab且e 2．」)，設定の caption_pattern より緩く見る．
# 雑誌ごとに変えるときは設定の scan.caption_pattern に書く (main で差し替える)
# 付表 (「Appendix 1.」「付表1」) も表として拾う (24(1):29・41 で丸ごと落ちていた)
# 番号は OCR が 1 字の数字もどきに読むことがある (24(1):29 の「Appendix Z.」= 2)．句点の前の Z・l・I・O も番号とみる
CAP_DEFAULT = r"^(図|付表|表|Fig|Tab|Appendix|APPENDIX)[^\d]{0,4}(\d+|[ZlIO](?=\s*[.．]))"
TABLE_WORDS = ("表", "付表", "Tab", "Appendix", "APPENDIX")
CAP = re.compile(CAP_DEFAULT)
# OCR が取り違えやすい字 (見た目が似ているもの)．直さずに report.txt へ出すだけ
SUSPECT = re.compile(r"(crn|CIn|rn[のに]|至|孟|墨|正|齠|繝|【|】|工工|[０-９]|"
                     r"[A-Za-z][，．][A-Za-z]|[A-Za-z]{2,}[ぁ-んァ-ヶ])")


def load_profile(name):
    return yaml.safe_load((SKILL_DIR / "journals" / f"{name}.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 行の取り出し

def bands(frs, band):
    """断片を y の帯でまとめる (OCR は1行が断片に分かれ，断片ごとに y が数 pt ずれる)．"""
    rows = []
    for r, t in sorted(frs, key=lambda f: f[0].y1):
        c = (r.y0 + r.y1) / 2
        if rows and abs(c - rows[-1]["mid"]) <= band:
            rows[-1]["frs"].append((r, t))
            rows[-1]["mid"] = (rows[-1]["mid"] + c) / 2
        else:
            rows.append({"mid": c, "frs": [(r, t)]})
    out = []
    for row in rows:
        row["frs"].sort(key=lambda f: f[0].x0)
        rect = pymupdf.Rect()
        for r, _ in row["frs"]:
            rect |= r
        out.append({"rect": rect, "raw": "".join(t for _, t in row["frs"]), "mid": row["mid"]})
    return out


def raw_rows(page, band):
    """ページの行を，読み順に並べた「かたまり」の列で返す．

    1ページ目は題名・著者・英文要旨が**紙面の幅いっぱい**に組まれ，その下から2段になる．
    段の境をまたぐ断片があるかで，全幅の帯と2段の帯を見分け，
    全幅の帯は1つのかたまりに，2段の帯は左の段・右の段の順に分ける (これが読み順)．
    戻り値は {"rows": 行の列, "colw": 段の幅, "col": 段の番号} の列．
    """
    frs = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for l in b["lines"]:
            t = "".join(s["text"] for s in l["spans"])
            if t.strip():
                frs.append((pymupdf.Rect(l["bbox"]), t))
    mid = page.rect.width / 2
    colw = page.rect.width / 2 - 60
    # 段の境をまたぐ断片がある高さは「全幅」とみなす (1ページ目の題名・要旨，2段にまたがる図表)．
    # ただし OCR は，左の段の行末を中央まで数 pt はみ出させることがある (16(1):1 の ' Associations')．
    # それを全幅とみなすと，帯が上下につながって本文の左右の段が交互に混ざるので，
    # 細い断片は，同じ高さに段の中だけの断片が左右そろってあれば，段の行のはみ出しとみなす．
    def crosses(f):
        if not (f.x0 < mid - 8 < mid + 8 < f.x1):
            return False
        if f.x1 - f.x0 >= colw * 1.15:
            return True          # 要旨・2段にまたがる図表の行 (段より明らかに広い)
        return abs((f.x0 + f.x1) / 2 - mid) <= 15   # 中央揃えの題名・著者・所属

    zones = []
    for f, _ in sorted((f for f in frs if crosses(f[0])), key=lambda f: f[0].y0):
        if zones and f.y0 - zones[-1].y1 <= 40:
            zones[-1] |= f
        else:
            zones.append(pymupdf.Rect(f))

    # 全幅の帯の最後の行 (折り返しの短い行) は境をまたがないので，行頭の位置で見分けて取り込む
    for z in zones:
        inside = [f[0] for f in frs if z.y0 - 2 <= (f[0].y0 + f[0].y1) / 2 <= z.y1 + 2]
        left = min((f.x0 for f in inside), default=z.x0)
        for f, _ in sorted(frs, key=lambda f: f[0].y0):
            if abs(f.x0 - left) <= 6 and 0 < (f.y0 + f.y1) / 2 - z.y1 <= 20:
                z.y1 = f.y1

    # 紙面を，全幅の帯とそれ以外の帯に，上から切り分ける (これが読み順)
    cuts, y = [], 0.0
    for z in sorted(zones, key=lambda z: z.y0):
        if z.y0 > y:
            cuts.append((y, z.y0, False))
        cuts.append((max(y, z.y0), z.y1, True))
        y = z.y1
    cuts.append((y, page.rect.height, False))

    groups = []
    for y0, y1, full in cuts:
        seg = [f for f in frs if y0 <= (f[0].y0 + f[0].y1) / 2 < y1]
        if not seg:
            continue
        if full:
            rows = bands(seg, band)
            for r in rows:
                r["col"] = "全幅"
            groups.append({"rows": rows, "colw": page.rect.width - 100, "col": "全幅"})
            continue
        for col in (0, 1):
            rows = bands([f for f in seg if (f[0].x0 >= mid - 10) == col], band)
            for r in rows:
                r["col"] = col
            if rows:
                groups.append({"rows": rows, "colw": page.rect.width / 2 - 60, "col": col})
    return groups


def drop_junk(rows, page):
    """透かし・柱・ノンブルの行を外す (外したものは report.txt に出す)．"""
    keep = []
    for r in rows:
        t = r["raw"].strip()
        if JUNK.search(t) or r["rect"].y1 < 25 or r["rect"].y0 > page.rect.height - 32:
            REPORT.append(f"p{page.number + 1}: 透かし・柱として外した {t[:40]!r}")
            continue
        if re.fullmatch(r"[0-9０-９\s]{1,4}", t):
            continue      # ノンブル
        keep.append(r)
    return keep


def normalize(t):
    """OCR が入れた余計な空白を詰める (和文どうし・数字と和文の間)．

    欧文の語の間の空白は残す．全角の空白は行頭のものだけ残す (段落の字下げの印になる)．
    """
    lead = "　" if t.startswith("　") or t.startswith(" ") else ""
    t = t.strip().replace("　", " ")
    for _ in range(3):
        t = re.sub(rf"(?<=[{JA}、。，．（）「」『』・：；])\s+", "", t)
        t = re.sub(rf"\s+(?=[{JA}、。，．（）「」『』・：；])", "", t)
    t = re.sub(rf"(?<=\d)\s+(?=[{JA}])", "", t)
    t = re.sub(rf"(?<=[{JA}])\s+(?=\d)", "", t)
    return lead + re.sub(r" {2,}", " ", t).strip()


# ---------------------------------------------------------------- 行の見分け

def classify(rows, colw, cap_pat):
    """行を body (本文)・cap (キャプション)・head (見出し)・float (図表の中身) に分ける．

    書体が使えないので，行の幅と位置で決める．
    - キャプション: 「図1」「表1」「Fig. 1」「Table 1」で始まる
    - 本文: 段の幅の 3/4 以上を占める
    - 見出し: 短くて段の中で中央にある (「結 果」のように字を空けたもの)
    - 段落の最後の行: 短いが行頭が本文とそろい，句点などで終わる
    - それ以外の短い行: 図表の中の文字
    """
    body_x = statistics.mode([round(r["rect"].x0) for r in rows]) if rows else 0
    col_x0 = min((r["rect"].x0 for r in rows if r["rect"].width >= colw * 0.75), default=body_x)
    col_x1 = max((r["rect"].x1 for r in rows if r["rect"].width >= colw * 0.75), default=body_x + colw)
    for i, r in enumerate(rows):
        t = r["text"]
        w = r["rect"].width
        left, right = r["rect"].x0 - col_x0, col_x1 - r["rect"].x1
        cm = cap_pat.match(t.lstrip("　 "))
        # 段落の字下げで始まり，番号のあとに句点・コロンが無い行は本文 (「　Figure 1 shows …」「　表1に示す」．
        # 24(1):53 で図題と取り違え，同じ番号の枠が2つできた)．図題は字下げが無いか，「Fig. 1.」と句点が付く
        if cm and t.startswith(("　", " ")) and not re.match(r"\s*[.．:：]", t.lstrip("　 ")[cm.end():]):
            cm = None
        if cm:
            r["kind"] = "cap"
        elif w >= colw * 0.75:
            r["kind"] = "body"
        elif left > 20 and right > 20 and len(t) <= 12:
            r["kind"] = "head"
        elif abs(r["rect"].x0 - body_x) <= 8 and re.search(r"[．。，、）\)]$", t):
            r["kind"] = "body"
        elif abs(r["rect"].x0 - body_x) <= 8 and len(t) <= 24 and not re.search(r"[0-9]{2}", t) \
                and i + 1 < len(rows) and rows[i + 1]["rect"].width >= colw * 0.75:
            r["kind"] = "head2"
        else:
            r["kind"] = "float"
    return body_x, col_x0, col_x1


def float_runs(rows):
    """キャプションを含む，続いた float の帯を1つの図表にまとめる．

    図はキャプションが下，表は上にあるので，キャプションから上下へ伸ばす．
    """
    runs = []
    for i, r in enumerate(rows):
        if r["kind"] != "cap":
            continue
        kind = "table" if CAP.match(r["text"].lstrip("　 ")).group(1) in TABLE_WORDS else "fig"
        a = b = i
        # 図表の中の字は float のほか，短いので head と見分けがつかないものもある (軸の目盛りなど)．
        # 本文かキャプションに当たるまで伸ばす
        inside = ("float", "head", "head2")
        if kind == "fig":
            while a - 1 >= 0 and rows[a - 1]["kind"] in inside:
                a -= 1
        else:
            while b + 1 < len(rows) and rows[b + 1]["kind"] in inside:
                b += 1
        runs.append({"kind": kind, "cap": i, "a": a, "b": b})
    return runs


def cap_text(rows, i, cap_pat, body_x=None):
    """キャプションの行と，その続きをつないで返す．

    図題の2行目以降は本文と同じくらいの幅があるので，幅では本文と見分けられない．
    **行頭の位置**で見分ける (図題の塊は本文より少し右から始まる)．
    """
    cap_x = rows[i]["rect"].x0
    parts = [rows[i]["text"]]
    for r in rows[i + 1:]:
        if r["kind"] in ("cap", "head", "head2"):
            break
        indented = body_x is None or abs(r["rect"].x0 - body_x) > 4
        if abs(r["rect"].x0 - cap_x) > 5 or not indented:
            break
        parts.append(r["text"])
        r["kind"] = "capcont"
    text = join_text("", parts[0])
    for p in parts[1:]:
        text = join_text(text, p)
    m = cap_pat.match(text.lstrip("　 "))
    # 呼び名の番号も数字に読み替える (「Appendix Z」→「Appendix 2」)
    label = m.group(0)[:m.start(2) - m.start(0)] + m.group(2).translate(DIGIT_OCR)
    body = text[m.end():].lstrip("　 .．")
    return label, body, m.group(2).translate(DIGIT_OCR)


# ---------------------------------------------------------------- 文字列の連結

# OCR が数字と取り違える字 (24(1) の脚注の実測: 20G7・2〔｝07・2t 日・IQ.・ZO06・Juty l2)
DIGIT_OCR = str.maketrans({"O": "0", "o": "0", "D": "0", "G": "0", "Q": "0", "l": "1", "I": "1", "i": "1",
                           "t": "1", "Z": "2", "z": "2", "S": "5", "〔": "0", "｝": ""})
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
          "september", "october", "november", "december"]


def history_candidates(text):
    """1 ページ目の文字から，受付日・受理日の候補を読む．{"received": ("2006-08-21", 元の文字), …}

    和文は「受付：2006 年9 月2t 日／受理：…」，英文は「Received january IQ. ZO06/Accepted April 19, 2007」の形．
    """
    flat = re.sub(r"\s+", " ", text)
    d = r"[0-9OoDGQlIitZzS〔｝]"
    out = {}
    for key, ja, en in (("received", "受付", r"R[ec]{2}[ie]{2}v[ec]d"), ("accepted", "受理", r"A[ce]{2}[ce]pt[ec]d")):
        m = re.search(rf"{ja}\s*[:：]\s*({d}{{4,5}})\s*年\s*({d}{{1,2}})\s*月\s*({d}{{1,2}})\s*[日H]", flat)
        if m:
            y, mo, dd = (g.translate(DIGIT_OCR) for g in m.groups())
        else:
            m = re.search(rf"{en}\s*:?\s*([A-Za-z]{{3,10}})\.?\s*({d}{{1,2}})\s*[.,]?\s*({d}{{4,5}})", flat)
            if not m:
                continue
            name = m.group(1).lower()
            best = difflib.get_close_matches(name, MONTHS, n=1, cutoff=0.6)
            if not best:
                continue
            mo, dd, y = str(MONTHS.index(best[0]) + 1), m.group(2).translate(DIGIT_OCR), m.group(3).translate(DIGIT_OCR)
        y = y[:4]                              # 直後のノンブルがつながることがある (24(1):53 の「20072」)
        if not (y.isdigit() and mo.isdigit() and dd.isdigit()) or not (1 <= int(mo) <= 12 and 1 <= int(dd) <= 31):
            continue
        out[key] = (f"{y}-{int(mo):02d}-{int(dd):02d}", m.group(0))
    return out


def section_of(line, names, max_len=18):
    """行が節の見出し (引用文献・謝辞など) なら (名前, 行の字) を返す．違えば (None, None)．

    OCR は見出しの頭の飾り記号 (■) を漢字や英字に読み (24 巻の「欝引用文献」「tw REFERENCES」)，
    綴りも崩す (「REFERIENCES」)．頭の余り3字までと，綴りの1〜2字の崩れを許す．
    「参考文献」のような意味のある頭は余りとみなさない (「文献」も見出しの名前にあるため)．
    """
    raw = line.strip()
    if not raw:
        return None, None
    # 飾り記号が細い線や点の並びとして読まれ，頭のゴミが長くなることがある (24(2):103 の
    # 「iil///1i'il,//il//･.,1, REFERENCES」)．頭が線・点に見える字だけなら，長さによらずゴミとして外す
    m = re.match(r"^[il1I|/\\'`.,･・:;_~\-\s　]{4,}(?=[A-Z一-龥])", raw)
    if m and len(raw) - m.end() <= max_len:
        raw = raw[m.end():]
    if len(raw) > max_len:
        return None, None
    t = re.sub(r"[\s　]", "", raw)
    for nm in sorted(names, key=len, reverse=True):
        n = nm.replace(" ", "")
        if t.endswith(n):
            extra = t[:len(t) - len(n)]
            if len(extra) <= 3 and extra not in ("参考", "主要", "引用", "付録"):
                return nm, raw
    best = (0.0, "")                           # いちばん似た名前を選ぶ (「REFERIENCES」は REFFERENCES でなく REFERENCES)
    for nm in names:
        n = nm.replace(" ", "")
        if len(n) < 6:                         # 短い名前 (文献・謝辞) は崩れを許すと取り違える
            continue
        for extra in range(0, 4):
            tail = t[extra:]
            if abs(len(tail) - len(n)) <= 2:
                r = difflib.SequenceMatcher(None, tail.lower(), n.lower()).ratio() + (0.001 if tail.isupper() == n.isupper() else 0)
                best = max(best, (r, nm))
    return (best[1], raw) if best[0] >= 0.85 else (None, None)


def join_text(a, b):
    """行をつなぐ．和文は詰め，欧文は空白を入れる．"""
    a, b = a.rstrip(), b.strip()
    if not a:
        return b
    if not b:
        return a
    if re.search(rf"[{JA}、。，．（）]$", a) or re.match(rf"^[{JA}、。，．（）]", b):
        return a + b
    return a + " " + b


# ---------------------------------------------------------------- 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--journal", default="vegsci")
    ap.add_argument("--out", required=True)
    ap.add_argument("--band", type=float, default=9.0, help="同じ行とみなす y の帯 (pt)")
    # extract.py から呼ばれたときと同じ 100dpi にそろえる (違うと，画素から pt への換算を取り違えて
    # 切り出しの枠が横に 40〜60pt ずれた．24(1):41)
    ap.add_argument("--dpi-page", type=int, default=100)
    ap.add_argument("--dpi-fig", type=int, default=300)
    ap.add_argument("--force", action="store_true", help="既にある body.md を上書きする")
    args = ap.parse_args()

    prof = load_profile(args.journal)
    # 体裁の見分け: DTP で組んだ PDF なら新しい号用のスクリプトへ渡す
    if layout.detect(args.pdf) == "dtp":
        print("DTP で組んだ PDF なので extract.py で処理する", file=sys.stderr)
        import extract
        return extract.hand_over(extract, args)
    # 雑誌固有の透かしと図表の題の形を設定から取る (scan の節が無ければ既定のまま)
    global JUNK, CAP
    scan_cfg = prof.get("scan") or {}
    if scan_cfg.get("junk"):
        JUNK = re.compile(f"(?:{JUNK_COMMON})|(?:{scan_cfg['junk']})")
    CAP = re.compile(scan_cfg.get("caption_pattern") or CAP_DEFAULT)
    cap_pat = CAP   # スキャンは約物が崩れるので，設定の layout.caption_pattern は使わない
    sec = prof["sections"]
    names = lambda k: [sec[k]] if isinstance(sec[k], str) else list(sec[k])
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
    # 受付日・受理日は 1 ページ目の脚注にあるが，柱と一緒に外れるうえ OCR が崩す．
    # 誤読 (月の 8→9 など) を直せないので meta.yaml には書かず，候補として report.txt に出す
    meta_hist = (yaml.safe_load(mp.read_text(encoding="utf-8")) or {}).get("history") or {} if mp.exists() else {}
    # 原稿種別 (article_type) は読まない．1 ページ目の帯は白抜きの図柄で，OCR の文字の層に入らない
    # (24(1) では「驪謹驤欝…」のようなゴミ．英文の本文の「Data」に当たる誤りも出た)．手順 2 の 9 で AI がページ画像から書く
    REPORT.append("原稿種別 (meta.yaml の article_type・category) と連絡著者 (corresp・email) は，"
                  "スキャンでは読めない．pages/p001.png の帯と脚注を見て書く")
    for k, v in history_candidates(doc[0].get_text()).items():
        now = meta_hist.get(k)
        REPORT.append(f"{'受付日' if k == 'received' else '受理日'}の候補 (1 ページ目の脚注の OCR．ページ画像で確かめて meta.yaml に書く): "
                      f"{v[0]}  ← {v[1]!r}" + (f"  (meta.yaml は {now})" if now else ""))
    md, ocr, page1, floats_txt = [], [], [], []
    para, in_refs, started = "", False, False
    refs, pending = [], []
    float_keys = set()
    seen_float = {}             # (種類, 付表か, 番号) → (最初のページ, 続きの数)

    def flush():
        nonlocal para
        if para.strip():
            md.append(para.strip())
            md.append("")
        para = ""
        while pending:
            md.extend(pending.pop(0))
            md.append("")

    for page in doc:
        pno = page.number + 1
        page.get_pixmap(dpi=args.dpi_page).save(out / "pages" / f"p{pno:03d}.png")
        colw = page.rect.width / 2 - 60
        cols = []
        for g in raw_rows(page, args.band):
            rows = drop_junk(g["rows"], page)
            for r in rows:
                r["text"] = normalize(r["raw"])
            rows = [r for r in rows if r["text"]]
            if rows:
                rows[0]["bounds"] = classify(rows, g["colw"], cap_pat)
            cols.append(rows)

        # 90 度回した図表のページ (OCR が字を横に読んでしまい，意味のある字にならない)
        # 見分け方は行の高さ: 横に読まれた縦書きの行は，ふつうの行 (12pt ほど) の何倍も高くなる
        heights = [r["rect"].height for g in cols for r in g]
        if len(heights) >= 5 and statistics.median(heights) > 25:
            name = f"table_p{pno}.png"
            page.get_pixmap(dpi=200, clip=pymupdf.Rect(30, 30, page.rect.width - 30,
                                                       page.rect.height - 36)).save(out / IMG["tables"] / name)
            REPORT.append(f"p{pno}: 90 度回した図表のページとみなした (OCR が読めていない)．"
                          f"tables/{name} を見て，body.md に `@image` の枠を AI が手で入れる")
            for g in cols:
                for r in g:
                    r["kind"] = "float"
            cols = []

        # 段をまたぐキャプション (「Table 2.」の続きが右の段にある) をつなぐ
        for rows in cols:
            for r in rows:
                if r.get("kind") != "cap":
                    continue
                for other in cols:
                    for o in other:
                        if (o is not r and o["col"] != r["col"] and o["kind"] != "body"
                                and r["col"] == 0 and abs(o["rect"].y0 - r["rect"].y0) <= 6):
                            r["partner"] = o
                            o["kind"] = "capcont"
                            REPORT.append(f"p{pno}: {r['text'][:12]} の題が段をまたぐ．2段の図表とみなす")

        # 図題の続きの行に先に印を付ける (そうしないと，下にある図の枠が
        # 上の図の図題まで伸びて，画像に図題が写り込む)
        caps = {}
        for rows in cols:
            for i, r in enumerate(rows):
                if r.get("kind") == "cap":
                    caps[id(r)] = cap_text(rows, i, cap_pat, rows[0]["bounds"][0])

        # 図表: キャプションの位置から枠を決めて切り出す (スキャンには画像・罫線の情報が無い)
        for rows in cols:
            if not rows:
                continue
            body_x, col_x0, col_x1 = rows[0]["bounds"]
            for run in float_runs(rows):
                label, cap_body, num = caps[id(rows[run["cap"]])]
                kind = run["kind"]
                # 図表の数は番号ごとに 1 回数える (続きのページ・つぶれた枠の重複を数えない)
                float_keys.add((kind, label.lstrip("　 ").startswith(("付表", "Appendix", "APPENDIX")), num))
                cap_r = rows[run["cap"]]["rect"]
                mid = page.rect.width / 2
                # 2段にまたがる図表 (ページ全体の表など): キャプションが段の境を越えている
                partner = rows[run["cap"]].get("partner")
                wide = bool(partner) or cap_r.x0 < mid - 10 < mid + 10 < cap_r.x1 or cap_r.width > colw * 1.3
                if partner:
                    cap_body = join_text(cap_body, partner["text"])
                    cap_r = pymupdf.Rect(cap_r) | partner["rect"]
                # 図題の2行目以降も枠から外す (表題の下から切り出すため)．
                # 行頭が図題とそろい，すぐ下にある行を図題の続きとみなす
                grown = True
                while grown:
                    grown = False
                    for g in cols:
                        for r in g:
                            if (abs(r["rect"].x0 - cap_r.x0) <= 8 and r["rect"].y1 > cap_r.y1
                                    and r["rect"].y0 - cap_r.y1 < 14):
                                cap_r = pymupdf.Rect(cap_r) | r["rect"]
                                r["kind"] = "capcont"
                                grown = True
                # 2段にまたがる図表は，中身の行が本文と見分けられないので紙面の端までを枠にする．
                # そうでなければ前後の本文の行までを枠にし，段の外 (隣の段の字・ノンブル) は入れない
                top = 30 if wide else max(rows[run["a"] - 1]["rect"].y1 + 4 if run["a"] > 0 else 30,
                                          rows[run["a"]]["rect"].y0 - 25)
                if wide:
                    # 2段にまたがる図表の下に本文が戻ることがある．その手前までを枠にする
                    below = [r["rect"].y0 for g in cols for r in g
                             if r not in rows and r["rect"].y0 > cap_r.y1 + 20
                             and colw * 0.8 <= r["rect"].width <= colw * 1.2
                             and len(re.findall(rf"[{JA}]", r["text"])) >= 8]
                    bottom = min(below, default=page.rect.height - 36) - 6
                else:
                    bottom = (page.rect.height - 36 if run["b"] + 1 >= len(rows)
                              else min(rows[run["b"] + 1]["rect"].y0 - 4, rows[run["b"]]["rect"].y1 + 25))
                if wide:
                    x0, x1 = 36, page.rect.width - 36
                elif rows[run["cap"]]["col"] == 0:
                    x0, x1 = col_x0 - 8, min(col_x1 + 8, mid - 2)
                else:
                    x0, x1 = max(col_x0 - 8, mid + 2), col_x1 + 8
                # 図はキャプションが下，表は上にあるので，反対側へ白いところまで伸ばす
                clip = (pymupdf.Rect(x0, top, x1, cap_r.y0 - 3) if kind == "fig"
                        else pymupdf.Rect(x0, cap_r.y1 + 3, x1, bottom)) & page.rect
                # 付表は Table 1 と番号が重なるので，画像の名前と枠の番号を分ける (TA1・appendix1.png)．
                # build.py は枠に書いた呼び名 (Appendix 1) で本文から引く
                appx = kind == "table" and label.lstrip("　 ").startswith(("付表", "Appendix", "APPENDIX"))
                name = f"appendix{num}.png" if appx else f"{kind}{num}.png"
                # 同じ番号の2つ目: 後のページなら，ページをまたぐ図表の続き (「Fig. 3 continue」．24(1):19) とみて
                # 続きの画像 (fig3_2.png．build.py が図の続きとして載せる) にし，枠は作らない．
                # 同じページなら，本文の行を図題と取り違えたとみて切り出さない (ID が重なって DTD の誤りになる)
                cont = False
                if (kind, appx, num) in seen_float:
                    first_p, n_cont = seen_float[(kind, appx, num)]
                    if pno == first_p:
                        REPORT.append(f"p{pno}: {label} が同じページに2つある．2つ目は図題でないとみて切り出さない (ページ画像で確かめる)")
                        continue
                    n_cont += 1
                    seen_float[(kind, appx, num)] = (first_p, n_cont)
                    name = f"{name[:-4]}_{n_cont}.png"
                    cont = True
                # 1 つ目として覚えるのは切り出せたときだけ (枠がつぶれたら，同じ番号の次の候補に譲る．24(1):41 の Fig. 3)
                if clip.width < 10 or clip.height < 10:
                    # 枠がつぶれた (図題の位置から中身の範囲を決められなかった)．
                    # 画像は作らず，ページ画像を見て AI が crop.py で手で切り出す
                    REPORT.append(f"p{pno}: {label} の枠がつぶれた {tuple(round(v) for v in clip)}．"
                                  f"pages/p{pno:03d}.png を見て crop.py で切り出し，tables/ か figs/ に置く")
                    continue
                page.get_pixmap(dpi=args.dpi_fig if kind == "fig" else 200, clip=clip).save(
                    out / IMG["figs" if kind == "fig" else "tables"] / name)
                if not cont:
                    seen_float[(kind, appx, num)] = (pno, 1)
                REPORT.append(f"p{pno}: {label} の枠 {tuple(round(v) for v in clip)} → {name}"
                              f"{'．2段にまたがる' if wide else ''}{'．前のページからの続き' if cont else ''}．ページ画像で確かめる")
                # 枠に入った行は本文から外す (図の軸の目盛り・表の中の字)
                for r in rows[run["a"]:run["b"] + 1]:
                    if r["kind"] not in ("cap", "capcont"):
                        r["kind"] = "float"
                if wide:
                    # 反対の段の，同じ高さにある行も図表の中身として外す
                    for other in cols:
                        for r in other:
                            if r not in rows and clip.y0 - 6 <= r["rect"].y0 <= clip.y1 + 6:
                                r["kind"] = "float"
                if cont:
                    pass                      # 続きの画像は 1 つ目の枠に載る (枠は作らない)
                elif kind == "fig":
                    pending.append([f":::fig F{num} {label.rstrip('.．')} {name}", cap_body, ":::"])
                else:
                    floats_txt.append(f"===== p{pno} {label} ({name} と見比べて組む)")
                    pending.append([f":::table {'TA' if appx else 'T'}{num} {label.rstrip('.．')}", cap_body,
                                    # 表は画像のまま載せる (2026-09-29 ユーザ指示．スキャンの表は OCR の文字しか無いので組まない)．
                                    # tables/ の画像の枠をページ画像で確かめる
                                    "@image", ":::"])

        for rows in cols:
            if rows:
                ocr.append(f"===== p{pno} {rows[0]['col'] if rows[0]['col'] == '全幅' else '段' + str(rows[0]['col'] + 1)}")
                ocr += [f"{r['kind']:7s} {r['rect'].x0:5.0f},{r['rect'].y0:5.0f},"
                        f"{r['rect'].x1:5.0f},{r['rect'].y1:5.0f} | {r['text']}" for r in rows]
            for r in rows:
                t, kind = r["text"], r["kind"]
                if kind in ("cap", "capcont", "float"):
                    if kind == "float":
                        floats_txt.append(f"p{pno} {r['rect'].x0:.0f},{r['rect'].y0:.0f} | {t}")
                    continue
                if not started:
                    # 本文は，段に分かれたところの最初の大見出し (「はじめに」) から始まる．
                    # それより上 (題名・著者・英文要旨) は page1.txt へ
                    if kind in ("head", "head2") and r["col"] != "全幅":
                        started = True
                    else:
                        page1.append(f"{r['rect'].x0:5.0f},{r['rect'].y0:5.0f} | {t}")
                        continue
                if kind in ("head", "head2"):
                    # 見出しの頭の飾り記号 (■ など) を OCR が漢字に読むことがある (24 巻の「欝引用文献」「鰄謝辞」)．
                    # 節の名前 (引用文献・謝辞・摘要) で終わり，頭の余りが3字以内なら，余りを外して大見出しにする
                    sec_name, extra = section_of(t, [nm for k in ("refs", "ack", "abstract") if k in sec for nm in names(k)])
                    if sec_name:
                        if extra != sec_name:
                            REPORT.append(f"p{pno}: 見出し {t!r} を「{sec_name}」とみた (頭のゴミ・綴りの崩れを OCR の読み誤りとみて直した)")
                        t, kind = sec_name, "head"
                if kind == "head":
                    flush()
                    in_refs = in_refs or t.replace(" ", "") in names("refs")
                    md.append(f"# {t.replace(' ', '')}")
                    md.append("")
                elif kind == "head2":
                    flush()
                    md.append(f"## {t}")
                    md.append("")
                elif in_refs:
                    if not refs or re.search(r"[．.，,]$", refs[-1]):
                        refs.append(t)
                    else:
                        refs[-1] = join_text(refs[-1], t)
                else:
                    if r["raw"].startswith("　") or r["raw"].startswith(" "):
                        flush()
                    para = join_text(para, t)
    flush()
    md += [r + "\n" for r in refs]

    # OCR が取り違えやすい字を拾う
    for i, line in enumerate(md):
        for m in SUSPECT.finditer(line):
            REPORT.append(f"OCR 要確認: {m.group(0)!r} ({line[max(0, m.start() - 12):m.start() + 14]})")
    fig_n = collections.Counter(k[0] for k in float_keys)
    REPORT.insert(0, f"図 {fig_n['fig']}・表 {fig_n['table']}，引用文献 {len(refs)} 件，"
                     f"本文 {sum(1 for l in md if l and not l.startswith(('#', ':', '<')))} 段落")
    REPORT.insert(1, "斜体の情報がスキャンには無い．学名・誌名の斜体は AI がページ画像を見て付ける")
    REPORT.insert(2, f"pages/p*.png は {args.dpi_page}dpi (画素 × {72 / args.dpi_page:.2f} = PDF の pt)．"
                     "crop.py の --rect は pt で渡すので，ocr.md の座標 (pt) から起こすのが確か")

    body = out / "body.md"
    target = body if (args.force or not body.exists()) else out / "body.new.md"
    target.write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "ocr.md").write_text("\n".join(ocr) + "\n", encoding="utf-8")
    (out / "page1.txt").write_text("\n".join(page1) + "\n", encoding="utf-8")
    (out / "floats.txt").write_text("\n".join(floats_txt) + "\n", encoding="utf-8")
    (out / "report.txt").write_text("\n".join(REPORT) + "\n", encoding="utf-8")
    print(f"{target.name}: 図 {fig_n['fig']}・表 {fig_n['table']}，引用文献 {len(refs)} 件")
    print(f"出力: {out} (report.txt に要確認 {len(REPORT)} 件)")


if __name__ == "__main__":
    main()
