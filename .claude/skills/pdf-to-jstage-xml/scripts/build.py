"""meta.yaml と body.md から J-STAGE 用の全文 XML (JATS 1.1) を組む (手順 3: 変換)．

使い方:
    python build.py <作業ディレクトリ> [--pdf <論文.pdf>]

全文 PDF は作業ディレクトリの <記事識別子>.pdf を使う (--pdf で別の場所も指定できる)．

出力 (作業ディレクトリ):
    out/<記事識別子>.xml   ... 全文 XML
    out/manifest.json      ... zip に入れるものの対応表 (manifest.py)
    <記事識別子>.zip       ... 登載用の一式 (全文 XML 作成ツールの「インポート」か，編集登載の一括アップロードへ)
                               中は「資料コード/巻/号/記事識別子/」に XML・PDF・Graphics/
    build_report.txt       ... リンクできなかった引用・図表など (手で確かめる箇所)

「資料コード/巻/号/記事識別子/」の入れ子は zip の中にだけ作り，ディスク上には作らない．
PDF と図表の画像も写さず，元のファイルから直接 zip へ入れる (画像は zip の中で別紙2の名前に改名する)．

body.md の書き方は SKILL.md の「body.md の書式」を見る．
"""
import argparse
import html
import re
import sys
import zipfile
from pathlib import Path

import yaml

import manifest

SKILL_DIR = Path(__file__).resolve().parent.parent
REPORT = []

JA = re.compile(r"[぀-ヿ㐀-鿿＀-￯]")


def esc(s):
    return html.escape(s, quote=False)


def attr(s):
    return html.escape(str(s), quote=True)


# ================================================================ 文中の修飾

def inline(s):
    """escape ずみの文字列に *斜体*・**太字**・^上付き^・~下付き~・URL の印を付ける．"""
    s = re.sub(r"\*\*(.+?)\*\*", r"<bold>\1</bold>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<italic>\1</italic>", s)
    s = re.sub(r"\^([^^\s][^^]*?)\^", r"<sup>\1</sup>", s)
    s = re.sub(r"(?<![~〜])~([^~\s][^~]*?)~(?!~)", r"<sub>\1</sub>", s)
    s = re.sub(r"(https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+;=%-]+?)(?=[，。．、）)\s]|$|\.(?:\s|$))",
               lambda m: f'<ext-link ext-link-type="uri" xlink:href="{m.group(1)}">{m.group(1)}</ext-link>', s)
    return s


# ================================================================ 引用文献

ORG = re.compile(r"(財団|協会|学会|省|庁|局|課|県|市|町|村役場|研究所|委員会|センター|会議|組合|機構|"
                 r"Ministry|Society|Agency|Institute|Committee|Council|Association)")


ORG_END = re.compile(r"(財団|協会|学会|省|庁|局|課|部|室|県|市|町|村|研究所|委員会|センター|会議|組合|機構|"
                     r"編|ほか)$")


def split_ja_names(auth):
    """「馬場多久男・伊藤精晤・田中　誠」→ 名前の (開始, 終了) の列．

    団体名の中の「・」では分けない．「環境省水・大気環境局 水環境課」のように，団体を表す字 (省・局など) を
    含むのにそれで終わっていない部分は，次の部分とつなぐ (植生学会誌 37(1) の文献 B9)．
    """
    parts, pos = [], 0
    for part in re.split(r"(・)", auth):
        if part != "・" and part.strip():
            start = auth.index(part, pos)
            parts.append([start, start + len(part)])
        pos += len(part)
    out = []
    for a, b in parts:
        if out and out[-1][2]:
            out[-1][1] = b                       # 前の部分 (団体名の途中) とつなぐ
            out[-1][2] = bool(ORG.search(auth[out[-1][0]:b])) and not ORG_END.search(auth[out[-1][0]:b].strip())
            continue
        name = auth[a:b].strip()
        out.append([a, b, bool(ORG.search(name)) and not ORG_END.search(name)])
    return [(a, b) for a, b, _ in out]


def tag_ja_name(name):
    suffix = ""
    m = re.match(r"^(.*?)(編|監修|ほか編|ほか)$", name)
    if m and m.group(1).strip():
        core = m.group(1)
        name = core.rstrip()
        suffix = core[len(name):] + m.group(2)   # 「奥田重俊 編」の空白を残す
    if ORG.search(name):
        return f'<collab xml:lang="ja">{esc(name)}</collab>{esc(suffix)}'
    parts = re.split(r"[\s　]+", name.strip(), maxsplit=1)
    if len(parts) == 2:
        sur, giv = parts
        sep = name.strip()[len(sur):len(name.strip()) - len(giv)]
        return (f'<string-name name-style="eastern" xml:lang="ja"><surname>{esc(sur)}</surname>{esc(sep)}'
                f'<given-names>{esc(giv)}</given-names></string-name>{esc(suffix)}')
    return (f'<string-name name-style="eastern" xml:lang="ja"><surname>{esc(name.strip())}</surname>'
            f'</string-name>{esc(suffix)}')


EN_NAME = re.compile(r"([^,&]+?),\s*((?:[A-Z][a-zà-ÿ]?\.\s?-?\s?)+)")


def tag_en_authors(auth):
    """「Batáry, P., Holzschuh, A. & Tscharntke, T.」の各人を string-name で囲む (区切りは残す)．"""
    out, pos, names = [], 0, []
    for m in EN_NAME.finditer(auth):
        sur = m.group(1).strip()
        lead = m.group(1)[: len(m.group(1)) - len(m.group(1).lstrip())]
        out.append(esc(auth[pos:m.start(1)]) + esc(lead))
        given = m.group(2).rstrip()
        trail = m.group(2)[len(given):]
        out.append(f'<string-name name-style="western" xml:lang="en"><surname>{esc(sur)}</surname>, '
                   f'<given-names>{esc(given)}</given-names></string-name>{esc(trail)}')
        names.append(sur)
        pos = m.end()
    out.append(esc(auth[pos:]))
    if not names:
        return None, []
    return "".join(out), names


YEAR = re.compile(r"^(?P<auth>.+?)\s*[（(]?(?P<year>(?:1[89]|20)\d{2})(?P<suf>[a-z]?)[)）]?\s*[.．]\s*(?P<rest>.*)$")
JOURNAL_TAIL = re.compile(
    r"\s*(?P<src>[^.．\s][^.．]*?)(?:\s*[,，]\s*|\s+)(?P<vol>[A-Za-z]?\d+[A-Za-z]?)"
    r"(?:\s*[（(](?P<iss>[^)）]+)[)）])?\s*[:：]\s*(?P<fp>[A-Za-z]?\d+)(?:\s*[-–−₋]\s*(?P<lp>[A-Za-z]?\d+))?\s*[.．]?\s*$")
CHAPTER_JA = re.compile(
    r"^(?P<title>.+?[.．])\s*(?P<eds>[^「」．.]+?)編「(?P<src>[^」]+)」\s*[,，]\s*(?P<fp>\d+)(?:\s*[-–]\s*(?P<lp>\d+))?"
    r"\s*[.．]\s*(?P<pub>[^,，．.]+?)\s*[,，]\s*(?P<loc>[^.．]+?)\s*[.．]\s*$")
# 章題．「書名」（編者編），ページ．出版社，所在地．(植生学会誌 37(1) の文献 B5・B12)
CHAPTER_JA2 = re.compile(
    r"^(?P<title>.+?[.．])\s*「(?P<src>[^」]+)」\s*[（(](?P<eds>[^）)]+?)\s*編[）)]\s*[,，]\s*(?P<fp>\d+)"
    r"(?:\s*[-–]\s*(?P<lp>\d+))?\s*[.．]\s*(?P<pub>[^,，．.]+?)\s*[,，]\s*(?P<loc>[^.．]+?)\s*[.．]\s*$")
CHAPTER_EN = re.compile(
    r"^(?P<title>.+?\.)\s*In:\s*(?P<eds>.+?)\s*\(?eds?\.\)?\s*(?P<src>.+?),\s*(?P<fp>\d+)\s*[-–]\s*(?P<lp>\d+)\.\s*(?P<pub>.+)$")
BOOK_PUB = re.compile(r"[.．]\s*(?P<pub>[^.．,，「」]+?)\s*[.．]\s*$")   # 題名．出版社．(所在地なし)
BOOK_TAIL = re.compile(r"\s*(?P<pub>[^.．,，「」\s][^.．,，「」]*?)\s*[,，]\s*(?P<loc>[^.．,，「」]+?)\s*[.．]\s*$")


class Ref:
    def __init__(self, idx, text):
        self.id = f"B{idx}"
        self.text = text.strip()
        self.lang = "ja" if JA.search(self.text.split(" ")[0] + self.text[:12]) else "en"
        self.year = None
        self.names = []      # 検索用の著者名 (姓 または 全名)
        self.xml = None
        self.kind = "other"
        self.parse()

    def parse(self):
        t = self.text
        m = YEAR.match(t)
        if not m:
            REPORT.append(f"文献を分解できない (平文のまま): {t[:60]}")
            self.xml = inline(esc(t))
            return
        self.year = m.group("year") + m.group("suf")
        auth = m.group("auth")
        if self.lang == "en":
            tagged, names = tag_en_authors(auth)
            if tagged is None:  # 団体名など
                tagged, names = f"<collab>{esc(auth)}</collab>", [auth]
        else:
            spans = split_ja_names(auth)
            parts, pos = [], 0
            names = []
            for a, b in spans:
                parts.append(esc(auth[pos:a]))
                parts.append(tag_ja_name(auth[a:b]))
                names.append(re.sub(r"(ほか編|ほか|編|監修)$", "", re.sub(r"[\s　]", "", auth[a:b])))
                pos = b
            parts.append(esc(auth[pos:]))
            tagged = "".join(parts)
        self.names = names
        head = f'<person-group person-group-type="author">{tagged}</person-group>'
        year_part = t[m.end("auth"):m.start("rest")]
        year_xml = esc(year_part).replace(self.year, f"<year>{self.year}</year>", 1)
        rest = m.group("rest")
        jm = JOURNAL_TAIL.search(rest)
        bm = BOOK_TAIL.search(rest)
        cm = (CHAPTER_JA.match(rest) or CHAPTER_JA2.match(rest)) if self.lang == "ja" else CHAPTER_EN.match(rest)
        if cm:
            self.kind = "book"
            body = self.chapter_xml(rest, cm)
        elif jm and jm.group("src").strip():
            self.kind = "journal"
            title = rest[:jm.start("src")]
            body = (self.title_xml(title) + esc(rest[jm.start("src"):jm.start("src")] ) +
                    self.tail_journal(rest, jm))
        elif bm and not re.search(r"(In:|編「|（編）|pp\.)", rest):
            self.kind = "book"
            title = rest[:bm.start("pub")]
            t2 = title.rstrip()
            end = re.search(r"[.．]\s*$", t2)
            main = t2[: end.start()] if end else t2
            body = (f'<source xml:lang="{self.lang}">{inline(esc(main.strip()))}</source>'
                    + esc(t2[len(main):]) + esc(title[len(t2):])
                    + f"<publisher-name>{esc(bm.group('pub'))}</publisher-name>"
                    + esc(rest[bm.end("pub"):bm.start("loc")])
                    + f"<publisher-loc>{esc(bm.group('loc'))}</publisher-loc>"
                    + esc(rest[bm.end("loc"):]))
        elif BOOK_PUB.search(rest) and not re.search(r"(In:|編「|（編）|pp\.)", rest):
            pm = BOOK_PUB.search(rest)
            self.kind = "book"
            main = rest[:pm.start()]
            body = (f'<source xml:lang="{self.lang}">{inline(esc(main))}</source>'
                    + esc(rest[pm.start():pm.start("pub")])
                    + f"<publisher-name>{esc(pm.group('pub'))}</publisher-name>" + esc(rest[pm.end("pub"):]))
        else:
            REPORT.append(f"文献の後半を分解できない (著者・年だけタグ付け): {self.id} {t[:70]}")
            body = inline(esc(rest))
        self.xml = head + year_xml + body

    def chapter_xml(self, rest, m):
        """編著の1章．どの書き方でも，見つけた部分 (章題・編者・書名・ページ・出版社・所在地) を
        元の文の位置のままタグで囲む (前後の空白はタグの外に出す)．"""
        eds = m.group("eds")
        if self.lang == "ja":
            parts, pos = [], 0
            for a, b in split_ja_names(eds):
                parts.append(esc(eds[pos:a]) + tag_ja_name(eds[a:b]))
                pos = b
            eds_xml = "".join(parts) + esc(eds[pos:])
        else:
            eds_xml, _ = tag_en_authors(eds)
            eds_xml = eds_xml or esc(eds)
        wrap = {
            "title": lambda t: self.title_xml(t),
            "eds": lambda t: f'<person-group person-group-type="editor">{eds_xml}</person-group>',
            "src": lambda t: f'<source xml:lang="{self.lang}">{inline(esc(t))}</source>',
            "fp": lambda t: f"<fpage>{esc(t)}</fpage>",
            "lp": lambda t: f"<lpage>{esc(t)}</lpage>",
            "pub": lambda t: f"<publisher-name>{esc(t)}</publisher-name>",
            "loc": lambda t: f"<publisher-loc>{esc(t)}</publisher-loc>",
        }
        spans = []
        for k in wrap:
            if k in m.groupdict() and m.group(k):
                a, b = m.span(k)
                if k not in ("title", "eds"):       # 前後の空白はタグの外へ
                    while a < b and rest[a].isspace():
                        a += 1
                    while b > a and rest[b - 1].isspace():
                        b -= 1
                spans.append((a, b, k))
        s, pos = "", 0
        for a, b, k in sorted(spans):
            s += esc(rest[pos:a]) + wrap[k](rest[a:b])
            pos = b
        return s + esc(rest[pos:])

    def title_xml(self, title):
        t = title.rstrip()
        end = re.search(r"[.．]\s*$", t)
        main = t[: end.start()] if end else t
        return (f'<article-title xml:lang="{self.lang}">{inline(esc(main.strip()))}</article-title>'
                + esc(t[len(main):]) + esc(title[len(t):]))

    def tail_journal(self, rest, m):
        g = lambda k: esc(m.group(k))
        s = f'<source xml:lang="{self.lang}">{inline(esc(m.group("src").strip()))}</source>'
        s += esc(rest[m.end("src"):m.start("vol")]) + f"<volume>{g('vol')}</volume>"
        if m.group("iss"):
            s += esc(rest[m.end("vol"):m.start("iss")]) + f"<issue>{g('iss')}</issue>"
            s += esc(rest[m.end("iss"):m.start("fp")])
        else:
            s += esc(rest[m.end("vol"):m.start("fp")])
        s += f"<fpage>{g('fp')}</fpage>"
        if m.group("lp"):
            s += esc(rest[m.end("fp"):m.start("lp")]) + f"<lpage>{g('lp')}</lpage>" + esc(rest[m.end("lp"):])
        else:
            s += esc(rest[m.end("fp"):])
        return s

    def to_xml(self):
        return (f'<ref id="{self.id}" xml:lang="{self.lang}">'
                f'<mixed-citation publication-type="{self.kind}">{self.xml}</mixed-citation></ref>')


# ================================================================ 本文中の引用 (著者 年) のリンク

DELIM = "(（;；,，:：、。．[ 「」『』*^"

KANJI_RUN = re.compile(r"[\u3005\u3006\u30a0-\u30ff\u3400-\u9fff\uf900-\ufaff・]+$")


def author_matches(window, ref):
    """window (年の直前の文字列．空白なし) が ref の著者表記で終わっているか．

    和文: 年の直前の漢字・カタカナのかたまり (「川村・大窪」「北川」+「ほか」) を切り出し，
    各部分が文献の著者名の先頭と一致するかで見る (末尾の1字だけの一致は採らない)．
    欧文: 「Surname」「S1 & S2」「S1 et al.」で終わり，その前が区切り記号であること．
    """
    w = re.sub(r"(編|\(eds?\.\)|\(ed\.\)|eds?\.)$", "", window)
    n = len(ref.names)
    if not n:
        return False
    if ref.lang == "en":
        S = [re.sub(r"\s", "", s) for s in ref.names]
        if n == 1:
            forms = [S[0]]
        elif n == 2:
            forms = [f"{S[0]}&{S[1]}", f"{S[0]}and{S[1]}"]
        else:
            forms = [f"{S[0]}etal.", f"{S[0]}etal"]
        for f in forms:
            if w.endswith(f):
                before = w[: len(w) - len(f)]
                if not before or before[-1] in DELIM or KANJI_RUN.search(before[-1:]) or \
                        re.search(r"[\u3040-\u309f]$", before):
                    return True
        return False
    etal = w.endswith("ほか")
    if etal:
        w = w[:-2]
    m = KANJI_RUN.search(w)
    if not m:
        return False
    token = m.group(0).strip("・")
    N = ref.names
    if n >= 3:
        return etal and "・" not in token and N[0].startswith(token)
    if etal:
        return False
    if n == 2:
        parts = token.split("・")
        if len(parts) < 2:
            return False
        # かたまりの前に余分な漢字が付いていることがあるので，左は末尾側で合わせる
        return N[1].startswith(parts[-1]) and any(N[0].startswith(parts[-2][k:]) for k in range(len(parts[-2])))
    if "・" in token:
        # 著者が1つの団体で，名前に「・」を含むとき (「環境省水・大気環境局水環境課」，37(1) の B9) は「・」ごと照合する
        return "・" in N[0] and any(N[0].startswith(token[k:]) and "・" in token[k:] for k in range(len(token)))
    # かたまり全体が姓の先頭なら1字 (「徐」) でもよい．前に余分な漢字が付くときは2字以上で合わせる
    return any(N[0].startswith(token[k:]) and (k == 0 or len(token[k:]) >= 2) for k in range(len(token)))


CITE_YEAR = re.compile(r"(?<![\d./:])((?:1[89]|20)\d{2})([a-z]?)(?![\d])")


MANUAL = re.compile(r"\{\{([^|{}]+?)\s+((?:1[89]|20)\d{2}[a-z]?)\|([^{}]+)\}\}")


def link_citations(text, refs, where):
    """手で指定したリンク {{著者名の先頭 年|表示}} を先に処理し，残りを自動でリンクする．

    手で指定するのは，原文の表記揺れで自動では当たらないとき
    (例: 本文「北海道環境科学センター（2005）」と文献「北海道環境科学研究センター 2005」)．
    表示の文字は原文のまま残す (PDF と HTML の内容は同一でなければならないため)．
    """
    out, pos = [], 0
    for m in MANUAL.finditer(text):
        out.append(auto_citations(text[pos:m.start()], refs, where))
        key = re.sub(r"[\s　]", "", m.group(1))
        hit = [r for r in refs if r.year == m.group(2) and r.names and
               re.sub(r"[\s　]", "", r.names[0]).startswith(key)]
        if len(hit) == 1:
            out.append(f"\x01{hit[0].id}\x02{m.group(3)}\x03")
        else:
            REPORT.append(f"手で指定したリンクの文献が{'見つからない' if not hit else '複数ある'} ({where}): {m.group(0)}")
            out.append(m.group(3))
        pos = m.end()
    out.append(auto_citations(text[pos:], refs, where))
    return "".join(out)


def auto_citations(text, refs, where):
    """本文の段落 (escape 前) の年に，対応する文献への印を付ける．\x01rid\x02表記\x03 の形で返す．"""
    by_year = {}
    for r in refs:
        if r.year:
            by_year.setdefault(r.year, []).append(r)
    out, pos, last_end, last_window = [], 0, None, None
    for m in CITE_YEAR.finditer(text):
        after = text[m.end():m.end() + 3]
        if re.match(r"\s*[)）]?\s*年", after) or re.match(r"\s*[/.]\d", after):  # 「2011 年」「平成4（1992）年」
            continue
        year = m.group(1) + m.group(2)
        between = text[last_end:m.start()] if last_end is not None else None
        cands = by_year.get(year, [])
        hit = None
        window = re.sub(r"[\s　]", "", text[max(0, m.start() - 60):m.start()])
        window = re.sub(r"[（(]$", "", window)
        if between is not None and re.fullmatch(r"\s*[,，]\s*", between) and last_window:
            window = last_window  # 「北川ほか2004, 2005」の 2005 は直前の著者表記を引き継ぐ
        if hit is None:
            ok = [r for r in cands if author_matches(window, r)]
            if len(ok) == 1:
                hit = ok[0]
            elif len(ok) > 1:
                REPORT.append(f"引用が複数の文献に当たる ({where}): …{text[max(0, m.start() - 20):m.end()]} → "
                              + ", ".join(r.id for r in ok))
        if hit is None:
            ctx = text[max(0, m.start() - 20):m.end() + 3]
            if re.search(r"[（(;；]|et al|ほか|・", text[max(0, m.start() - 25):m.start()]):
                REPORT.append(f"引用をリンクできない ({where}): …{ctx}")
            continue
        out.append(text[pos:m.start()])
        out.append(f"\x01{hit.id}\x02{m.group(0)}\x03")
        pos = m.end()
        last_end, last_window = m.end(), window
        # 「1991a, b」の b
        while True:
            mm = re.match(r"(\s*[,，]\s*)([a-z])(?![A-Za-z])", text[pos:])
            if not mm:
                break
            y2 = m.group(1) + mm.group(2)
            r2s = [r for r in by_year.get(y2, []) if author_matches(window, r)]
            r2 = r2s[0] if len(r2s) == 1 else None
            if not r2:
                break
            out.append(mm.group(1))
            out.append(f"\x01{r2.id}\x02{mm.group(2)}\x03")
            pos += mm.end()
            last_end = pos
    out.append(text[pos:])
    return "".join(out)


def link_floats(text, floats):
    """「図1」「表1」を図表へのリンクにする．「図2，3，4」「図3, 4」の2つ目以降の番号もリンクする．"""
    def one(kind, num, shown):
        key = ("F" if kind == "図" else "T") + num
        if key not in floats:
            REPORT.append(f"本文の {kind}{num} に対応する図表が無い")
            return shown
        return f"\x04{key}\x02{shown}\x03"

    def rep(m):
        kind = m.group(1)
        out = one(kind, m.group(3), m.group(1) + m.group(2) + m.group(3))
        for mm in re.finditer(r"(\s*[，,、]\s*)(\d+)", m.group(4)):
            out += mm.group(1) + one(kind, mm.group(2), mm.group(2))
        return out
    return re.sub(r"(図|表)(\s*)(\d+)((?:\s*[，,、]\s*\d+(?![\d.]))*)", rep, text)


def link_formulas(text, floats):
    """「式(1)」「式1」「(1)式」を別行立ての式へのリンクにする．

    番号だけの「(1)」は，引用の番号や注の番号と紛れるのでリンクしない．"""
    def rep(m):
        num = m.group(2) or m.group(3)
        key = "E" + num
        if key not in floats:
            return m.group(0)
        return f"\x05{key}\x02{m.group(0)}\x03"
    return re.sub(r"(式\s*\(?(\d+)\)?|\((\d+)\)\s*式)", rep, text)


def para_xml(text, refs, floats, where):
    t = link_citations(text, refs, where)
    t = link_floats(t, floats)
    t = link_formulas(t, floats)
    s = inline(esc(t))
    s = re.sub(r"\x01(B\d+)\x02(.*?)\x03", r'<xref ref-type="bibr" rid="\1">\2</xref>', s)
    s = re.sub(r"\x04(F\d+)\x02(.*?)\x03", r'<xref ref-type="fig" rid="\1">\2</xref>', s)
    s = re.sub(r"\x04(T\d+)\x02(.*?)\x03", r'<xref ref-type="table" rid="\1">\2</xref>', s)
    s = re.sub(r"\x05(E\d+)\x02(.*?)\x03", r'<xref ref-type="disp-formula" rid="\1">\2</xref>', s)
    return s


# ================================================================ body.md の読み取り

def parse_body(path):
    """body.md を (種類, 中身) の列にする．"""
    lines = path.read_text(encoding="utf-8").splitlines()
    blocks, i = [], 0
    while i < len(lines):
        l = lines[i]
        if not l.strip() or l.strip().startswith("<!--") and l.strip().endswith("-->"):
            i += 1
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", l)
        if m:
            blocks.append(("h", len(m.group(1)), m.group(2).strip()))
            i += 1
            continue
        m = re.match(r"^:::(fig|table|formula)\s+(\S+)(?:\s+(\S+))?(?:\s+(\S+))?\s*$", l)
        if m:
            kind, fid, label, file = m.groups()
            if kind != "formula" and label is None:
                REPORT.append(f"{kind} {fid} に番号 (図1・表1) が書かれていない")
            label = label or ""
            j = i + 1
            content = []
            while j < len(lines) and lines[j].strip() != ":::":
                content.append(lines[j])
                j += 1
            blocks.append((kind, fid, label, file, content))
            i = j + 1
            continue
        if re.match(r"^(- |\d+[.)] )", l) and i + 1 < len(lines) and re.match(r"^(- |\d+[.)] )", lines[i + 1]):
            items = []
            while i < len(lines) and re.match(r"^(- |\d+[.)] )", lines[i]):
                items.append(lines[i])
                i += 1
            blocks.append(("list", items))
            continue
        blocks.append(("p", l.strip()))
        i += 1
    return blocks


# ================================================================ 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--pdf")
    args = ap.parse_args()
    work = Path(args.work)
    meta = yaml.safe_load((work / "meta.yaml").read_text(encoding="utf-8"))
    prof = yaml.safe_load((SKILL_DIR / "journals" / f"{meta['journal']}.yaml").read_text(encoding="utf-8"))
    sec_names = prof["sections"]
    blocks = parse_body(work / "body.md")

    # 特別な節を切り出す
    abstract_ja, ack, ref_lines, main_blocks = [], [], [], []
    mode = "body"
    for b in blocks:
        if b[0] == "h" and b[1] == 1:
            mode = {sec_names["abstract"]: "abstract", sec_names["ack"]: "ack",
                    sec_names["refs"]: "refs"}.get(b[2], "body")
            if mode != "body":
                continue
        if mode == "abstract" and b[0] == "p":
            abstract_ja.append(b[1])
        elif mode == "ack" and b[0] == "p":
            ack.append(b[1])
        elif mode == "refs" and b[0] == "p":
            ref_lines.append(b[1])
        elif mode == "body":
            main_blocks.append(b)

    refs = [Ref(i + 1, t) for i, t in enumerate(ref_lines)]
    floats = {b[1] for b in main_blocks if b[0] in ("fig", "table", "formula")}
    # 記事識別子は J-STAGE の既存のもの (meta.yaml の article_id) を使う．無ければ「巻_開始ページ」
    art_id = str(meta.get("article_id") or f"{meta['volume']}_{meta['fpage']}")
    out_dir = work / manifest.OUT
    out_dir.mkdir(exist_ok=True)
    if (work / "jstage").is_dir():
        REPORT.append("古い形の出力 jstage/ が残っている (いまは out/ と zip だけを作る)．要らなければ消す")

    names = GraphicNames(art_id)
    body_xml = build_body(main_blocks, refs, floats, work, names)
    front = build_front(meta, prof, abstract_ja, refs, floats)
    back = build_back(ack, refs, sec_names)
    lang = meta.get("lang", "ja")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Publishing DTD v1.1 20151215//EN" '
        '"https://www.jstage.jst.go.jp/dtds/1.1/JATS-journalpublishing1.dtd">\n'
        '<article xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:mml="http://www.w3.org/1998/Math/MathML" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'xmlns:ali="http://www.niso.org/schemas/ali/1.0/" '
        f'xml:lang="{lang}" dtd-version="1.1" article-type="{attr(meta["article_type"])}">\n'
        f"{front}\n{body_xml}\n{back}\n</article>\n")
    (out_dir / f"{art_id}.xml").write_text(xml, encoding="utf-8")
    check_refs_text(out_dir / f"{art_id}.xml", refs)
    web_cmp = compare_web_refs(work, refs)
    pdf = Path(args.pdf) if args.pdf else work / f"{art_id}.pdf"
    if not pdf.exists():
        REPORT.append(f"全文 PDF が無い: {pdf} (作業ディレクトリに {art_id}.pdf を置くか --pdf で渡す)")
        pdf = None
    elif pdf.resolve().parent != work.resolve():
        REPORT.append(f"全文 PDF が作業ディレクトリの外にある: {pdf} (中に {art_id}.pdf として置く決まり)")
    m = manifest.write(work, meta["journal"], meta["volume"], meta["issue"], art_id, pdf, names.items)

    zpath = work / f"{art_id}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        manifest.add_to_zip(z, work, m)
    (work / "build_report.txt").write_text("\n".join(REPORT) + "\n", encoding="utf-8")
    n_x = xml.count('ref-type="bibr"')
    print(f"XML: {out_dir / (art_id + '.xml')}")
    print(f"文献 {len(refs)} 件 (雑誌 {sum(r.kind == 'journal' for r in refs)}・書籍 {sum(r.kind == 'book' for r in refs)}"
          f"・その他 {sum(r.kind == 'other' for r in refs)})，本文の文献リンク {n_x}，要確認 {len(REPORT)} 件 (build_report.txt)")
    if web_cmp:
        print(f"ウェブ版との照合: 件数 PDF {web_cmp[0]} / ウェブ {web_cmp[1]}，中身の違い {web_cmp[2]} 件"
              f" (build_report.txt)，表記だけの違い {web_cmp[3]} 件")
    print(f"zip: {zpath}")


def compare_web_refs(work, refs):
    """J-STAGE に登録ずみの引用文献 (refs_web.txt) と，XML に使う PDF 版を照合する．

    句読点の全角・半角，空白，斜体の印の違いは表記だけの違いとして件数だけを出し，
    それ以外 (字の抜け・綴り・数字) を中身の違いとして1件ずつ build_report に書く．
    植生学会誌 31(2) ではウェブ版のハイフン脱落 1 件，42(2) では PDF 版の字の取り違え 1 件が見つかった．
    """
    path = work / "refs_web.txt"
    if not path.exists():
        return None
    import difflib
    import unicodedata
    web = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    pdf = [r.text.replace("*", "") for r in refs]
    norm = lambda t: re.sub(r"[\s　．.，,]", "", unicodedata.normalize("NFKC", t))
    if len(web) != len(pdf):
        REPORT.append(f"引用文献の件数がウェブ版と違う: PDF {len(pdf)} 件 / ウェブ {len(web)} 件．並びもずれている恐れがある")
    content, form = 0, 0
    for k, (w, p) in enumerate(zip(web, pdf)):
        if w == p:
            continue
        if norm(w) == norm(p):
            form += 1
            continue
        content += 1
        a, b = norm(w), norm(p)
        ops = [(a[i1 - 6:i2 + 6], b[j1 - 6:j2 + 6]) for t, i1, i2, j1, j2 in
               difflib.SequenceMatcher(None, a, b).get_opcodes() if t != "equal"][:3]
        REPORT.append(f"引用文献がウェブ版と違う: B{k + 1} " + "; ".join(f"ウェブ「{x}」/ PDF「{y}」" for x, y in ops))
    return len(pdf), len(web), content, form


def check_refs_text(path, refs):
    """タグを入れたことで文献の文字が変わっていないか (斜体の印を除いて元の行と同じか) を確かめる．"""
    try:
        from lxml import etree
    except ImportError:
        return
    doc = etree.parse(str(path), etree.XMLParser(load_dtd=False, no_network=True))
    xs = ["".join(e.itertext()) for e in doc.xpath("//ref/mixed-citation")]
    for r, x in zip(refs, xs):
        if r.text.replace("*", "") != x:
            REPORT.append(f"文献の文字が変わった: {r.id} {r.text[:40]} → {x[:40]}")


class GraphicNames:
    """画像の名前を「{記事識別子}_{連番}.{拡張子}」の0埋めの通し番号で付ける (_01, _02, …)．

    J-STAGE 操作マニュアル 編集登載編 別紙2 の決まり．連番を0埋めすると書誌画面に番号順に並ぶ．
    図も，画像で載せる表も，ページをまたぐ続きの画像も，本文に出てくる順に1つの通し番号にする．
    画像は写さず，(zip の中の名前, 元のファイル) を items に控える (manifest.py が zip へ入れる)．
    """
    def __init__(self, art_id):
        self.art_id, self.items = art_id, []

    def add(self, src):
        name = f"{self.art_id}_{len(self.items) + 1:02d}{src.suffix.lower()}"
        self.items.append((name, src))
        return name


def continued(dir_, stem):
    """figN.png と，その続きの figN_2.png, figN_3.png … を順に返す．"""
    first = dir_ / f"{stem}.png"
    rest = sorted(dir_.glob(f"{stem}_*.png"), key=lambda p: int(p.stem.split("_")[-1]))
    return [p for p in [first] + rest if p.exists()]


def build_body(blocks, refs, floats, work, names):
    out = ["<body>"]
    depth = 0
    for b in blocks:
        if b[0] == "h":
            level = b[1]
            while depth >= level:
                out.append("</sec>")
                depth -= 1
            while depth < level - 1:  # 見出しの段が飛んだとき
                out.append("<sec>")
                depth += 1
            out.append(f"<sec><title>{inline(esc(b[2]))}</title>")
            depth += 1
        elif b[0] == "p":
            out.append(f"<p>{para_xml(b[1], refs, floats, 'body')}</p>")
        elif b[0] == "list":
            typ = "order" if re.match(r"\d", b[1][0]) else "bullet"
            marker = re.compile(r"^(- |\d+[.)] )")  # 箇条書きの行頭の印 (f 文字列の中では書けない)
            items = "".join(
                f"<list-item><p>{para_xml(marker.sub('', it), refs, floats, 'list')}</p></list-item>"
                for it in b[1])
            out.append(f'<list list-type="{typ}">{items}</list>')
        elif b[0] == "formula":
            if [c for c in b[4] if c.strip() and not c.strip().startswith("<!--")]:
                REPORT.append(f"{b[1]}: 式の枠の中身は使わない (式は画像で載せる)")
            out.append(build_formula(b[1], b[2], b[3], work, names))
        elif b[0] in ("fig", "table"):
            kind, fid, label, file, content = b
            if kind == "fig":
                srcs = continued(work / "figs", Path(file).stem)
                if not srcs:
                    REPORT.append(f"図の画像が無い: figs/{file}")
                graphics = "".join(f'<graphic xlink:href="{names.add(p)}"/>' for p in srcs)
                cap = " ".join(c for c in content if not c.strip().startswith("<!--"))
                out.append(f'<fig id="{fid}"><label>{esc(label)}</label><caption><p>{para_xml(cap, refs, floats, fid)}'
                           f'</p></caption>{graphics}</fig>')
            else:
                out.append(build_table(fid, label, content, refs, floats, work, names))
    while depth > 0:
        out.append("</sec>")
        depth -= 1
    out.append("</body>")
    return "\n".join(out)


def build_formula(fid, label, file, work, names):
    """別行立ての式を画像で載せる (<disp-formula>)．

    MathML は組まない (2026-09-19 の決めごと)．式番号は画像に入れず <label> に文字で持つ．"""
    stem = Path(file).stem if file else "eq" + re.sub(r"\D", "", fid)
    srcs = continued(work / "formulas", stem)
    if not srcs:
        REPORT.append(f"{fid}: 式の画像が無い (formulas/{stem}.png)")
    graphics = "".join(f'<graphic xlink:href="{names.add(p)}"/>' for p in srcs)
    lab = f"<label>{esc(label)}</label>" if label else ""
    return f'<disp-formula id="{fid}">{lab}{graphics}</disp-formula>'


def build_table(fid, label, content, refs, floats, work, names):
    lines = [c for c in content if not c.strip().startswith("<!--")]
    intended_image = any(c.strip() == "@image" for c in lines)
    lines = [c for c in lines if c.strip() != "@image"]
    cap = lines[0] if lines else ""
    rest = lines[1:]
    tbl = [l for l in rest if l.strip().startswith("<") or l.strip().startswith("|")]
    foot = [l for l in rest if l not in tbl and l.strip()]
    head = f'<table-wrap id="{fid}"><label>{esc(label)}</label><caption><p>{para_xml(cap, refs, floats, fid)}</p></caption>'
    if any(l.strip().startswith("<") for l in tbl):
        table = raw_table(tbl, refs, floats, fid)
    elif tbl:
        table = pipe_table(tbl, refs, floats, fid)
    else:
        # 表を組んでいないとき・「@image」と書いたときは画像で載せる (続きのページの画像も足す)
        num = re.sub(r"\D", "", fid)
        table = "".join(f'<graphic xlink:href="{names.add(p)}"/>' for p in continued(work / "tables", f"table{num}"))
        if not table:
            REPORT.append(f"{fid}: 表も画像も無い")
        elif not intended_image:
            REPORT.append(f"{fid}: 表が組まれていないので画像で代用した (tables/table{num}*.png)．"
                          "できれば表に組む．画像のままでよければ枠に「@image」と書く")
    ft = ""
    if foot:
        ft = "<table-wrap-foot>" + "".join(f"<p>{para_xml(f, refs, floats, fid)}</p>" for f in foot) + "</table-wrap-foot>"
    return head + table + ft + "</table-wrap>"


def raw_table(lines, refs, floats, fid):
    """HTML で書いた表．タグはそのまま残し，セルの文字だけに引用のリンクと修飾をかける．"""
    out = []
    for part in re.split(r"(<[^>]+>)", "\n".join(lines)):
        if part.startswith("<") or not part.strip():
            out.append(part)
        else:
            out.append(para_xml(html.unescape(part), refs, floats, fid))
    return "".join(out)


def pipe_table(rows, refs, floats, fid):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    has_head = len(cells) > 1 and all(re.fullmatch(r":?-{2,}:?", c) for c in cells[1])
    out = ["<table>"]
    if has_head:
        out.append("<thead><tr>" + "".join(f"<th>{para_xml(c, refs, floats, fid)}</th>" for c in cells[0]) + "</tr></thead>")
        cells = cells[2:]
    out.append("<tbody>")
    for r in cells:
        out.append("<tr>" + "".join(f"<td>{para_xml(c, refs, floats, fid)}</td>" for c in r) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def date_xml(tag, attrs, ymd):
    """「2025-12-24」「2025-12」「2025」のどれでも組む (日・月は省ける)．"""
    parts = str(ymd).split("-")
    y = parts[0]
    m = f"<month>{int(parts[1]):02d}</month>" if len(parts) > 1 else ""
    d = f"<day>{int(parts[2]):02d}</day>" if len(parts) > 2 else ""
    return f"<{tag} {attrs}>{d}{m}<year>{y}</year></{tag}>"


def build_front(meta, prof, abstract_ja, refs, floats):
    lang = meta.get("lang", "ja")
    other = "en" if lang == "ja" else "ja"
    o = ["<front>", "<journal-meta>",
         f'<journal-id journal-id-type="j-stage">{esc(prof["journal_id"])}</journal-id>',
         "<journal-title-group>",
         f'<journal-title xml:lang="ja">{esc(prof["title"]["ja"])}</journal-title>',
         f'<trans-title-group xml:lang="en"><trans-title>{esc(prof["title"]["en"])}</trans-title></trans-title-group>',
         "</journal-title-group>",
         f'<issn pub-type="ppub">{prof["issn"]["ppub"]}</issn>',
         f'<issn pub-type="epub">{prof["issn"]["epub"]}</issn>',
         "<publisher>",
         f'<publisher-name xml:lang="ja">{esc(prof["publisher"]["ja"])}</publisher-name>',
         f'<publisher-name xml:lang="en">{esc(prof["publisher"]["en"])}</publisher-name>',
         "</publisher>", "</journal-meta>", "<article-meta>"]
    if meta.get("doi"):
        o.append(f'<article-id pub-id-type="doi">{esc(meta["doi"])}</article-id>')
    cat = meta.get("category") or {}
    if cat.get("ja") or cat.get("en"):
        o.append("<article-categories>")
        for lg in ("ja", "en"):
            if cat.get(lg):
                o.append(f'<subj-group subj-group-type="article" xml:lang="{lg}"><subject>{esc(cat[lg])}</subject></subj-group>')
        o.append("</article-categories>")
    t = meta["title"]
    o.append("<title-group>")
    o.append(f'<article-title xml:lang="{lang}">{inline(esc(t[lang]))}</article-title>')
    if t.get(other):
        o.append(f'<trans-title-group xml:lang="{other}"><trans-title>{inline(esc(t[other]))}</trans-title></trans-title-group>')
    o.append("</title-group>")

    o.append("<contrib-group>")
    for i, a in enumerate(meta["authors"]):
        at = ['contrib-type="author"']
        if a.get("corresp"):
            at.append('corresp="yes"')
        if i == 0:
            at.append('specific-use="first-author"')
        o.append(f"<contrib {' '.join(at)}>")
        for idt in a.get("ids") or []:
            o.append(f'<contrib-id contrib-id-type="{attr(idt["type"])}">{esc(idt["value"])}</contrib-id>')
        o.append("<name-alternatives>")
        nj, ne = a["name"].get("ja"), a["name"].get("en")
        if nj:
            o.append(f'<name name-style="eastern" xml:lang="ja"><surname>{esc(nj[0])}</surname>'
                     f'<given-names>{esc(nj[1])}</given-names></name>')
        if ne:
            o.append(f'<name name-style="western" xml:lang="en"><surname>{esc(ne[0])}</surname>'
                     f'<given-names>{esc(ne[1])}</given-names></name>')
        o.append("</name-alternatives>")
        if a.get("email"):
            o.append(f"<address><email>{esc(a['email'])}</email></address>")
        for k in a.get("aff") or []:
            o.append(f'<xref ref-type="aff" rid="aff{k}">{k}</xref>')
        o.append("</contrib>")
    for af in meta["affiliations"]:
        o.append(f'<aff-alternatives id="aff{af["id"]}">')
        for lg in ("ja", "en"):
            if af.get(lg):
                o.append(f'<aff xml:lang="{lg}"><institution>{esc(af[lg])}</institution>'
                         f'<country country="{af.get("country", "JP")}">{"日本" if lg == "ja" else "Japan"}</country></aff>')
        o.append("</aff-alternatives>")
    o.append("</contrib-group>")

    pd = meta.get("pub_date") or {}
    if pd.get("ppub"):
        o.append(date_xml("pub-date", 'pub-type="ppub"', pd["ppub"]))
    if pd.get("epub"):
        o.append(date_xml("pub-date", 'pub-type="epub"', pd["epub"]))
    o.append(f"<volume>{esc(str(meta['volume']))}</volume><issue>{esc(str(meta['issue']))}</issue>")
    o.append(f"<fpage>{esc(str(meta['fpage']))}</fpage><lpage>{esc(str(meta['lpage']))}</lpage>")
    h = meta.get("history") or {}
    if any(h.values()):
        o.append("<history>")
        for k in ("received", "rev-recd", "accepted"):
            if h.get(k):
                o.append(date_xml("date", f'date-type="{k}"', h[k]))
        o.append("</history>")
    cp = meta.get("copyright") or {}
    st, ho = cp.get("statement") or {}, cp.get("holder") or {}
    if st.get("ja") and st.get("en"):
        year = re.search(r"\d{4}", st["ja"])
        o.append("<permissions>")
        o.append(f'<copyright-statement xml:lang="ja">{esc(st["ja"])}</copyright-statement>')
        o.append(f'<copyright-statement xml:lang="en">{esc(st["en"])}</copyright-statement>')
        if year:
            o.append(f"<copyright-year>{year.group(0)}</copyright-year>")
        if ho.get("ja") and ho.get("en"):
            o.append(f'<copyright-holder xml:lang="ja">{esc(ho["ja"])}</copyright-holder>')
            o.append(f'<copyright-holder xml:lang="en">{esc(ho["en"])}</copyright-holder>')
        o.append("</permissions>")

    ab = meta.get("abstract") or {}
    paras = abstract_ja if lang == "ja" and abstract_ja else ([ab[lang]] if ab.get(lang) else [])
    if paras:
        o.append(f'<abstract xml:lang="{lang}">' + "".join(f"<p>{inline(esc(p))}</p>" for p in paras) + "</abstract>")
    if ab.get(other):
        o.append(f'<trans-abstract xml:lang="{other}"><p>{inline(esc(ab[other]))}</p></trans-abstract>')
    for lg in ("ja", "en"):
        kws = (meta.get("keywords") or {}).get(lg) or []
        if kws:
            o.append(f'<kwd-group kwd-group-type="author" xml:lang="{lg}">'
                     + "".join(f"<kwd>{esc(k)}</kwd>" for k in kws) + "</kwd-group>")
    o += ["</article-meta>", "</front>"]
    return "\n".join(o)


def build_back(ack, refs, sec_names):
    o = ["<back>"]
    if ack:
        o.append(f"<ack><title>{esc(sec_names['ack'])}</title>" + "".join(f"<p>{inline(esc(p))}</p>" for p in ack) + "</ack>")
    if refs:
        o.append(f"<ref-list><title>{esc(sec_names['refs'])}</title>")
        o += [r.to_xml() for r in refs]
        o.append("</ref-list>")
    o.append("</back>")
    return "\n".join(o)


if __name__ == "__main__":
    sys.exit(main())
