"""分镜驱动的二维知识动画：25fps 逐帧插值，画面内元素真正运动。

动画规则（每条旁白短句内部）：
- 该句首次进入某个步骤时，节点依次缩放淡入，连线从头生长到位，当前步骤高亮扫过；
- 同一句的后续时间里保持稳定，只留一个很轻的高亮呼吸，避免抖动；
- 说明面板从下方滑入，字幕淡入。

不做的事：不使用视频生成模型，不画任意可执行内容，画面完全由已确认的分镜结构决定。
"""

import math
import subprocess
import time
import wave

import imageio_ffmpeg
from PIL import Image, ImageDraw

from .render_cards import fit, supported_codepoints
from .repository import DomainError

FPS = 25
WIDTH, HEIGHT = 1080, 1920

BG = (245, 241, 231)
INK = (37, 55, 47)
MUTED = (150, 162, 150)
NODE_IDLE = (225, 231, 223)
NODE_ACTIVE = (180, 217, 191)
STROKE_IDLE = (141, 154, 142)
STROKE_ACTIVE = (40, 118, 83)
LINK_IDLE = (169, 181, 170)
LINK_DONE = (59, 135, 103)
PANEL = (255, 255, 255)
PANEL_TEXT = (54, 70, 59)


def ffmpeg(args, timeout=600):
    try:
        process = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
             *map(str, args)],
            capture_output=True, timeout=timeout, check=False,
        )
        if process.returncode:
            raise DomainError("RENDER_FAILED", "视频工具未能完成处理，音频与旧视频仍保留", 502)
    except (OSError, subprocess.TimeoutExpired):
        raise DomainError("RENDER_TIMEOUT", "视频处理失败或超时，已保留原文件和任务", 504) from None


def normalize(source, target):
    ffmpeg(["-i", source, "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", target], 60)
    with wave.open(str(target)) as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 24000:
            raise DomainError("AUDIO_INVALID", "音频格式无法校验", 502)
        frames = audio.getnframes()
        if not 2400 <= frames <= 24_000 * 25:
            raise DomainError("AUDIO_DURATION", "单句配音时长不在可用范围内", 422)
        return math.ceil(frames / 960) * 40  # 向上对齐 25fps 帧边界，补静音不足 40ms


# ---------- 插值工具 ----------

def clamp(value, low=0.0, high=1.0):
    return low if value < low else high if value > high else value


def progress(time_s, start, duration):
    """在 [start, start+duration] 区间内返回 0→1，之外夹紧。"""
    if duration <= 0:
        return 1.0 if time_s >= start else 0.0
    return clamp((time_s - start) / duration)


def ease_out(value):
    return 1.0 - (1.0 - value) ** 3


def ease_in_out(value):
    return value * value * (3 - 2 * value)


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def node_positions(steps, template):
    """按模板给出每个节点的中心点。"""
    count = len(steps)
    span = max(1, count - 1)
    positions = []
    for index in range(count):
        x = 120 + (840 * index // span)
        if template == "relation":
            y = 500 + (index % 2) * 320
        elif template == "compare":
            y = 420 if index % 2 == 0 else 650
        else:  # flow
            y = 620
        positions.append((x, y))
    return positions


# ---------- 单帧绘制 ----------

class ScenePainter:
    """一个分镜片段的绘制器：背景与标题只画一次，每帧只画会动的部分。"""

    def __init__(self, piece):
        self.steps = piece["scene_steps"]
        self.active = int(piece["scene_step_index"])
        self.template = piece["scene_template"]
        self.positions = node_positions(self.steps, self.template)
        self.enter = bool(piece.get("is_step_entry", True))
        # 标题与字幕的排版结果缓存下来，避免每帧重新测字
        probe = ImageDraw.Draw(Image.new("RGB", (WIDTH, HEIGHT), BG))
        self.title_font, self.title_lines, self.title_step = fit(
            probe, piece["scene_title"], 940, 100, 42, 28
        )
        self.caption_font, self.caption_lines, self.caption_step = fit(
            probe, piece["text"], 920, 230, 54, 36
        )
        detail = self.steps[self.active]["detail"]
        self.detail_font, self.detail_lines, self.detail_step = fit(
            probe, detail, 900, 210, 30, 20
        )
        self.label_fonts = [
            fit(probe, step["label"], 190, 70, 34, 22) for step in self.steps
        ]
        self.base = Image.new("RGB", (WIDTH, HEIGHT), BG)
        base_draw = ImageDraw.Draw(self.base)
        for index, line in enumerate(self.title_lines[:2]):
            base_draw.text((70, 60 + index * self.title_step), line, fill=INK,
                           font=self.title_font)

    def draw(self, time_s, duration_s):
        frame = self.base.copy()
        draw = ImageDraw.Draw(frame)
        intro = 0.0 if not self.enter else 1.0

        self._draw_links(draw, time_s, intro)
        self._draw_nodes(draw, time_s, intro)
        self._draw_panel(draw, time_s, duration_s)
        self._draw_caption(draw, time_s)
        return frame

    def _node_alpha(self, index, time_s, intro):
        """节点出现进度：进入新步骤时依次错开，否则直接满。"""
        if not intro:
            return 1.0
        if index > self.active:
            return 0.0
        # 每个节点错开 0.12 秒，从当前步骤往前推
        delay = max(0, self.active - index) * 0.08
        return ease_out(progress(time_s, delay, 0.34))

    def _draw_links(self, draw, time_s, intro):
        for index in range(len(self.positions) - 1):
            x1, y1 = self.positions[index]
            x2, y2 = self.positions[index + 1]
            start = (x1, y1 + 85)
            end = (x2, y2 + 85)
            done = index < self.active
            if index == self.active:
                grow = ease_in_out(progress(time_s, 0.28, 0.5)) if intro else 1.0
            else:
                grow = 1.0 if done else 0.0
            if grow <= 0:
                continue
            color = LINK_DONE if index < self.active else LINK_IDLE
            tip = (start[0] + (end[0] - start[0]) * grow,
                   start[1] + (end[1] - start[1]) * grow)
            draw.line((start, tip), fill=color, width=12)
            # 箭头只在基本走完时画出来，避免半截箭头乱飘
            if grow > 0.86:
                angle = math.atan2(end[1] - start[1], end[0] - start[0])
                head = (end[0] - math.cos(angle) * 10, end[1] - math.sin(angle) * 10)
                span = 20
                draw.polygon([
                    (head[0] - math.cos(angle - 0.5) * span, head[1] - math.sin(angle - 0.5) * span),
                    (head[0] - math.cos(angle + 0.5) * span, head[1] - math.sin(angle + 0.5) * span),
                    (end[0] + math.cos(angle) * 6, end[1] + math.sin(angle) * 6),
                ], fill=color)

    def _draw_nodes(self, draw, time_s, intro):
        for index, (x, y) in enumerate(self.positions):
            alpha = self._node_alpha(index, time_s, intro)
            if alpha <= 0.01:
                continue
            is_active = index == self.active
            # 当前步骤持续呼吸：填充与描边随时间轻微起伏，视线跟着走
            pulse = (0.5 + 0.5 * math.sin(time_s * 3.0)) if is_active else 0.0
            fill_base = NODE_ACTIVE if is_active else NODE_IDLE
            if is_active:
                fill_base = mix(NODE_ACTIVE, (206, 232, 213), pulse * 0.8)
            fill = mix(BG, fill_base, alpha)
            stroke = mix(BG, STROKE_ACTIVE if is_active else STROKE_IDLE, alpha)
            half_w = 115 * (0.86 + 0.14 * alpha)
            half_h = 85 * (0.86 + 0.14 * alpha)
            if is_active:
                half_w += 3 * pulse
                half_h += 3 * pulse
            width = int(3 + (2 if is_active else 0) + (4 * pulse if is_active else 0))
            draw.rounded_rectangle(
                (x - half_w, y + 85 - half_h, x + half_w, y + 85 + half_h),
                radius=24, fill=fill, outline=stroke, width=max(2, width),
            )
            label_font, label_lines, label_step = self.label_fonts[index]
            if is_active:
                text_color = mix(BG, INK, alpha)
            else:
                text_color = mix(BG, (78, 90, 79), alpha)
            for line_no, line in enumerate(label_lines[:2]):
                text_width = draw.textlength(line, font=label_font)
                draw.text(
                    (x - text_width / 2, y + 85 - len(label_lines[:2]) * label_step / 2
                     + line_no * label_step),
                    line, fill=text_color, font=label_font,
                )

    def _draw_panel(self, draw, time_s, duration_s):
        # 面板滑入：前 0.4 秒从下方 18px 升到位并淡入
        appear = ease_out(progress(time_s, 0.1, 0.4))
        top = 1120 + int(18 * (1 - appear))
        bottom = top + 312
        fill = mix(BG, PANEL, appear)
        stroke = mix(BG, (169, 181, 170), appear)
        draw.rounded_rectangle((70, top, 1010, bottom), radius=20, fill=fill,
                               outline=stroke, width=3)
        if appear <= 0.02:
            return
        head = mix(BG, STROKE_ACTIVE, appear)
        draw.text((100, top + 30), f"当前讲解：{self.steps[self.active]['label']}",
                  fill=head, font=self.title_font)
        body = mix(BG, PANEL_TEXT, appear)
        for line_no, line in enumerate(self.detail_lines[:5]):
            draw.text((100, top + 100 + line_no * self.detail_step), line, fill=body,
                      font=self.detail_font)
        # 旁白进度条：这一句还要讲多久，画面上能看出来
        ratio = clamp(time_s / duration_s) if duration_s > 0 else 1.0
        track_top = bottom - 26
        draw.rounded_rectangle((100, track_top, 980, track_top + 8), radius=4,
                               fill=mix(BG, (228, 233, 226), appear))
        filled = 100 + int((980 - 100) * ratio)
        if filled > 102:
            draw.rounded_rectangle((100, track_top, filled, track_top + 8), radius=4,
                                   fill=mix(BG, LINK_DONE, appear))

    def _draw_caption(self, draw, time_s):
        appear = ease_out(progress(time_s, 0.05, 0.25))
        if appear <= 0.02:
            return
        color = mix(BG, INK, appear)
        total = len(self.caption_lines)
        y = 1640 + (230 - total * self.caption_step) // 2
        for line in self.caption_lines:
            draw.text(((WIDTH - draw.textlength(line, font=self.caption_font)) // 2, y),
                      line, fill=color, font=self.caption_font)
            y += self.caption_step


# ---------- 片段编码（原始帧直接送进 ffmpeg，不落 PNG，快很多） ----------

def encode_clip(painter, duration_ms, target, fade_in, fade_out, deadline):
    frames = max(1, round(duration_ms / 1000 * FPS))
    seconds = duration_ms / 1000.0
    filters = []
    if fade_in:
        filters.append("fade=t=in:st=0:d=0.12")
    if fade_out and seconds > 0.2:
        filters.append(f"fade=t=out:st={seconds - 0.12:.3f}:d=0.12")
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}",
        "-framerate", str(FPS), "-i", "pipe:0",
        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-threads", "2",
    ]
    if filters:
        command += ["-vf", ",".join(filters)]
    command.append(str(target))
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError:
        raise DomainError("RENDER_FAILED", "视频工具未能启动，已保留音频与旧视频", 502) from None
    try:
        for index in range(frames):
            if time.monotonic() > deadline:
                process.kill()
                raise DomainError("RENDER_TIMEOUT", "视频渲染超时，已保留音频与旧视频", 504)
            time_s = (index / FPS)
            frame = painter.draw(time_s, seconds)
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        process.stderr.read()
        code = process.wait()
        if code:
            raise DomainError(
                "RENDER_FAILED", "视频编码未完成，音频与旧视频仍保留", 502
            )
    finally:
        if process.poll() is None:
            process.kill()
        process.stderr.close()
    return seconds


def render_video(directory, pieces, target, min_ms=30_000, max_ms=60_000):
    deadline = time.monotonic() + 900
    duration = sum(p["duration_ms"] for p in pieces)
    if not min_ms <= duration <= max_ms:
        raise DomainError(
            "VIDEO_DURATION", "实际配音总时长不在30–60秒内，请调整旁白；已完成音频会复用", 422
        )
    ranges = supported_codepoints()
    # 同一分镜同一句首次出现时才算「进入新步骤」，其余句子保持静止，省算力也不抖
    seen_steps = set()
    for piece in pieces:
        if any(not c.isspace() and not any(a <= ord(c) <= b for a, b in ranges)
               for c in piece["text"]):
            raise DomainError("GLYPH_UNSUPPORTED", "字幕含字体不支持的字符，请修改后再导出", 422)
        key = (piece["scene_id"], piece["scene_step_index"])
        piece["is_step_entry"] = key not in seen_steps
        seen_steps.add(key)

    paths, timeline, cursor = [], [], 0
    audio_path = directory / "combined.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        for index, piece in enumerate(pieces):
            painter = ScenePainter(piece)
            fade_in = index == 0 or pieces[index - 1]["card_id"] != piece["card_id"]
            fade_out = (index == len(pieces) - 1
                        or pieces[index + 1]["card_id"] != piece["card_id"])
            clip_path = directory / f"{index:03d}.mp4"
            encode_clip(painter, piece["duration_ms"], clip_path, fade_in, fade_out, deadline)
            paths.append(clip_path)
            with wave.open(str(piece["audio_path"])) as source:
                pcm = source.readframes(source.getnframes())
            required = piece["duration_ms"] * 24 * 2
            audio.writeframes(pcm + b"\0" * (required - len(pcm)))
            timeline.append({
                "text": piece["text"],
                "card_id": piece["card_id"],
                "audio_id": piece["audio_id"],
                "scene_id": piece["scene_id"],
                "scene_step_index": piece["scene_step_index"],
                "start_ms": cursor,
                "end_ms": cursor + piece["duration_ms"],
            })
            cursor += piece["duration_ms"]

    listing = directory / "clips.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in paths))
    ffmpeg([
        "-f", "concat", "-safe", "1", "-i", listing, "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-shortest", target,
    ], max(1, deadline - time.monotonic()))
    return timeline, duration
