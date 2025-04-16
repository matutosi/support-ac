import fitz  # PyMuPdf
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

def create_session_number(c, x, y, str, font_name=None, font_size=None):
    if font_size:
        c.setFontSize(font_size)
        if font_name:
            c.setFont(font_name, font_size)
    c.drawString(x * mm, y * mm, str)

def create_session_numbers(path_pdf, pagesize=A4, start=1, end=1, pre="A", post="", x=20, y=20, font_name=None, font_size=30):
    c = canvas.Canvas(path_pdf, pagesize=pagesize)
    y = (pagesize[1] / mm) - y
    for i in range(start, end + 1):
        str = f'{pre}{i:02}{post}'
        create_number_page(c, x, y, str, font_name, font_size)
        c.showPage()
    c.save()

def create_number_page(c, x, y, str, font_name=None, font_size=None):
    if font_size:
        c.setFontSize(font_size)
        if font_name:
            c.setFont(font_name, font_size)
    c.drawCentredString(x * mm, y * mm, str)

def create_number_pages(path_pdf, pagesize=A4, start=1, end=1, pre="- ", post=" -", x=None, y=10, font_name=None, font_size=None):
    c = canvas.Canvas(path_pdf, pagesize=pagesize)
    if x is None:
        x = (pagesize[0]/ 2) / mm # Centering the text horizontally
    for i in range(start, end + 1):
        str = f'{pre}{i}{post}'
        create_number_page(c, x, y, str, font_name, font_size)
        c.showPage()
    c.save()

def overlay_pdf(background_path, overlay_path, output_path):
    background_doc = fitz.open(background_path)
    overlay_doc = fitz.open(overlay_path)
    for background_page, overlay_page in zip(background_doc, overlay_doc):
        background_page.show_pdf_page(background_page.rect, overlay_doc, overlay_page.number)
    background_doc.save(output_path)
    background_doc.close()
    overlay_doc.close()

if __name__ == "__main__":
    # pdfmetrics.registerFont(TTFont(font_name, "path_to_font.ttf"))  # Register the font if needed

    ### 源真ゴシック（ http://jikasei.me/font/genshin/）
    ### フォント登録
    font_name = "GenShinGothic"
    GEN_SHIN_GOTHIC_MEDIUM_TTF = "./GenShinGothic-Monospace-Medium.ttf"
    pdfmetrics.registerFont(TTFont(font_name, GEN_SHIN_GOTHIC_MEDIUM_TTF))

    # create page_numbers
    path_pagenumbers = "page_numbers.pdf"
    pagesize = A4
    y = 10  # Y coordinate in mm
    font_size = 12  # Font size
    # create_number_pages(path_pdf, pagesize=A4, start=1, end=1, pre="- ", post=" -", x=None, y=10, font_name=None, font_size=None):
    create_number_pages(path_pagenumbers, pagesize, start=1, end=100, y=y, font_size=font_size)

    # session numbers
    path_session_a = "session_a.pdf"
    create_session_numbers(path_session_a, pagesize, start=1, end=30, pre="A")
    path_session_a = "session_b.pdf"
    create_session_numbers(path_session_a, pagesize, start=1, end=30, pre="B")
    path_session_a = "session_p.pdf"
    create_session_numbers(path_session_a, pagesize, start=1, end=30, pre="P")

    # overlay session numbers on page numbers
    path_overlaid = "overlaid.pdf"
    overlay_pdf(path_session_a, path_pagenumbers, path_overlaid)
