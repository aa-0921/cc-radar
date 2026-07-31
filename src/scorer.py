"""重要度スコアリングと同一イベントの重複排除

LLM 呼び出しは1リクエストにまとめる（OpenRouter free 枠 50req/日を守るため）。
評価ルーブリックは Thysrael/Horizon の CONTENT_ANALYSIS_SYSTEM を
Claude Code 文脈の日本語に適応させたもの（MIT License）。
"""

from src.llm import LLMClient, extract_json
from src.models import Item

SYSTEM = """あなたは Claude Code（Anthropic の CLI コーディングツール）で日々開発している
エンジニア向けに、技術ニュースの重要度を判定するキュレーターです。

以下の 0-10 スケールで採点してください。

**9-10 破壊的変更・メジャーリリース**
- Claude Code 本体のメジャー/マイナーリリース、破壊的変更、料金・制限の変更
- 開発ワークフローを変える新機能（新しいツール、権限モデル、サブエージェント等）

**7-8 すぐ読む価値がある**
- 実用的な新機能・設定・技術的な深掘り記事
- 広く使われうる MCP サーバー / スキル / サブエージェントの登場
- 既知の問題への新しい解法、質の高い検証・ベンチマーク

**5-6 知っておく程度**
- 小さな改善、入門チュートリアル、個人の使用感レポート
- 話題性はあるが実務への影響が限定的なもの

**3-4 低優先**
- 定型的な紹介記事、既知情報の焼き直し、細かなバグ修正
- 宣伝色の強い内容

**0-2 ノイズ**
- スパム、無関係な話題、中身の無い告知

判定の観点:
- Claude Code とその周辺エコシステム（MCP / スキル / サブエージェント / CLI）への関連度が低いものは
  たとえ技術的に立派でも 4 以下にする
- 技術的な新規性と、読者の作業への影響の大きさを重視する
- HackerNews のポイント数やコメント数が多いものはコミュニティ検証済みとして加点する
- 単なるコミットログや自動生成の更新通知は低く抑える"""

USER_TEMPLATE = """以下のニュース候補それぞれを採点してください。

同一の出来事（同じリリース・同じ発表）を複数のソースが報じている場合は、
後に出てくる方の dup_of に、代表とする**より小さい番号**を入れてください。
別々の出来事なら dup_of は null です。迷ったら null にしてください。

{items}

JSON 配列のみを出力してください。説明文は不要です。
[
  {{"id": 1, "score": 8.5, "reason": "<採点理由を日本語20字程度>", "tags": ["<タグ>"], "dup_of": null}},
  ...
]"""


def _render_items(items: list[Item]) -> str:
    """LLM に渡す候補一覧を組み立てる"""
    lines = []
    for i, it in enumerate(items, start=1):
        meta = f"ソース={it.source} 言語={it.lang}"
        if it.points:
            meta += f" ポイント={it.points}"
        if it.comments:
            meta += f" コメント={it.comments}"
        lines.append(f"[{i}] {meta}\nタイトル: {it.title}")
        if it.summary:
            lines.append(f"要旨: {it.summary[:200]}")
    return "\n".join(lines)


def heuristic_score(item: Item) -> float:
    """LLM が使えないときの機械的な代替スコア"""
    if item.source in ("公式changelog", "claude-code releases"):
        return 9.0
    if item.source == "claude-code commits":
        return 3.0
    if item.source == "GitHub新着":
        # star 数は「Claude Code にとって重要か」を測れない（無関係な人気リポも混ざる）。
        # LLM 不在時は判定不能として閾値未満に留め、一次情報と HN を優先する
        return 6.0
    base = 5.0
    if item.points:
        base += min(item.points / 50.0, 3.0)
    return round(min(base, 8.0), 1)


def apply_heuristic(items: list[Item], note: str) -> None:
    """全アイテムに代替スコアを設定する"""
    for it in items:
        it.score = heuristic_score(it)
        it.reason = note


async def score(items: list[Item], llm: LLMClient) -> str:
    """全件を1リクエストで採点し、Item に score/reason/tags/dup_of を反映する。

    戻り値は警告メッセージ（正常時は空文字）。LLM が失敗した場合は
    機械的スコアにフォールバックし、その旨を返す。
    """
    if not items:
        return ""

    try:
        raw = await llm.call(SYSTEM, USER_TEMPLATE.format(items=_render_items(items)))
        rows = extract_json(raw)
        if not isinstance(rows, list):
            raise ValueError("配列以外が返った")
    except Exception as e:
        apply_heuristic(items, "機械スコア")
        return f"スコアリング失敗のため機械順で出力（{type(e).__name__}: {e}）"

    scored_ids = set()
    for row in rows:
        try:
            idx = int(row["id"]) - 1
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= idx < len(items):
            continue
        it = items[idx]
        try:
            it.score = float(row.get("score", 0))
        except (TypeError, ValueError):
            it.score = 0.0
        it.reason = str(row.get("reason") or "")
        tags = row.get("tags")
        it.tags = [str(t) for t in tags] if isinstance(tags, list) else []
        dup = row.get("dup_of")
        # dup_of は自分より前の番号のみ有効（循環参照を避ける）
        if isinstance(dup, int) and 0 < dup < idx + 1:
            it.also_seen = [f"__dup__{dup - 1}"]
        scored_ids.add(idx)

    missing = [i for i in range(len(items)) if i not in scored_ids]
    for i in missing:
        items[i].score = heuristic_score(items[i])
        items[i].reason = "機械スコア"

    if missing:
        return f"LLM が {len(missing)}/{len(items)} 件を採点せず、その分は機械スコアで補完"
    return ""


def _root_of(idx: int, items: list[Item]) -> int:
    """dup_of の連鎖をたどって代表アイテムの添字を返す"""
    seen = set()
    while idx not in seen:
        seen.add(idx)
        marks = items[idx].also_seen
        if not marks or not marks[0].startswith("__dup__"):
            return idx
        idx = int(marks[0][len("__dup__") :])
    return idx


def dedupe(items: list[Item]) -> list[Item]:
    """同一イベントを1件に統合する。代表はスコア最大値を引き継ぐ"""
    merged_into: dict[int, list[str]] = {}
    survivors: list[int] = []

    for i, it in enumerate(items):
        root = _root_of(i, items)
        if root == i:
            survivors.append(i)
            merged_into.setdefault(i, [])
        else:
            merged_into.setdefault(root, []).append(it.source)
            items[root].score = max(items[root].score, it.score)

    result = []
    for i in survivors:
        items[i].also_seen = merged_into.get(i, [])
        result.append(items[i])
    return result


def select(items: list[Item], threshold: float, max_items: int) -> list[Item]:
    """閾値以上をスコア降順で上限まで取る"""
    picked = [it for it in items if it.score >= threshold]
    picked.sort(key=lambda x: (x.score, x.points), reverse=True)
    return picked[:max_items]
