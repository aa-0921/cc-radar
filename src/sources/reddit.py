"""Reddit のサブレディット RSS を取得する（best-effort）

Actions の共有 IP からは 429 で弾かれることがある。失敗しても他ソースを止めない。
"""

import asyncio

import httpx

from src.models import Item
from src.sources.rss import USER_AGENT, parse_feed

TIMEOUT = 20.0
# 実測（2026-08-01）: 1 本取ると以降 429 が返り続け、10 秒後・20 秒後もまだ 429、
# 最初の成功から 60 秒でようやく回復する。old.reddit.com も同じ制限を共有していて
# ホストを分けても回避できない。他ソースとは並列に走るので、待つ分だけ待つ
FETCH_INTERVAL = 60.0


async def collect(conf: dict) -> tuple[list[Item], list[str]]:
    """設定のサブレディットを順に取得する。戻り値 = (アイテム一覧, 失敗ソース名一覧)

    同時に叩くと必ず片方が 429 で落ちるため、並列にせず間隔を空けて 1 本ずつ取る。
    """
    items: list[Item] = []
    failed: list[str] = []

    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        for i, sub in enumerate(conf.get("subreddits", [])):
            if i:
                await asyncio.sleep(FETCH_INTERVAL)
            try:
                resp = await client.get(
                    f"https://www.reddit.com/r/{sub}/.rss", follow_redirects=True
                )
                resp.raise_for_status()
                items.extend(parse_feed(resp.content, f"r/{sub}", "en"))
            except Exception as e:
                failed.append(f"r/{sub}: {type(e).__name__}")

    return items, failed
