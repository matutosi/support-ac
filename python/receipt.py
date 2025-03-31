import os
import image

import pandas as pd
from PIL import Image # pillow
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4, portrait, landscape
from reportlab.pdfbase.ttfonts import TTFont

from draw_string import draw_string

### データ
filepath = '名簿・領収書.xlsx'
values1 = pd.read_excel(filepath)

# # # # 入力欄 # # # # # # # # # # # # # # # # # # # # # 
TITLE         = "領収書"
CONGRESS      = "支援学会第100回大会"
COMMITTEE_SUB = "支援学会大会支援委員会"
PRESIDENT     = "会長 支援 太郎"
RECEIPT_DATE  = "2025年10月10日"
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 

# フォント登録
# 源真ゴシック（ http://jikasei.me/font/genshin/）
GEN_SHIN_GOTHIC_MEDIUM_TTF = "./GenShinGothic-Monospace-Medium.ttf"
pdfmetrics.registerFont(TTFont('GenShinGothic', GEN_SHIN_GOTHIC_MEDIUM_TTF))
FONT_NAME = 'GenShinGothic'

# # # # 当日参加用の入力欄 # # # # # # # # # # # # # # # # # # # # # 
TITLE_ON_THE_DAY = f'{CONGRESS}参加費として'
FOTTER = [
    "学会事務局",
    "〒100-0000" ,
    "東京都千代田区どこそこあれこれ",
    "大会支援株式会社  東京営業所内",
    "TEL: 03-0000-0000",
    "FAX: 03-0000-0000",
    "E-mail: shien@info.com"
    ]

LOC_FOTTER = [
    [ 90 * mm, 47 * mm], 
    [100 * mm, 42 * mm], 
    [100 * mm, 37 * mm], 
    [100 * mm, 32 * mm], 
    [100 * mm, 27 * mm], 
    [100 * mm, 22 * mm], 
    [100 * mm, 17 * mm]
    ]

def draw_footer(p, locations, footers):
    for loc, footer in zip(locations, footers):
        draw_string(p, loc[0], loc[1], footer, font_name=FONT_NAME, font_size=12)

def draw_receit(p, locations, name, amount, himoku, img=None):
    x, y = locations
    # 押印
    if img:
        if type(img) is str:
            img_w, img_h = Image.open(img).size
        else:
            img_w, img_h = img.getSize()
        w = 22                  # 印刷時の幅
        h = (w * img_h) / img_w # 印刷時の高さ
        p.drawImage(img, x + 140*mm, y - 65*mm, w*mm, h*mm)
    # 外枠
    p.setLineWidth(0.2*mm)
    p.rect(x, y - 66*mm, 182*mm, 66*mm, 1, 0)
    # 領収書
    draw_string(p, x + 42*mm, y - 7*mm, 
                TITLE, font_name=FONT_NAME, font_size=12, 
                align='center', width = 98*mm)
    # 宛名
    draw_string(p, x + 42*mm, y - 15*mm, 
                f'{name} 様', font_name=FONT_NAME, font_size=13, 
                align='center', shape="underlined", line_width=0.3*mm, width=98*mm)
    # 金額
    draw_string(p, x + 42*mm, y - 28*mm, 
                amount, font_name=FONT_NAME, font_size=13, 
                align='center', shape="rect", bg_color="lightgrey", width = 98*mm)
    # 但書
    item = f'但し，{himoku}として'
    draw_string(p, x + 42*mm, y - 39*mm, 
                item, font_name=FONT_NAME, font_size=10, 
                align='center', shape="underlined", width = 98*mm, line_width=0.3*mm)
    # 日付
    draw_string(p, x + 45*mm, y - 45*mm, 
                RECEIPT_DATE, font_name=FONT_NAME, font_size=10)
    # 受領
    draw_string(p, x + 45*mm, y - 48.5*mm, 
                '上記正に領収いたしました。', font_name=FONT_NAME, font_size=10)
    # 事務局
    draw_string(p, x + 105*mm, y - 58*mm, 
                COMMITTEE_SUB, font_name=FONT_NAME, font_size=10)
    # 委員長
    draw_string(p, x + 118*mm, y - 61.5*mm, 
                PRESIDENT, font_name=FONT_NAME, font_size=10)

# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # 

loc = [[ 14*mm, 286*mm], 
       [ 14*mm, 216*mm], 
       [ 14*mm, 146*mm]
    ]


path = f'{TITLE}.pdf'
p = canvas.Canvas(path, pagesize=A4)

# img = image.read_bz2("stamp.bz2", "stamp.bz2.txt")
img = "stamp.png"

for i, value in enumerate(values1.iterrows()):
    name     = value[1].iloc[0] # 氏名
    for j, n in enumerate([3,4,5]):
        amount   = value[1].iloc[n]
        himoku   = CONGRESS + values1.columns[n]
        if amount != 0:
            amount = f'￥{format(amount,",")}－'
            draw_receit(p, loc[j], name, amount, himoku, img=img)
    draw_footer(p, LOC_FOTTER, FOTTER)
    p.showPage()

p.save()

path2 = f'{TITLE}2.pdf'
p = canvas.Canvas(path2, pagesize=A4)

for i, value in enumerate(values1.iterrows()):
    name     = "                "
    amount   = "￥              "
    himoku   = CONGRESS + "参加費"
    draw_receit(p, loc[0], name, amount, himoku, img=None)
    draw_footer(p, LOC_FOTTER, FOTTER)
    p.showPage()

p.save()

os.startfile(path)
os.startfile(path2)
