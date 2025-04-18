# support-ac

学会の大会実施時に必要な名札や領収書を作成するためのPythonスクリプトです．
名札と領収書の作成および発表番号やページ番号の生成と原稿との重ね合わせができます．
名札は，氏名や所属と参加状況に合わせた名札を作成します．
領収書は，参加費，懇親会費，研修会費などの領収書を作成します．

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

データを 名簿・領収書.xlsx というExcelに保存しておけば，以下のコマンドで名札を作成できます．


## 領収書の作成

receipt.py

A4版で，参加費・懇親会費・研修会費などの領収書を印刷します．
データを 名簿・領収書.xlsx というExcelに保存しておけば，以下のコマンドで領収書を作成できます．
印影データはpng形式("stamp.png")もしくはpngをbz2形式で圧縮したものを用意します．



### 画像データの準備

学会印の画像データをpngで用意しておくと，領収書に押印する手間が省略できます．
押印データ流出防止のため，bz2形式で圧縮して保存することもできます．
また，圧縮したファイルを復元するために，画像のshape情報を別ファイルに保存します．
圧縮ファイルとshape情報は大切に保管してください．

```{python}
from image import compress_png_to_bz2, read_bz2 # ./image.py

input_file = 'stamp.png' # 元の画像
output_file = 'stamp.bz2' # bz2形式

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
