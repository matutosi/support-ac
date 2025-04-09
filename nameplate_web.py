import os
import sys
from pathlib import Path
import streamlit as st
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# import custom modules
from nameplate import create_named_nameplate, create_empty_nameplate
from convert_pdf_to_png import convert_pdf_to_png

############ 設定箇所はじめ ############
### 源真ゴシック（ http://jikasei.me/font/genshin/）
### フォント登録
font_name = "GenShinGothic"
GEN_SHIN_GOTHIC_MEDIUM_TTF = "./GenShinGothic-Monospace-Medium.ttf"
pdfmetrics.registerFont(TTFont(font_name, GEN_SHIN_GOTHIC_MEDIUM_TTF))

st.set_page_config(
    page_title = "名札作成",
    layout = "wide",
)

### 出力ファイル名
path_named_plate = "nameplate.pdf"
path_empty_plate = "nameplate_empty.pdf"

settings = st.sidebar

with settings:
    ### 入力ファイル
    use_example = st.checkbox("use example", value=True)
    if use_example:
        path_input = "名簿・領収書.xlsx"
        st.download_button('Excelファイルのダウンロード', open(path_input, 'br'), path_input)
    else:
        path_input = st.file_uploader("名簿ファイル", type=["xlsx"])

    ### 大会情報
    CONGRESS       = st.text_input("大会名" , "支援学会第100回大会")
    congress_color = st.color_picker("大会名の背景色", "#00a960")
    CONG_DATE      = st.text_input("年月日" , "2025年10月10日")
    COMMITTEE      = st.text_input("委員会1", "支援学会第100回大会実行委員会")
    COMMITTEE_SUB  = st.text_input("委員会2", "支援学会大会支援委員会")
    PLACE          = st.text_input("場所"   , "支援大学")
    SHOZOKU        = st.text_input("所属"   , "所属")
    SIMEI          = st.text_input("氏名"   , "氏名")
    CONSTANT_STRINGS = (CONGRESS, CONG_DATE, COMMITTEE, COMMITTEE_SUB, PLACE, SHOZOKU, SIMEI)
        
############ 設定箇所おわり ############

if path_input:
    create_named_nameplate(path_input, path_named_plate, congress_color, CONSTANT_STRINGS=CONSTANT_STRINGS, font_name=font_name)
    create_empty_nameplate(path_empty_plate, congress_color, CONSTANT_STRINGS=CONSTANT_STRINGS, font_name=font_name)

    path_named_png = convert_pdf_to_png(path_named_plate)
    path_empty_png = convert_pdf_to_png(path_empty_plate)

    col1, col2 = st.columns(2)

    with col1:
        st.image(path_named_png, "事前申込(p1)")
        st.download_button('PDFのダウンロード', open(path_named_plate, 'br'), path_named_plate)

    with col2:
        st.image(path_empty_png, "当日用")
        st.download_button('PDFのダウンロード', open(path_empty_plate, 'br'), path_empty_plate)
