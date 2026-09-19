"""入出力のパスをまとめる．

どこから起動しても同じ場所を指すように，このファイルの位置を基準にする．
- assets/ … フォント・印影・名簿の見本 (追跡する)
- output/ … 生成した PDF・PNG (追跡しない)
"""
from pathlib import Path

ROOT   = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output"

# 源真ゴシック（ http://jikasei.me/font/genshin/）
FONT_GENSHIN  = str(ASSETS / "GenShinGothic-Monospace-Medium.ttf")
STAMP_PNG     = str(ASSETS / "stamp.png")
STAMP_BZ2     = str(ASSETS / "stamp.bz2")
STAMP_BZ2_TXT = str(ASSETS / "stamp.bz2.txt")
ROSTER_XLSX   = str(ASSETS / "名簿・領収書.xlsx")

def output_path(name):
    """output/ の下のパスを返す (output/ は追跡しないので，無ければ作る)．"""
    OUTPUT.mkdir(exist_ok=True)
    return str(OUTPUT / name)
