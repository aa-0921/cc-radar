"""RSS/Atom 汎用取得（公式 changelog・GitHub atom・Zenn・Qiita・Google News を1実装で処理）"""

import asyncio
import re
from datetime import datetime, timezone

import feedparser
import httpx

from src.models import Item

MAX_CONCURRENT = 6
TIMEOUT = 30.0
USER_AGENT = "cc-radar/1.0 (+https://github.com/aa-0921/cc-radar)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str, limit: int = 300) -> str:
    """RSS description から HTML タグを落として要旨にする"""
    if not text:
        return ""
    plain = _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()
    return plain[:limit]


def _parse_published(entry) -> datetime | None:
    """published/updated を UTC aware datetime に変換する"""
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            return datetime(*st[:6], tzinfo=timezone.utc)
    return None


def parse_feed(body: bytes, name: str, lang: str) -> list[Item]:
    """feedparser の結果を Item 一覧に変換する"""
    parsed = feedparser.parse(body)
    items: list[Item] = []
    for entry in parsed.entries:
        url = entry.get("link") or ""
        title = (entry.get("title") or "").strip()
        if not url or not title:
            continue
        published = _parse_published(entry)
        if published is None:
            # 日時が取れないフィードは時間窓で切れないため捨てる
            continue
        summary = _strip_html(entry.get("summary") or entry.get("description") or "")
        items.append(
            Item(
                source=name,
                title=title,
                url=url,
                published=published,
                lang=lang,
                summary=summary,
            )
        )
    return items


async def fetch_one(client: httpx.AsyncClient, feed: dict) -> list[Item]:
    """フィード1本を取得してパースする。例外は呼び出し元に投げる"""
    resp = await client.get(feed["url"], follow_redirects=True)
    resp.raise_for_status()
    return parse_feed(resp.content, feed["name"], feed.get("lang", "en"))


async def collect(feeds: list[dict]) -> tuple[list[Item], list[str]]:
    """全フィードを並列取得する。戻り値 = (アイテム一覧, 失敗ソース名一覧)"""
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    items: list[Item] = []
    failed: list[str] = []

    async with httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as client:

        async def guarded(feed: dict) -> None:
            async with sem:
                try:
                    items.extend(await fetch_one(client, feed))
                except Exception as e:
                    failed.append(f"{feed['name']}: {type(e).__name__}")

        await asyncio.gather(*[guarded(f) for f in feeds])

    return items, failed


if __name__ == "__main__":
    # 単体確認: python -m src.sources.rss <url>
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "https://code.claude.com/docs/en/changelog/rss.xml"
    got, err = asyncio.run(collect([{"name": "test", "url": url, "lang": "en"}]))
    print(f"取得 {len(got)} 件 / 失敗 {err}")
    for it in got[:5]:
        print(f"  [{it.published:%Y-%m-%d %H:%M}] {it.title}")
        print(f"    {it.url}")
