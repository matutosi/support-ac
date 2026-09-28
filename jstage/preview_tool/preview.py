"""J-STAGE の全文 XML (JATS 1.1，FULL-J) から，J-STAGE の全文 HTML 画面に似せたプレビューを作る．

J-STAGE に上げてプレビューするのは時間がかかるので，手元で見た目と中身を確かめるためのもの．
公式の検証 (全文 XML 作成ツールの「XML 検証」，編集登載のプレビュー) の代わりにはならない．

使い方:
    python preview.py <入力> [<入力> ...] [--out <出力先>] [--lang ja|en] [--jstage-css <フォルダ>] [--open]

    入力は次のどれでもよい．
      - 記事の zip (build.py の <記事識別子>.zip)・まとめた zip (vegsci.zip)・記事ダウンロードの zip
      - 作業ディレクトリ (jstage/work/<巻>/<開始ページ>/．中の <記事識別子>.zip を使う)
      - XML (画像は同じフォルダの Graphics/ から探す)

出力: <出力先>/<記事識別子>/index.html と Graphics/ (既定の出力先は preview_tool/out/)．
      記事が複数あれば <出力先>/index.html に一覧を作る．

HTML の組み方は，J-STAGE が XML から作った全文 HTML (記事ダウンロードの zip の <記事識別子>.html．
植生学会誌 43(1):1 で確かめた) に合わせ，クラス名も同じにしてある．見出し部分 (原稿種別・題名・著者・
巻号・DOI・日付) は J-STAGE の記事ページ (全文) の組み方をまねた．
J-STAGE の CSS は `--jstage-css` で渡すか，_sample/ に保存したページがあれば自動で使う (写さず参照する)．
無いときは同じフォルダの preview.css だけで表示する．

J-STAGE の画面には出ないもの (キーワード・カナ・license など) と，リンク先の無い引用・画像の欠けなどは，
ページの先頭の「プレビューの点検」の枠に出す．
"""
import argparse
import datetime
import html
import os
import re
import sys
import webbrowser
import zipfile
from pathlib import Path

from lxml import etree

HERE = Path(__file__).resolve().parent
XLINK = "{http://www.w3.org/1999/xlink}href"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
MML = "http://www.w3.org/1998/Math/MathML"
PARSER = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False, recover=False)

# J-STAGE の CSS (保存したページの _files にあるもの) のうち，全文 HTML の見た目に要るもの
JSTAGE_CSS = ["bootstrap_fullhtml.min.css", "style.css", "common-elements-style.css", "main.css"]

WORDS = {
    "ja": dict(author_info="著者情報", details="詳細", journal="ジャーナル", free="フリー",
               ppub="発行日", received="受付日", epub="J-STAGE公開日", accepted="受理日",
               early="早期公開日", revised="改訂日", corresp="責任著者",
               issue=lambda y, v, i, f, l: f"{y} 年 {v} 巻 {i} 号 p. {f}-{l}" if l and l != f else f"{y} 年 {v} 巻 {i} 号 p. {f}"),
    "en": dict(author_info="Author information", details="Details", journal="JOURNAL", free="FREE ACCESS",
               ppub="Published", received="Received", epub="Released on J-STAGE", accepted="Accepted",
               early="Advance online publication", revised="Revised", corresp="Corresponding author",
               issue=lambda y, v, i, f, l: f"{y} Volume {v} Issue {i} Pages {f}-{l}" if l and l != f else f"{y} Volume {v} Issue {i} Page {f}"),
}


def esc(s):
    return html.escape(s or "", quote=False)


def ws(s, keep=False):
    """XML の字下げ (改行と，その後ろの空白) を捨てる．改行の前の空白は残す．J-STAGE の全文 HTML と同じ扱い
    (43(1):1 で「(\\n   <xref>」は「(Suzuki」，「of \\n   <xref>」は「of Numata」，
    43(1):79 で「<italic>WL<sub>i</sub>\\n  </italic>は」は「WLiは」になる)．
    ただし <ext-link> の中の，空白だけで改行を含む部分は空白 1 つになる (keep．J-STAGE は字下げを残す．
    43(1):55 の「oblongifolia</italic>\\n\\t</ext-link>，」が「oblongifolia ，」)．"""
    if not s:
        return s
    if keep and not s.strip() and "\n" in s:
        return " "
    # 「</italic> \\n   <italic>」の改行の前の空白は残る (43(1):55 の「Carex lasiocarpa」)
    return re.sub(r"\r?\n[ \t]*", "", s)


def attr(s):
    return html.escape(s or "", quote=True)


def lang_of(e, default=None):
    while e is not None:
        if e.get(XML_LANG):
            return e.get(XML_LANG)
        e = e.getparent()
    return default


def local(e):
    return etree.QName(e).localname if isinstance(e.tag, str) else ""


def plain(e):
    """要素の文字 (DOI の <pub-id> を除く)．"""
    if e is None:
        return ""
    return re.sub(r"\s+", " ", "".join(e.xpath(".//text()[not(ancestor::pub-id)]"))).strip()


# ================================================================ 入力を読む

class Article:
    """1本の記事: XML の木と，画像の名前 → バイト列．"""

    def __init__(self, name, xml_bytes, images, source):
        self.name, self.source, self.images = name, source, images
        self.root = etree.fromstring(xml_bytes, PARSER)
        self.id = name
        self.am = self.root.find("front/article-meta")


def read_zip(path):
    """zip の中の <資料コード>/<巻>/<号>/<記事識別子>/<記事識別子>.xml を記事として読む．"""
    out = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        for n in names:
            m = re.search(r"(?:^|/)([^/]+)/\1\.xml$", n)
            if not m:
                continue
            art = m.group(1)
            base = n[: -len(f"{art}.xml")]
            imgs = {Path(g).name: z.read(g) for g in names
                    if g.startswith(base + "Graphics/") and not g.endswith("/")}
            out.append(Article(art, z.read(n), imgs, f"{path} : {n}"))
    return out


def read_input(p):
    p = Path(p)
    if p.is_dir():
        zips = [z for z in p.glob("*.zip")]
        if zips:
            return [a for z in zips for a in read_zip(z)]
        xmls = list((p / "out").glob("*.xml")) or list(p.glob("*.xml"))
        return [a for x in xmls for a in read_input(x)]
    if p.suffix.lower() == ".zip":
        return read_zip(p)
    if p.suffix.lower() == ".xml":
        g = p.parent / "Graphics"
        imgs = {f.name: f.read_bytes() for f in g.glob("*")} if g.is_dir() else {}
        return [Article(p.stem, p.read_bytes(), imgs, str(p))]
    sys.exit(f"読めない入力: {p} (zip・作業ディレクトリ・XML のどれか)")


# ================================================================ 本文を HTML にする

class Renderer:
    def __init__(self, art, page_lang):
        self.art, self.lang = art, page_lang
        self.root = art.root
        self.ids = {e.get("id") for e in self.root.iter() if isinstance(e.tag, str) and e.get("id")}
        self.refs = {r.get("id"): r for r in self.root.xpath("//ref-list/ref")}
        self.warn = []            # 点検の枠に出す警告
        self.notes = []           # 点検の枠に出す注意 (警告ほどではないもの)
        self.unknown = set()      # 対応していない要素
        self.cited = set()        # 本文から引かれた id
        self.floats = []          # (id, ラベル, キャプションの HTML, 画像) … 末尾の Figures の一覧
        self.nav = []             # (href, 見出し) … 左の目次

    # ---------------------------------------------------------------- 行内
    def inline(self, e, in_ref=False):
        """要素の中身 (文字と子要素) を HTML にする．e 自身のタグは出さない．"""
        keep = local(e) == "ext-link"
        out = [esc(ws(e.text, keep))]
        for c in e:
            out.append(self.inline_el(c, in_ref))
            out.append(esc(ws(c.tail, keep)))
        return "".join(out)

    def inline_el(self, c, in_ref=False):
        if not isinstance(c.tag, str):          # コメント・処理命令
            return ""
        t = local(c)
        simple = {"italic": "i", "bold": "b", "sup": "sup", "sub": "sub", "underline": "u", "monospace": "code"}
        if t in simple:
            h = simple[t]
            return f"<{h}>{self.inline(c, in_ref)}</{h}>"
        if t == "sc":
            return f'<span style="font-variant:small-caps">{self.inline(c, in_ref)}</span>'
        if t == "break":
            return "<br>"
        if t == "xref":
            return self.xref(c)
        if t in ("ext-link", "uri"):
            href = c.get(XLINK) or plain(c)
            if c.get("ext-link-type") == "doi" and not href.startswith("http"):
                href = "https://doi.org/" + href
            return f'<a href="{attr(href)}" class="bluelink-style" target="_blank" rel="noopener">{self.inline(c, in_ref)}</a>'
        if t == "inline-formula":
            return self.inline(c, in_ref)
        if c.tag == f"{{{MML}}}math":
            return self.mathml(c)
        if t == "inline-graphic":
            return self.img(c.get(XLINK), inline=True)
        if t == "pub-id":
            return ""                           # 文献の DOI は ref の側で扱う
        if t in ("named-content", "styled-content", "string-name", "person-group", "surname", "given-names",
                 "prefix", "suffix", "collab", "article-title", "source", "year", "volume", "issue", "fpage",
                 "lpage", "publisher-name", "publisher-loc", "edition", "chapter-title", "etal", "comment",
                 "part-title", "trans-title", "trans-source", "date-in-citation", "page-range", "size",
                 "institution", "country", "addr-line", "email", "abbrev", "title", "label", "caption", "p"):
            return self.inline(c, in_ref)
        self.unknown.add(t)
        return self.inline(c, in_ref)

    def mathml(self, m):
        # MathML の中の字下げはそのまま残す (J-STAGE も残している．43(1):1・23)
        s = etree.tostring(m, encoding="unicode", with_tail=False)
        # 名前空間の接頭辞 (mml:) を外し，HTML に直接書ける <math> にする
        s = re.sub(r"<(/?)mml:", r"<\1", s)
        s = re.sub(r'\sxmlns:mml="[^"]*"', "", s)
        if "xmlns=" not in s[:80]:
            s = s.replace("<math", f'<math xmlns="{MML}"', 1)
        return s

    def xref(self, x):
        rid, rt = x.get("rid", ""), x.get("ref-type", "")
        body = self.inline(x)
        missing = [r for r in rid.split() if r not in self.ids]
        if missing or not rid:
            self.warn.append(f"リンク先の無い引用: 「{plain(x)}」→ {rid or '(rid なし)'}")
            return f'<span class="pv-broken" title="リンク先が無い: {attr(rid)}">{body}</span>'
        first = rid.split()[0]
        self.cited.update(rid.split())
        tip = ""
        if rt == "bibr" and first in self.refs:
            tip = f' title="{attr("<p>&nbsp;&nbsp;" + esc(plain(self.refs[first].find("mixed-citation"))) + "</p>")}"'
        return (f'<a href="#{attr(first)}" class="global-para-14 bluelink-style"{tip} '
                f'data-html="true" data-placement="bottom" data-toggle="tooltip">{body}</a>')

    def img(self, href, inline=False):
        name = Path(href or "").name
        if name not in self.art.images:
            self.warn.append(f"画像が無い: {href}")
            return f'<span class="pv-broken">[画像が無い: {esc(href)}]</span>'
        cls = ' class="pv-inline-graphic"' if inline else ""
        return f'<img src="./Graphics/{attr(name)}"{cls} alt="{attr(name)}">'

    # ---------------------------------------------------------------- 段落などの塊
    BLOCKS = {"fig", "table-wrap", "disp-formula", "list", "disp-quote", "boxed-text", "fig-group",
              "table-wrap-group", "def-list", "graphic", "preformat", "statement"}

    def para(self, p):
        """<p>．中に図や式などの塊があれば，そこで段落を切って塊を別に出す．"""
        out, cur = [], [esc(ws(p.text))]
        has_block = any(isinstance(c.tag, str) and local(c) in self.BLOCKS for c in p)

        def flush():
            # 空の <p/> も J-STAGE は空の段落として出す (43(1):23・55・79)．塊で切った残りの空は出さない
            if "".join(cur).strip() or not has_block:
                out.append(f'<p class="global-para-14 fj-sec-p">{"".join(cur)}</p>')

        for c in p:
            if isinstance(c.tag, str) and local(c) in self.BLOCKS:
                flush()
                cur = []
                out.append(self.block(c))
                cur.append(esc(ws(c.tail)))
            else:
                cur.append(self.inline_el(c))
                cur.append(esc(ws(c.tail)))
        flush()
        return "\n".join(out)

    def block(self, e, level=1, num=None):
        t = local(e)
        if t == "p":
            return self.para(e)
        if t == "sec":
            return self.sec(e, level, num)
        if t == "fig":
            return self.fig(e)
        if t == "table-wrap":
            return self.table_wrap(e)
        if t == "disp-formula":
            return self.formula(e)
        if t == "list":
            return self.list_(e)
        if t == "disp-quote":
            # J-STAGE は <blockquote><p> で，本文の段落のクラスは付けない (43(1):45)
            return "<blockquote>" + "".join(
                f"<p>{self.inline(c)}</p>" if local(c) == "p" else self.block(c)
                for c in e if isinstance(c.tag, str)) + "</blockquote>"
        if t == "boxed-text":
            return '<div class="pv-boxed">' + "".join(self.block(c) for c in e if isinstance(c.tag, str)) + "</div>"
        if t in ("fig-group", "table-wrap-group"):
            return "".join(self.block(c) for c in e if isinstance(c.tag, str) and local(c) not in ("label", "caption"))
        if t == "graphic":
            return f'<div class="global-image-holder overview-landing-limg">{self.img(e.get(XLINK))}</div>'
        if t in ("title", "label"):
            return ""
        if t == "fn-group":
            return "".join(f'<p class="global-para-14 fj-sec-p pv-fn">{self.inline(p)}</p>'
                           for fn in e.findall("fn") for p in fn.findall("p"))
        self.unknown.add(t)
        return f'<p class="global-para-14 fj-sec-p">{self.inline(e)}</p>'

    def sec(self, s, level, num):
        """節．大見出しは section-title-18，小見出しは太字の行 (J-STAGE の組み方)．"""
        title = s.find("title")
        label = s.find("label")
        head = (self.inline(label) + " " if label is not None else "") + (self.inline(title) if title is not None else "")
        sid = s.get("id", "")
        out = []
        if level == 1:
            anchor = f"sec{num:02d}"
            self.nav.append((f"#{anchor}", plain(title) if title is not None else anchor))
            out.append(f'<div id="{anchor}"><span id="{attr(sid)}"></span><p class="global-para-14"></p>'
                       f'<div class="section-title-18">{head}</div>')
        else:
            anchor = f"sec{num}"
            size = "font-size14" if level == 2 else "font-size14 pv-level3"
            out.append(f'<p class="global-para-14"></p><span id="{attr(sid)}"></span>'
                       f'<span class="global-bold-txt {size} span-block bottom-margin-1" id="{anchor}">{head}</span>')
        k = 0
        for c in s:
            if not isinstance(c.tag, str) or local(c) in ("title", "label"):
                continue
            if local(c) == "sec":
                k += 1
                sub = f"{num:02d}{k:02d}" if level == 1 else f"{num}{k:02d}"
                out.append(self.sec(c, level + 1, sub))
            else:
                out.append(self.block(c, level))
        if level == 1:
            out.append("</div>")
        return "\n".join(out)

    def caption(self, e):
        """<label> と <caption> を「ラベル. キャプション」の1段落にする (43(1) の図の説明と同じ見た目)．"""
        label, cap = e.find("label"), e.find("caption")
        parts = []
        if cap is not None:
            ct = cap.find("title")
            if ct is not None:
                parts.append(self.inline(ct))
            parts += [self.inline(p) for p in cap.findall("p")]
        lab = f"<b>{self.inline(label)}</b>" if label is not None else ""
        text = " ".join(x for x in parts if x.strip())
        if not lab and not text:
            return "", ""
        return lab, f'<p class="pv-caption">{lab}{" " if lab and text else ""}{text}</p>'

    def fig(self, f):
        fid = f.get("id", "")
        lab, cap = self.caption(f)
        g = f.find(".//graphic")
        img = self.img(g.get(XLINK)) if g is not None else '<span class="pv-broken">[graphic が無い]</span>'
        # 43(1) のように図の説明を <fig> の中の <p> で書いたもの
        ps = "".join(f"<p>{self.inline(p)}</p>" for p in f.findall("p"))
        self.floats.append((fid, plain(f.find("label")) or fid, cap or ps, img))
        return (f'<div class="global-image-holder overview-landing-limg" id="{attr(fid)}">{img}'
                f'<div class="figures-tables-support-txt"></div></div>\n{cap}{ps}')

    def table_wrap(self, t):
        tid = t.get("id", "")
        lab, cap = self.caption(t)
        inner = []
        for c in t:
            if not isinstance(c.tag, str):
                continue
            n = local(c)
            if n == "table":
                inner.append(self.table(c))
            elif n == "graphic":
                inner.append(self.img(c.get(XLINK)))
            elif n == "alternatives":
                tb = c.find("table")
                inner.append(self.table(tb) if tb is not None else self.img((c.find("graphic") or c).get(XLINK)))
            elif n == "table-wrap-foot":
                inner.append('<div class="pv-table-foot">' + "".join(
                    f"<p>{self.inline(p)}</p>" for p in c.iter("p")) + "</div>")
        self.floats.append((tid, plain(t.find("label")) or tid, cap, "".join(inner)))
        # 表は表題を上に出す (余白は図のキャプションと別)
        cap = cap.replace('class="pv-caption"', 'class="pv-caption pv-caption-top"', 1)
        return (f'{cap}<div class="global-image-holder overview-landing-limg pv-table" id="{attr(tid)}">'
                f'{"".join(inner)}<div class="figures-tables-support-txt"></div></div>')

    def table(self, tb):
        def cell(c):
            a = "".join(f' {k}="{attr(c.get(k))}"' for k in ("colspan", "rowspan", "align", "valign") if c.get(k))
            return f"<{local(c)}{a}>{self.inline(c)}</{local(c)}>"
        rows = []
        for part in tb:
            if not isinstance(part.tag, str):
                continue
            pn = local(part)
            trs = part.findall("tr") if pn in ("thead", "tbody", "tfoot") else ([part] if pn == "tr" else [])
            body = "".join("<tr>" + "".join(cell(c) for c in tr if isinstance(c.tag, str)) + "</tr>" for tr in trs)
            if pn in ("thead", "tbody", "tfoot"):
                rows.append(f"<{pn}>{body}</{pn}>")
            else:
                rows.append(body)
        return f'<table class="table pv-data-table">{"".join(rows)}</table>'

    def formula(self, f):
        label = f.find("label")
        g = f.find(".//graphic")
        m = f.find(f".//{{{MML}}}math")
        body = self.img(g.get(XLINK)) if g is not None else (self.mathml(m) if m is not None else self.inline(f))
        lab = f'<span class="pv-formula-label">{self.inline(label)}</span>' if label is not None else ""
        return f'<div class="pv-formula" id="{attr(f.get("id", ""))}"><span class="pv-formula-body">{body}</span>{lab}</div>'

    def list_(self, l):
        tag = "ol" if l.get("list-type") in ("order", "arabic", "roman-lower", "roman-upper", "alpha-lower", "alpha-upper") else "ul"
        items = []
        for it in l.findall("list-item"):
            lab = it.find("label")
            ps = " ".join(self.inline(p) for p in it.findall("p"))
            items.append(f"<li>{(self.inline(lab) + ' ') if lab is not None else ''}{ps}</li>")
        style = ' style="list-style:none"' if l.get("list-type") in (None, "simple") and tag == "ul" else ""
        return f'<{tag} class="global-para-14"{style}>{"".join(items)}</{tag}>'

    # ---------------------------------------------------------------- 文献
    def reflist(self, rl, head):
        refs = rl.findall("ref")
        items = []
        for r in refs:
            mc = r.find("mixed-citation")
            if mc is None:
                mc = r.find("element-citation")
            text = self.inline(mc, in_ref=True) if mc is not None else ""
            text = re.sub(r"\s+", " ", text).strip()
            lab = r.find("label")
            num = esc(plain(lab)) if lab is not None else ""
            doi = r.find(".//pub-id[@pub-id-type='doi']")
            span = (f'<span class="reference-num-sequence">{num}</span>'
                    f'<span class="reference-num-txt">&nbsp;{text}</span>')
            if doi is not None:
                d = plain(doi)
                span = (f'<a href="https://doi.org/{attr(d)}" target="_blank" rel="noopener noreferrer" '
                        f'title="DOI: {attr(d)} (J-STAGE では公開後の原文問合わせでリンクが付く)">{span}</a>')
            items.append(f'<li id="{attr(r.get("id", ""))}">{span}<div class="clearfix"></div></li>')
        # 入れ子の <ref-list> の段落 (文献一覧の末尾の注記)
        notes = "".join(f'<p class="global-para-14 fj-sec-p">{self.inline(p)}</p>'
                        for sub in rl.findall("ref-list") for p in sub.findall("p"))
        return (f'<div id="article-overiew-references-wrap"><div class="section-title-18">{head}</div>'
                f'<ul id="article-overview-references-list">{"".join(items)}</ul>{notes}</div>'), len(refs)


# ================================================================ ページ全体

def pick(elems, lang):
    """言語の合うものを優先して1つ選ぶ．"""
    elems = [e for e in elems if e is not None]
    for e in elems:
        if lang_of(e) == lang:
            return e
    return elems[0] if elems else None


def date_str(d):
    if d is None:
        return "-"
    y, m, dd = (plain(d.find(k)) for k in ("year", "month", "day"))
    if not y:
        return "-"
    return "/".join(x.zfill(2) if i else x for i, x in enumerate([y, m, dd]) if x)


def build_page(art, page_lang, css_links, base_css):
    r = Renderer(art, page_lang)
    W = WORDS[page_lang]
    root, am = art.root, art.am
    alang = root.get(XML_LANG) or "ja"
    jm = root.find("front/journal-meta")

    # ---- 見出し部分
    jt = pick(jm.findall(".//journal-title") + jm.findall(".//trans-title"), page_lang)
    issn = {i.get("pub-type"): plain(i) for i in jm.findall("issn")}
    cat = pick([s.find("subject") for s in am.findall("article-categories/subj-group")], page_lang)
    # 題名は画面の言語のものを出す (日本語の画面では英文の論文でも和文の題名．43(1):1)
    titles = [am.find("title-group/article-title")] + am.findall("title-group/trans-title-group/trans-title")
    for t in titles:
        if t is not None and lang_of(t) is None:
            t.set(XML_LANG, alang)
    title = pick(titles, page_lang)

    affs = {}
    for aa in am.findall("contrib-group/aff-alternatives") + am.findall("contrib-group/aff") + am.findall("aff"):
        aid = aa.get("id")
        alts = aa.findall("aff") if local(aa) == "aff-alternatives" else [aa]
        # 画面の言語の所属が空 (43(1):1 の <aff xml:lang="ja"/>) なら，もう一方の言語のものを出す
        alts = [a for a in alts if (plain(a.find("institution")) or plain(a))]
        a = pick(alts, page_lang)
        if a is not None:
            affs[aid] = plain(a.find("institution")) or plain(a)
    authors, info = [], []
    for c in am.findall("contrib-group/contrib"):
        names = c.findall("name-alternatives/name") + c.findall("name") + c.findall("collab")
        nm = pick([n for n in names if lang_of(n) in ("ja", "en", None)], page_lang)
        if nm is None:
            continue
        if local(nm) == "collab":
            label = plain(nm)
        elif lang_of(nm) == "ja" or nm.get("name-style") == "eastern":
            label = f"{plain(nm.find('surname'))} {plain(nm.find('given-names'))}".strip()
        else:
            label = f"{plain(nm.find('given-names'))} {plain(nm.find('surname'))}".strip()
        # 責任著者: corresp="yes"，著者の中の E-mail (43(1):1)，または <corresp> への xref
        corr = (c.get("corresp") == "yes" or c.find(".//email") is not None
                or c.find("xref[@ref-type='corresp']") is not None)
        mail = ' <span class="pv-mail" title="' + attr(W["corresp"]) + '">✉</span>' if corr else ""
        a_list = [affs.get(x.get("rid"), f"[所属 {x.get('rid')} が無い]") for x in c.findall("xref[@ref-type='aff']")]
        authors.append(f'<a class="customTooltip" title="{attr(label + ", " + "; ".join(a_list))}"><span>{esc(label)}</span></a>{mail}')
        info.append(f'<li><span style="font-size:1.1em">{esc(label)}</span>'
                    + (f' <span class="pv-mail">✉ {esc(W["corresp"])}</span>' if corr else "")
                    + f'<p class="accordion_affilinfo">{"<br>".join(esc(a) for a in a_list)}</p></li>')

    vol, iss = plain(am.find("volume")), plain(am.find("issue"))
    fp, lp = plain(am.find("fpage")), plain(am.find("lpage"))
    ppub = pick(am.findall("pub-date[@pub-type='ppub']"), page_lang)
    epub = am.find("pub-date[@pub-type='epub']")
    year = plain(ppub.find("year")) if ppub is not None else ""
    doi = plain(am.find("article-id[@pub-id-type='doi']"))
    hist = {d.get("date-type"): d for d in am.findall("history/date")}

    header = f"""
<div class="journal-name">{esc(plain(jt))}</div>
<div class="fs-12 pv-issn">Online ISSN : {esc(issn.get('epub', ''))} &nbsp; Print ISSN : {esc(issn.get('ppub', ''))}</div>
<div class="top-margin-2x bottom-margin-2x"></div>
<div class="global-article-subtitle">{esc(plain(cat)) if cat is not None else ''}</div>
<div class="global-article-title">{r.inline(title) if title is not None else ''}</div>
<div class="global-authors-name-tags">{',&nbsp;'.join(authors)}
<details class="accordion_container" open><summary class="accordion_head">{W['author_info']}</summary>
<ul class="accodion_body_ul">{''.join(info)}</ul></details></div>
<div class="global-tags"><span class="tags-wrap original-tag-style">{W['journal']}</span>
<span class="tags-wrap freeaccess-tag-style">{W['free']}</span>
<span class="tags-wrap fulltext-tag-style">HTML</span></div>
<p class="global-para">{esc(W['issue'](year, vol, iss, fp, lp))}</p>
<div class="articleoverview-doi-wrap"><span class="doi-icn">DOI</span>
<a href="https://doi.org/{attr(doi)}" class="bluelink-style">https://doi.org/{esc(doi)}</a></div>
<details class="accordion_container"><summary class="accordion_head">{W['details']}</summary>
<ul class="accodion_body_ul accodion_detail"><li>
<span class="accodion_lic">{W['ppub']}: {date_str(ppub)}</span>
<span class="accodion_lic">{W['received']}: {date_str(hist.get('received'))}</span>
<span class="accodion_lic">{W['epub']}: {date_str(epub)}</span>
<span class="accodion_lic">{W['accepted']}: {date_str(hist.get('accepted'))}</span>
<span class="accodion_lic">{W['early']}: -</span>
<span class="accodion_lic">{W['revised']}: {date_str(hist.get('rev-recd'))}</span>
</li></ul></details>"""

    # ---- 抄録
    main = []
    for kind, e in [("abstract", x) for x in am.findall("abstract")] + [("trans", x) for x in am.findall("trans-abstract")]:
        lg = lang_of(e, alang)
        head = "要約" if lg == "ja" else "Abstract"
        wid = "abstract" if kind == "abstract" else "trans-abstract-wrap"
        if any(wid == h[1:] for h, _ in r.nav):
            wid += f"-{lg}"
        r.nav.append((f"#{wid}", head))
        paras = "".join(r.block(c) for c in e if isinstance(c.tag, str) and local(c) != "title")
        main.append(f'<div id="{wid}"><div class="section-title-18">{head}</div>{paras}</div>')

    # ---- 本文
    body = root.find("body")
    if body is not None:
        n = 0
        for c in body:
            if not isinstance(c.tag, str):
                continue
            if local(c) == "sec":
                n += 1
                main.append(r.sec(c, 1, n))
            else:
                main.append(r.block(c))
    else:
        r.warn.append("<body> が無い (書誌だけの XML)")

    # ---- 後付け: 謝辞・付録・脚注・文献
    back = root.find("back")
    nref = 0
    refs_html = []            # 文献は XML の並びによらず最後に出す (J-STAGE は謝辞を文献の前に出す．43(1):79)
    if back is not None:
        for c in back:
            if not isinstance(c.tag, str):
                continue
            t = local(c)
            if t == "ack":
                ti = c.find("title")
                head = r.inline(ti) if ti is not None else ("謝辞" if alang == "ja" else "Acknowledgments")
                r.nav.append(("#ack", plain(ti) if ti is not None else head))
                main.append(f'<div id="ack"><div class="section-title-18">{head}</div>'
                            + "".join(r.block(p) for p in c if isinstance(p.tag, str) and local(p) != "title") + "</div>")
            elif t == "app-group" or t == "app":
                apps = c.findall("app") if t == "app-group" else [c]
                for i, a in enumerate(apps, 1):
                    main.append(r.sec(a, 1, 90 + i))
            elif t == "fn-group":
                main.append('<div id="fn">' + r.block(c) + "</div>")
            elif t == "ref-list":
                refs_html.append(c)
            else:
                r.unknown.add(f"back/{t}")
    for c in refs_html:
        # 見出しは文献の多数の言語で決まる (XML の <title> は使われない．43(1) の 7 本で確かめた:
        # 和文が多ければ「引用文献」，英文が多ければ「References」．和文の論文 43(1):79 は英文 12・和文 10 で References)
        langs = [x.get(XML_LANG) for x in c.findall("ref")]
        ja = langs.count("ja") > langs.count("en")
        html_refs, nref = r.reflist(c, "引用文献" if ja else "References")
        r.nav.append(("#article-overiew-references-wrap", f"引用文献({nref})" if ja else f"Reference&nbsp;List({nref})"))
        main.append(html_refs)
        xt = c.find("title")
        if xt is not None and plain(xt) != ("引用文献" if ja else "References"):
            r.notes.append(f"文献の見出し: XML の「{plain(xt)}」ではなく「{'引用文献' if ja else 'References'}」と出る見込み "
                           "(J-STAGE は文献の多数の言語で決める．XML に題がある場合は未確認)")

    # ---- 図表の一覧 (J-STAGE では JS が作る)．1 列に並べる．
    # 見出しは記事の言語で決まる: 日本語の記事は「図」，英語の記事は「Figures」(43(1):1 は英語の記事で「Figures (10)」)
    if r.floats:
        figs = "図" if alang == "ja" else "Figures"
        r.nav.append(("#figures-tables-wrap", f"{figs} ({len(r.floats)})"))
        cards = "".join(f'<div class="pv-float-card"><a href="#{attr(fid)}">{img}</a>{cap}</div>'
                        for fid, lab, cap, img in r.floats)
        main.append(f'<div id="figures-tables-wrap"><div class="section-title-noborder-18">'
                    f'{figs}</div><div class="pv-float-grid">{cards}</div></div>')

    # ---- 点検 (J-STAGE の画面に出ない項目と警告)
    check = check_panel(art, r, page_lang)

    nav_items = "".join(
        (('<p class="divider-solid-bottom"></p>' if h == "#article-overiew-references-wrap" else "")
         + f'<li><div><a class="customTooltip bluelink-style anchorLink" href="{attr(h)}">{t if "&nbsp;" in t else esc(t)}</a></div></li>')
        for h, t in r.nav)
    fragment = (f'<div class="clearfix container pv-fulltext"><div id="sticky-sidebar"><div id="article-overiew-header" '
                f'class="section-title-14">&nbsp;</div><nav id="article-overiew-section-links"><ul id="article-overiew-section-list">'
                f'{nav_items}</ul></nav></div><div class="non-sticky-content" id="article-overiew-abstract-wrap">'
                + "\n".join(main) + "</div></div>")

    css = "\n".join(f'<link rel="stylesheet" href="{attr(h)}">' for h in css_links)
    page_title = plain(title) if title is not None else art.id
    return f"""<!DOCTYPE html>
<html lang="{page_lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>[プレビュー] {esc(page_title)}</title>
{css}
<style>{base_css}</style>
</head><body class="{'pv-with-jstage' if css_links else 'pv-plain'}">
<div class="pv-banner">プレビュー (手元で作ったもの．J-STAGE の画面ではない) — {esc(art.id)}</div>
<div class="container pv-page">
{check}
<div class="row"><div class="col-md-18 pv-head">{header}</div></div>
{fragment}
</div></body></html>
"""


def check_panel(art, r, page_lang):
    am, root = art.am, art.root
    rows = []

    def row(k, v):
        rows.append(f"<tr><th>{esc(k)}</th><td>{v}</td></tr>")

    row("入力", esc(art.source))
    row("記事識別子", esc(art.id))
    ids = ", ".join(f"{i.get('pub-id-type')}: {esc(plain(i))}" for i in am.findall("article-id"))
    row("記事の ID", ids)
    row("article-type", esc(root.get("article-type")))
    row("原稿種別", " / ".join(esc(plain(s.find("subject"))) + f" ({s.get(XML_LANG)})"
                          for s in am.findall("article-categories/subj-group")) or "(無い)")
    tl = [am.find("title-group/article-title")] + am.findall("title-group/trans-title-group/trans-title")
    row("題名", "<br>".join(f"({lang_of(t)}) {r.inline(t)}" for t in tl if t is not None))
    names = []
    for c in am.findall("contrib-group/contrib"):
        ns = []
        for n in c.findall("name-alternatives/name") + c.findall("name"):
            ns.append(f"{esc(lang_of(n) or '')}: {esc(plain(n))}")
        mail = plain(c.find(".//email"))
        corr = c.get("corresp") == "yes" or bool(mail) or c.find("xref[@ref-type='corresp']") is not None
        names.append(" ／ ".join(ns) + (f" [責任著者{': ' + esc(mail) if mail else ''}]" if corr else ""))
    row("著者 (日・英・読み)", "<br>".join(names))
    affs = []
    for a in am.iter("aff"):
        inst = plain(a.find("institution")) if a.find("institution") is not None else plain(a)
        extra = [f"住所: {esc(plain(x))}" for x in a.findall("addr-line")]
        extra += [f"国: {esc(x.get('country') or plain(x))}" for x in a.findall("country")]
        affs.append(f"({esc(lang_of(a) or '')}) {esc(inst)}" + (f" <small>[{' / '.join(extra)}]</small>" if extra else ""))
    row("所属", "<br>".join(affs))
    kw = [f"({esc(g.get(XML_LANG) or '')}) " + "; ".join(r.inline(k) for k in g.findall("kwd"))
          for g in am.findall("kwd-group")]
    row("キーワード", "<br>".join(kw) or "(無い)")
    hist = ", ".join(f"{d.get('date-type')}: {date_str(d) if plain(d) else '(空)'}" for d in am.findall("history/date"))
    row("履歴", esc(hist) or "(無い)")
    lic = ", ".join(l.get("license-type") or "" for l in am.findall("permissions/license"))
    cp = " / ".join(esc(plain(c)) for c in am.findall("permissions/copyright-statement"))
    row("著作権・license", f"{cp} ／ license: {esc(lic) or '(無い．資料の設定を引き継ぐ)'}")
    nref = len(root.xpath("//ref-list/ref"))
    ndoi = len(root.xpath("//ref-list/ref//pub-id[@pub-id-type='doi']"))
    row("引用文献", f"{nref} 件 (DOI 付き {ndoi} 件)")
    unref = [i for i in r.refs if i not in r.cited]
    if unref:
        row("本文から引かれていない文献", esc(", ".join(unref)))
    fl_unref = [fid for fid, *_ in r.floats if fid and fid not in r.cited]
    if fl_unref:
        row("本文から引かれていない図表", esc(", ".join(fl_unref)))
    if r.unknown:
        row("表示に対応していない要素", esc(", ".join(sorted(r.unknown))) + " (文字だけ出している)")
    for n in r.notes:
        row("注意", esc(n))
    w = "".join(f"<li>{esc(x)}</li>" for x in dict.fromkeys(r.warn))
    status = f'<span class="pv-bad">警告 {len(dict.fromkeys(r.warn))} 件</span>' if r.warn else '<span class="pv-ok">警告なし</span>'
    return (f'<details class="pv-check" {"open" if r.warn else ""}><summary>プレビューの点検 (J-STAGE の画面に出ない項目) — {status}</summary>'
            f'{"<ul class=pv-warn>" + w + "</ul>" if w else ""}<table>{"".join(rows)}</table></details>')


# ================================================================ 書き出し

def find_jstage_css(opt):
    """J-STAGE の CSS のあるフォルダ．--jstage-css か，_sample/ に保存したページの *_files．"""
    if opt == "none":
        return None
    if opt:
        return Path(opt)
    for d in sorted((HERE / "_sample").glob("*_files")):
        if (d / "style.css").exists():
            return d
    return None


def write_article(art, out_root, page_lang, css_dir, base_css):
    d = out_root / art.id
    (d / "Graphics").mkdir(parents=True, exist_ok=True)
    for name, data in art.images.items():
        (d / "Graphics" / name).write_bytes(data)
    links = []
    if css_dir:
        for c in JSTAGE_CSS:
            f = (css_dir / c).resolve()
            if f.exists():
                try:
                    links.append(os.path.relpath(f, d.resolve()).replace(os.sep, "/"))
                except ValueError:                   # 別のドライブ (Windows) は絶対パスで参照する
                    links.append(f.as_uri())
    page = build_page(art, page_lang, links, base_css)
    (d / "index.html").write_text(page, encoding="utf-8")
    return d / "index.html"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("inputs", nargs="+", help="zip・作業ディレクトリ・XML")
    ap.add_argument("--out", default=str(HERE / "out"), help="出力先 (既定: preview_tool/out/)")
    ap.add_argument("--lang", choices=["ja", "en"], default="ja", help="画面の言語 (既定: ja．J-STAGE の日本語の画面に合わせる)")
    ap.add_argument("--jstage-css", default="", help="J-STAGE の CSS のあるフォルダ (none で使わない．既定: _sample/ から探す)")
    ap.add_argument("--open", action="store_true", help="できたページをブラウザで開く")
    args = ap.parse_args()

    arts = [a for p in args.inputs for a in read_input(p)]
    if not arts:
        sys.exit("記事の XML が見つからない")
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    css_dir = find_jstage_css(args.jstage_css)
    base_css = (HERE / "preview.css").read_text(encoding="utf-8")
    pages = []
    for a in sorted(arts, key=lambda a: a.id):
        p = write_article(a, out_root, args.lang, css_dir, base_css)
        pages.append((a, p))
        print(f"{a.id}: {p}")
    if len(pages) > 1:
        items = "".join(f'<li><a href="{attr(os.path.relpath(p, out_root).replace(os.sep, "/"))}">{esc(a.id)}</a> '
                        f'{esc(plain(a.am.find("title-group/article-title")))}</li>' for a, p in pages)
        idx = out_root / "index.html"
        idx.write_text(f'<!DOCTYPE html><html lang="ja"><meta charset="utf-8"><title>プレビューの一覧</title>'
                       f'<body><h1>プレビューの一覧 ({len(pages)} 本)</h1><p>{datetime.datetime.now():%Y-%m-%d %H:%M}</p>'
                       f'<ol>{items}</ol></body></html>', encoding="utf-8")
        print(f"一覧: {idx}")
    print(f"J-STAGE の CSS: {css_dir if css_dir else '使わない (preview.css だけ)'}")
    if args.open:
        webbrowser.open((out_root / "index.html" if len(pages) > 1 else pages[0][1]).resolve().as_uri())


if __name__ == "__main__":
    main()
