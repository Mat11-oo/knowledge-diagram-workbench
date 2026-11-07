"""Deterministic PNG compositor. Measures every glyph; refuses missing/overflow text."""

import hashlib
import io
import json
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .repository import DomainError

FONT = Path(__file__).resolve().parents[2] / "assets/fonts/NotoSansCJKsc-Regular.otf"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def supported_codepoints():
    # Read the font's Unicode cmap without adding a font-tools runtime dependency.
    data = FONT.read_bytes()
    count = struct.unpack_from(">H", data, 4)[0]
    cmap = None
    for i in range(count):
        tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + i * 16)
        if tag == b"cmap":
            cmap = offset
            break
    if cmap is None:
        raise DomainError("FONT_UNAVAILABLE", "中文字体无法读取", 503)
    ranges = []
    for i in range(struct.unpack_from(">H", data, cmap + 2)[0]):
        _, _, relative = struct.unpack_from(">HHI", data, cmap + 4 + i * 8)
        offset = cmap + relative
        if struct.unpack_from(">H", data, offset)[0] == 12:
            for n in range(struct.unpack_from(">I", data, offset + 12)[0]):
                start, end, glyph = struct.unpack_from(">III", data, offset + 16 + n * 12)
                if glyph:
                    ranges.append((start, end))
    return ranges


def lines_for(text, font, width, draw):
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for char in paragraph.expandtabs(2):
            if draw.textlength(line + char, font=font) > width and line:
                lines.append(line)
                line = ""
            line += char
        lines.append(line)
    return lines


def fit(draw, text, width, height, maximum, minimum):
    for size in range(maximum, minimum - 1, -2):
        font = ImageFont.truetype(str(FONT), size)
        lines = lines_for(text, font, width, draw)
        step = int(size * 1.5)
        if len(lines) * step <= height:
            return font, lines, step
    raise DomainError("TEXT_OVERFLOW", "卡片文字太多，排版会溢出；请缩短文字后重新导出", 422)


def render(card, image_path, index, total, source_title, image_label="AI 生成插图"):
    ranges = supported_codepoints()
    # Footer source title is full text: no silent ellipsizing of source/claim text.
    for text in (card["title"], card["body"], source_title):
        if any(not c.isspace() and not any(a <= ord(c) <= b for a, b in ranges) for c in text):
            raise DomainError(
                "GLYPH_UNSUPPORTED", "文字中含字体不支持的字符，请替换表情或特殊符号后导出", 422
            )
    dark = card["template"] == "ink"
    bg, fg, muted = ("#25372f", "#f6f3e8", "#b8c6b8") if dark else ("#f5f1e7", "#293a30", "#657562")
    image = Image.new("RGB", (1080, 1920), bg)
    draw = ImageDraw.Draw(image)
    small = ImageFont.truetype(str(FONT), 27)
    draw.text((80, 65), f"知识图解   /   {index:02d} — {total:02d}", fill=muted, font=small)
    label = "补充说明" if card["kind"] == "supplement" else "原文提炼"
    if card["edited"]:
        label += " · 文案经编辑"
    draw.text((80, 124), label, fill=muted, font=small)
    title_font, titles, title_step = fit(draw, card["title"], 920, 230, 70, 40)
    y = 206
    for line in titles:
        draw.text((80, y), line, fill=fg, font=title_font)
        y += title_step
    if image_path:
        with Image.open(image_path) as illustration:
            draw_image = ImageOps.fit(illustration.convert("RGB"), (920, 580))
        image.paste(draw_image, (80, 470))
        draw.text((80, 1063), image_label, fill=muted, font=small)
    else:
        draw.rounded_rectangle((80, 470, 1000, 1050), radius=12, outline=muted, width=2)
        draw.text((370, 735), "插图尚未生成", fill=muted, font=small)
    font, lines, step = fit(draw, card["body"], 920, 535, 46, 28)
    y = 1150
    for line in lines:
        draw.text((80, y), line, fill=fg, font=font)
        y += step
    draw.line((80, 1730, 1000, 1730), fill=muted, width=2)
    font, lines, step = fit(draw, "来源：" + source_title, 920, 105, 26, 18)
    y = 1750
    for line in lines:
        draw.text((80, y), line, fill=muted, font=font)
        y += step
    draw.text(
        (80, 1870),
        "知识图解工作台 · 内容请结合原文核对",
        fill=muted,
        font=ImageFont.truetype(str(FONT), 22),
    )
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()
