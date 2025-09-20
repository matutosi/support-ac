from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

def create_empty_page(path_pdf, pagesize=A4, bleed=0):
    width  = pagesize[0] + bleed * 2 * mm # *2: both ends
    height = pagesize[1] + bleed * 2 * mm
    c = canvas.Canvas(path_pdf, pagesize=[width, height])
    c.showPage()
    c.save()

if __name__ == "__main__":
    path_pdf = "empty_page.pdf"
    pagesize = A4
    create_empty_page(path_pdf, pagesize = pagesize)
