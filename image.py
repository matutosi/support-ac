import bz2
import csv
import numpy as np
from PIL import Image # pillow
from reportlab.lib.utils import ImageReader

def read_bz2(bz2_file, shape_file):
    """
    bz2とshapeを読み込み・解凍して，PILのImageReaderオブジェクトを返す
    """
    with bz2.open(bz2_file, 'rb') as f:
        uncompressed_data = f.read()
    with open(shape_file, 'r') as f_shape:
        reader = csv.reader(f_shape)
        shape_str = [row for row in reader][0]
        shape_int = [int(str) for str in shape_str]
    np_data = np.frombuffer(uncompressed_data, dtype = np.uint8)
    img = Image.fromarray(np_data.reshape(shape_int[0], shape_int[1], shape_int[2],))
    img_reader = ImageReader(img)
    return img_reader

def compress_png_to_bz2(input_file, output_file):
    """
    PNG画像を読み込み，bz2形式に圧縮して保存
    Args:
        input_file (str): 入力PNGファイルのパス．
        output_file (str): 出力bz2ファイルのパス．
    """
    try:
        img = Image.open(input_file)
        img_array = np.array(img)
        img_bytes = img_array.tobytes()
        with bz2.open(output_file, 'wb') as f:
            f.write(img_bytes)
        print(f"画像を {output_file} に保存しました．")
        img_shape = img_array.shape
        output_shape = output_file + ".txt"
        with open(output_shape, 'w', encoding='utf-8') as f_csv:
            writer = csv.writer(f_csv)
            writer.writerows([img_shape])
        print(f"shapeを {output_shape} に保存しました．")
    except FileNotFoundError:
        print(f"エラー：ファイル {input_file} が見つかりません．")
    except Exception as e:
        print(f"エラーが発生しました：{e}")
    return output_file, output_shape


if __name__ == '__main__':

    input_file = 'stamp.png' # 元の画像
    output_file = 'stamp.bz2' # bz2形式
    # 圧縮して，bz2とshapeを返す
    bz2_file, shape_file = compress_png_to_bz2(input_file, output_file)
    # bz2とshapeから画像を復元し，reportlabのImageReaderオブジェクトを返す
    read_bz2(bz2_file, shape_file)
