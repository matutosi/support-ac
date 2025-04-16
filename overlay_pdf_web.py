import streamlit as st
from reportlab.lib.pagesizes import A4, A3, A5
from reportlab.lib.units import mm

from overlay_pdf import create_number_pages, create_session_numbers, overlay_pdf
from convert_pdf_to_png import convert_pdf_to_png, add_border

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

def create():

    with st.sidebar:

        create_obj = st.selectbox("作成するPDF", ("ページ番号", "発表番号"))

        pagesize = A4
        width, height = pagesize

        if create_obj == "ページ番号":
            font_size = st.slider("Font size", value=12, min_value=8, max_value=60, step=1)
            start = st.number_input("開始ページ", value=1, min_value=1, max_value=100, step=1)
            end = st.number_input("終了ページ", value=50, min_value=1, max_value=999, step=1)
            centering_x = st.checkbox("横位置の中央揃え", value=True)
            if centering_x:
                x = width * 0.5 / mm 
            else:
                x = st.number_input("左端からの距離(mm)", value=10, min_value=0, max_value=100, step=1)
            y = st.number_input("下からの距離(mm)", value=10, min_value=0, max_value=100, step=1)        
        else:
            font_size = st.slider("Font size", value=30, min_value=8, max_value=60, step=1)
            start = st.number_input("開始番号", value=1, min_value=1, max_value=100, step=1)
            end = st.number_input("終了番号", value=30, min_value=1, max_value=999, step=1)
            session = st.text_input("セッション名", "A")
            x = st.number_input("左端からの距離(mm)", value=20, min_value=0, max_value=100, step=1)
            y = st.number_input("上からの距離(mm)", value=20, min_value=0, max_value=100, step=1)


    # create PDF, convert to PNG, and display
    if create_obj == "ページ番号": # page numbers
        path_page_numbers = "page_numbers.pdf"
        create_number_pages(path_page_numbers, pagesize, start=start, end=end, x=x, y=y, font_size=font_size)
        path_page_numbers_png = convert_pdf_to_png(path_page_numbers)
        add_border(path_page_numbers_png)
        st.download_button('PDFのダウンロード', open(path_page_numbers, 'br'), path_page_numbers)
        st.image(path_page_numbers_png)
    else: # session numbers
        path_session_numbers = "session_numbers.pdf"
        create_session_numbers(path_session_numbers, pagesize, start=start, end=end, pre=session, post="", x=x, y=y, font_size=font_size)
        path_session_numbers_png = convert_pdf_to_png(path_session_numbers)
        add_border(path_session_numbers_png)
        st.download_button('PDFのダウンロード', open(path_session_numbers, 'br'), path_session_numbers)
        st.image(path_session_numbers_png)

def home():
    st.sidebar.success("Select")

page_names_to_funcs = {
    "home": home,
    "create": create,
    "overlay": overlay
}
demo_name = st.sidebar.selectbox("select", page_names_to_funcs.keys())
page_names_to_funcs[demo_name]()

