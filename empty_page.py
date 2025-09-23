from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

def create_empty_page(path_pdf, pagesize=A4, color=None, bleed=0):
    width  = pagesize[0] + bleed * 2 * mm # *2: both ends
    height = pagesize[1] + bleed * 2 * mm
    c = canvas.Canvas(path_pdf, pagesize=[width, height])
    if color is not None:
        c.setFillColor(color)
        c.rect(0, 0, c._pagesize[0], c._pagesize[1], stroke=0, fill=1)
    c.showPage()
    c.save()

if __name__ == "__main__":
    path_pdf = "empty_page.pdf"
    pagesize = A4
    create_empty_page(path_pdf, pagesize = pagesize)

    from reportlab.lib import colors
    path_pdf = "empty_page_color.pdf"
    pagesize = A4
    create_empty_page(path_pdf, pagesize = pagesize, color = colors.greenyellow, bleed=3)
