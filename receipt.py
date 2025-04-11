import os

import streamlit as st
import pandas as pd
from PIL import Image # pillow
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.ttfonts import TTFont
from image import read_bz2

from draw_string import draw_string

def draw_footer(p, locations, footers, font_name="GenShinGothic"):
    for loc, footer in zip(locations, footers):
        draw_string(p, loc[0], loc[1], footer, font_name=font_name, font_size=11)

def draw_receit(p, locations, name, amount, himoku, CONSTANT_STRINGS, font_name, img=None):
    # 定数
    TITLE         = CONSTANT_STRINGS[0]
    CONGRESS      = CONSTANT_STRINGS[1]
    COMMITTEE_SUB = CONSTANT_STRINGS[2]
    PRESIDENT     = CONSTANT_STRINGS[3]
    RECEIPT_DATE  = CONSTANT_STRINGS[4]

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
                TITLE, font_name=font_name, font_size=12, 
                align='center', width = 98*mm)
    # 宛名
    draw_string(p, x + 42*mm, y - 15*mm, 
                f'{name} 様', font_name=font_name, font_size=13, 
                align='center', shape="underlined", line_width=0.3*mm, width=98*mm)
    # 金額
    draw_string(p, x + 42*mm, y - 28*mm, 
                amount, font_name=font_name, font_size=13, 
                align='center', shape="rect", bg_color="lightgrey", width = 98*mm)
    # 但書
    item = f'ただし，{CONGRESS}{himoku}として'
    draw_string(p, x + 42*mm, y - 39*mm, 
                item, font_name=font_name, font_size=10, 
                align='center', shape="underlined", width = 98*mm, line_width=0.3*mm)
    # 日付
    draw_string(p, x + 45*mm, y - 45*mm, 
                RECEIPT_DATE, font_name=font_name, font_size=10)
    # 受領
    draw_string(p, x + 45*mm, y - 48.5*mm, 
                '上記正に領収いたしました。', font_name=font_name, font_size=10)
    # 事務局
    draw_string(p, x + 105*mm, y - 58*mm, 
                COMMITTEE_SUB, font_name=font_name, font_size=10)
    # 委員長
    draw_string(p, x + 118*mm, y - 61.5*mm, 
                PRESIDENT, font_name=font_name, font_size=10)

# 全体での位置
loc = [[ 14*mm, 286*mm], # 参加費
       [ 14*mm, 216*mm], # 懇親会費
       [ 14*mm, 146*mm]  # 研修会費
    ]

# 備考の位置
LOC_FOOTER_1 = [
    [ 10 * mm, 47 * mm], 
    [ 15 * mm, 42 * mm], 
    [ 15 * mm, 37 * mm], 
    [ 15 * mm, 32 * mm], 
    [ 15 * mm, 27 * mm], 
    [ 15 * mm, 22 * mm], 
    [ 15 * mm, 17 * mm],
    [ 15 * mm, 12 * mm]
]

# 事務局住所の位置
LOC_FOOTER_2 = [
    [125 * mm, 47 * mm], 
    [130 * mm, 42 * mm], 
    [130 * mm, 37 * mm], 
    [130 * mm, 32 * mm], 
    [130 * mm, 27 * mm], 
    [130 * mm, 22 * mm], 
    [130 * mm, 17 * mm],
    [130 * mm, 12 * mm]
    ]

def create_named_receipt(path_input, path_named_receipt, CONSTANT_STRINGS, font_name, img=None):
    """
    事前申込者の領収書の作成
    """
    df = pd.read_excel(path_input)
    p = canvas.Canvas(path_named_receipt, pagesize=A4)
    FOOTER_1      = CONSTANT_STRINGS[5]
    FOOTER_2      = CONSTANT_STRINGS[6]
    for value in df.iterrows():
        name     = value[1].iloc[0] # 氏名
        for j, n in enumerate([3,4,5]):
            amount   = value[1].iloc[n]
            himoku   = df.columns[n]
            if amount != 0:
                amount = f'￥{format(amount,",")}－'
                draw_receit(p, loc[j], name, amount, himoku, CONSTANT_STRINGS, font_name, img=img)
        draw_footer(p, LOC_FOOTER_1, FOOTER_1)
        draw_footer(p, LOC_FOOTER_2, FOOTER_2)
        p.showPage()
    p.save()


def create_empty_receipt(path_empty_plate, CONSTANT_STRINGS, font_name):
    """
    当日参加者の領収書の作成
    """
    FOOTER_1      = CONSTANT_STRINGS[5]
    FOOTER_2      = CONSTANT_STRINGS[6]
    p = canvas.Canvas(path_empty_plate, pagesize=A4)
    name     = "                "
    amount   = "￥              "
    himoku   = "参加費"
    draw_receit(p, loc[0], name, amount, himoku, CONSTANT_STRINGS, font_name, img=None)
    draw_footer(p, LOC_FOOTER_1, FOOTER_1)
    draw_footer(p, LOC_FOOTER_2, FOOTER_2)
    p.showPage()
    p.save()


if __name__ == "__main__":

    ############ 設定箇所はじめ ############
    # フォント登録
    # 源真ゴシック（ http://jikasei.me/font/genshin/）
    font_name = "GenShinGothic"
    GEN_SHIN_GOTHIC_MEDIUM_TTF = "./GenShinGothic-Monospace-Medium.ttf"
    pdfmetrics.registerFont(TTFont(font_name, GEN_SHIN_GOTHIC_MEDIUM_TTF))

    # img = read_bz2("stamp.bz2", "stamp.bz2.txt")
    img = "stamp.png"

    ### 大会情報
    TITLE         = "領収書"
    CONGRESS      = "支援学会第100回大会"
    COMMITTEE_SUB = "支援学会大会支援委員会"
    PRESIDENT     = "会長 支援 太郎"
    RECEIPT_DATE  = "2025年10月10日"
    ### 註釈
    FOOTER_1 = [
        "領収書について",
        "会員の大会参加費：不課税",
        "非会員の大会参加費：消費税課税対象取引",
        "懇親会参加費・現地研修会参加費：消費税課税対象取引",
        "消費税課税対象取引への金額の上乗せはしていません．",
        "本学会は免税事業者で，適格請求書発行事業者の登録を",
        "しておらず，領収書には登録番号を記載していません．"
        ]
    FOOTER_2 = [
        "学会事務局",
        "〒100-0000" ,
        "東京都千代田区どこそこあれこれ",
        "大会支援株式会社  東京営業所内",
        "TEL: 03-0000-0000",
        "FAX: 03-0000-0000",
        "E-mail: shien@info.com"
        ]
    CONSTANT_STRINGS = (TITLE, CONGRESS, COMMITTEE_SUB, PRESIDENT, RECEIPT_DATE, FOOTER_1, FOOTER_2)


    ### 入力データ
    path_input = "名簿・領収書.xlsx"

    ### 出力ファイル名
    path_named_receipt = "receipt.pdf"
    path_empty_receipt = "receipt_empty.pdf"


    ############ 設定箇所おわり ############

    create_named_receipt(path_input, path_named_receipt, CONSTANT_STRINGS, font_name, img=img)
    create_empty_receipt(path_empty_receipt, CONSTANT_STRINGS, font_name)

    os.startfile(path_named_receipt)
    os.startfile(path_empty_receipt)
