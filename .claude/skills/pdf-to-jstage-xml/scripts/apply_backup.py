"""手順 1 の下書き (body.md) に，J-STAGE の控えにあるものを当てる (手順 1 の続き．控えから始めたとき)．

使い方:
    python apply_backup.py <作業ディレクトリ> [--backup <控えの zip>]

控えの zip は既定で meta.yaml の source (from_backup.py が書いたもの)．meta.yaml が先にあって
from_backup.py が meta.backup.yaml に書いたときは source が無いので，--backup で渡す．
body.md を直し，直した中身を W/backup_report.txt に書く．引用文献と要旨の節は毎回控えから組み直すので，
**AI が手順 2 でそこを直したあとは走らせない**．

1. 引用文献の節を，控えの .txt (J-STAGE が PDF から取った全文) から組み直す．
   .txt は 1 件目の行が字下げなし・続きの行が全角空白で始まるので，文献の区切りが確か
   (下書きの OCR は段の並びから文献をつなぐので，区切りがずれることがある)．ページの変わり目の柱・透かしは外す．
   ただし .txt の行の並びが崩れている号がある (24(1):41・53)．組んだ件数が登録の件数と 3 割以上違えば，
   .txt は使わず下書きの文献を使う．下書きの引用文献の節に挟まった偽の見出し (表の文字) は外す．
2. その文献の OCR の読み誤りを，控えの XML の引用文献 (登録ずみ．筆頭著者だけだが綴り・年・巻・ページは正しい)
   と突き合わせて直す．直すのは，数字もどき・ゴミの字・和文の中の英字・英文の語の中の取り違えのような，
   読み誤りとはっきり言えるものだけ (漢字どうしの違いは紙面の字のことがあるので直さない)．
   **直したものはすべて backup_report.txt に出す**ので，手順 2 でページ画像と照らして確かめる．
   組にならなかった文献・直さなかった食い違い (要確認) も出す．
3. 和文の要旨の節 (「# 摘要」「# 要約」) を，控えの XML の和文要旨に差し替える (段落を保つ．OCR の誤りが無い)．
   控えは半角の約物で登録されていることがあるので，和文の中の「,」「.」「()」は全角にする (紙面に合わせる)．
   **英文要旨は meta.yaml の abstract.en が正**．body.md に英文の要旨の節 (「# ABSTRACT」) があれば外す
   (build.py は要旨の節の中身を和文の要旨として扱うので，残すと英文が和文の要旨に混ざる)．
4. 登録の文献の一覧を W/refs_backup.md に書く (手順 2 で紙面と照らす手本)．

控えの引用文献の DOI は，build.py が refs_web.txt から文献に付ける (from_backup.py が書いたもの)．
"""
import argparse
import difflib
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

import yaml

import extract_scan as es
import from_backup as fb

SKILL_DIR = Path(__file__).resolve().parent.parent
REPO = SKILL_DIR.parent.parent.parent
# OCR が数字と取り違える字 (実測: 24(1):65 の 2DOO・200D・ll2・3斗4・4フ5・］17)
DIGITISH = "0-9OoDlI斗フ］\\]"
CONF = {"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "］": "1", "]": "1", "斗": "4", "フ": "7"}
# OCR が字の代わりや間に挟むゴミ (24(1):65 の「ft〕rest」「Ecologica】Research」)
JUNKCH = "〕〔】【］［｜|亅"
# 英文で OCR が取り違える字の組 (OCR の字, 正しい字)．実測は 24(1):41・19 の引用文献
ASCII_CONF = {("c", "e"), ("e", "c"), ("j", "i"), ("i", "j"), ("l", "i"), ("i", "l"), ("u", "a"), ("ll", "n"),
              ("rn", "m"), ("m", "rn"), ("ll", "li"), ("Q", "o"), ("Qf", "of"), ("U", "ti"), ("1", "l"), ("l", "1"),
              ("I", "l"), ("l", "I"), ("1", "I"), ("n", "fl"), ("恥", "fo")}
# 登録の文献から外す巻号・DOI (2つの書き方がある: 「(1994) vol.9, p.269-280.」と「1994; vol. 9, no. 3, p. 269- 280. 10.1007/…」)
REG_NUMS = re.compile(r"\(\d{4}\)|(?<!\d)\d{4};|vol\.\s*\d+|no\.\s*\d+|p\.\s*[\d\s-]+|doi:\s*\S+|10\.\d{4,9}/\S+|DN/\S+")


# 控えの .txt のページの変わり目に入る柱・透かしのうち，設定の scan.junk で拾えない崩れ方
# (24(1):19 の「Service」「The Soolety of ▽egetatlon Solenoe」「Vegetation Science Vo1 24」)
RUNNING_HEAD = re.compile(r"^\s*(Library\s*)?Serv[il1]ce\s*$|S[o0][o0cl1]{1,2}[il1]?ety\s+of|egetat[il1][o0]n\s+S[co][il1][eo]nce"
                          r"|Science\s+V[o0][l1I]\.?\s*\d|植生学会誌\s*Veg", re.I)


def ja_punct(s):
    """控えの和文要旨の半角の約物を，紙面の全角にする (「,」「.」「()」．小数点・欧文の中は変えない)．"""
    ja = r"[ぁ-んァ-ヶ一-龥々ー）」』]"
    s = re.sub(r"\((?=[^()]*[ぁ-んァ-ヶ一-龥])([^()]*)\)", r"（\1）", s)
    # 約物の後ろの空白は詰めるが，改行 (段落の区切り) は残す (\s だと改行まで食べ，段落がつながった．24(2):113)
    s = re.sub(rf"(?<={ja}),[ \t]?", "，", s)
    s = re.sub(rf"(?<={ja})\.(?!\d)[ \t]?", "．", s)
    s = re.sub(rf",[ \t]?(?={ja[:-1]}])", "，", s)
    # 箇条の番号「1. 」は紙面の「1．」にする (24(2):113 の摘要)
    s = re.sub(r"(?m)^(\d{1,2})\.[ \t]*(?=\S)", r"\1．", s)
    return s


def reg_text(r):
    return REG_NUMS.sub(" ", r)


def refs_from_txt(txt, prof):
    """控えの .txt の引用文献の節を，1件1行にして返す．"""
    sec = prof["sections"]
    names = lambda k: [sec[k]] if isinstance(sec[k], str) else list(sec[k])
    junk = re.compile(f"(?:{es.JUNK_COMMON})" + (f"|(?:{prof['scan']['junk']})" if prof.get("scan", {}).get("junk") else ""))
    lines = txt.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if es.section_of(ln, names("refs"))[0]:
            start = i + 1          # 最後に出てくる見出しを使う (本文中の「文献」を避ける)
    if start is None:
        return []
    others = [n for k in ("appendix", "abstract", "ack") if k in sec for n in names(k)]
    refs = []
    for ln in lines[start:]:
        if not ln.strip():
            continue
        if others and es.section_of(ln, others)[0]:
            break
        if junk.search(ln) or re.fullmatch(r"[\s　0-9０-９]{1,6}", ln) or RUNNING_HEAD.search(ln):
            continue
        t = es.normalize(ln)
        if ln.startswith(("　", " ")) and refs:
            refs[-1] = es.join_text(refs[-1], t)
        else:
            refs.append(t.strip())
    return refs


def key(s):
    """比べるための字の列と，その字の元の位置 (約物・空白を除き，字形をそろえる)．"""
    out, pos = [], []
    for i, ch in enumerate(s):
        c = unicodedata.normalize("NFKC", ch)
        if not c or not re.match(r"\w", c):
            continue
        out.append(c.lower())
        pos.append(i)
    return "".join(out), pos


def pair(ocr, reg):
    """OCR の文献と登録ずみの文献を組にする．{OCR の添字: 登録の添字}"""
    res, used = {}, set()
    scores = []
    for i, o in enumerate(ocr):
        ko, _ = key(o)
        for j, r in enumerate(reg):
            kr, _ = key(reg_text(r))
            if not ko or not kr:
                continue
            sm = difflib.SequenceMatcher(None, ko, kr, autojunk=False)
            m = sum(b.size for b in sm.get_matching_blocks())
            s = m / min(len(ko), len(kr))                      # 短い方の字がどれだけ他方に入っているか
            if ko[:2] != kr[:2]:
                s *= 0.7                                       # 筆頭著者の頭が違えば割り引く
            scores.append((s, i, j))
    for s, i, j in sorted(scores, reverse=True):
        if s < 0.6 or i in res or j in used:
            continue
        res[i] = j
        used.add(j)
    return res


def fix_numbers(o, r, log):
    """巻・年・ページの数字の読み誤りを，登録の数字で直す (字数が同じで，違う字が数字もどきのときだけ)．"""
    nums = set(re.findall(r"\d+", re.sub(r"doi:\S+", "", r)))

    def sub(m):
        t = m.group(0)
        if not re.search(r"[^0-9]", t):
            return t
        for n in nums:
            if len(n) == len(t) and all(a == b or CONF.get(a) == b for a, b in zip(t, n)):
                log.append(f"{t} → {n}")
                return n
        return t
    return re.sub(rf"(?<![A-Za-z{DIGITISH}])[{DIGITISH}]{{2,}}(?![A-Za-z{DIGITISH}])",
                  lambda m: sub(m) if re.search(r"\d", m.group(0)) else m.group(0), o)


def misread(seg, tail, b):
    """OCR の読み誤りだとはっきり言える食い違いか．

    - ゴミの字 (〕】 など) を含む
    - 和文の字の代わりに英字が入っている (「H本」「R本」→「日本」)
    - 欧文の語の中の1字の違いで，OCR が数字や記号と取り違えやすい字 (l・I・1・0・O)
    漢字どうし・かなどうしの違いは紙面の字のことがあるので，ここでは直さない．
    """
    if any(c in JUNKCH for c in seg + tail):
        return True
    ja = re.compile(r"[ぁ-んァ-ヶ一-龥々]")
    if all(c.isascii() and c.isalpha() for c in seg) and all(ja.match(c) for c in b):
        return True
    if seg.isascii() and b.isascii() and len(seg) == 1 and seg in "lI1O0" and b in "lI1O0":
        return True
    # 英文の語の中の，OCR がよく取り違える字 (24(1):41 の「cffcct」「specjes」「Legendrc」「vanaUon」)
    if (seg, b) in ASCII_CONF:
        return True
    # 英文の語に紛れた漢字・かな (「Veget乱tion」「a且exible」「ground臼ora」)
    if b.isascii() and b.isalpha() and not seg.isascii() and all(ja.match(c) for c in seg):
        return True
    if seg == "目" and b == "日" and tail == "本":      # 「目本生態学会誌」
        return True
    return False


def fix_chars(o, r, log, notes):
    """前後がそろった短い食い違い (4字まで) を，登録の字で直す．"""
    ko, po = key(o)
    rc = reg_text(r)
    kr, pr = key(rc)
    sm = difflib.SequenceMatcher(None, ko, kr, autojunk=False)
    edits = []
    ops = sm.get_opcodes()
    for n, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag not in ("replace", "insert"):
            continue
        before = ops[n - 1] if n else None
        after = ops[n + 1] if n + 1 < len(ops) else None
        ok_ctx = before and before[0] == "equal" and before[2] - before[1] >= 2 \
            and after and after[0] == "equal" and after[2] - after[1] >= 2
        if not ok_ctx:
            continue
        b = rc[pr[j1]:pr[j2 - 1] + 1]           # 登録の元の字 (大文字・小文字を保つ)
        if tag == "insert":
            # OCR で字が落ち，代わりにゴミが入った所 (「Ecologica】Research」)．ゴミの字数が合うときだけ直す
            s, e = po[i1 - 1] + 1, po[i1]
            seg = o[s:e]
            if seg and all(c in JUNKCH for c in seg) and len(seg) == len(b):
                edits.append((s, e, b, pr[j2 - 1] + 1))
            elif len(b) <= 4:
                notes.append(f"直さなかった抜け「{o[max(0, s - 3):e + 3]}」に登録の「{b}」")
            continue
        s, e = po[i1], po[i2 - 1] + 1
        seg = o[s:e]
        tail = o[e] if e < len(o) else ""
        same_len = len(b) == len(seg.strip(JUNKCH)) or (seg, b) in ASCII_CONF
        if len(b) <= 4 and same_len and misread(seg, tail, b):
            while e < len(o) and o[e] in JUNKCH:          # 直後に挟まったゴミも一緒に外す (「ft〕rest」)
                e += 1
            edits.append((s, e, b, pr[j2 - 1] + 1))
        else:
            # 漢字どうし・かなどうしの違いは，紙面の字 (原文の誤り・登録側の直し) のことがあるので直さない
            # (24(1):65 の「施行事例」は紙面の字で，登録は「施工事例」)
            notes.append(f"要確認 (直さなかった)「{seg}」/ 登録「{b}」")
    for k, (s, e, b, re_) in enumerate(edits):
        # 字の代わりのゴミが語の間の空白まで食っていたら補う (「Ecologica】Research」→「Ecological Research」)
        if rc[re_:re_ + 1] == " " and e < len(o) and o[e].isalpha() and b[-1:].isalpha():
            edits[k] = (s, e, b + " ", re_)
    for s, e, b, _ in reversed(edits):
        seg = o[s:e]
        o = o[:s] + b + o[e:]
        log.append(f"{seg} → {b}")
    return o


def section_span(md, names, stop):
    """body.md の「# 見出し」の節の範囲 (見出しの行, 終わりの行)．

    手順 1 の下書きは，引用文献の本文をファイルの末尾にまとめて置き，その間に同じページの表の文字が
    偽の見出し (「# 53.78」「# E」) になって挟まることがある (24(1):41)．そこで節の終わりは，
    次の本物の節の見出し (stop に並べた名前) かファイルの末尾とする．見つからなければ None．
    """
    lines = md.split("\n")
    idx = next((i for i, ln in enumerate(lines) if ln.startswith("# ") and ln[2:].strip() in names), None)
    if idx is None:
        return None
    end = next((i for i in range(idx + 1, len(lines)) if lines[i].startswith("# ") and lines[i][2:].strip() in stop),
               len(lines))
    return idx, end


def section_lines(md, names, stop):
    """節の中の，空でない行 (偽の見出し・メモを除く．文献なら1件1行)．"""
    sp = section_span(md, names, stop)
    if sp is None:
        return []
    lines = md.split("\n")[sp[0] + 1:sp[1]]
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith(("# ", "## ", "<!--"))]


def replace_section(md, names, stop, new_lines):
    """節の中身を置き換える (偽の見出しも消える)．(新しい md, 消した偽の見出しの数)．節が無ければ (None, 0)．"""
    sp = section_span(md, names, stop)
    if sp is None:
        return None, 0
    lines = md.split("\n")
    junk = sum(1 for ln in lines[sp[0] + 1:sp[1]] if ln.startswith(("# ", "## ")))
    return "\n".join(lines[:sp[0] + 1] + [""] + new_lines + [""] + lines[sp[1]:]), junk


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("work")
    ap.add_argument("--backup", help="控えの zip (既定は meta.yaml の source)")
    args = ap.parse_args()
    w = Path(args.work)
    meta = yaml.safe_load((w / "meta.yaml").read_text(encoding="utf-8"))
    art = meta["article_id"]
    if not args.backup and not meta.get("source"):
        sys.exit("meta.yaml に source (控えの zip) が無い．from_backup.py が meta.backup.yaml に書いたときは，"
                 "--backup jstage/work/_backup/<巻>_<号>/<記事識別子>.zip で渡す")
    bz = Path(args.backup) if args.backup else REPO / meta["source"]
    if not bz.exists():
        sys.exit(f"控えの zip が無い: {bz} (--backup で渡す)")
    with zipfile.ZipFile(bz) as z:
        names_ = z.namelist()
        xml = z.read(next(n for n in names_ if n.endswith(f"/{art}.xml")))
        tn = next((n for n in names_ if n.endswith(f"/{art}.txt")), None)
        raw = z.read(tn) if tn else b""
        try:
            txt = raw.decode("utf-8")
        except UnicodeDecodeError:   # 35(1):35 の控えの .txt は Shift_JIS だった
            txt = raw.decode("cp932")
    prof = es.load_profile(meta.get("journal") or "vegsci")
    sec = prof["sections"]
    names = lambda k: [sec[k]] if isinstance(sec[k], str) else list(sec[k])
    root = fb.parse(xml)
    reg = fb.refs_text(root)
    md = (w / "body.md").read_text(encoding="utf-8")
    rep = [f"控え: {bz.name}"]

    # 登録の文献の一覧 (手順 2 で紙面と照らす手本．筆頭著者だけ・綴りは正しい)
    (w / "refs_backup.md").write_text(
        "# J-STAGE に登録ずみの引用文献 (控えの XML．apply_backup.py が書いた)\n\n"
        "筆頭著者だけで，並び・書き方は紙面と違う．題名・誌名・巻・ページ・年の綴りを確かめる手本にする．\n\n"
        + "\n".join(f"{j + 1}. {r}" for j, r in enumerate(reg)) + "\n", encoding="utf-8")

    # 1・2. 引用文献: 控えの .txt から組み，件数が登録と大きく違えば (並びが崩れている) 下書きの文献を使う
    refs_names = [n.replace(" ", "") for n in names("refs")]
    ab_names = [n.replace(" ", "") for n in names("abstract")]
    all_names = [n.replace(" ", "") for k in ("abstract", "ack", "refs", "appendix") if k in sec for n in names(k)]
    ocr = refs_from_txt(txt, prof)
    src = "控えの .txt"
    if reg and ocr and not (0.7 <= len(ocr) / len(reg) <= 1.3):
        rep.append(f"控えの .txt から組んだ文献は {len(ocr)} 件で登録 {len(reg)} 件とかけ離れる (行の並びが崩れている) ので使わない")
        ocr = []
    far = None
    if not ocr:
        draft = section_lines(md, refs_names, all_names)
        if draft and reg and not (0.7 <= len(draft) / len(reg) <= 1.3):
            # 下書きの文献も件数がかけ離れていれば使わない (文献の後ろの付表を拾った 35(1):1 の 647 件 / 登録 26 件など)．
            # 文献の節は書き換えず，作成役に紙面から組み直させる
            far = len(draft)
        elif draft:
            ocr, src = draft, "下書き (手順 1)"
    if far is not None:
        rep.insert(1, f"引用文献: **要確認**．下書きの文献は {far} 件で登録 {len(reg)} 件とかけ離れる (付表などを拾った疑い)．"
                      "文献の節は書き換えていない．紙面の文献一覧と refs_backup.md を手本に組み直す")
    elif ocr:
        pr = pair(ocr, reg)
        fixed = []
        n_fix = 0
        for i, o in enumerate(ocr):
            log, notes = [], []
            if i in pr:
                r = reg[pr[i]]
                o = fix_numbers(o, r, log)
                o = fix_chars(o, r, log, notes)
            fixed.append(o)
            if log or notes or i not in pr:
                rep.append(f"B{i + 1}: " + ("登録と組にならない" if i not in pr else "・".join(log) or "(直しなし)"))
                rep += [f"    {m}" for m in notes]
            n_fix += len(log)
        new, junk = replace_section(md, refs_names, all_names, fixed)
        if junk:
            rep.append(f"引用文献の節に挟まっていた偽の見出し {junk} 行 (同じページの表の文字) を外した")
        if new is None:
            md = md.rstrip("\n") + "\n\n# 引用文献\n\n" + "\n".join(fixed) + "\n"
        else:
            md = new
        unpaired = sorted(set(range(len(reg))) - set(pr.values()))
        rep.insert(1, f"引用文献: {src} から {len(ocr)} 件 (登録 {len(reg)} 件のうち {len(pr)} 件と組)．直した字 {n_fix} か所")
        for j in unpaired:
            rep.append(f"登録にだけある文献: {reg[j][:80]}")
    else:
        rep.insert(1, f"引用文献: 控えの .txt にも下書きにも見つからない．refs_backup.md (登録 {len(reg)} 件) を手本に，"
                      "ページ画像から AI が組む")

    # 3. 要旨: 和文の見出し (摘要・要約) には控えの和文要旨を当てる (英文の論文も末尾に和文の「要約」を持つ．24(1):19・29・53)．
    #    英文要旨は meta.yaml の abstract.en が正．build.py は要旨の節の中身を和文の要旨として扱うので，
    #    英文の要旨の節 (「# ABSTRACT」) が body.md に残ると英文が和文の要旨に混ざる．あれば外す
    ab = (meta.get("abstract") or {}).get("ja")
    names_ja = [n for n in ab_names if not re.search(r"[A-Za-z]", n)]
    names_en = [n for n in ab_names if re.search(r"[A-Za-z]", n)]
    if ab:
        # 控えの和文要旨は半角の約物で登録されていることがある．紙面は全角 (24(1):19・65)
        ab = ja_punct(ab)
        new, _ = replace_section(md, names_ja, all_names, ab.split("\n"))
        if new is not None:
            md = new
            rep.append(f"要旨: 控えの和文要旨 ({ab.count(chr(10)) + 1} 段落) に差し替えた")
        else:
            rep.append("要旨: body.md に和文の要旨の節が無いので差し替えない (build.py は meta.yaml の要旨を使う)")
    sp = section_span(md, names_en, all_names)
    if sp is not None:
        lines = md.split("\n")
        md = "\n".join(lines[:sp[0]] + lines[sp[1]:])
        rep.append("要旨: body.md の英文の要旨の節を外した (英文要旨は meta.yaml の abstract.en．紙面と照らして直す)")

    (w / "body.md").write_text(md, encoding="utf-8")
    (w / "backup_report.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep[:2]))
    print(f"くわしくは {w / 'backup_report.txt'}")


if __name__ == "__main__":
    sys.exit(main())
