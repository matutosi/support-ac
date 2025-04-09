# support-ac

学会の大会実施時に必要な名札や領収書を作成するためのPythonスクリプトです．
名札は，氏名や所属と参加状況に合わせた名札を作成します．
領収書は，参加費，懇親会費，研修会費などの領収書を作成します．



## ライブラリのインストール

必要なライブラリをインストールします．

```
pip install -r requirements.txt
# or
pip install numpy==1.25.1
pip install openpyxl==3.1.5
pip install pandas==2.2.3
pip install pdfrw==0.4
pip install Pillow==11.1.0
pip install reportlab==4.3.1
```

## 名札の作成

名刺サイズ(w91mm, h55mm)の名札を作成します．
A4版(w210mm, h297mm, 左右余白: 各14mm, 上下余白: 各11mm)で10面(横2, 縦5)印刷可能なマルチカードに対応しています．

カスタマイズすれば，名刺作成にも使えます．

氏名や所属と参加状況に合わせた名札を作成します．


```{python}

```

## 領収書の作成

### 画像データの準備

学会印の画像データをpngで用意しておくと，領収書に押印する手間が省略できます．
ただし，押印データ流出防止のため，bz2形式で圧縮して保存します．
また，圧縮したファイルを復元するために，画像のshape情報を別ファイルに保存します．
圧縮ファイルとshape情報は大切に保管してください．

```{python}
from image import compress_png_to_bz2, read_bz2 # ./python/image.py

input_file = 'stamp.png' # 元の画像
output_file = 'stamp.bz2' # bz2形式

# 圧縮して，bz2とshapeを返す
bz2_file, shape_file = compress_png_to_bz2(input_file, output_file)

# bz2とshapeから画像を復元し，reportlabのImageReaderオブジェクトを返す
# ImageReaderオブジェクトはreportlab.pdfgen.canvas.Canvasで使う
image = read_bz2(bz2_file, shape_file)
```


```
pip install -r requiremets.txt
```




参加費，懇親会費，研修会費などの領収書を作成します．
pngで学会印の陰影を用意すれば，押印の手間も省略できます．

