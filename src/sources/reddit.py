"""Reddit のサブレディット RSS を取得する（best-effort）

Actions の共有 IP からは 429 で弾かれることがある。失敗しても他ソースを止めない。
"""

import asyncio

import httpx

from src.models import Item
from src.sources.rss import USER_AGENT, parse_feed

TIMEOUT = 20.0


async def collect(conf: dict) -> tuple[list[Item], list[str]]:
    """設定のサブレディットを取得する。戻り値 = (アイテム一覧, 失敗ソース名一覧)"""
    items: list[Item] = []
    failed: list[str] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:

        async def one(sub: str) -> None:
            try:
                resp = await client.get(
                    f"https://www.reddit.com/r/{sub}/.rss", follow_redirects=True
                )
                resp.raise_for_status()
                items.extend(parse_feed(resp.content, f"r/{sub}", "en"))
            except Exception as e:
                failed.append(f"r/{sub}: {type(e).__name__}")

        await asyncio.gather(*[one(s) for s in conf.get("subreddits", [])])

    return items, failed
