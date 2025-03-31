from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4, portrait
from reportlab.pdfbase.ttfonts import TTFont
import os

def draw_string(p, x, y, 
                str, font_name=None, font_size=30, color="black",
                shape="rect",
                bg_color="white", 
                width=None, line_width=0.2*mm,
                align="left"):
    if bg_color!="white" and shape=="rect":
        p.setFillColor(bg_color)
        offset_x = font_size * 0.5
        offset_y = font_size * 0.5
        height = font_size * 2
        p.rect(x - offset_x, y - offset_y, width, height, stroke=0, fill=1)
    if bg_color!="white" and shape=="circle":
        p.setFillColor(bg_color)
        r =  font_size * 0.75
        offset_x = font_size * 0.48
        offset_y = font_size * 0.38
        p.circle(x + offset_x, y + offset_y, r, stroke=0, fill=1)
    if shape=="underlined":
        offset_y = -1*mm
        p.setLineWidth(line_width)
        p.line(x, y + offset_y, x + width, y + offset_y)
    p.setFillColor(color)
    p.setFont(font_name, font_size)
    if align == "left":
        p.drawString(x, y, str)
    if align == "center":
        x = x + width * 0.5
        p.drawCentredString(x, y, str)

# 
if __name__ == '__main__':

    # フォント登録
    # 源真ゴシック（ http://jikasei.me/font/genshin/）
    GEN_SHIN_GOTHIC_MEDIUM_TTF = "./GenShinGothic-Monospace-Medium.ttf"
    pdfmetrics.registerFont(TTFont('GenShinGothic', GEN_SHIN_GOTHIC_MEDIUM_TTF))

    path_file = "a.pdf"

    p = canvas.Canvas(path_file, pagesize=A4)

    x=10
    y=100
    str="あ"
    draw_string(p, x, y, str)

    x=10
    y=200
    str="研修会"
    color="white"
    bg_color="green"
    width=200
    draw_string(p, x, y, str, color=color, bg_color=bg_color, shape="rect", width=width)

    x=200
    y=300
    str="懇"
    color="white"
    bg_color="green"
    draw_string(p, x, y, str, color=color, bg_color=bg_color, shape="circle")

    p.save()

    os.startfile(path_file)
