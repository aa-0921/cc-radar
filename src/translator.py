"""選抜済みアイテムの日本語化（タイトル翻訳 + 何が変わったか / なぜ重要か）

出力構造は Thysrael/Horizon の whats_new / why_it_matters を踏襲（MIT License）。
呼び出しは選抜分まとめて1リクエスト。
"""

from src.llm import LLMClient, extract_json
from src.models import Item

SYSTEM = """あなたは技術ニュースを日本語で伝える編集者です。
Claude Code で開発しているエンジニアが、読んで即座に判断できる短い日本語にします。

守ること:
- 与えられた情報の範囲だけで書く。書かれていないことを推測で補わない
- 技術用語・製品名・バージョン番号は原語のまま残す（例: MCP, subagent, v2.1.0）
- 元が日本語のタイトルはそのまま使う（訳し直さない）
- 誇張しない。「革命的」「驚異の」などの煽り表現を使わない"""

USER_TEMPLATE = """以下の各ニュースについて、日本語で3項目を書いてください。

- title_ja: 日本語の見出し（40字以内）
- whats_new: 何が変わったか（1〜2文）
- why_matters: なぜ重要か・誰に影響するか（1〜2文）

情報が足りず書けない項目は空文字にしてください。

{items}

JSON 配列のみを出力してください。説明文は不要です。
[
  {{"id": 1, "title_ja": "...", "whats_new": "...", "why_matters": "..."}},
  ...
]"""


def _render(items: list[Item]) -> str:
    lines = []
    for i, it in enumerate(items, start=1):
        lines.append(f"[{i}] ソース={it.source} 言語={it.lang}\nタイトル: {it.title}")
        if it.summary:
            lines.append(f"要旨: {it.summary[:300]}")
        if it.reason:
            lines.append(f"重要と判定した理由: {it.reason}")
    return "\n".join(lines)


def _fallback(items: list[Item]) -> None:
    """LLM が使えないときは原文をそのまま見出しにする"""
    for it in items:
        if not it.title_ja:
            it.title_ja = it.title
        if not it.whats_new:
            it.whats_new = it.summary


async def translate(items: list[Item], llm: LLMClient) -> str:
    """選抜分を1リクエストで日本語化する。戻り値は警告メッセージ（正常時は空文字）"""
    if not items:
        return ""

    try:
        raw = await llm.call(SYSTEM, USER_TEMPLATE.format(items=_render(items)))
        rows = extract_json(raw)
        if not isinstance(rows, list):
            raise ValueError("配列以外が返った")
    except Exception as e:
        _fallback(items)
        return f"日本語化に失敗したため原文で出力（{type(e).__name__}: {e}）"

    filled = set()
    for row in rows:
        try:
            idx = int(row["id"]) - 1
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= idx < len(items):
            continue
        it = items[idx]
        it.title_ja = str(row.get("title_ja") or "").strip()
        it.whats_new = str(row.get("whats_new") or "").strip()
        it.why_matters = str(row.get("why_matters") or "").strip()
        filled.add(idx)

    _fallback(items)  # 欠けた分は原文で埋める

    missing = len(items) - len(filled)
    return f"{missing}/{len(items)} 件は日本語化されず原文のまま" if missing else ""
