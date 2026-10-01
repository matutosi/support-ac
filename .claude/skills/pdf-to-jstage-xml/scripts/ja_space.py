"""和文と英数字の間に半角の空白を入れる (DTP の号の body.md と和文要旨)．
あわせて，全角の括弧の前の空白を詰め，摘要の番号を「1.　」にそろえる．

使い方:
    python ja_space.py <作業ディレクトリ>            # 変わる行の数と例を出すだけ
    python ja_space.py <作業ディレクトリ> --write    # body.md と meta.yaml を書き換える

DTP の紙面は和文と数字・英字の間に約 1/4 字の自動の空き (和欧間) を入れるが，
文字の層には空白があったり無かったりする (31(2) で 1 本の中に混ざっていた)．
紙面の見た目どおり，スキャンの号 (13 巻〜31(1)) と同じく半角の空白にそろえる
(2026-10-01 ユーザ指示)．何度かけても同じ結果になる．

入れるところ:
- 和文 ↔ 英数字 (「舘脇 1948」「3 月から 5 月」「16.2% に」「m^2^ 以上」)
- 和名と斜体の学名の間 (「アカマツ *Pinus*」「*densiflora* の」)

入れないところ:
- 引用文献の節 (書き方の決めごとが別にある)
- 図表・式の枠の行 (`:::`・`@image`) と，組んだ表の行 (`<` で始まる行．セルは文字の層で照合する)
- `{{鍵|表示}}` の鍵の部分
- 図表の参照の番号 (「図1」「表2」「付表1」は詰める．前が漢字なら語の一部 (地表・植生図) なので詰めない)
- 中黒「・」の前後 (「°C・月」)

ほかにそろえるもの (2026-10-01 ユーザ指示．文字の層では論文ごと・1 本の中でも揺れていた):
- 全角の「（」の前の半角の空白は詰める (「Hattori （1979）」→「Hattori（1979）」．
  組んだ表の行・図表の題も．引用文献の節は文字の層どおりにするので触らない)
- 摘要・要約の箇条の番号は紙面どおり「1.　」(半角の点 + 全角の空白) にする
  (`apply_backup.py` が控えから入れる「1．」はスキャンの号の紙面の形)

書き換えた後は build.py で組み直し，空白以外の文字とリンクが変わっていないことを確かめる．
"""
import argparse
import re
from pathlib import Path

J = "[ぁ-ゖァ-ヺー一-鿿々〆]"  # 中黒「・」(U+30FB) は含めない
A = "[A-Za-z0-9]"
REF_HEADINGS = ("# 引用文献", "# 文献", "# References", "# REFERENCES", "# REFFERENCES", "# REFERENCE",
                "# Literature cited", "# Literature Cited")  # journals/vegsci.yaml の refs と同じ


def fix_text(t):
    t = re.sub("(" + J + ")(" + A + ")", r"\1 \2", t)
    t = re.sub("(" + A + r"|%|(?<=[A-Za-z0-9])\^)(" + J + ")", r"\1 \2", t)
    # 斜体の印をはさむ和名と学名
    t = re.sub("(" + J + r")(\*[A-Za-z])", r"\1 \2", t)
    t = re.sub(r"(?<=[A-Za-z0-9.])\*(" + J + ")", r"* \1", t)
    # 図表の参照の番号は詰める
    t = re.sub(r"(?<![一-鿿])(付表|図|表) (?=\d)", r"\1", t)
    return t


PAREN = re.compile(r"(?m)^[ \t]*(?:[-*+]|\d{1,2}\.|[A-Za-z_][\w-]*:)[ \t]+|(?<=\S) +（")


def tight_paren(t):
    """全角の「（」の前の半角の空白を詰める．行頭の字下げ・箇条の印 (「- 」「1. 」) の後ろと，
    行頭の「鍵: 」の後ろは残す (Markdown と YAML の書き方を壊さない)．文中のコロンの後ろは詰める
    (英文要旨の「types:（1）」．35(1):35)．"""
    t = PAREN.sub(lambda m: "（" if m.group(0).endswith("（") else m.group(0), t)
    # 閉じの「）」の後ろに和文が続くときの半角の空白も詰める (「Miyawaki（1960） がまとめた」．
    # 文字の層では 34(2) から現れる．紙面に空きは無い．2026-10-02 ユーザ指示)．
    # 箇条の番号「（1） 十分」は紙面に空きがあるので残す (35(2):117)
    return CLOSE.sub(lambda m: m.group(0) if m.group(1) else "）", t)


CLOSE = re.compile("（(\\d{1,2})） +|） +(?=" + J + ")")


def fix_line(line):
    if line.startswith("@image"):
        return line
    if line.startswith(":::") or line.lstrip().startswith("<"):
        return tight_paren(line)
    out, pos = [], 0
    for m in re.finditer(r"\{\{([^|{}]*)\|", line):  # {{鍵|表示}} の鍵は変えない
        out.append(fix_text(line[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(fix_text(line[pos:]))
    return tight_paren("".join(out))


ABS_HEADS = ("# 摘要", "# 要約", "# 和文の要約")
ABS_NUM = re.compile(r"^(\d{1,2})[．.][ \u3000]*(?=\S)")


def fix_body(s):
    res, in_refs, in_abs = [], False, False
    for ln in s.split("\n"):
        if ln.startswith("# "):
            in_refs = ln.strip() in REF_HEADINGS
            in_abs = ln.strip() in ABS_HEADS
            res.append(ln)
        elif in_refs:
            res.append(ln)
        else:
            ln = fix_line(ln)
            res.append(ABS_NUM.sub("\\1.\u3000", ln) if in_abs else ln)
    return "\n".join(res)


def fix_meta(s):
    m = re.search(r"(\nabstract:\n  ja: ')(.*?)('\n  en:)", s, re.S)
    if m:
        s = s[:m.start(2)] + fix_text(m.group(2)) + s[m.end(2):]
    # 全角の括弧の前の空白は，題名・英文要旨・所属なども含めて全体で詰める (meta.yaml に引用文献は無い)
    return tight_paren(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--write", action="store_true", help="body.md と meta.yaml を書き換える")
    a = ap.parse_args()
    w = Path(a.work)
    body = (w / "body.md").read_text(encoding="utf-8")
    meta = (w / "meta.yaml").read_text(encoding="utf-8")
    nb, nm = fix_body(body), fix_meta(meta)
    diff = [(o, n) for o, n in zip(body.split("\n"), nb.split("\n")) if o != n]
    print(f"body.md: 変わる行 {len(diff)}，空白の増減 {nb.count(' ') - body.count(' ')}"
          f"／meta.yaml の和文要旨: {'変わる' if nm != meta else 'そのまま'}")
    for o, n in diff[:5]:
        i = next(k for k in range(min(len(o), len(n))) if o[k] != n[k])
        print(f"  {o[max(0, i - 8):i + 8]!r} → {n[max(0, i - 8):i + 9]!r}")
    if a.write:
        (w / "body.md").write_text(nb, encoding="utf-8")
        (w / "meta.yaml").write_text(nm, encoding="utf-8")
        print("書き換えた．build.py で組み直す")


if __name__ == "__main__":
    main()
