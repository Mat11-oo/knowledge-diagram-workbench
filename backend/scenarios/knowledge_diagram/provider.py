import json
import os
import time
from pathlib import Path

import httpx

from .repository import DomainError
from .schemas import Extraction


class Provider:
    """No SDK retries. One transport send per ledger entry; never log payloads."""

    def __init__(self):
        self.key = os.getenv("MODEL_API_KEY", "")
        self.model = os.getenv("MODEL_NAME", "deepseek-flash")
        self.base_url = os.getenv("MODEL_BASE_URL", "https://api.deepseek.com").rstrip("/")
        self.enabled = os.getenv("KNOWLEDGE_ALLOW_PAID", "0") == "1"
        # Explicit commissioning guard: pricing/token accounting must first be verified.
        self.pricing_confirmed = os.getenv("KNOWLEDGE_PRICING_CONFIRMED", "0") == "1"

    def ready(self):
        if not self.key:
            raise DomainError(
                "MODEL_NOT_CONFIGURED", "请先在后端配置模型密钥；本次没有调用或扣费", 503
            )
        if not self.enabled:
            raise DomainError(
                "PAID_CALLS_DISABLED", "云端调用未启用，当前可保存和编辑材料；本次没有扣费", 403
            )
        if not self.pricing_confirmed:
            raise DomainError(
                "PRICING_UNVERIFIED", "当前价格和计量上界尚未核验，已暂停云端调用", 503
            )
        if self.base_url not in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
            raise DomainError("PROVIDER_NOT_ALLOWED", "只允许已核价的DeepSeek官方接口", 400)
        if self.model != "deepseek-flash":
            raise DomainError("MODEL_NOT_ALLOWED", "当前只启用已选定的文本模型", 400)

    def messages(self, source):
        prompt = (Path(__file__).parent / "prompts/extract.txt").read_text()
        return [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(source, ensure_ascii=False)},
        ]

    def reservation(self, source):
        # Commissioning must verify this conservative bound against tokenizer/usage.
        # No live calls are permitted before KNOWLEDGE_PRICING_CONFIRMED is set.
        input_bound = sum(len(m["content"].encode("utf-8")) for m in self.messages(source)) + 4096
        return input_bound * 2 + 4000 * 8  # integer micro-yuan, peak no-cache tariff

    def extract(self, source):
        self.ready()
        start = time.monotonic()
        try:
            with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = client.post(
                    self.base_url + "/chat/completions",
                    headers={"Authorization": "Bearer " + self.key},
                    json={
                        "model": self.model,
                        "messages": self.messages(source),
                        "response_format": {"type": "json_object"},
                        "max_tokens": 4000,
                        "stream": False,
                        "thinking": {"type": "disabled"},
                    },
                )
            if response.status_code in {400, 401, 403, 404}:
                raise DomainError(
                    "MODEL_REJECTED", "模型服务拒绝请求，请核对配置；已保留费用预留", 502
                )
            if response.status_code != 200:
                raise DomainError(
                    "MODEL_UNCERTAIN", "模型服务暂时不可用，结果待核对，未自动重试", 502
                )
            data = response.json()
            usage = data.get("usage", {})
            usage = {key: usage.get(key) for key in ("prompt_tokens", "completion_tokens")}
            if any(type(v) is not int or v < 0 for v in usage.values()):
                raise DomainError("USAGE_UNKNOWN", "模型未返回有效用量，已保留费用预留", 502)
            return {
                "content": data["choices"][0]["message"]["content"],
                "usage": usage,
                "request_id": str(data.get("id", ""))[:200],
                "duration": time.monotonic() - start,
            }
        except DomainError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError):
            raise DomainError(
                "MODEL_UNCERTAIN", "模型请求结果未知，费用仍预留；请核对后继续", 502
            ) from None


def parse_claims(raw, source):
    try:
        payload = Extraction.model_validate_json(raw)
    except ValueError:
        raise DomainError(
            "MODEL_FORMAT", "模型返回格式不符合要求，费用已记账；请核对后重试", 502
        ) from None
    claims = []
    from .repository import uid

    for item in payload.claims:
        references = []
        for quote in item.quotes:
            start = source["text"].find(quote)
            if not quote or start < 0 or source["text"].find(quote, start + 1) >= 0:
                raise DomainError(
                    "REFERENCE_INVALID", "模型引文不存在或位置不唯一，请核对材料后重试", 502
                )
            references.append(
                {
                    "source_revision": source["revision"],
                    "start_cp": start,
                    "end_cp": start + len(quote),
                    "quote": quote,
                }
            )
        claims.append(
            {
                "id": uid(),
                "text": item.text,
                "kind": item.kind,
                "references": references,
                "confirmed": False,
                "active": True,
            }
        )
    return claims
