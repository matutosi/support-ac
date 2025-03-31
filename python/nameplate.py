import os

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4, portrait, landscape
from reportlab.pdfbase.ttfonts import TTFont
import pandas as pd

from draw_string import draw_string

def draw_name(p, x, y, name, affil, dinner=0, workshop=0, font_name='GenShinGothic'):
    # 大会名
    draw_string(p, x + 1*mm, y - 10*mm, CONGRESS, font_name=font_name, font_size=14, 
                color="white", shape="rect", bg_color="green", width=89*mm)
    # 会場・日時
    draw_string(p, x + 65*mm, y -10*mm, PLACE    , font_name=font_name, font_size=7, color="white")
    draw_string(p, x + 65*mm, y - 6*mm, CONG_DATE, font_name=font_name, font_size=7, color="white")
    # 所属・氏名欄
    draw_string(p, x + 10*mm, y - 15*mm, SHOZOKU, font_name=font_name, font_size=6)
    draw_string(p, x + 10*mm, y - 25*mm, SIMEI  , font_name=font_name, font_size=6)
    p.line(x + 10*mm, y - 20*mm, x + 80*mm, y - 20*mm)
    p.line(x + 10*mm, y - 30*mm, x + 80*mm, y - 30*mm)
    # 所属：長い文字列はフォントサイズを小さくする
    if (affil is not None) and (affil != ""):
        font_size = min((180 / len(affil)), 12)
        draw_string(p, x + 15*mm, y - 19*mm, affil, font_name=font_name, font_size=font_size)
    # 氏名
    draw_string(p, x + 15*mm, y - 29*mm, name, font_name=font_name, font_size=18)
    # 懇親会：参加マーク
    if dinner > 0:
        draw_string(p, x + 75*mm, y - 25*mm, str="懇", font_name='GenShinGothic', font_size=9, 
                    color="white", shape="circle", bg_color="red")
    # 研修会：参加マーク
    if workshop > 0 :
        draw_string(p, x + 80*mm, y - 25*mm, str="研", font_name='GenShinGothic', font_size=9, 
                    color="white", shape="circle", bg_color="blue")
    # 主催
    draw_string(p, x + 55*mm, y - 45*mm, COMMITTEE    , font_name=font_name, font_size=6)
    draw_string(p, x + 55*mm, y - 48*mm, COMMITTEE_SUB, font_name=font_name, font_size=6)


############ 設定箇所はじめ ############

### 名札の左上の各位置
###   参考
###     A4: width=210mm, height=297mm
###     余白 左右: 14mm, 上下: 11mm
###     有効幅: 182mm, 有効高: 275mm
###     横2枚, 縦5枚
###     1枚あたり: width=91mm, height=55mm
loc = [[ 14*mm, 286*mm], 
       [ 14*mm, 231*mm], 
       [ 14*mm, 176*mm], 
       [ 14*mm, 121*mm], 
       [ 14*mm,  66*mm],
       [105*mm, 286*mm], 
       [105*mm, 231*mm], 
       [105*mm, 176*mm], 
       [105*mm, 121*mm], 
       [105*mm,  66*mm]]

### 源真ゴシック（ http://jikasei.me/font/genshin/）
### フォント登録
GEN_SHIN_GOTHIC_MEDIUM_TTF = "./GenShinGothic-Monospace-Medium.ttf"
pdfmetrics.registerFont(TTFont('GenShinGothic', GEN_SHIN_GOTHIC_MEDIUM_TTF))

### データ
filepath = '名簿・領収書.xlsx'
values1 = pd.read_excel(filepath)

### 大会情報
CONGRESS      = "支援学会第100回大会"
CONG_DATE     = "2025年10月10日"
COMMITTEE     = "支援学会第100回大会実行委員会"
COMMITTEE_SUB = "支援学会大会支援委員会"
PLACE         = '支援大学'
SHOZOKU       = '所属'
SIMEI         = '氏名'

### 出力ファイル名
path = "nameplate.pdf"
path_2 = "nameplate_2.pdf"

############ 設定箇所おわり ############

### 事前申込者
p = canvas.Canvas(path, pagesize=A4)
for i, value in enumerate(values1.iterrows()): # i: 全体での番号
    n = i % 10                      # n: 1枚の中での番号
    x = loc[n][0]
    y = loc[n][1]
    name     = value[1].iloc[0] # 氏名
    affil    = value[1].iloc[1] # 所属
    dinner   = value[1].iloc[4] # 懇親会
    workshop = value[1].iloc[5] # 研修会
    draw_name(p, x, y, name, affil, dinner, workshop)
    if ((i+1) % 10) == 0:
        p.showPage()

p.showPage()
p.save()

### 当日用の空白名札

n_sheet = 2 # 必要なシート数: 1シートあたり10枚印刷

p = canvas.Canvas(path_2, pagesize=A4)
for i in range(n_sheet * 10): # i: 全体での番号
    n = i % 10                # n: 1枚の中での番号
    x = loc[n][0]
    y = loc[n][1]
    name     = ""
    affil    = ""
    dinner   = 0
    workshop = 0
    draw_name(p, x, y, name, affil, dinner, workshop)
    if ((i+1) % 10) == 0:
        p.showPage()

p.save()

### PDFを開く
os.startfile(path)
os.startfile(path_2)
