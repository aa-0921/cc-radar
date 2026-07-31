"""GitHub Search API でエコシステムの新着リポジトリを検出する"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx

from src.models import Item

SEARCH_URL = "https://api.github.com/search/repositories"
TIMEOUT = 30.0
CREATED_WITHIN_DAYS = 30  # 「新着」とみなす作成日の範囲
TOP_N = 10  # クエリごとの採用上限


async def collect(conf: dict) -> tuple[list[Item], list[str]]:
    """設定のクエリごとに新着リポを検索する。戻り値 = (アイテム一覧, 失敗ソース名一覧)"""
    min_stars = int(conf.get("min_stars", 0))
    created_after = (datetime.now(timezone.utc) - timedelta(days=CREATED_WITHIN_DAYS)).date()

    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    items: list[Item] = []
    failed: list[str] = []

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers) as client:

        async def one(query: str) -> None:
            try:
                resp = await client.get(
                    SEARCH_URL,
                    params={
                        "q": f"{query} stars:>={min_stars} created:>={created_after}",
                        "sort": "stars",
                        "order": "desc",
                        "per_page": TOP_N,
                    },
                )
                resp.raise_for_status()
                for repo in resp.json().get("items", []):
                    items.append(
                        Item(
                            source="GitHub新着",
                            title=f"{repo['full_name']} — {repo.get('description') or ''}".strip(
                                " —"
                            ),
                            url=repo["html_url"],
                            published=datetime.fromisoformat(
                                repo["created_at"].replace("Z", "+00:00")
                            ),
                            lang="en",
                            summary=repo.get("description") or "",
                            points=int(repo.get("stargazers_count") or 0),
                            window_exempt=True,
                        )
                    )
            except Exception as e:
                failed.append(f"GitHub({query}): {type(e).__name__}")

        await asyncio.gather(*[one(q) for q in conf.get("queries", [])])

    return items, failed
