from pathlib import Path
from PIL import Image # pillow

import streamlit as st
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# import custom modules
from receipt import create_named_receipt, create_empty_receipt
from convert_pdf_to_png import convert_pdf_to_png
from image import read_bz2

############ 設定箇所はじめ ############
### 源真ゴシック（ http://jikasei.me/font/genshin/）
### フォント登録
font_name = "GenShinGothic"
GEN_SHIN_GOTHIC_MEDIUM_TTF = "./GenShinGothic-Monospace-Medium.ttf"
pdfmetrics.registerFont(TTFont(font_name, GEN_SHIN_GOTHIC_MEDIUM_TTF))

st.set_page_config(
    page_title = "領収書作成",
    layout = "wide",
)

### 出力ファイル名
path_named_receipt = "receipt.pdf"
path_empty_receipt = "receipt_empty.pdf"

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
    TITLE         = st.text_input("タイトル"  , "領収書"                )
    CONGRESS      = st.text_input("大会名"    , "支援学会第100回大会"   )
    COMMITTEE_SUB = st.text_input("委員会"    , "支援学会大会支援委員会")
    PRESIDENT     = st.text_input("肩書・氏名", "会長 支援 太郎"        )
    RECEIPT_DATE  = st.text_input("年月日"    , "2025年10月10日"        )
    FOOTER_1 = st.text_area(
        "備考",
        "領収書について\n"
        "会員の大会参加費：不課税\n"
        "非会員の大会参加費：消費税課税対象取引\n"
        "懇親会参加費・現地研修会参加費：消費税課税対象取引\n"
        "消費税課税対象取引への金額の上乗せはしていません．\n"
        "本学会は免税事業者で，適格請求書発行事業者の登録を\n"
        "しておらず，領収書には登録番号を記載していません．\n",
        height=300,
        help="最大8行まで入力可能"
    ).split("\n")
    FOOTER_2 = st.text_area(
        "学会事務局",
        "〒100-0000\n" 
        "東京都千代田区どこそこあれこれ\n"
        "大会支援株式会社  東京営業所内\n"
        "TEL: 03-0000-0000\n"
        "FAX: 03-0000-0000\n"
        "E-mail: shien@info.com\n",
        height=180,
        help="最大8行まで入力可能"
    ).split("\n")
    CONSTANT_STRINGS = (TITLE, CONGRESS, COMMITTEE_SUB, PRESIDENT, RECEIPT_DATE, FOOTER_1, FOOTER_2)

    img = None
    use_stamp_example = st.checkbox("use stamp example", value=True)
    if use_stamp_example:
        img = "stamp.png"
    else:
        use_png = st.checkbox("use PNG", value=True)
        if use_png:
            img = st.file_uploader("押印用画像", type=["png"])
            if img:
                Image.open(img).save(img.name, "png")
                img = img.name
        else:
            bz2 = st.file_uploader("bz2", type=["bz2"])
            bz2_shape = st.file_uploader("shape", type=["txt"])
            if bz2 and bz2_shape:
                Path(bz2.name).write_bytes(bz2.getvalue())
                Path(bz2_shape.name).write_text(bz2_shape.getvalue().decode("utf-8"))
                img = read_bz2(bz2.name, bz2_shape.name)

############ 設定箇所おわり ############

if path_input:
    create_named_receipt(path_input, path_named_receipt, CONSTANT_STRINGS=CONSTANT_STRINGS, font_name=font_name, img=img)
    create_empty_receipt(path_empty_receipt, CONSTANT_STRINGS=CONSTANT_STRINGS, font_name=font_name)

    path_named_png = convert_pdf_to_png(path_named_receipt)
    path_empty_png = convert_pdf_to_png(path_empty_receipt)

    col1, col2 = st.columns(2)

    with col1:
        st.image(path_named_png, "事前申込(p1)")
        st.download_button('PDFのダウンロード', open(path_named_receipt, 'br'), path_named_receipt)

    with col2:
        st.image(path_empty_png, "当日用")
        st.download_button('PDFのダウンロード', open(path_empty_receipt, 'br'), path_empty_receipt)

