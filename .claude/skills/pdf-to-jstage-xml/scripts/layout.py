"""PDF の体裁を見分け，巻号から分かっている体裁と食い違わないかを確かめる．

雑誌は何年かごとに組み方を変える．**どの巻号で何が変わったかは雑誌ごとの設定**
(`journals/<資料コード>.yaml` の `eras`) に書く．その雑誌での経緯は
`journals/<資料コード>.md` にまとめる (調べ方は `jstage/pdf_fingerprint.py`)．

使い方 (スクリプトから):
    from layout import detect, era_of, check
    detect(pdf)            # "scan" か "dtp"．PDF そのものを見て決める
    era_of(prof, 13, 1)    # 設定 (journals/*.yaml) の eras から，その巻号の体裁を引く
    check(prof, pdf, ...)  # 食い違い (取り違えた PDF・設定の古さ) を文字列の列で返す

**決めるのは PDF そのもの**．設定の表は「そのはずだ」という控えで，食い違ったら報告する
(新しい号が出て表が古くなったとき，取り違えた PDF を渡したときに気づける)．
"""
import pymupdf


def detect(pdf):
    """PDF が「紙のスキャン」か「DTP 版」かを返す ("scan" / "dtp")．

    スキャンは (1) 書体が1〜2種類しかなく (OCR が付けた1種類 + 記号)，
    (2) 1ページ目がページ全体を覆う画像1枚でできている．
    """
    doc = pdf if isinstance(pdf, pymupdf.Document) else pymupdf.open(pdf)
    fonts = {s["font"].split("+")[-1]
             for p in doc for b in p.get_text("dict")["blocks"] if b["type"] == 0
             for l in b["lines"] for s in l["spans"]}
    page = doc[0]
    area = page.rect.width * page.rect.height
    big = any(pymupdf.Rect(i["bbox"]).get_area() > area * 0.5 for i in page.get_image_info())
    return "scan" if len(fonts) <= 2 and big else "dtp"


def era_of(prof, volume, issue):
    """設定の `eras` から，その巻号に当てはまるものを返す (無ければ None)．

    `eras` の各項目は `from: [巻, 号]` を持ち，その巻号から次の項目の手前までを指す．
    """
    eras = prof.get("eras") or []
    key = (int(volume), int(issue or 1))
    hit = None
    for e in sorted(eras, key=lambda e: tuple(e["from"])):
        if tuple(e["from"]) <= key:
            hit = e
    return hit


def check(prof, pdf, volume=None, issue=None):
    """PDF の体裁と，設定が言う体裁との食い違いを文字列の列で返す (無ければ空)．"""
    out = []
    kind = detect(pdf)
    era = era_of(prof, volume, issue) if volume else None
    if era and era.get("source") and era["source"] != kind:
        out.append(f"体裁の食い違い: {volume}({issue}) は設定では {era['source']} だが，"
                   f"PDF は {kind} に見える．巻号か PDF を確かめる "
                   f"(設定が古いなら journals/{prof['journal_id']}.yaml の eras を直す)")
    return out, kind, era
