# support-ac プロジェクト

学会の大会運営を支援する Python スクリプト集．
名札・領収書の作成，発表番号やページ番号の生成と原稿への重ね合わせなどを行う．
Streamlit の web 版 (`*_web.py`) もある．

## 主なファイル

- `nameplate.py` / `nameplate_web.py`，`1名札.py` … 名札の作成
  (氏名・所属・参加状況に応じて出し分ける)
- `receipt.py` / `receipt_web.py`，`2領収書.py` … 領収書の作成
  (参加費・懇親会費・研修会費など)
- `overlay_pdf.py` / `overlay_pdf_web.py` … 発表番号・ページ番号と原稿の重ね合わせ
- `combine_pdf.py` … PDF の結合
- `empty_page.py`，`draw_string.py`，`image.py`，`convert_pdf_to_png.py` … 補助
- `jstage.py`，`xmltest.py` / `xmltest_en.py` … J-STAGE 投稿用の XML の作成・確認
  (`xmltest*.py` は未追跡)
- `create_form.gs`，`form_questions.csv` … 申込フォーム (Google Apps Script)
- `名簿・領収書.xlsx` … 名札・領収書の入力データ
- `data/` … 作業用データ (`adress.txt`，`file.dat`，`shape.dat`)
- `GenShinGothic-Monospace-Medium.ttf` … 出力に使うフォント
- `requirements.txt` … 依存パッケージ (版を固定してある)
- `*.pdf` / `*.png` … 動作確認の入出力例

## 決めごと

- **入力は Excel** で受け取る (書式は README に記載)．書式を変えたら README も直す．
- 依存パッケージは `requirements.txt` で版を固定する (PyMuPDF・reportlab・pdfrw・streamlit など)．
- 個人情報を含む実データ (参加者名簿) は追跡しない．
- PDF 操作の汎用部分は [easypdf](../easypdf) と重なる．直すときは両方の整合を確認する．

### J-STAGE の全文 XML 化 (スキル `pdf-to-jstage-xml`)

2026-09-19 に congress_vs から移した決めごと．

- **J-STAGE の記事ページは，1本につき日本語版と英語版を1回ずつ読むだけにする** (2026-09-19 ユーザ指示)．
  文献一覧の AJAX (タブの読み込み) を順に叩くのは止められた．読んだページは作業ディレクトリの
  `web/` に保存し，2回目からはそれを使う (`fetch_jstage.py` がそうしている)．
- **J-STAGE 用の図・表の画像には図題 (表題) を入れない** (2026-09-19 調査して決定)．図番号と図題は
  XML の `<label>`・`<caption>` に文字で持ち，J-STAGE が画像の下に表示する．根拠は
  `jstage/pdf_to_jstage_xml.md` の8節 (J-STAGE の手順書・公式の見本・公開例と JATS4R)．
- **原文の表記揺れ (引用の著者名の誤りなど) は，XML でも文字を直さない**．リンクだけを
  `{{著者名の先頭 年|表示}}` で手で付ける (J-STAGE は PDF と HTML の内容が同一であることを求めている)．
- **J-STAGE 用の XML は，作ったのとは別のエージェント (別のモデル) に PDF と見比べて検証させる**
  (2026-09-19 ユーザ指示)．スキルの手順 5．**検証役のモデル (fable か opus) は，起動の前に利点・欠点を
  示してユーザーに確認する** (同日ユーザ指示．既定の候補は作った側と別のモデル)．
  検証役には `review_pack.py` の資料とページ画像だけを見せ，
  `body.md`・`meta.yaml` は見せない．結果は作った側が1件ずつ採否を判断し，`review/triage.md` に残す．
- **引用文献の正は PDF 版，J-STAGE の登録ずみのものは照合用** (2026-09-19)．照合は `build.py` が毎回行う．
  31(2): 193 では 225 件のうち違いは3件で，ウェブ版のハイフン脱落 1 件・アポストロフィの字形 1 件・
  PDF 側の斜体の印 1 件 (直した)．PDF 版は学名の斜体と全角の空白も保てる．

## 進捗状況

### 現在の状態

- 2026-08-20 08:39
  プロジェクト管理用の `.claude/CLAUDE.md` を新規に設置した．最終コミットは 2026-03-07．
  **`README.md` に未コミットの変更があり，`create_form.gs`・`form_questions.csv` が
  未追跡のまま残っている**．
- それ以前は [notes/history.md](notes/history.md) を見る．

### 次にやること

- 未コミットの変更と未追跡ファイル (申込フォーム関係) を整理してコミットする．
- 新しく追加した `jstage.py`・`xmltest*.py` の使い方を README に書く．
- `名簿・領収書.xlsx` に実データが入っているなら，追跡対象から外す．
