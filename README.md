# support-ac

学会の大会実施時に必要な名札や領収書を作成するためのPythonスクリプトです．
名札と領収書の作成および発表番号やページ番号の生成と原稿との重ね合わせができます．
名札は，氏名や所属と参加状況に合わせた名札を作成します．
領収書は，参加費，懇親会費，研修会費などの領収書を作成します．
学会誌の論文を J-STAGE に登載するための全文 XML の作成と，論文の一覧の取得もできます．

## ディレクトリ構成

```
*_web.py        Streamlit の web アプリ (名札・領収書・重ね合わせ)
*.py            名札・領収書・重ね合わせなどの本体
paths.py        入出力のパス (assets/ と output/) をまとめたもの
assets/         フォント・印影・名簿の見本 (名簿・領収書.xlsx)
output/         生成した PDF・PNG (git では追跡しない)
form/           申込フォーム (Google Apps Script)
jstage/         J-STAGE 関係 (論文の一覧・全文 XML の調査・作業ディレクトリ)
.claude/skills/pdf-to-jstage-xml/   論文 PDF から全文 XML を作る Claude Code のスキル
```

## ライブラリのインストール

必要なライブラリをインストールします．

```
pip install -r requirements.txt
# or
pip install PyMuPdf
pip install numpy==2.2.4
pip install openpyxl==3.1.5
pip install pandas==2.2.3
pip install pdfrw==0.4
pip install Pillow==11.1.0
pip install reportlab==4.3.1
pip install streamlit==1.43.2
pip install reportlab==4.3.1                                                   
```

## 名札と領収書用のデータ

名札と領収書用のデータをExcelファイルで用意します．
形式は以下のとおりです．

| 氏名    | 所属  | 会員属性 | 参加費 | 懇親会参加費 | 研修会参加費 | 合計  |
| ----    | ----  | ---      | ----   | ----         | ----         | ----  |
| 参加者1 | 所属1 | 一般     | 4000   | 6000         | 5000         | 15000 |
| 参加者2 | 所属2 | 学生     | 2000   |    0         | 2000         |  4000 |

## webアプリの起動

名札の作成
- https://z4xzzyugqbjmkv6jtfjh3b.streamlit.app/

領収書の作成
- https://ehbozegkt8dkrx4mv4cjgg.streamlit.app/

発表番号とページ番号の生成およびPDFの重ね合わせ
- https://lz6ctgytnknwd65ptcgdmz.streamlit.app/

## 名札の作成

nameplate.py

名刺サイズ(w91mm, h55mm)の名札を作成します．
A4版(w210mm, h297mm, 左右余白: 各14mm, 上下余白: 各11mm)で10面(横2, 縦5)印刷可能なマルチカードに対応しています．
氏名や所属と参加状況に合わせた名札を作成します．

コードをカスタマイズすれば，名刺作成にも使えます．

データを assets/名簿・領収書.xlsx というExcelに保存しておけば，以下のコマンドで名札を作成できます．
作成した PDF は output/ に保存されます．

```
python nameplate.py
```


## 領収書の作成

receipt.py

A4版で，参加費・懇親会費・研修会費などの領収書を印刷します．
データを assets/名簿・領収書.xlsx というExcelに保存しておけば，以下のコマンドで領収書を作成できます．
作成した PDF は output/ に保存されます．
印影データはpng形式("assets/stamp.png")もしくはpngをbz2形式で圧縮したものを用意します．

```
python receipt.py
```



### 画像データの準備

学会印の画像データをpngで用意しておくと，領収書に押印する手間が省略できます．
押印データ流出防止のため，bz2形式で圧縮して保存することもできます．
また，圧縮したファイルを復元するために，画像のshape情報を別ファイルに保存します．
圧縮ファイルとshape情報は大切に保管してください．

```{python}
from image import compress_png_to_bz2, read_bz2 # ./image.py
from paths import STAMP_PNG, STAMP_BZ2          # ./paths.py

input_file = STAMP_PNG  # 元の画像 (assets/stamp.png)
output_file = STAMP_BZ2 # bz2形式 (assets/stamp.bz2)

# 圧縮して，bz2とshapeを返す
bz2_file, shape_file = compress_png_to_bz2(input_file, output_file)

# bz2とshapeから画像を復元し，reportlabのImageReaderオブジェクトを返す
# ImageReaderオブジェクトはreportlab.pdfgen.canvas.Canvasで使う
image = read_bz2(bz2_file, shape_file)
```

## 発表番号とページ番号の生成 

overlay_pdf.py

発表番号(A01, A02, ...)あるいはページ番号(1, 2, 3, ...)のみのPDFファイルを生成できます．

## PDFの重ね合わせ

overlay_pdf.py

発表番号あるいはページ番号を原稿のPDFファイルに重ね合わせることができます．



## Google Formの生成

form/create_form.gs：form/form_questions.csv のデータをもとに Google フォームを生成するスクリプト

- 準備
  - form_questions.csv を Google Drive（マイドライブ直下）にアップロード
  - CSV の ## 部分を実際の値に置き換えてから保存
  - この GAS スクリプトで createVSJFormFromCSV() を実行
  - セキュリティの警告の画面がでたら，承認する

- CSV仕様
   - form_questions.csv: 1行1エントリ
     - section_id   : config 行ではキー名，page_break では分岐先 ID
     - type         : config | text | paragraph | radio | checkbox | page_break
     - title        : config 行では設定値，それ以外は質問タイトル
     - required     : TRUE | FALSE
     - help_text    : 説明文（改行は \n と記述）
     - choices      : 選択肢をパイプ (|) 区切りで記述
     - other_option : TRUE で「その他（自由記述）」を追加
     - validation   : max_length:N  または  pattern:正規表現
     - branching    : 選択肢->移動先 をパイプ区切り．移動先: section_id | SUBMIT | NEXT

- 注意
 - ファイルの提出は GAS で作成不可
 - Google Forms 編集画面から手動でファイルアップロード質問を追加する

## J-STAGE 関係

必要なライブラリは直下とは別に用意しています (直下の requirements.txt は web アプリ用のため)．

```
pip install -r jstage/requirements.txt
```

### 論文の一覧

jstage/list_articles.py

J-STAGE から学会誌の論文の一覧を取ります．

```
# 号の目次 (記事種別・題名・著者・書誌) を表示する
python jstage/list_articles.py toc vegsci 41 2
# サイト用の論文リスト (<li> の HTML) を出す．--vol・--no で絞れる
python jstage/list_articles.py html --lang ja --out list_ja.html
python jstage/list_articles.py html --lang en --out list_en.html
```

### 論文 PDF から全文 XML を作る

Claude Code のスキル pdf-to-jstage-xml を使います．
手順は .claude/skills/pdf-to-jstage-xml/SKILL.md，調査のまとめは jstage/pdf_to_jstage_xml.md にあります．
作業ディレクトリは jstage/work/<巻>_<開始ページ>/ です (git では追跡しない)．
論文の PDF はその中に <巻>_<開始ページ>.pdf として置きます．
登載用の一式は <巻>_<開始ページ>.zip にまとめられます (J-STAGE が求めるフォルダの入れ子は zip の中にだけ作ります)．
