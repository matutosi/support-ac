"""J-STAGE の1号分 (目次・記事ページ・本文 PDF) を手元に保存する．

    python backup_jstage.py 13 1                 # 植生学会誌 13 巻 1 号
    python backup_jstage.py 13 1 --journal vegsci --out backup_13_1
"""
import argparse
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
TIMEOUT = 30
WAIT = 1.5  # サーバー負担軽減のためのウェイト (秒)

def sanitize_filename(filename):
    """ファイル名に使用できない文字を置換"""
    return re.sub(r'[\\/:*?"<>|]', "_", filename)

def get_html(url):
    """HTML を取得する．失敗したら例外を投げる"""
    res = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    res.raise_for_status()
    res.encoding = res.apparent_encoding
    return res.text

def download_pdf(url, save_path):
    """PDF をストリーミングでダウンロード保存．中身が PDF でなければ保存しない"""
    try:
        response = requests.get(url, headers=HEADERS, stream=True, timeout=TIMEOUT)
        response.raise_for_status()
        chunks = response.iter_content(chunk_size=8192)
        first = next(chunks, b"")
        if not first.startswith(b"%PDF"):
            print(f"  └─ PDF ではない応答のため保存しません ({url})")
            return False
        with open(save_path, "wb") as f:
            f.write(first)
            for chunk in chunks:
                f.write(chunk)
        print(f"  └─ 保存完了: {save_path}")
        return True
    except Exception as e:
        print(f"  └─ ダウンロード失敗 ({url}): {e}")
        return False

def backup_jstage_issue(journal, volume, issue, save_dir):
    base_url = f"https://www.jstage.jst.go.jp/browse/{journal}/{volume}/{issue}/_contents/-char/ja"
    pdf_dir = os.path.join(save_dir, "pdf")
    os.makedirs(pdf_dir, exist_ok=True)

    print(f"目次ページを取得中: {base_url}")
    toc_html = get_html(base_url)

    # 目次HTMLそのものをバックアップ
    toc_html_path = os.path.join(save_dir, "index.html")
    with open(toc_html_path, "w", encoding="utf-8") as f:
        f.write(toc_html)
    print(f"目次HTMLを保存しました: {toc_html_path}")

    soup = BeautifulSoup(toc_html, "html.parser")

    # 記事のリンクは /article/<資料コード>/<巻>/<号>/<記事ID>/_article/... の形
    article_re = re.compile(rf"/article/{journal}/{volume}/{issue}/([^/]+)/_article")

    # 同じ記事への複数のリンク (-char/ja・-char/en など) は記事ID でまとめる
    processed_ids = set()

    for a_tag in soup.find_all("a", href=article_re):
        article_id = article_re.search(a_tag["href"]).group(1)
        if article_id in processed_ids:
            continue
        processed_ids.add(article_id)

        article_url = urljoin(base_url, f"/article/{journal}/{volume}/{issue}/{article_id}/_article/-char/ja")
        print(f"\n[処理中] 論文ページ: {article_url}")

        # 記事詳細ページの取得
        time.sleep(WAIT)
        try:
            art_html = get_html(article_url)
        except Exception as e:
            print(f"  └─ 取得失敗: {e}")
            continue
        art_soup = BeautifulSoup(art_html, "html.parser")

        # タイトルの抽出
        title_node = art_soup.find("div", class_="article-title") or art_soup.find("h1")
        title_text = title_node.get_text(strip=True) if title_node else "article"
        safe_title = sanitize_filename(title_text)[:50]  # 長すぎるファイル名を制限

        # 1. 論文個別HTMLページの保存
        html_file_name = f"{article_id}_{safe_title}.html"
        with open(os.path.join(save_dir, html_file_name), "w", encoding="utf-8") as f:
            f.write(art_html)
        print(f"  ├─ HTMLメタデータ保存: {html_file_name}")

        # 2. 本文PDFリンクの抽出とダウンロード
        pdf_link = art_soup.find("a", href=re.compile(r"/_pdf"))
        if pdf_link:
            pdf_url = urljoin(article_url, pdf_link["href"])
            pdf_file_name = f"{article_id}_{safe_title}.pdf"
            pdf_save_path = os.path.join(pdf_dir, pdf_file_name)

            print(f"  ├─ PDFを取得中: {pdf_url}")
            time.sleep(WAIT)
            download_pdf(pdf_url, pdf_save_path)
        else:
            print("  └─ PDFリンクが見つかりませんでした。")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="J-STAGE の1号分を保存する")
    parser.add_argument("volume", help="巻 (例: 13)")
    parser.add_argument("issue", help="号 (例: 1)")
    parser.add_argument("--journal", default="vegsci", help="資料コード (既定: vegsci)")
    parser.add_argument("--out", help="保存先 (既定: <資料コード>_vol<巻>_no<号>_backup)")
    args = parser.parse_args()
    save_dir = args.out or f"{args.journal}_vol{args.volume}_no{args.issue}_backup"
    backup_jstage_issue(args.journal, args.volume, args.issue, save_dir)
