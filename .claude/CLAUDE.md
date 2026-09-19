# support-ac プロジェクト

学会の大会運営と学会誌の J-STAGE 登載を支援するスクリプト集．
名札・領収書の作成，発表番号やページ番号の生成と原稿への重ね合わせなどを行う．
Streamlit の web 版 (`*_web.py`) もある．
J-STAGE の論文の一覧の取得と，論文 PDF から全文 XML を作るスキルも置いてある
(スキルは 2026-09-19 に congress_vs から移した)．

## 主なファイル

- `nameplate.py` / `nameplate_web.py` … 名札の作成 (氏名・所属・参加状況に応じて出し分ける)
- `receipt.py` / `receipt_web.py` … 領収書の作成 (参加費・懇親会費・研修会費など)
- `overlay_pdf.py` / `overlay_pdf_web.py` … 発表番号・ページ番号と原稿の重ね合わせ
- `combine_pdf.py`，`empty_page.py`，`draw_string.py`，`image.py`，`convert_pdf_to_png.py` … 補助
- `paths.py` … 入出力のパス (`assets/`・`output/`) の定義．**パスはここにだけ書く**
- `assets/` … フォント (源真ゴシック)・印影 (`stamp.*`)・名簿の見本 (`名簿・領収書.xlsx`．中身はダミー)
- `output/` … 生成した PDF・PNG (追跡しない)
- `form/` … 申込フォーム (`create_form.gs`・`form_questions.csv`)
- `jstage/` … J-STAGE 関係
  - `list_articles.py` … 号の目次 (`toc`) とサイト用の論文リスト (`html`)
  - `pdf_to_jstage_xml.md` … PDF を J-STAGE 用の XML にする方法の調査
  - `requirements.txt` … J-STAGE 関係の依存 (直下のものとは分けてある)
  - `work/<巻>_<開始ページ>/` … スキルの作業ディレクトリ (追跡しない)
- `.claude/skills/pdf-to-jstage-xml/` … 論文 PDF から J-STAGE の全文 XML を作るスキル (手順は `SKILL.md`)
- `data/adress.txt` … 植生学会第30回大会の領収書の文面の控え (実際の値なので追跡しない)
- `requirements.txt` … web アプリの依存 (版を固定してある．Streamlit Cloud が使う)

## 決めごと

- **入力は Excel** で受け取る (書式は README に記載)．書式を変えたら README も直す．
- 依存パッケージは `requirements.txt` で版を固定する (PyMuPDF・reportlab・pdfrw・streamlit など)．
- **入口の `*_web.py` 3本は直下から動かさない**．Streamlit Cloud の公開アプリ (README の3つ) と
  `.devcontainer` がこの場所を指している．
- **公開リポジトリなので，実際の大会の値 (委員長名・事務局の住所など) は追跡しない**．コードの既定値はダミー．
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

- 2026-09-19 09:10 (このセッション，x280-home)
  **ファイル・ディレクトリ構造を整理し，J-STAGE の全文 XML 化のスキルを congress_vs から移した**．
  素材は `assets/`，生成物は `output/`，パスは `paths.py` に集約．`jstage.py`・`xmltest*.py` は
  `jstage/list_articles.py` にまとめた．web 版 3 本は AppTest で動作を確かめた．

- それ以前は [notes/history.md](notes/history.md) を見る．

### 次にやること

- **【次のタスク】スキル `pdf-to-jstage-xml` の独立検証 (手順 5) を，実行時のオプションで選べるようにする**
  (2026-09-19 ユーザ指示)．選択肢は「検証不要」「opus (XML の作成と同じ) で検証」「fable で検証」．
- `data/adress.txt` (植生学会の大会の領収書の文面) は，大会の運営を扱う congress_vs へ移すかを決める．
- `draw_string.py` を単体で実行すると `KeyError: 'None'` で落ちる (デモがフォント名を渡していない)．
  部品としては名札・領収書から正しく使えている．直すかは未定．
- `requirements.txt` の固定版 (numpy 2.2.4・pandas 2.2.3 など) は Python 3.14 用のビルド済みパッケージが無い．
  Streamlit Cloud の Python の版と合わせて，上げるかを決める．
