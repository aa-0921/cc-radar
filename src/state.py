"""既報 URL の記録（data/seen.json）と最終送信日の記録（data/last_sent.json）"""

import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "seen.json"
SENT_PATH = Path(__file__).resolve().parent.parent / "data" / "last_sent.json"


def load(path: Path = DEFAULT_PATH) -> set[str]:
    """既報 URL を読み込む。壊れていても処理は止めない（初回扱い）"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("seen", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save(known: list[str], new_urls: list[str], limit: int, path: Path = DEFAULT_PATH) -> None:
    """既報リストに新規 URL を追記し、上限を超えた古い分を切り捨てる"""
    merged = known + [u for u in new_urls if u not in set(known)]
    if len(merged) > limit:
        merged = merged[-limit:]
    path.write_text(
        json.dumps({"seen": merged}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_ordered(path: Path = DEFAULT_PATH) -> list[str]:
    """順序を保ったまま既報 URL を読む（save の第1引数用）"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("seen", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def sent_on(path: Path = SENT_PATH) -> str:
    """最後にメールを送った日（JST の YYYY-MM-DD）。記録が無ければ空文字"""
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("date", ""))
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


def mark_sent(date_str: str, path: Path = SENT_PATH) -> None:
    """送信した日を記録する。同じ日の後続 cron を送信前に止めるために使う"""
    path.write_text(
        json.dumps({"date": date_str}, ensure_ascii=False) + "\n", encoding="utf-8"
    )
