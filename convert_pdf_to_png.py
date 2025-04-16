import fitz  # PyMuPdf
from PIL import Image, ImageOps

def convert_pdf_to_png(pdf_path):
    """
    指定されたPDFファイルの1ページ目をPNG画像に変換
    Args:
        pdf_path (str): 変換するPDFファイルのパス
    """
    png_image = str(pdf_path).replace(".pdf", ".png")
    pdf_document = fitz.open(pdf_path)
    page = pdf_document.load_page(0)
    pix = page.get_pixmap() # Pixmap (画像) を取得
    pix.save(png_image, "png")
    pdf_document.close()
    return png_image

def add_border(path_img, border=1, border_color="black"):
    image = Image.open(path_img)
    bordered_image = ImageOps.expand(image, border=border, fill=border_color)
    bordered_image.save(path_img)
