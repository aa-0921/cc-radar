"""Hacker News（Algolia API）からキーワード該当ストーリーを取得する"""

import asyncio
from datetime import datetime, timezone

import httpx

from src.models import Item

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search"
TIMEOUT = 30.0
HITS_PER_PAGE = 50


def _to_item(hit: dict) -> Item | None:
    """Algolia の hit を Item に変換する。必須項目が欠けたら None"""
    title = hit.get("title") or hit.get("story_title") or ""
    object_id = hit.get("objectID")
    created_at_i = hit.get("created_at_i")
    if not title or not object_id or not created_at_i:
        return None

    discuss_url = f"https://news.ycombinator.com/item?id={object_id}"
    return Item(
        source="HackerNews",
        title=title,
        # 外部リンクを持たない Ask HN 等は議論ページ自体を本体 URL にする
        url=hit.get("url") or discuss_url,
        published=datetime.fromtimestamp(int(created_at_i), tz=timezone.utc),
        lang="en",
        summary=(hit.get("story_text") or "")[:300],
        points=int(hit.get("points") or 0),
        comments=int(hit.get("num_comments") or 0),
        discuss_url=discuss_url,
    )


async def collect(conf: dict, since: datetime) -> tuple[list[Item], list[str]]:
    """設定のクエリごとに検索する。戻り値 = (アイテム一覧, 失敗ソース名一覧)"""
    since_ts = int(since.timestamp())
    min_points = int(conf.get("min_points", 0))
    items: list[Item] = []
    failed: list[str] = []

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:

        async def one(query: str) -> None:
            try:
                resp = await client.get(
                    ALGOLIA_URL,
                    params={
                        "query": query,
                        "tags": "story",
                        "numericFilters": f"created_at_i>={since_ts},points>={min_points}",
                        "hitsPerPage": HITS_PER_PAGE,
                    },
                )
                resp.raise_for_status()
                for hit in resp.json().get("hits", []):
                    item = _to_item(hit)
                    if item:
                        items.append(item)
            except Exception as e:
                failed.append(f"HN({query}): {type(e).__name__}")

        await asyncio.gather(*[one(q) for q in conf.get("queries", [])])

    return items, failed
