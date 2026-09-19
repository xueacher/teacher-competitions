# -*- coding: utf-8 -*-
"""生成应用图标 icon-192.png / icon-512.png（蓝底白字"赛"）"""
from PIL import Image, ImageDraw, ImageFont
import os

ROOT = os.path.dirname(os.path.abspath(__file__))

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",   # 微软雅黑 Bold
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


def get_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return None


def make_icon(size):
    img = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(img)
    # 蓝色渐变背景
    for y in range(size):
        t = y / size
        r = int(37 + (79 - 37) * t)    # #2563eb -> #4f46e5
        g = int(99 + (70 - 99) * t)
        b = int(235 + (229 - 235) * t)
        d.line([(0, y), (size, y)], fill=(r, g, b))
    # 圆角遮罩（简单起见画纯色底+白色圆角框，直接输出方形在主流系统也会被裁圆）
    font = get_font(int(size * 0.62))
    if font:
        text = "赛"
        bbox = d.textbbox((0, 0), text, font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1] - size * 0.02),
               text, font=font, fill=(255, 255, 255))
    return img


for s in (192, 512):
    make_icon(s).save(os.path.join(ROOT, "icon-%d.png" % s), optimize=True)
print("图标已生成: icon-192.png, icon-512.png")
