"""Beijing DashScope async image adapter. One POST, bounded GET polling, no paid retry."""

import io
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image

from .repository import DomainError

PRICE_MICRO = 40_000  # official Beijing list price, 2026-11-07; account pricing must be confirmed


class ImageProvider:
    def __init__(self):
        self.key = os.getenv("DASHSCOPE_API_KEY", "")
        self.model = os.getenv("KNOWLEDGE_IMAGE_MODEL", "wanx2.0-t2i-turbo")
        self.base = os.getenv("KNOWLEDGE_IMAGE_BASE_URL", "https://dashscope.aliyuncs.com").rstrip(
            "/"
        )
        self.enabled = os.getenv("KNOWLEDGE_ALLOW_IMAGES", "0") == "1"
        self.pricing_confirmed = os.getenv("KNOWLEDGE_IMAGE_PRICING_CONFIRMED", "0") == "1"

    def ready(self):
        if not self.key:
            raise DomainError("IMAGE_NOT_CONFIGURED", "请在本产品后端配置北京地域百炼密钥", 503)
        if not self.enabled:
            raise DomainError("PAID_CALLS_DISABLED", "真实生图尚未启用，本次未调用", 403)
        if not self.pricing_confirmed:
            raise DomainError("PRICING_UNVERIFIED", "生图价格和账户地域尚未确认", 503)
        if self.model != "wanx2.0-t2i-turbo" or not (
            self.base == "https://dashscope.aliyuncs.com"
            or re.fullmatch(r"https://[a-zA-Z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com", self.base)
        ):
            raise DomainError("PROVIDER_NOT_ALLOWED", "仅支持已选北京地域官方模型与地址", 400)

    def prompt(self, text):
        value = (Path(__file__).parent / "prompts/illustration.txt").read_text().format(prompt=text)
        if len(value) > 800:
            raise DomainError("PROMPT_TOO_LONG", "插图提示词过长，请缩短到650字以内", 422)
        return value

    def submit(self, prompt):
        self.ready()
        try:
            with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = client.post(
                    self.base + "/api/v1/services/aigc/text2image/image-synthesis",
                    headers={"Authorization": "Bearer " + self.key, "X-DashScope-Async": "enable"},
                    json={
                        "model": self.model,
                        "input": {"prompt": self.prompt(prompt)},
                        "parameters": {"size": "1024*1024", "n": 1, "prompt_extend": False},
                    },
                )
                response.raise_for_status()
                data = response.json()
                task_id = data["output"]["task_id"]
                if not isinstance(task_id, str) or not re.fullmatch(
                    r"[a-zA-Z0-9_-]{1,160}", task_id
                ):
                    raise ValueError()
                return task_id
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise DomainError(
                "IMAGE_UNCERTAIN", "生图提交结果未知，已停止重发并保留预算", 502
            ) from None

    def wait(self, task_id):
        # GET only: resuming a known remote task never creates a second paid task.
        self.ready()
        deadline = time.monotonic() + 180
        with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
            while time.monotonic() < deadline:
                try:
                    response = client.get(
                        self.base + "/api/v1/tasks/" + task_id,
                        headers={"Authorization": "Bearer " + self.key},
                    )
                    response.raise_for_status()
                    data = response.json()
                    output = data["output"]
                    status = output["task_status"]
                    if status == "SUCCEEDED":
                        if (
                            data.get("usage", {}).get("image_count") != 1
                            or len(output["results"]) != 1
                        ):
                            raise DomainError(
                                "IMAGE_USAGE_UNKNOWN", "生图数量无法核对，保留预算待核对", 502
                            )
                        return {
                            "url": output["results"][0]["url"],
                            "request_id": str(data.get("request_id", ""))[:160],
                        }
                    if status in {"FAILED", "CANCELED", "UNKNOWN"}:
                        raise DomainError("IMAGE_FAILED", "生图未成功，保留任务与预算供核对", 502)
                    if status not in {"PENDING", "RUNNING"}:
                        raise ValueError()
                except (httpx.HTTPError, KeyError, ValueError, TypeError):
                    raise DomainError(
                        "IMAGE_UNCERTAIN", "生图结果查询中断，可核对原任务，不会重新提交", 502
                    ) from None
                time.sleep(2)
        raise DomainError("IMAGE_TIMEOUT", "生图等待超时，原任务已保留；不会重新提交", 504)

    def download(self, url):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or not (parsed.hostname or "").endswith(".aliyuncs.com")
            or not re.fullmatch(r"[a-z0-9-]+\.oss[a-z0-9-]*\.aliyuncs\.com", parsed.hostname or "")
        ):
            raise DomainError("IMAGE_URL_REJECTED", "生图结果不是受支持的官方存储地址", 502)
        try:
            with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 12_000_000:
                            raise ValueError()
            with Image.open(io.BytesIO(content)) as image:
                if (
                    image.format not in {"PNG", "JPEG", "WEBP"}
                    or image.width * image.height > 4_000_000
                ):
                    raise ValueError()
                image.load()
                buffer = io.BytesIO()
                image.convert("RGB").save(buffer, "PNG")
                return buffer.getvalue()
        except (httpx.HTTPError, OSError, ValueError):
            raise DomainError(
                "IMAGE_INVALID", "插图下载或格式校验失败，已保留远程任务与费用", 502
            ) from None
