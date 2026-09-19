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
  - `work/<巻>_<開始ページ>/` … スキルの作業ディレクトリ (追跡しない)．論文の PDF もこの中に置く．
    出力は `out/` (XML と対応表 `manifest.json`) と `<記事識別子>.zip` だけ
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
  (2026-09-19 ユーザ指示)．スキルの手順 5．**やり方は実行時のオプション `--review none|opus|fable|sonnet` で選ぶ**
  (同日ユーザ指示．「検証不要」「opus で検証」「fable で検証」「sonnet で検証」)．
  sonnet は安く速く，作った側が opus でも fable でも別のモデルになるが，**まだ実測していない**
  (2026-09-19 に 37(1) で比べる案は中止)．表の大きい論文には勧めない．
  **指定が無ければ `sonnet` (既定．2026-09-19 ユーザ指示)．聞かずに進める**．
  表の大きい論文 (セル 500 超・見開き・縦続き) のときだけ，手順 1 で分かった時点で1回聞く
  (推奨は作った側と別のモデル．`none` は推奨しない)．
  検証役には `review_pack.py` の資料とページ画像だけを見せ，
  `body.md`・`meta.yaml` は見せない．結果は作った側が1件ずつ採否を判断し，`review/triage.md` に残す．
- **数式は画像で載せる (MathML は組まない)** (2026-09-19 ユーザ指示)．`body.md` の `:::formula` の枠が
  `<disp-formula>` + `<graphic>` になり，画像は `crop.py` で PDF から切り出して `formulas/` に置く．
  **式番号は画像に入れず `<label>` に文字で持つ** (図題・表題を画像に入れないのと同じ)．
  本文の「式(1)」は自動でリンクする．MathML が要るときは全文 XML 作成ツールの画面で足す．
- **作業ディレクトリの中に写しや入れ子を作らない** (2026-09-19 ユーザ指示)．J-STAGE の
  「資料コード/巻/号/記事識別子/」は zip の中の名前にだけ付け，PDF と図表の画像は元のファイルから
  直接 zip へ入れる (`scripts/manifest.py`)．`_bundle/` のまとめた zip は登載が済んだら消してよい．
- **引用文献の正は PDF 版，J-STAGE の登録ずみのものは照合用** (2026-09-19)．照合は `build.py` が毎回行う．
  31(2): 193 では 225 件のうち違いは3件で，ウェブ版のハイフン脱落 1 件・アポストロフィの字形 1 件・
  PDF 側の斜体の印 1 件 (直した)．PDF 版は学名の斜体と全角の空白も保てる．

## 進捗状況

### 現在の状態

- 2026-09-19 20:05 (このセッション，web)
  **別行立ての数式に対応した** (`:::formula` → `<disp-formula><graphic/>`．切り出しは新しい `crop.py`)．
  本文の「式(1)」「(1)式」は自動リンク，検証役の見る点と `validate.py` の注意も足した．
  JATS 1.1 の DTD で，式の画像・番号なし・続きの画像・`xref ref-type="disp-formula"` が妥当なことを確かめた．

- 2026-09-19 19:40 (このセッション，web)
  **独立検証の既定を `sonnet` にした** (指定が無ければ聞かずに sonnet．表の大きい論文のときだけ確かめる)．
  あわせて，スキルの説明の「湖」を「地点」に直した (37(1) がたまたま湖だっただけで，一般には地点)．

- 2026-09-19 19:25 (このセッション，web)
  **独立検証の選択肢に `--review sonnet` を足した**．安く速く，作った側が opus・fable の
  どちらでも別のモデルになる．ただし未実測で，小さい字の表のセル照合では見落としが増えうるため，
  利点・欠点の表にその旨を書いた (37(1) で fable と比べる実測は中止)．

- 2026-09-19 19:10 (このセッション，web)
  **スキル `pdf-to-jstage-xml` の例を `37_37` から `31_193` に変えた** (巻・号・開始ページが
  どれも 37/1/37 で見分けが付かなかった．実測値の記録はそのまま)．あわせて `build.py` が
  Python 3.11 で構文エラーになるのを直した (f 文字列の中のバックスラッシュ．正規表現を外に出した)．

- 2026-09-19 19:00 (このセッション，web)
  **`requirements.txt` の固定版を Python 3.11〜3.14 で入るものに上げた** (numpy 2.3.5・pandas 2.3.3・
  Pillow 12.3.0・PyMuPDF 1.28.2・reportlab 4.5.1・streamlit 1.64.0．pandas は挙動の変化を避けて 2.x 系の最後)．
  重複していた `reportlab` の行を消し，README の版も合わせた．PyMuPDF 1.28 で非推奨になった
  `import fitz` は `import pymupdf as fitz` にした．3.11 の仮想環境で導入し，web 版 3 本を AppTest で確認．

- 2026-09-19 18:52 (このセッション，web)
  **`draw_string.py` の単体実行を直した**．デモが `font_name` を渡すようにし，
  書体の指定が無いときは `KeyError: 'None'` ではなく理由の分かる `ValueError` で止まるようにした．
  `os.startfile` は Windows のときだけ呼ぶ (他では出力先のパスを表示)．

- 2026-09-19 09:48 (このセッション，x280-home)
  **`jstage/work` に入れ子と写しを作らないようにした** (`build.py` は `out/` と zip だけ．対応表 `manifest.py`)．
  3 本を組み直して zip の中身が前と一致することを確かめ，古い入れ子を消した (79 → 66 MB)．

- 2026-09-19 09:11 (このセッション，x280-home)
  **スキル `pdf-to-jstage-xml` の独立検証を，実行時のオプション `--review none|opus|fable` で選べるようにした**．
  指定が無ければ手順 5 の直前ではなく最初に1回だけ聞き，途中で止まらないようにした．

- 2026-09-19 09:10 (このセッション，x280-home)
  **ファイル・ディレクトリ構造を整理し，J-STAGE の全文 XML 化のスキルを congress_vs から移した**．
  素材は `assets/`，生成物は `output/`，パスは `paths.py` に集約．`jstage.py`・`xmltest*.py` は
  `jstage/list_articles.py` にまとめた．web 版 3 本は AppTest で動作を確かめた．

- それ以前は [notes/history.md](notes/history.md) を見る．

### 次にやること

- `data/adress.txt` (植生学会の大会の領収書の文面) は，大会の運営を扱う congress_vs へ移すかを決める．
