"""cc-radar — Claude Code エコシステムの新着を収集し、重要度順の日本語メールを送る

実行:
    python -m src.main                 # 通常実行（設定の時間窓）
    DRYRUN=1 python -m src.main --since-hours 72   # 送信せず標準出力に整形結果
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src import mailer, scorer, state, translator
from src.llm import LLMClient
from src.models import Item
from src.sources import github as gh_source
from src.sources import hackernews as hn_source
from src.sources import reddit as reddit_source
from src.sources import rss as rss_source

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
JST = timezone(timedelta(hours=9))


def load_env_file(path: Path = ROOT / ".env") -> None:
    """ローカル実行用に .env を読む（既に設定済みの環境変数は上書きしない）。

    Gmail のアプリパスワードは値に空白を含み `. .env` では壊れるので自前でパースする。
    Actions では .env が無いので何もしない。
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def normalize_url(url: str) -> str:
    """トラッキングパラメータを落として重複判定を安定させる。

    フラグメントは残す（公式 changelog は #2-1-220 のようにアンカーで版を区別するため、
    落とすと全リリースが同一 URL に潰れる）。
    """
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_")]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path.rstrip("/"), urlencode(query), parts.fragment)
    )


async def collect_all(conf: dict, since: datetime) -> tuple[list[Item], list[str]]:
    """全ソースを並列取得する。ソース単位の失敗は握って続行する"""
    results = await asyncio.gather(
        rss_source.collect(conf.get("rss", [])),
        hn_source.collect(conf.get("hackernews", {}), since),
        gh_source.collect(conf.get("github", {})),
        reddit_source.collect(conf.get("reddit", {})),
    )
    items: list[Item] = []
    failed: list[str] = []
    for got, err in results:
        items.extend(got)
        failed.extend(err)
    return items, failed


def filter_candidates(items: list[Item], seen: set[str], since: datetime) -> list[Item]:
    """既報・時間窓外・URL 重複を落とす"""
    picked: list[Item] = []
    local_seen: set[str] = set()
    for it in items:
        key = normalize_url(it.url)
        if key in seen or key in local_seen:
            continue
        if not it.window_exempt and it.published < since:
            continue
        local_seen.add(key)
        picked.append(it)
    return picked


async def run(args: argparse.Namespace) -> int:
    load_env_file()
    conf = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    dryrun = args.dry_run or os.getenv("DRYRUN", "") not in ("", "0", "false")

    hours = args.since_hours or int(conf.get("window_hours", 24))
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    raw_items, failed = await collect_all(conf, since)
    print(f"[収集] {len(raw_items)} 件 / 失敗 {len(failed)} ソース")
    if failed:
        print("[収集] 失敗:", ", ".join(failed))
    if not raw_items:
        print("[中断] 全ソースから1件も取得できなかった")
        return 1

    known = state.load_ordered()
    candidates = filter_candidates(raw_items, set(known), since)
    print(f"[候補] 既報・時間窓({hours}h)で絞って {len(candidates)} 件")
    if not candidates:
        print("[終了] 新着なし。メールは送らない")
        return 0

    warnings = [f"取得失敗: {f}" for f in failed]

    llm = LLMClient(conf.get("llm_models", []))
    warn = await scorer.score(candidates, llm, int(conf.get("score_batch_size", 80)))
    if warn:
        warnings.append(warn)

    merged = scorer.dedupe(candidates)
    categories = conf.get("categories") or {}
    by_category = scorer.select_by_category(merged, categories, conf.get("source_caps") or {})

    # ジャンルの並びは config の記載順（cc → dev → mac）を維持する
    sections = [
        (str(categories[key].get("label", key)), by_category.get(key, []))
        for key in categories
    ]
    selected = [it for _, items in sections for it in items]

    histogram = " ｜ ".join(
        f"{categories[key].get('label', key)}: "
        f"{scorer.histogram([it for it in merged if it.category == key])}"
        for key in categories
    )
    print(f"[選抜] 統合後 {len(merged)} 件 → 掲載 {len(selected)} 件 " + ", ".join(
        f"{key} {len(by_category.get(key, []))}" for key in categories
    ))
    print(f"[分布] {histogram}")

    # 評価済みは低スコアでも既報にする（翌日以降の再評価でトークンを無駄にしないため）
    evaluated_urls = [normalize_url(it.url) for it in candidates]

    if not selected:
        print("[終了] 閾値を超える記事なし。メールは送らない")
        if not dryrun:
            state.save(known, evaluated_urls, int(conf.get("seen_max", 2000)))
        return 0

    warn = await translator.translate(selected, llm, int(conf.get("translate_batch_size", 20)))
    if warn:
        warnings.append(warn)

    date_str = datetime.now(JST).strftime("%Y-%m-%d")
    subject = mailer.build_subject(date_str, sections)
    plain = mailer.build_plain(date_str, sections, len(candidates), warnings, histogram)

    if dryrun:
        print("=" * 60)
        print(subject)
        print("=" * 60)
        print(plain)
        return 0

    sent = mailer.send(
        subject,
        plain,
        mailer.build_html(date_str, sections, len(candidates), warnings, histogram),
    )
    if not sent:
        # 送れなかったのに既報にすると、その記事は二度と通知されない。
        # 設定漏れに気づけるよう異常終了させる
        print("[中断] 送信できなかったので既報を更新しない")
        return 1
    state.save(known, evaluated_urls, int(conf.get("seen_max", 2000)))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code 新着ダイジェスト")
    parser.add_argument("--since-hours", type=int, default=0, help="収集する時間窓（既定は config）")
    parser.add_argument("--dry-run", action="store_true", help="送信せず標準出力に整形結果を出す")
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
