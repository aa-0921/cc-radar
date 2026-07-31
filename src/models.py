"""収集アイテムの共通データモデル"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Item:
    """全ソース共通の記事表現"""

    source: str  # ソース表示名（例: "公式changelog", "HN"）
    title: str  # 原題（英語のまま。日本語ソースなら日本語）
    url: str  # 本体 URL（重複判定のキー）
    published: datetime  # UTC aware
    lang: str = "en"
    summary: str = ""  # 要旨（RSS description 等の先頭抜粋）
    points: int = 0  # HN スコア / GitHub star 数
    comments: int = 0  # コメント数
    discuss_url: str = ""  # 議論ページ（HN item ページ等）
    # 時間窓フィルタを免除する（GitHub の新着リポは作成日が窓外でも「初出」として拾う。
    # 重複通知は seen.json 側で防ぐ）
    window_exempt: bool = False

    # 後段で埋める
    score: float = 0.0
    reason: str = ""
    tags: list[str] = field(default_factory=list)
    title_ja: str = ""
    whats_new: str = ""
    why_matters: str = ""
    also_seen: list[str] = field(default_factory=list)  # 重複統合された他ソース名

    def engagement(self) -> str:
        """出典行に添える反響情報。無ければ空文字"""
        parts = []
        if self.points:
            parts.append(f"{self.points}pt")
        if self.comments:
            parts.append(f"{self.comments}コメント")
        return " / ".join(parts)
