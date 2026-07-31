"""OpenRouter の :free モデル呼び出し（products/hn-matome/scripts/llm_client.py から移植）"""

import json
import os
import re

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 180.0  # free 枠は待たされることがあるので長め


class LLMError(RuntimeError):
    """全モデルで応答が得られなかった場合に投げる"""


class LLMClient:
    def __init__(self, models: list[str], api_key: str = ""):
        self.models = models
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")

    async def call(self, system: str, user: str) -> str:
        """モデルを順に試し、最初に本文を返したものを採用する"""
        if not self.api_key:
            raise LLMError("OPENROUTER_API_KEY 未設定")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/aa-0921/cc-radar",
            "X-Title": "cc-radar",
        }
        errors = []
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            for model in self.models:
                try:
                    resp = await client.post(
                        OPENROUTER_URL,
                        headers=headers,
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": user},
                            ],
                        },
                    )
                    resp.raise_for_status()
                    message = resp.json().get("choices", [{}])[0].get("message", {})
                    content = (message.get("content") or "").strip()
                    if content:
                        return content
                    errors.append(f"{model}: 空応答")
                except httpx.HTTPStatusError as e:
                    # free モデルは予告なく廃止される（404 で代替 slug を教えてくれる）ので
                    # ステータスと本文を残さないと原因が追えない
                    body = e.response.text.replace("\n", " ")[:160]
                    errors.append(f"{model}: HTTP {e.response.status_code} {body}")
                except Exception as e:
                    errors.append(f"{model}: {type(e).__name__}")
        raise LLMError(" / ".join(errors))


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str):
    """コードフェンスや前置きを含む応答から JSON 本体を取り出す"""
    candidates = _FENCE_RE.findall(text)
    candidates.append(text)
    for cand in candidates:
        for opener, closer in (("[", "]"), ("{", "}")):
            start = cand.find(opener)
            end = cand.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(cand[start : end + 1])
                except json.JSONDecodeError:
                    continue
    raise ValueError("JSON を抽出できなかった")


def parse_numbered_list(text: str, fallback: list[str]) -> list[str]:
    """'1. xxx' 形式をパースする。件数が合わなければ不足分を原文で埋める"""
    results = []
    for line in text.strip().splitlines():
        m = re.match(r"^\s*(\d+)[.)]\s+(.+)$", line.strip())
        if m:
            results.append(m.group(2).strip())
    if len(results) == len(fallback):
        return results
    return [results[i] if i < len(results) else orig for i, orig in enumerate(fallback)]
