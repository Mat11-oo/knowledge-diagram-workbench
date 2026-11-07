"""Official Beijing Qwen3 TTS: no retries, character accounting, bounded private download."""

import os
import re
from urllib.parse import urlsplit, urlunsplit

import httpx

from .repository import DomainError

MICRO_PER_CHAR = 80


class TTSProvider:
    def __init__(self):
        self.key = os.getenv("DASHSCOPE_API_KEY", "")
        self.model = os.getenv("KNOWLEDGE_TTS_MODEL", "qwen3-tts-flash")
        self.voice = os.getenv("KNOWLEDGE_TTS_VOICE", "Cherry")
        self.base = os.getenv("KNOWLEDGE_TTS_BASE_URL", "https://dashscope.aliyuncs.com").rstrip(
            "/"
        )
        self.enabled = os.getenv("KNOWLEDGE_ALLOW_TTS", "0") == "1"
        self.pricing_confirmed = os.getenv("KNOWLEDGE_TTS_PRICING_CONFIRMED", "0") == "1"

    def ready(self):
        if not self.key or not self.enabled or not self.pricing_confirmed:
            raise DomainError("TTS_DISABLED", "真实配音尚未配置或授权，本次没有调用", 403)
        if (
            self.model != "qwen3-tts-flash"
            or self.voice != "Cherry"
            or not (
                self.base == "https://dashscope.aliyuncs.com"
                or re.fullmatch(
                    r"https://[a-zA-Z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com", self.base
                )
            )
        ):
            raise DomainError("TTS_NOT_ALLOWED", "仅启用已选北京地域Qwen3及Cherry系统音色", 400)

    def synthesize(self, text):
        self.ready()
        try:
            with httpx.Client(timeout=60, trust_env=False, follow_redirects=False) as client:
                response = client.post(
                    self.base + "/api/v1/services/aigc/multimodal-generation/generation",
                    headers={"Authorization": "Bearer " + self.key},
                    json={
                        "model": self.model,
                        "input": {"text": text, "voice": self.voice, "language_type": "Chinese"},
                    },
                )
                response.raise_for_status()
                data = response.json()
                count = data["usage"]["characters"]
                if type(count) is not int or count <= 0:
                    raise ValueError()
                if data.get("code") or data["output"]["finish_reason"] != "stop":
                    raise ValueError()
                return {
                    "url": data["output"]["audio"]["url"],
                    "characters": count,
                    "request_id": str(data.get("request_id", ""))[:160],
                }
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise DomainError(
                "TTS_UNCERTAIN", "配音请求结果或用量无法核对，已停止，不自动重发", 502
            ) from None

    def download(self, url):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
            or not re.fullmatch(r"[a-z0-9-]+\.oss[a-z0-9-]*\.aliyuncs\.com", parsed.hostname or "")
        ):
            raise DomainError("AUDIO_URL_REJECTED", "配音文件地址不是受支持的官方存储", 502)
        # Official responses may contain HTTP URLs: upgrade to HTTPS before transmitting anything.
        secure_url = urlunsplit(("https", parsed.hostname, parsed.path, parsed.query, ""))
        try:
            with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
                with client.stream("GET", secure_url) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for part in response.iter_bytes():
                        content.extend(part)
                        if len(content) > 6_000_000:
                            raise ValueError()
            if not (content[:4] == b"RIFF" and content[8:12] == b"WAVE"):
                raise ValueError()
            return bytes(content)
        except (httpx.HTTPError, ValueError):
            raise DomainError(
                "AUDIO_DOWNLOAD_FAILED", "配音文件未下载成功，已保留结果；不会重新配音", 502
            ) from None
