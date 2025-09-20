import streamlit as st
from reportlab.lib.pagesizes import A4, A3, A5
from reportlab.lib.units import mm

from overlay_pdf import create_page_numbers
from overlay_pdf import create_session_numbers
from overlay_pdf import create_division
from overlay_pdf import overlay_pdf
from empty_page import create_empty_page
from combine_pdf import combine_pdfs
from convert_pdf_to_png import convert_pdf_to_png, add_border

def home():
    st.sidebar.success("Select")

def create():
    pagesize = A4
    width, height = pagesize

    with st.sidebar:

        create_obj = st.selectbox("作成するPDF", ("ページ番号", "発表番号", "区切り", "空白ページ"))

        if create_obj == "ページ番号":
            font_size = st.slider("Font size", value=12, min_value=8, max_value=60, step=1)
            start = st.number_input("開始ページ", value=1, min_value=1, max_value=100, step=1)
            end = st.number_input("終了ページ", value=50, min_value=1, max_value=999, step=1)
            centering_x = st.checkbox("横位置の中央揃え", value=True)
            if centering_x:
                x = None # width * 0.5 / mm 
            else:
                x = st.number_input("左端からの距離(mm)", value=10, min_value=0, max_value=100, step=1)
            y = st.number_input("下からの距離(mm)", value=10, min_value=0, max_value=100, step=1)
        if create_obj == "発表番号":
            font_size = st.slider("Font size", value=30, min_value=8, max_value=60, step=1)
            start = st.number_input("開始番号", value=1, min_value=1, max_value=100, step=1)
            end = st.number_input("終了番号", value=30, min_value=1, max_value=999, step=1)
            session = st.text_input("セッション名", "A")
            x = st.number_input("左端からの距離(mm)", value=20, min_value=0, max_value=100, step=1)
            y = st.number_input("上からの距離(mm)", value=20, min_value=0, max_value=100, step=1)
        if create_obj == "区切り":
            font_size = st.slider("Font size", value=30, min_value=8, max_value=60, step=1)
            division = st.text_input("区切り名", "区切り名")
            centering_x = st.checkbox("横位置の中央揃え", value=True)
            if centering_x:
                x = None # width * 0.5 / mm 
            else:
                x = st.number_input("左端からの距離(mm)", value=10, min_value=0, max_value=100, step=1)
            y = st.number_input("上からの距離(mm)", value=20, min_value=-3, max_value=300, step=1)
            height = st.number_input("帯の幅(mm)", value=40, min_value=0, max_value=100, step=10)
        if create_obj == "空白ページ":
            pass
        bleed = st.number_input("全体に余白追加(mm)", value=3, min_value=0, step=1)

    # create PDF, convert to PNG, and display
    if create_obj == "ページ番号": # page numbers
        path_page_numbers = "page_numbers.pdf"
        create_page_numbers(path_page_numbers, pagesize=pagesize, start=start, end=end, x=x, y=y, font_size=font_size, bleed=bleed)
        path_page_numbers_png = convert_pdf_to_png(path_page_numbers)
        add_border(path_page_numbers_png)
        st.download_button('PDFのダウンロード', open(path_page_numbers, 'br'), path_page_numbers)
        st.image(path_page_numbers_png)
    if create_obj == "発表番号":
        path_session_numbers = "session_numbers.pdf"
        create_session_numbers(path_session_numbers, pagesize=pagesize, start=start, end=end, pre=session, post="", x=x, y=y, font_size=font_size, bleed=bleed)
        path_session_numbers_png = convert_pdf_to_png(path_session_numbers)
        add_border(path_session_numbers_png)
        st.download_button('PDFのダウンロード', open(path_session_numbers, 'br'), path_session_numbers)
        st.image(path_session_numbers_png)
    if create_obj == "区切り":
        path_division = "division.pdf"
        create_division(path_division, pagesize=pagesize, str=division, x=x, y=y, height=height, font_size=font_size, bleed=bleed)
        path_division_png = convert_pdf_to_png(path_division)
        add_border(path_division_png)
        st.download_button('PDFのダウンロード', open(path_division, 'br'), path_division)
        st.image(path_division_png)
    if create_obj == "空白ページ":
        path_empty_page = "empty_page.pdf"
        create_empty_page(path_empty_page, pagesize=pagesize, bleed=bleed)
        path_empty_page_png = convert_pdf_to_png(path_empty_page)
        add_border(path_empty_page_png)
        st.download_button('PDFのダウンロード', open(path_empty_page, 'br'), path_empty_page)
        st.image(path_empty_page_png)

def overlay():
    with st.sidebar:
        pdf_base = st.file_uploader("基礎のPDF(下側)", type=["pdf"])
        pdf_overlay = st.file_uploader("重合わせPDF(上側)", type=["pdf"])

    if pdf_base is not None and pdf_overlay is not None:
        path_overlaid = "overalaid.pdf"
        overlay_pdf(pdf_base, pdf_overlay, path_overlaid)
        path_overalaid_png = convert_pdf_to_png(path_overlaid)
        add_border(path_overalaid_png)
        st.download_button('PDFのダウンロード', open(path_overlaid, 'br'), path_overlaid)
        st.image(path_overalaid_png)

def combine():
    with st.sidebar:
        pdf_files = st.file_uploader("結合するPDF", type=["pdf"], accept_multiple_files=True)
        st.write("ファイル名の順序で並べ替えて結合")

    if pdf_files != []:
        path_combined = "combined.pdf"
        pdf_files_sorted = sorted(pdf_files, key=lambda x: x.name)
        combine_pdfs(pdf_files_sorted, output=path_combined)
        st.download_button('PDFのダウンロード', open(path_combined, 'br'), path_combined)

page_names_to_funcs = {
    "home": home,
    "create": create,
    "overlay": overlay,
    "combime": combine,
}

page_name = st.sidebar.selectbox("select", page_names_to_funcs.keys())
page_names_to_funcs[page_name]()
