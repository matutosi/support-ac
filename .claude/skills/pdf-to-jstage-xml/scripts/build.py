"""meta.yaml と body.md から J-STAGE 用の全文 XML (JATS 1.1) を組む (手順 3: 変換)．

使い方:
    python build.py <作業ディレクトリ> [--pdf <論文.pdf>]

全文 PDF は作業ディレクトリの <記事識別子>.pdf を使う (--pdf で別の場所も指定できる)．

出力 (作業ディレクトリ):
    out/<記事識別子>.xml   ... 全文 XML
    out/manifest.json      ... zip に入れるものの対応表 (manifest.py)
    <記事識別子>.zip       ... 登載用の一式 (全文 XML 作成ツールの「インポート」か，編集登載の一括アップロードへ)
                               中は「資料コード/巻/号/記事識別子/」に XML・PDF・Graphics/
    build_report.txt       ... リンクできなかった引用・図表など (AI が手で確かめる箇所)

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
    """escape ずみの文字列に *斜体*・**太字**・^上付き^・~下付き~・URL の印を付ける．

    印にしたくない「*」は `\\*` と書く (表の脚注の「*1: …」など．16(1):57)．
    """
    s = s.replace("\\*", "\x00")          # 印にしない「*」をいったん外す
    s = re.sub(r"\*\*(.+?)\*\*", r"<bold>\1</bold>", s)
    # 前後の字で区切るのは，語の中の「*」(N*・log*x*) を印と取り違えないため．
    # \w は仮名・漢字にも当たるので，和文に接した学名 (「山麓部に*Abies*の…」) が
    # 斜体にならなかった (16(2):115)．ASCII の語の字だけを見る
    s = re.sub(r"(?<![A-Za-z0-9_*])\*(?!\s)(.+?)(?<!\s)\*(?![A-Za-z0-9_*])", r"<italic>\1</italic>", s)
    s = re.sub(r"\^([^^\s][^^]*?)\^", r"<sup>\1</sup>", s)
    s = re.sub(r"(?<![~〜])~([^~\s][^~]*?)~(?!~)", r"<sub>\1</sub>", s)
    s = re.sub(r"(https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+;=%-]+?)(?=[，。．、）)\s]|$|\.(?:\s|$))",
               lambda m: f'<ext-link ext-link-type="uri" xlink:href="{m.group(1)}">{m.group(1)}</ext-link>', s)
    return s.replace("\x00", "*")


# ================================================================ 引用文献

ORG = re.compile(r"(財団|協会|学会|省|庁|局|課|県|市|町|村役場|研究所|委員会|センター|会議|組合|機構|グループ|調査団|"
                 r"Ministry|Society|Agency|Institute|Committee|Council|Association)")


ORG_END = re.compile(r"(財団|協会|学会|省|庁|局|課|部|室|県|市|町|村|研究所|委員会|センター|会議|組合|機構|グループ|調査団|"
                     r"編|ほか)$")


def split_ja_names(auth):
    """「馬場多久男・伊藤精晤・田中　誠」→ 名前の (開始, 終了) の列．

    団体名の中の「・」では分けない．「環境省水・大気環境局 水環境課」のように，団体を表す字 (省・局など) を
    含むのにそれで終わっていない部分は，次の部分とつなぐ (植生学会誌 37(1) の文献 B9)．

    ただし人の名前にも団体の字が入る (「市川浩一郎」の「市」)．**次の部分が団体の字で終わるときだけ**
    つなぐことで，人の名前を団体と取り違えないようにする (13(2):59 の文献 B8)．
    """
    parts, pos = [], 0
    for part in re.split(r"(・)", auth):
        if part != "・" and part.strip():
            start = auth.index(part, pos)
            parts.append([start, start + len(part)])
        pos += len(part)

    def incomplete_org(name, nxt):
        """name が団体名の途中か (次の部分 nxt が団体の字で終わるときだけ真)．"""
        return (bool(ORG.search(name)) and not ORG_END.search(name)
                and nxt is not None and bool(ORG_END.search(nxt.strip())))

    out = []
    for i, (a, b) in enumerate(parts):
        nxt = auth[parts[i + 1][0]:parts[i + 1][1]] if i + 1 < len(parts) else None
        if out and out[-1][2]:
            out[-1][1] = b                       # 前の部分 (団体名の途中) とつなぐ
            out[-1][2] = incomplete_org(auth[out[-1][0]:b].strip(), nxt)
            continue
        out.append([a, b, incomplete_org(auth[a:b].strip(), nxt)])
    return [(a, b) for a, b, _ in out]


def tag_ja_name(name):
    # 「ほか13名」のような人数の表記は名前ではないので，そのままの文字で出す
    if re.fullmatch(r"[\s　]*(ほか|他)[\s　]*\d+[\s　]*名[\s　．.，,・]*", name):
        return esc(name)
    suffix = ""
    m = re.match(r"^(.*?)(編|監修|ほか編|ほか)$", name)
    if m and m.group(1).strip():
        core = m.group(1)
        name = core.rstrip()
        suffix = core[len(name):] + m.group(2)   # 「奥田重俊 編」の空白を残す
    # 団体の字で終わるか，人名としては長すぎるときだけ団体とみなす
    # (「岡本省吾」の「省」だけで団体にしていた．16(1):39 の B35)
    if ORG_END.search(name.strip()) or (ORG.search(name) and len(name.strip()) >= 6):
        return f'<collab xml:lang="ja">{esc(name)}</collab>{esc(suffix)}'
    parts = re.split(r"[\s　]+", name.strip(), maxsplit=1)
    if len(parts) == 2:
        sur, giv = parts
        sep = name.strip()[len(sur):len(name.strip()) - len(giv)]
        return (f'<string-name name-style="eastern" xml:lang="ja"><surname>{esc(sur)}</surname>{esc(sep)}'
                f'<given-names>{esc(giv)}</given-names></string-name>{esc(suffix)}')
    return (f'<string-name name-style="eastern" xml:lang="ja"><surname>{esc(name.strip())}</surname>'
            f'</string-name>{esc(suffix)}')


# イニシャルの点が落ちている原文もある (「Ishizuka, M & Sugawara, S. 1986.」．植生学会誌 14(2))．
# 点の無いイニシャルは，後ろが区切り (& / and / , / 行末) のときだけ認める
# イニシャルの前に空白が入る原文もある (「Krummel, J .P.」．16(2):103 の B16)
# 世代を表す呼称が続くこともある (「Webb, T III.」．18(1):31 の B14)
# 「Fang, J-Y.」「Wang, C-W.」のようにイニシャルを引き合わせてある原文もある (15(2):79)
EN_NAME = re.compile(r"([^,&]+?),\s*((?:[A-Z][a-zà-ÿ]?(?:\s?-\s?[A-Z][a-zà-ÿ]?)?\s?\.\s?-?\s?)+(?:\s*(?:Jr|Sr|I{1,3}|IV|V)\.?)?"
                     r"|[A-Z][a-zà-ÿ]?\s+(?:Jr|Sr|I{1,3}|IV|V)\.?"
                     r"|[A-Z][a-zà-ÿ]?(?=\s*(?:&|and\b|,|$)))")


# 並びの途中に，読点を落とした「Li Y.」の形が混ざることがある
# (「Nakamura, T., Go, T., Li Y. & Hayashi, I.」．19(1):55 の B4)．
# 区切りに挟まれた所でだけ見るので，題名の語を姓名と取り違えることはない
NAME_NO_COMMA = re.compile(r"(?P<sur>[A-Z][A-Za-z'\u2019\-]+)[ 　]"
                           r"(?P<given>(?:[A-Z]\s*\.?\s*){1,3})(?=\s*(?:&|＆|and\b|[,，]|$))")


def tag_gap(seg):
    """「Li Y.」のように姓のあとの読点を落とした名前にタグを付ける (無ければそのまま)．

    姓のあとに読点を打たない書式の雑誌もあり，その号では著者が1人も分かれない
    (「Glaser P.H., Janssens J.A. & Siegel D.I.」．19(2):95 の B11)．"""
    out, pos, names = [], 0, []
    for m in NAME_NO_COMMA.finditer(seg):
        given = m.group("given").rstrip()
        out.append(esc(seg[pos:m.start()]) +
                   f'<string-name name-style="western" xml:lang="en">'
                   f'<surname>{esc(m.group("sur"))}</surname> '
                   f'<given-names>{esc(given)}</given-names></string-name>' +
                   esc(m.group("given")[len(given):]))
        pos = m.end()
        names.append(m.group("sur"))
    return ("".join(out) + esc(seg[pos:]), names)


def tag_en_authors(auth):
    """「Batáry, P., Holzschuh, A. & Tscharntke, T.」の各人を string-name で囲む (区切りは残す)．"""
    out, pos, names = [], 0, []
    for m in EN_NAME.finditer(auth):
        sur = m.group(1).strip()
        if not sur:
            continue          # 姓が空になる当たり方 (区切り記号だけ) は人ではない
        lead = m.group(1)[: len(m.group(1)) - len(m.group(1).lstrip())]
        # 「Nakashizuka, T. and Numata, M.」の「and」は姓の一部ではないので，タグの外へ出す
        conj = re.match(r"^(and\s+|&\s*)(.+)$", sur, re.I)
        if conj:
            lead += conj.group(1)
            sur = conj.group(2)
        gap, gn = tag_gap(auth[pos:m.start(1)])
        names += gn
        out.append(gap + esc(lead))
        given = m.group(2).rstrip()
        trail = m.group(2)[len(given):]
        # 姓と名の間の区切りは原文のまま残す (「Braun-Blanquet J.」のようにカンマの無い原文がある．
        # ここで「, 」を足すと，PDF と HTML の文字が変わってしまう)
        sep = auth[m.start(1) + len(m.group(1).rstrip()):m.start(2)]
        out.append(f'<string-name name-style="western" xml:lang="en"><surname>{esc(sur)}</surname>{esc(sep)}'
                   f'<given-names>{esc(given)}</given-names></string-name>{esc(trail)}')
        names.append(sur)
        pos = m.end()
    # 並びの最後だけ「& Li, Sek-ha」のようにイニシャルでない名のことがある
    # (18(2):99 の B17)．末尾に限るのは，題名の語を名と読まないため
    tail = re.match(r"^(?P<lead>\s*(?:&|＆|and\s|,\s)\s*)(?P<sur>[A-Z][A-Za-z'\u2019\-]+)\s*,\s*"
                    r"(?P<given>[A-Z][A-Za-z\u00e0-\u00ff]*(?:-[A-Za-z]+)*)\s*$", auth[pos:])
    if names and tail:
        out[-1] = out[-1] if out else ""
        out.append(esc(tail.group("lead")) +
                   f'<string-name name-style="western" xml:lang="en">'
                   f'<surname>{esc(tail.group("sur"))}</surname>, '
                   f'<given-names>{esc(tail.group("given"))}</given-names></string-name>')
        names.append(tail.group("sur"))
    else:
        tail_xml, tail_names = tag_gap(auth[pos:])   # 末尾にも読点なしの名前が来る
        out.append(tail_xml)
        names += tail_names
    if not names:
        return None, []
    return "".join(out), names


# 編者は「W. Holzner, M. J. A. Werger & I. Ikushima」のように名を先に書くことがある
# (18(2):47 の B9)．姓が後ろに来るので EN_NAME (「姓, 名.」) では取れない
GIVEN_FIRST = re.compile(r"^\s*(?P<given>(?:[A-Z]\s*\.\s*)+)"
                         r"(?P<sur>[A-Z][A-Za-z'\u2019\-]+(?:\s+[A-Z][A-Za-z'\u2019\-]+)*)\s*$")


def tag_en_names_given_first(s):
    """「W. Holzner, M. J. A. Werger & I. Ikushima」の各人を string-name で囲む．

    全員がこの形のときだけ使う (1人でも「姓, 名.」の形が混ざれば None を返して
    tag_en_authors に任せる)．"""
    parts = re.split(r"(\s*(?:[,，]|&|＆|\band\b)\s*)", s)
    out, n = [], 0
    for i, part in enumerate(parts):
        if i % 2:                       # 区切りはそのまま
            out.append(esc(part))
            continue
        if not part.strip():
            out.append(esc(part))
            continue
        m = GIVEN_FIRST.match(part)
        if not m:
            return None, 0
        lead = part[: len(part) - len(part.lstrip())]
        given = m.group("given").rstrip()
        gap = m.group("given")[len(given):]      # 名と姓の間の空き (原文のまま残す)
        # 原文が「名 姓」の順なので，タグもその順に置く (姓を前に出すと
        # 表示される文字が変わり，PDF と HTML の内容が違ってしまう．19(1):55 の B20)
        out.append(esc(lead) + f'<string-name name-style="western" xml:lang="en">'
                   f'<given-names>{esc(given)}</given-names>{esc(gap)}'
                   f'<surname>{esc(m.group("sur"))}</surname></string-name>')
        n += 1
    return ("".join(out), n) if n else (None, 0)


# 年は「1996．」のほか，古い号では「1971-78．」「1979-80．」のような範囲で書かれることがある
# 年のあとは「1965．」が普通だが，「今井　努 1965 西日本における…」のように点の無い号もある
YEAR = re.compile(r"^(?P<auth>.+?)\s*[（(]?(?P<year>(?:1[89]|20)\d{2})(?P<suf>[a-z]?)"
                  r"(?:\s*[-–−~〜]\s*\d{2,4})?[)）]?\s*(?:[.．]\s*|\s+)(?P<rest>.*)$")
JOURNAL_TAIL = re.compile(
    # 誌名は *斜体* で囲まれていれば中に「.」があってもよい (J. Sci. Hiroshima Univ. など)
    # 誌名と巻の間は，読点のほか「Journal of Ecology. 19 : 95-99.」のように
    # 句点のこともある (16(2):103 の B1．これを受けないと雑誌と分からず書籍になる)
    # 誌名は *斜体* で囲まれていれば中に「.」があってもよい．
    # 囲まれていなくても，「Eco. Rev.」「J. Veg. Sci.」「Bot. Mag. Tokyo」のように
    # 略記の切れ目の「.」だけでできているものは誌名として拾う (17(2):89・16(2):103)．
    # 略記は「大文字で始まる 5 字までの語 + .」の並びとみなす
    r"\s*(?P<src>\*[^*]+\*"
    # 先頭は 4 字までの略記に限る．題名の末尾の語 (「…in Japan.」「…of Tokyo.」) を
    # 誌名に巻き込まないため (5 字の Japan・Tokyo は先頭になれない)
    # 略記が2つ以上なら最後は点が無くてもよい (Bot. Mag. Tokyo)．
    # 1つだけのときは最後にも点が要る (Eco. Rev.)．
    # そうしないと「…in Asia. Vegetatio 100: …」の Asia を誌名に含めてしまう
    # 「Korean J. Ecol.」のように，略記の前に点の付かない語が来ることもある．
    # 点で終わる語ではないので，題名の末尾の「…in Japan.」とは紛れない
    # 略記の途中の，点の付かない語 (「Bull. Tokyo Univ. For.」の Tokyo) は，
    # **直後がまた略記のときだけ**許す．「USA. Tree Physiology」「Mt. Iide. Ecological Review」
    # のように題名の語を巻き込む形を除くため
    r"|(?:[A-Z][a-z]{2,11}[ 　])?[A-Z][A-Za-z]{0,3}\.\s*"
    r"(?:[A-Z][A-Za-z]{0,5}\.\s*|[A-Z][a-z]{2,11}[ 　]+(?=(?:[A-Z][a-z]{2,11}[ 　]+)*[A-Z][A-Za-z]{0,5}\.)){1,6}[A-Z][A-Za-z]{0,11}\.?"
    # 「…Ser. E (Biol.)」のように括弧つきの略記で終わる誌名もある (18(1):23 の B8，18(1):31 の B19)
    r"(?:\s*[（(][A-Za-z][A-Za-z.]{0,9}[)）])?"
    # 「Sci. Rep. Yokohama Nat. Univ., Sect II, 15：1-23.」のように，
    # 読点のあとに部門 (Sect・Ser・Sec) が続く誌名もある (18(2):99 の B23)
    r"(?:\s*[,，]\s*(?:Sect|Sec|Ser)[.．]?\s*[A-Z\u2160-\u216f\u2170-\u217f0-9]{1,4}[.．]?)?"
    # 「Bull. Fac. Agr., Tamagawa Univ., 38：1-10.」のように，読点のあとに
    # 大学名などが続く誌名もある (19(1):25 の B23)
    r"(?:\s*[,，]\s*(?:[A-Z][a-z]{2,11}[ 　]+)*[A-Z][A-Za-z]{0,7}[.．])?"
    r"|(?:[A-Z][a-z]{2,11}[ 　])?[A-Z][A-Za-z]{0,3}\.\s*[A-Z][A-Za-z]{0,11}\."
    # 「Trans. ASAE」「J. JASS」のように，略記のあとが頭字語だけの誌名もある
    # (19(1):25 の B13・B24)．頭字語は大文字だけなので，題名の末尾の語とは紛れない
    r"|[A-Z][a-z]{0,7}[.．]\s*[A-Z]{2,6}"
    r"|[^.．\s][^.．]*?)(?:\s*[.．,，]\s*|\s+)"
    # 巻は「52-53」「41/42」(合併号．19(1):25 の B11・B22)・「66 A-9」(19(1):43 の B23)
    # のような範囲や，「Suppl. 1」のような別冊の言い方もある．
    # 巻を立てず号だけの雑誌もある (「フロラ栃木，(3)：1-10」．植生学会誌 13(2) の B3)
    # 紙面が巻を太字で組む雑誌があり，body.md も原文どおり **75** と書く (19(1):25 の B11)
    r"(?:\*{0,2}(?P<vol>(?:Suppl\.?\s*|Spec\.?\s*|[Nn]o\s*[.．]\s*)?[A-Za-z]?\d+(?:\s*[-–−/／]\s*\d+)?[A-Za-z]?(?:[ 　][A-Z][-–−]\d+)?)"
    # 巻と号をハイフンでつなぐ書き方もある (「土木技術資料, 41-(7)：32-37」．18(1):1 の B5)
    r"\*{0,2}(?:\s*[-–−]?\s*[（(](?P<iss>[^)）]+)[)）])?|[（(](?P<iss2>[^)）]+)[)）])"
    # ページは「14：p.151．」のように p. が付くこともある (1ページだけの記事)
    # 巻とページの間を読点で区切る和文の雑誌もある (「生態学会誌, 42, 241-248.」．19(1):61 の B29)
    r"\s*[:：,，]\s*(?:p\s*\.\s*)?(?P<fp>[A-Za-z]?\d+)"
    r"(?:\s*[-–−₋~〜～]\s*(?P<lp>[A-Za-z]?\d+))?"
    # 分載の論文は「9：1-37, 108-127, 195-219, 271-300．」のようにページ範囲を並べる
    # (18(2):107 の B3)．2つめ以降は文字のまま置く (fpage・lpage は先頭の範囲)
    r"(?:\s*[,，]\s*\d+\s*[-–−₋~〜～]\s*\d+)*"
    # 「1-10, pls. 1-4.」のように図版の付記が続くことがある (植生学会誌 13(2) の B3)
    r"(?:\s*[,，]\s*(?:pls?|figs?)\s*\.?\s*[\dA-Za-z,\s\-–−]*)?"
    r"(?:\s*[+＋]\s*[^.．]*)?"
    # 古い和文の雑誌は，ページのあとに発行地が続くことがある
    # (「寒地農学，2（2）：143−173，札幌．」．16(1):13 の B12)
    r"(?:\s*[,，]\s*[^.．,，:：\d][^.．,，:：]{0,9})?"
    # 「(in Japanese with English summary).」のような付記が続くことがある．
    # これを受けないと雑誌と分からず，書籍として誌名と題名が入れ替わっていた (16(2):149)．
    # 原文の閉じ括弧が落ちていることもある (同 Maesako 1985) ので，閉じは無くてもよい
    # 「Hikobia 9: 137-145. (In Japanese with English summary).」のように，
    # ページのあとに句点を置いてから括弧が来ることもある (17(2):81)
    r"(?:\s*[.．]?\s*[（(][^)）]*[)）]?)?"
    r"\s*[.．]?\s*$")     # 「371-486+30 plates.」のような後ろ付きも雑誌として扱う
# 編者を書名のあとに括弧で置く書き方もある
# (「In: 書名．副題．(ed. H. Dierschke), pp. 21-39. J. Cramer, Vaduz.」．17(1):1・17(1):31)
CHAPTER_EN2 = re.compile(
    r"^(?P<title>.+?\.)\s*(?:In\s*:\s*)?(?P<src>.+?)\s*[（(]\s*eds?\.?(?:\s+by)?\s+(?P<eds>[^)）]*)[)）]"
    r"\s*[,，]?\s*(?:pp?\s*\.\s*)?(?P<fp>\d+)\s*[-–]\s*(?P<lp>\d+)\s*[.．]\s*(?P<pub>.+)$")
CHAPTER_JA = re.compile(
    r"^(?P<title>.+?[.．])\s*(?P<eds>[^「」．.]+?)編「(?P<src>[^」]+)」\s*[,，]\s*(?P<fp>\d+)(?:\s*[-–]\s*(?P<lp>\d+))?"
    r"\s*[.．]\s*(?P<pub>[^,，．.]+?)\s*[,，]\s*(?P<loc>[^.．]+?)\s*[.．]\s*$")
# 章題．「書名」（編者編），ページ．出版社，所在地．(植生学会誌 37(1) の文献 B5・B12)
# 編者は「編」のほか「編著」「監修」とも書かれ，書かれないこともある．
# ページは「pp. 87-100」のように pp. が付くこともある (植生学会誌 14(1) の文献)
CHAPTER_JA2 = re.compile(
    r"^(?P<title>.+?[.．])\s*「(?P<src>[^」]+)」\s*"
    r"(?:[（(](?P<eds>[^）)]+?)\s*(?:編著|編|監修)[）)])?\s*[,，]\s*(?:pp?\s*\.\s*)?(?P<fp>\d+)"
    r"(?:\s*[-–]\s*(?P<lp>\d+))?\s*[.．]\s*(?P<pub>[^,，．.]+?)\s*[,，]\s*(?P<loc>[^.．]+?)\s*[.．]\s*$")
# 「In:」を書かない号もある (「章題. 編者 (eds.) 書名, pp. 243-272. 出版社, 所在地.」．17(2):97)．
# ページに pp. が付くこともある
# 「In:」も「」も使わない和文の編著の章
# (「章題．書名（編者編），pp.33-94．出版社．」．18(1):23 の B7，18(1):39 の B1・B5・B10・B17)
CHAPTER_JA3 = re.compile(
    r"^(?P<title>.+?[.．])\s*(?P<src>[^.．]+?)\s*"
    # 編者の括弧が無い (書名のあとにそのままページが来る) 書き方もある．
    # 編者を書くときは，そのあとの読点を省くことがある (「（…編）pp. 19-47.」．18(2):87 の B4)
    r"(?:[（(](?P<eds>[^）)]+?)\s*(?:編著|編|監修)[）)]\s*[,，]?|[,，])"
    # ページのあとは「．」のほか「．，」と重ねることもあり，出版社と所在地の区切りも
    # 読点でなく句点のことがある (「pp. 186-197., 至文堂. 東京.」．18(2):99 の B24)
    r"\s*(?:pp?\s*[.．]\s*)?(?P<fp>\d+)\s*[-–−]\s*(?P<lp>\d+)\s*(?:[.．]\s*[,，]?|[,，])\s*"
    r"(?P<pub>[^,，.．]+?)(?:\s*[,，.．]\s*(?P<loc>[^,，.．]+?))?\s*[.．]?\s*$")
def ja3(rest):
    """CHAPTER_JA3 を当てる．書名が数字や1〜2字だけになる当たり方は採らない．

    「大町市史，Vol. 1, pp. 655-663.」のように書名の中に句点があると，
    書名の切れ端 (「1」) だけが残る形で当たってしまう (16(1):115 の B80)．"""
    m = CHAPTER_JA3.match(rest)
    if not m:
        return None
    if not m.group("src").strip() or re.fullmatch(r"[\dA-Za-z\s　,，]+", m.group("src")):
        return None
    # 出版社・所在地がページの範囲になる当たり方も採らない．分載の論文
    # (「地理学評論，9：1-37, 108-127, 195-219, 271-300．」) は雑誌 (18(2):107 の B3)
    for g in ("pub", "loc"):
        if m.group(g) and NOT_PUB.search(m.group(g).strip()):
            return None
    return m


CHAPTER_EN = re.compile(
    r"^(?P<title>.+?\.)\s*(?:In\s*:\s*)?(?P<eds>.+?)\s*\(?eds?\.\)?\s*(?P<src>.+?),\s*(?:pp?\s*\.\s*)?"
    r"(?P<fp>\d+)\s*[-–]\s*(?P<lp>\d+)\.\s*(?P<pub>.+)$")
# 「In :」を必ず見る形．章題の中に「Mt.」「No.」のような略記があると，
# 「In :」が任意だと略記の点を章題の終わりと取り違える (「Mt. Horai. In : …」．19(1):1 の B22)
CHAPTER_EN2_IN = re.compile(CHAPTER_EN2.pattern.replace(r"(?:In\s*:\s*)?", r"In\s*:\s*"))
CHAPTER_EN_IN = re.compile(CHAPTER_EN.pattern.replace(r"(?:In\s*:\s*)?", r"In\s*:\s*"))
# 編者を書かない英文の報告書の章 (「章題. In : 報告書名, pp. 37-48. 発行者 (in Japanese).」．
# 19(1):1 の B16・B39)．和文の CHAPTER_JA3 と同じ形で，前に「In :」が付く
# 発行者・発行地のあとにページを置く章もある
# (「章題. In : 書名 (ed. A. Miyawaki), 発行者. 東京. pp. 55-60 (付記).」．19(1):11 の B9・B15)
CHAPTER_EN4 = re.compile(
    r"^(?P<title>.+?[.．])\s*In\s*:?\s*(?P<src>.+?)\s*[（(]\s*[Ee]ds?\.?(?:\s+by)?\s+"
    r"(?P<eds>[^)）]*)[)）]\s*[,，.．]?\s*(?P<pub>.+?)\s*[.．]\s*(?P<loc>[^.．,，]+?)\s*[.．]\s*"
    r"pp?\s*[.．]\s*(?P<fp>\d+)\s*[-–−]\s*(?P<lp>\d+)\s*(?:[（(][^)）]*[)）])?\s*[.．]?\s*$")
CHAPTER_EN3 = re.compile(
    r"^(?P<title>.+?[.．])\s*In\s*:\s*(?P<src>.+?)\s*[,，]\s*(?:pp?\s*[.．]\s*)?"
    r"(?P<fp>\d+)\s*[-–−]\s*(?P<lp>\d+)\s*[.．]\s*"
    r"(?P<pub>[^.．].*?)\s*[.．]?\s*(?:[（(][^)）]*[)）])?\s*[.．]?\s*$")
# 題名．出版社．(所在地なし)．ただし「…報告書（追加調査）．」のような副題は出版社ではない
# 末尾の句点は落とさない．落ちている紙面もあるが (「…75年史. 東京大学」．19(2):125 の B14)，
# 句点を任意にすると「…大明堂．東京」の発行地を出版社と取り違える (16(2):103・18(1):39)
BOOK_PUB = re.compile(r"[.．]\s*(?P<pub>[^.．,，「」]+?)\s*[.．]\s*$")
# 出版社の候補が数字やページの範囲だけのものは出版社ではない
# (「…特定植物群落調査報告書，pp．21−22．」の 21−22．17(1):23 の B7)
NOT_PUB = re.compile(r"(報告書|調査|目録|一覧|紀要|年報)$|[）)]$"
                     r"|^[\dA-Za-z]*[\s　]*[\d]+[\s　]*[-–−~〜～][\s　]*\d+$|^[\d\s　]+$")
# 出版社は「SPSS Inc., Chicago.」「… Co., Ltd., Tokyo.」のように略記で終わることがある
# (19(1):1 の B32)．略記の点は出版社の一部なので，そこだけ点を許す
BOOK_TAIL = re.compile(r"\s*(?P<pub>[^.．,，「」\s][^.．,，「」]*?"
                       r"(?:\s*(?:Inc|Ltd|Co|Corp|Univ|Press|Publ|Pub)[.．])?)"
                       # 発行地は「Washington, D.C.」のように略記が続くことがある
                       # (19(2):73 の B3)．D.C. の点で切ると出版社と発行地が割れる
                       r"\s*[,，]\s*(?P<loc>[^.．,，「」]+?"
                       # 州の略号が続く形もある (「Vicksburg, MS.」．19(2):95 の B39)
                       r"(?:\s*[,，]\s*(?:[A-Z][.．]\s*(?:[A-Z][.．])?|[A-Z]{2}))?)\s*[.．]?\s*$")


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
        self.auth = auth          # 著者の部分そのまま (手で指定するリンクの照合に使う)
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
        cm = ((CHAPTER_JA.match(rest) or CHAPTER_JA2.match(rest) or ja3(rest))
              if self.lang == "ja"
              # 編者を括弧で後置する形を先に見る (CHAPTER_EN だと編者と書名が入れ替わるため)
              else (CHAPTER_EN2_IN.match(rest) or CHAPTER_EN_IN.match(rest)
                    or CHAPTER_EN2.match(rest) or CHAPTER_EN.match(rest)
                    or CHAPTER_EN3.match(rest) or CHAPTER_EN4.match(rest)))
        if cm:
            self.kind = "book"
            body = self.chapter_xml(rest, cm)
        elif jm and jm.group("src").strip():
            self.kind = "journal"
            title = rest[:jm.start("src")]
            body = (self.title_xml(title) + inline(esc(rest[jm.start("src"):jm.start("src")])) +
                    self.tail_journal(rest, jm))
        # 出版社の候補に閉じ括弧だけが入るのは切れ目の取り違え
        # (「…（付着色植生図　4，付表），横浜．」．植生学会誌 14(2) の B6)
        elif (bm and not re.search(r"(In\s*:|編「|（編）|pp\.)", rest)
              # 発行地の位置に数字だけが来るのは，ページを発行地と取り違えた形
              # (「…第106回日本林学会講演要旨集, 540」．18(2):75 の B24)
              and not re.fullmatch(r"[\d\s　]+|[\dA-Za-z]*[\s　]*\d+[\s　]*[-–−~〜～][\s　]*\d+",
                                  bm.group("loc").strip())
              and bm.group("pub").count("）") <= bm.group("pub").count("（")
              and bm.group("pub").count(")") <= bm.group("pub").count("(")):
            self.kind = "book"
            title = rest[:bm.start("pub")]
            t2 = title.rstrip()
            # 書名のあとが読点の書き方もある (「Saline Agriculture, National Academy Press, …」)
            end = re.search(r"[.．,，]\s*$", t2)
            main = t2[: end.start()] if end else t2
            # タグで囲まない部分にも *斜体* の印が残ることがあるので inline を通す
            body = (f'<source xml:lang="{self.lang}">{inline(esc(main.strip()))}</source>'
                    + inline(esc(t2[len(main):])) + inline(esc(title[len(t2):]))
                    + f"<publisher-name>{inline(esc(bm.group('pub')))}</publisher-name>"
                    + inline(esc(rest[bm.end("pub"):bm.start("loc")]))
                    + f"<publisher-loc>{inline(esc(bm.group('loc')))}</publisher-loc>"
                    + inline(esc(rest[bm.end("loc"):])))
        elif BOOK_PUB.search(rest) and not re.search(r"(In\s*:|編「|（編）|pp\.)", rest)                 and not NOT_PUB.search(BOOK_PUB.search(rest).group("pub").strip()):
            pm = BOOK_PUB.search(rest)
            self.kind = "book"
            main = rest[:pm.start()]
            body = (f'<source xml:lang="{self.lang}">{inline(esc(main))}</source>'
                    + inline(esc(rest[pm.start():pm.start("pub")]))
                    + f"<publisher-name>{inline(esc(pm.group('pub')))}</publisher-name>"
                    + inline(esc(rest[pm.end("pub"):])))
        else:
            REPORT.append(f"文献の後半を分解できない (著者・年だけタグ付け): {self.id} {t[:70]}")
            body = inline(esc(rest))
        self.xml = head + year_xml + body

    def chapter_xml(self, rest, m):
        """編著の1章．どの書き方でも，見つけた部分 (章題・編者・書名・ページ・出版社・所在地) を
        元の文の位置のままタグで囲む (前後の空白はタグの外に出す)．"""
        eds = m.group("eds") if "eds" in m.groupdict() else None
        if not eds:
            eds_xml = ""
        elif self.lang == "ja":
            parts, pos = [], 0
            for a, b in split_ja_names(eds):
                parts.append(esc(eds[pos:a]) + tag_ja_name(eds[a:b]))
                pos = b
            eds_xml = "".join(parts) + esc(eds[pos:])
        else:
            eds_xml, _ = tag_en_names_given_first(eds)
            if not eds_xml:
                eds_xml, _ = tag_en_authors(eds)
            eds_xml = eds_xml or esc(eds)
        wrap = {
            "title": lambda t: self.title_xml(t),
            "eds": lambda t: f'<person-group person-group-type="editor">{eds_xml}</person-group>',
            "src": lambda t: f'<source xml:lang="{self.lang}">{inline(esc(t))}</source>',
            "fp": lambda t: f"<fpage>{esc(t)}</fpage>",
            "lp": lambda t: f"<lpage>{esc(t)}</lpage>",
            # 斜体の印は発行者・発行地の側に入ることもある (書名を発行者と取り違えたとき)．
            # そのまま出すと「*…*」の印が文字として残ってしまうので inline を通す
            "pub": lambda t: f"<publisher-name>{inline(esc(t))}</publisher-name>",
            "loc": lambda t: f"<publisher-loc>{inline(esc(t))}</publisher-loc>",
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
        # 題名の前後の空白はタグの外へ出す (落とすと PDF と文字が変わる．
        # 「…*Larix dahurica* . Can. J. …」の空白を消していた．14(2):119 の B18)
        core = main.strip()
        lead = main[:len(main) - len(main.lstrip())]
        trail = main[len(main.rstrip()):]
        return (esc(lead) + f'<article-title xml:lang="{self.lang}">{inline(esc(core))}</article-title>'
                + esc(trail) + esc(t[len(main):]) + esc(title[len(t):]))

    def tail_journal(self, rest, m):
        g = lambda k: esc(m.group(k))
        s = f'<source xml:lang="{self.lang}">{inline(esc(m.group("src").strip()))}</source>'
        iss = "iss" if m.group("iss") else ("iss2" if m.group("iss2") else None)
        if m.group("vol"):
            pre = rest[m.end("src"):m.start("vol")]
            pos = m.end("vol")
            bold = pre.endswith("**") and rest[pos:pos + 2] == "**"
            if bold:                # 巻を太字で組む雑誌 (19(1):25)．太字のまま <volume> に入れる
                pre, pos = pre[:-2], pos + 2
                s += esc(pre) + f"<volume><bold>{g('vol')}</bold></volume>"
            else:
                s += esc(pre) + f"<volume>{g('vol')}</volume>"
        else:                       # 巻が無く号だけの雑誌
            pos = m.end("src")
        if iss:
            s += esc(rest[pos:m.start(iss)]) + f"<issue>{g(iss)}</issue>"
            s += esc(rest[m.end(iss):m.start("fp")])
        else:
            s += esc(rest[pos:m.start("fp")])
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


def author_matches(window, ref, raw=None):
    """window (年の直前の文字列．空白なし) が ref の著者表記で終わっているか．

    和文: 年の直前の漢字・カタカナのかたまり (「川村・大窪」「北川」+「ほか」) を切り出し，
    各部分が文献の著者名の先頭と一致するかで見る (末尾の1字だけの一致は採らない)．
    欧文: 「Surname」「S1 & S2」「S1 et al.」で終わり，その前が区切り記号であること．
    **英文の論文**では著者名の前が語の切れ目 (空白) のこともあるので，空白を残した raw でも見る．
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
                if raw:
                    # \u300ccarried out by Jones (1965)\u300d\u306e\u3088\u3046\u306b\uff0c\u8457\u8005\u540d\u306e\u524d\u304c\u7a7a\u767d\u306e\u3053\u3068\u3082\u3042\u308b
                    flex = r"\s*".join(re.escape(c) for c in f)
                    if re.search(r"(?:^|[\s(\uff08\[\u300c\u300e,\uff0c;\uff1b:\uff1a])" + flex + r"[\s,\uff0c]*$", raw):
                        return True
        return False
    # 「ほか」のほかに「ら」と書く号もある (13(2) など)
    etal = w.endswith("ほか") or w.endswith("ら")
    if etal:
        w = w[:-2] if w.endswith("ほか") else w[:-1]
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


MANUAL = re.compile(r"\{\{(?:(?P<rid>B\d+)|(?P<key>[^|{}]+?)\s+(?P<year>(?:1[89]|20)\d{2}[a-z]?))"
                    r"\|(?P<shown>[^{}]+)\}\}")


def link_citations(text, refs, where):
    """AI が手で指定したリンク {{著者名の先頭 年|表示}}・{{B12|表示}} を先に処理し，残りを自動でリンクする．

    AI が手で指定するのは，原文の表記揺れで自動では当たらないとき
    (例: 本文「北海道環境科学センター（2005）」と文献「北海道環境科学研究センター 2005」)．
    著者名と年では引けないとき (同じ著者の同じ年の文献が2件あり，本文はどちらも「村上 1985」と
    書いている場合など) は，文献の番号で {{B20|村上 1985}} と書く (16(1):39・16(1):57)．
    表示の文字は原文のまま残す (PDF と HTML の内容は同一でなければならないため)．
    """
    out, pos = [], 0
    by_id = {r.id: r for r in refs}
    for m in MANUAL.finditer(text):
        out.append(auto_citations(text[pos:m.start()], refs, where))
        shown = m.group("shown")
        if m.group("rid"):
            hit = [by_id[m.group("rid")]] if m.group("rid") in by_id else []
        else:
            key = re.sub(r"[\s　]", "", m.group("key"))
            # 第一著者の名前か，著者の部分そのもの (「橘ヒサ子・樫村利道」) の先頭で照合する．
            # 同じ第一著者・同じ年の文献が2件あるときは，2人目まで書いて選び分ける
            def match(r):
                # 著者を人ごとに分けられなかった文献 (原文にカンマが無いなど) は auth だけで見る
                heads = [r.names[0] if r.names else "", getattr(r, "auth", "")]
                return any(re.sub(r"[\s　]", "", h).startswith(key) for h in heads if h)
            hit = [r for r in refs if r.year == m.group("year") and match(r)]
        if len(hit) == 1:
            out.append(f"\x01{hit[0].id}\x02{shown}\x03")
        else:
            REPORT.append(f"AI が手で指定したリンクの文献が{'見つからない' if not hit else '複数ある'} ({where}): {m.group(0)}")
            out.append(shown)
        pos = m.end()
    out.append(auto_citations(text[pos:], refs, where))
    return "".join(out)


def auto_citations(text, refs, where):
    """本文の段落 (escape 前) の年に，対応する文献への印を付ける．\x01rid\x02表記\x03 の形で返す．"""
    by_year = {}
    for r in refs:
        if r.year:
            by_year.setdefault(r.year, []).append(r)
    out, pos, last_end, last_window, last_raw = [], 0, None, None, None
    for m in CITE_YEAR.finditer(text):
        after = text[m.end():m.end() + 3]
        if re.match(r"\s*[)）]?\s*年", after) or re.match(r"\s*[/.]\d", after):  # 「2011 年」「平成4（1992）年」
            continue
        year = m.group(1) + m.group(2)
        between = text[last_end:m.start()] if last_end is not None else None
        cands = by_year.get(year, [])
        hit = None
        raw_window = re.sub(r"[（(]\s*$", "", text[max(0, m.start() - 60):m.start()])
        # 斜体の印 (*et al*.) は表示の飾りなので，照合では外す
        raw_window = raw_window.replace("*", "")
        window = re.sub(r"[\s　]", "", raw_window)
        window = re.sub(r"[,，]$", "", window)   # 「Takatsuki & Gorai, 1994」の読点
        if between is not None and re.fullmatch(r"\s*[,，]\s*", between) and last_window:
            window = last_window  # 「北川ほか2004, 2005」の 2005 は直前の著者表記を引き継ぐ
            raw_window = last_raw  # 空白を残したほうも引き継ぐ (「Li (1989, 1993)」の 1993)
        if hit is None:
            ok = [r for r in cands if author_matches(window, r, raw_window)]
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
        last_end, last_window, last_raw = m.end(), window, raw_window
        # 「1991a, b」の b
        while True:
            mm = re.match(r"(\s*[,，]\s*)([a-z])(?![A-Za-z])", text[pos:])
            if not mm:
                break
            y2 = m.group(1) + mm.group(2)
            r2s = [r for r in by_year.get(y2, []) if author_matches(window, r, raw_window)]
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
    """「図1」「表1」を図表へのリンクにする．「図2，3，4」「図3, 4」の2つ目以降の番号もリンクする．

    1990 年代の号のように，和文の中で「Fig. 1」「Table 1」と英語で呼ぶ論文もある．
    複数形 (「Figs. 3 and 4」「Tables 1, 2」) も，「and」でつないだ2つ目以降もリンクする．
    """
    def one(kind, num, shown):
        key = ("F" if kind == "図" or kind.startswith("Fig") else "T") + num   # Fig./Figure/図 → F
        if key not in floats:
            REPORT.append(f"本文の {kind}{num} に対応する図表が無い")
            return shown
        return f"\x04{key}\x02{shown}\x03"

    def rep(m):
        kind = m.group(1)
        out = one(kind, m.group(3), m.group(1) + m.group(2) + m.group(3))
        for mm in re.finditer(r"(\s*(?:[，,、]|and|&|＆)\s*)(\d+)", m.group(4)):
            out += mm.group(1) + one(kind, mm.group(2), mm.group(2))
        return out
    return re.sub(r"(図|表|Figs\.|Fig\.|Figures|Figure|Figs|Fig"
                  r"|Tables|Table|Tabs\.|Tab\.)(\s*)(\d+)"
                  # 「Fig. 4, 1a」の「1a」のように英字が続くものは番号の続きではない
                  # (Fig. 4 の中の群落 1 の下位単位 a を指す．17(2):55)
                  r"((?:\s*(?:[，,、]|and|&|＆)\s*\d+(?![\d.A-Za-z]))*)", rep, text)


APPENDIX_REF = re.compile(r"(Appendices|Appendix|付録)(\s*)(\d+)")


def link_appendix(text, floats):
    """「Appendix 1」「付録1」を，その番号の付録へのリンクにする．

    図表と違って番号の言い方が「Appendix 1」なので，枠の番号 (`:::table T3 Appendix 1`) と
    突き合わせて行き先を決める．該当する枠が無ければ，そのままの文字で残す．
    """
    def rep(m):
        key = (m.group(1) + m.group(3)).replace(" ", "").lower().replace("appendices", "appendix")
        for fid, label in floats.items():
            if (label or "").replace(" ", "").lower() == key:
                return f"\x04{fid}\x02{m.group(0)}\x03"
        return m.group(0)
    return APPENDIX_REF.sub(rep, text)


SEC_NUM = re.compile(r"^[\s\u3000]*(?:[0-9０-９]+|[IVXivx]+)[\s\u3000]*[．.、，,:：]?[\s\u3000]*")


def sec_head(t):
    """節の見出しを，設定の文言と引き合わせるための形にする．

    原文が「5．謝辞」「7．引用文献」のように番号を付けていても振り分けられるように，
    行頭の番号を落とす．**XML に出す見出しは原文のまま** (番号も残る)．
    """
    return SEC_NUM.sub("", t).strip().strip("．.：:　 ")


def link_formulas(text, floats):
    """「式(1)」「式1」「(1)式」を別行立ての式へのリンクにする．

    欧文の論文は「Eq. (1)」「Eqs. 1 and 2」と書くので，それも受ける (16(2):103)．
    番号だけの「(1)」は，引用の番号や注の番号と紛れるのでリンクしない．"""
    def rep(m):
        num = m.group(2) or m.group(3) or m.group(4)
        key = "E" + num
        if key not in floats:
            return m.group(0)
        return f"\x05{key}\x02{m.group(0)}\x03"
    return re.sub(r"(式\s*[（(]?(\d+)[)）]?|[（(](\d+)[)）]\s*式"
                  r"|Eqs?\s*\.?\s*[（(]?(\d+)[)）]?)", rep, text)


def title_xml(text, floats):
    """見出しの中の図表の参照だけをリンクにする (「(2) …群落（Table 1-(B)）…」の Table 1)．

    見出しには群集名の命名者 (「Tohyama et Mochida 1978」) が入ることがあり，
    これを引用と取り違えるので，引用 (著者 年) のリンクは行わない．
    """
    t = link_floats(text, floats)
    t = link_appendix(t, floats)
    s = inline(esc(t))
    s = re.sub(r"\x04(F\d+)\x02(.*?)\x03", r'<xref ref-type="fig" rid="\1">\2</xref>', s)
    s = re.sub(r"\x04(T\d+)\x02(.*?)\x03", r'<xref ref-type="table" rid="\1">\2</xref>', s)
    return s


def para_xml(text, refs, floats, where):
    t = link_citations(text, refs, where)
    t = link_floats(t, floats)
    t = link_appendix(t, floats)
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
        # 枠の見出し: `:::fig F1 図1 fig1.png`．番号の言い方が「Fig. 1」のように
        # 空白を含むこともあるので，画像のファイル名を末尾から外し，残りを番号とする
        m = re.match(r"^:::(fig|table|formula)\s+(\S+)(?:\s+(.*?))?\s*$", l)
        if m:
            kind, fid, rest = m.groups()
            label, file = (rest or "").strip(), None
            mf = re.search(r"\s(\S+\.(?:png|jpg|jpeg|gif|tif|tiff))$", " " + label, re.I)
            if mf:
                file = mf.group(1)
                label = label[: len(label) - len(file)].strip()
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

def check_article_id(meta):
    """記事識別子を取り出す．YAML が数として読んでしまった書き方をここで止める．

    YAML 1.1 では下線は数の桁区切りなので，引用符の無い `article_id: 13_193` は
    整数 13193 になり，そのままでは別の記事識別子の XML と zip ができてしまう．
    """
    art_id = meta.get("article_id")
    if isinstance(art_id, (int, float)) and not isinstance(art_id, bool):
        sys.exit(
            f"meta.yaml の article_id が数として読まれている ({art_id!r})．\n"
            "  YAML では下線が桁の区切りなので，引用符の無い 13_193 は 13193 になる．\n"
            "  引用符で囲む:  article_id: '13_193'")
    return str(art_id or f"{meta['volume']}_{meta['fpage']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--pdf")
    args = ap.parse_args()
    work = Path(args.work)
    meta = yaml.safe_load((work / "meta.yaml").read_text(encoding="utf-8"))
    prof = yaml.safe_load((SKILL_DIR / "journals" / f"{meta['journal']}.yaml").read_text(encoding="utf-8"))
    # 節の見出しは号によって言い方が違う (「引用文献」と「文献」)．設定は文字列か，その並びで書ける
    sec_names = {k: ([v] if isinstance(v, str) else list(v)) for k, v in prof["sections"].items()}
    titles = {k: v[0] for k, v in sec_names.items()}   # XML に出す見出しは，原稿にあった文言を使う
    blocks = parse_body(work / "body.md")

    # 特別な節を切り出す
    abstract_ja, ack, ref_lines, main_blocks = [], [], [], []
    mode = "body"
    for b in blocks:
        if b[0] == "h" and b[1] == 1:
            head = sec_head(b[2])
            mode = next((k for k in ("abstract", "ack", "refs")
                         if head in [sec_head(n) for n in sec_names[k]]), "body")
            if mode != "body":
                titles[mode] = b[2]
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
    floats = {b[1]: b[2] for b in main_blocks if b[0] in ("fig", "table", "formula")}
    # 記事識別子は J-STAGE の既存のもの (meta.yaml の article_id) を使う．無ければ「巻_開始ページ」
    art_id = check_article_id(meta)
    out_dir = work / manifest.OUT
    out_dir.mkdir(exist_ok=True)
    if (work / "jstage").is_dir():
        REPORT.append("古い形の出力 jstage/ が残っている (いまは out/ と zip だけを作る)．要らなければ消す")

    names = GraphicNames(art_id)
    body_xml = build_body(main_blocks, refs, floats, work, names)
    front = build_front(meta, prof, abstract_ja, refs, floats)
    back = build_back(ack, refs, titles)
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
    # 旧号ではウェブ版と PDF で並びが全く違うことがある (19(2):113 では 36 件すべてが
    # 添字のずれで「違う」と出ていた)．著者の先頭と年で組にしてから比べる
    def key(t):
        # ウェブ版は「1) BRADFIELD G. E. 題名. 誌名. (1984) vol.55, p.105-114.」の形で，
        # 通し番号が付き，姓が総大文字で，年の位置も違う．番号を外し，大文字小文字も揃える
        n = re.sub(r"^\d+[)）]", "", norm(t)).casefold()
        y = re.search(r"(1[89]|20)\d{2}", n)
        return (n[:5], y.group(0) if y else "")
    rest = list(range(len(web)))
    pair = {}
    for i, p in enumerate(pdf):                 # まず著者の先頭と年が合うものを組にする
        for j in list(rest):
            if key(web[j]) == key(p):
                pair[i] = j
                rest.remove(j)
                break
    for i in range(len(pdf)):                   # 組にならなかったものは，残りを順に当てる
        if i not in pair and rest:
            pair[i] = rest.pop(0)
    # ウェブ版が「1) 著者. 題名. 誌名. (1984) vol.55, p.105-114.」のように
    # 項目ごとに組み直されている号がある (旧号のほとんど)．そのときは並びも書き方も違う
    structured = sum(bool(re.match(r"^\d+[)）]", l)) for l in web) > len(web) / 2

    from collections import Counter

    def words(t):
        n = unicodedata.normalize("NFKC", t).casefold()
        n = re.sub(r"^\s*\d+[)）]", "", n)             # ウェブ版の通し番号
        n = re.sub(r"(?:doi|https?)\S*", "", n)        # ウェブ版だけが持つ DOI・URL
        c = Counter(re.findall(r"[a-z]+|\d+|[^\x00-\x7f\W\d_]", n))
        for w in ("vol", "p", "pp", "no", "in", "and"):  # 組み方の違いで出入りする語
            c.pop(w, None)
        for w in [w for w in c if len(w) == 1 and w.isascii()]:
            c.pop(w)                                  # イニシャル (ウェブ版は落とすことがある)
        return c

    content, form = 0, 0
    for k in range(len(pdf)):
        if k not in pair:
            continue
        w, p = web[pair[k]], pdf[k]
        if w == p:
            continue
        if norm(w) == norm(p):
            form += 1
            continue
        if structured:
            # ウェブ版が項目ごとに組み直された形のときは，字の並びで比べても意味が無い
            # (年や巻の位置が違う)．語の多重集合で比べ，片方にしかない語だけを出す
            miss = words(w) - words(p)
            extra = words(p) - words(w)
            if not miss and not extra:
                form += 1
                continue
            content += 1
            REPORT.append(f"引用文献がウェブ版と違う: B{k + 1} "
                          + (f"ウェブにだけある語「{'・'.join(sorted(miss)[:5])}」" if miss else "")
                          + (f" PDF にだけある語「{'・'.join(sorted(extra)[:5])}」" if extra else ""))
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
    # 続きの部分は「table2_2.png」のように番号を付ける．番号でないものは確かめ用の切り出しとみて外す
    rest = sorted((p for p in dir_.glob(f"{stem}_*.png") if p.stem.split("_")[-1].isdigit()),
                  key=lambda p: int(p.stem.split("_")[-1]))
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
            out.append(f"<sec><title>{title_xml(b[2], floats)}</title>")
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

    # 訂正記事のように著者の無い記事では contrib-group を出さない (空だと DTD に合わない)
    has_contrib = bool(meta["authors"]) or bool(meta["affiliations"])
    if has_contrib:
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
                         f'<country country="{af.get("country", "JP")}">'
                         f'{country_name(af.get("country", "JP"), lg)}</country></aff>')
        o.append("</aff-alternatives>")
    if has_contrib:
        o.append("</contrib-group>")

    # 著者の脚注 (「現所属」「Present address」など)．meta.yaml の author_notes に書く
    notes = meta.get("author_notes") or []
    if notes:
        o.append("<author-notes>")
        for n in notes:
            ft = f' fn-type="{attr(n["type"])}"' if n.get("type") else ""
            o.append(f"<fn{ft}>")
            for lg in ("ja", "en"):
                if n.get(lg):
                    o.append(f'<p xml:lang="{lg}">{inline(esc(n[lg]))}</p>')
            o.append("</fn>")
        o.append("</author-notes>")

    pd = meta.get("pub_date") or {}
    if pd.get("ppub"):
        o.append(date_xml("pub-date", 'pub-type="ppub"', pd["ppub"]))
    if pd.get("epub"):
        o.append(date_xml("pub-date", 'pub-type="epub"', pd["epub"]))
    o.append(f"<volume>{esc(str(meta['volume']))}</volume><issue>{esc(str(meta['issue']))}</issue>")
    # 1ページだけの記事 (訂正など) は lpage が無いので，fpage と同じにする
    lp = meta.get("lpage") or meta["fpage"]
    o.append(f"<fpage>{esc(str(meta['fpage']))}</fpage><lpage>{esc(str(lp))}</lpage>")
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
    # meta.yaml の要旨は，改行で段落に分ける (紙面が段落を分けている要旨があるため．16(1):1)．
    # 和文は body.md の「# 摘要」があればそちらを使う (段落がそのまま残っているので)
    def ab_paras(lg):
        return [x.strip() for x in re.split(r"\n\s*", ab.get(lg) or "") if x.strip()]

    def paras_of(lg):
        # 和文の摘要は body.md にあればそちらを使う．英文の論文でも同じ
        # (それまでは英文の論文だと J-STAGE 登録版の1段落が使われていた．16(1):1)
        return abstract_ja if lg == "ja" and abstract_ja else ab_paras(lg)

    paras = paras_of(lang)
    if paras:
        o.append(f'<abstract xml:lang="{lang}">' + "".join(f"<p>{inline(esc(p))}</p>" for p in paras) + "</abstract>")
    op = paras_of(other)
    if op:
        o.append(f'<trans-abstract xml:lang="{other}">'
                 + "".join(f"<p>{inline(esc(x))}</p>" for x in op) + "</trans-abstract>")
    for lg in ("ja", "en"):
        kws = (meta.get("keywords") or {}).get(lg) or []
        if kws:
            o.append(f'<kwd-group kwd-group-type="author" xml:lang="{lg}">'
                     + "".join(f"<kwd>{inline(esc(k))}</kwd>" for k in kws) + "</kwd-group>")
    o += ["</article-meta>", "</front>"]
    return "\n".join(o)


# 国名 (所属に country: を書いたときに使う．無い国は符号をそのまま出す)
COUNTRIES = {"JP": ("日本", "Japan"), "NP": ("ネパール", "Nepal"), "US": ("アメリカ合衆国", "USA"),
             "GB": ("イギリス", "UK"), "CN": ("中国", "China"), "KR": ("韓国", "Korea"),
             "RU": ("ロシア", "Russia"), "DE": ("ドイツ", "Germany"), "FR": ("フランス", "France"),
             "AU": ("オーストラリア", "Australia"), "TW": ("台湾", "Taiwan")}


def country_name(code, lang):
    ja, en = COUNTRIES.get(code, (code, code))
    return ja if lang == "ja" else en


def build_back(ack, refs, titles):
    o = ["<back>"]
    if ack:
        o.append(f"<ack><title>{esc(titles['ack'])}</title>" + "".join(f"<p>{inline(esc(p))}</p>" for p in ack) + "</ack>")
    if refs:
        o.append(f"<ref-list><title>{esc(titles['refs'])}</title>")
        o += [r.to_xml() for r in refs]
        o.append("</ref-list>")
    o.append("</back>")
    return "\n".join(o)


if __name__ == "__main__":
    sys.exit(main())
