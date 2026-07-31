# cc-radar

Claude Code とその周辺エコシステム（MCP サーバー / スキル / サブエージェント / CLI）の新着情報を
毎日集めて、**重要度順に並べた日本語のメール**を朝に届ける仕組み。

英語ソースの方が数日〜数週間早いが毎日巡回するのは現実的でないので、
英語・日本語の両方を自動で集めて要約する。ランニングコストは 0 円。

## 仕組み

```
収集 → 既報/時間窓フィルタ → LLM で採点(0-10)+重複統合 → 閾値7.0で選抜 → 日本語化 → メール
```

- 実行基盤: GitHub Actions の cron（public リポなら無料）
- 送信: Gmail SMTP（アプリパスワード）
- 要約・翻訳: OpenRouter の `:free` モデル。**1実行あたり LLM 呼び出しは2回**
  （採点+重複判定で1回、日本語化で1回）。free 枠の 50req/日 を守るためバッチ化している

`config.json` の `llm_models` は上から順に試し、最初に応答したものを使う。
**OpenRouter の `:free` モデルは予告なく廃止される**（廃止済みモデルは 404 + 有料版の slug を返す）。
メール末尾に `HTTP 404 ... unavailable for free` が並んだら、以下で現行の無料モデルを取り直す。

```bash
curl -s https://openrouter.ai/api/v1/models | python3 -c "
import json,sys
for m in sorted(json.load(sys.stdin)['data'], key=lambda m: -(m.get('context_length') or 0)):
    if m['id'].endswith(':free'): print(m['id'], m.get('context_length'))"
```

## 収集ソース

| 種別 | ソース |
|---|---|
| 一次情報 | 公式 changelog RSS、`anthropics/claude-code` の releases / commits Atom |
| 英語コミュニティ | Hacker News（Algolia API）、Google News RSS、GitHub Search API、Reddit（best-effort） |
| 日本語 | Zenn（claudecode / mcp）、Qiita（claudecode）、Google News RSS |

ソースの追加・閾値の変更は `config.json` で行う。

## ローカルで試す

```bash
pip install -r requirements.txt

# 送信せず整形結果だけ見る（初回は時間窓を広げる）
DRYRUN=1 python -m src.main --since-hours 72

# 実際に自分宛へ送る
export GMAIL_USER=... GMAIL_APP_PASSWORD=... TARGET_EMAIL=... OPENROUTER_API_KEY=...
python -m src.main
```

単体確認:

```bash
python -m src.sources.rss https://code.claude.com/docs/en/changelog/rss.xml
```

## GitHub Actions の設定

リポジトリの Secrets に以下を登録する（`GITHUB_TOKEN` は Actions が自動供給するので不要）。

- `OPENROUTER_API_KEY`
- `GMAIL_USER`
- `GMAIL_APP_PASSWORD`（Gmail のアプリパスワード）
- `TARGET_EMAIL`（受信先。省略時は `GMAIL_USER`）

cron は `50 21 * * *` UTC（6:50 JST）。Actions の schedule は高負荷時に遅延・スキップするため
早めに撃ち、`workflow_dispatch` も併記している。

## 運用メモ

- 閾値 7.0 で 0 件の日はメールを送らない。届かない日が続くなら `config.json` の
  `score_threshold` を 6.5 に下げる。多すぎるなら 7.5 に上げる
- 採点済みの記事は低スコアでも `data/seen.json` に記録し、翌日以降 再採点しない
- LLM が落ちた日は機械的なスコアにフォールバックし、メール末尾に「注意」として明示する。
  機械スコアでは GitHub 新着を 6.0（閾値未満）に抑える — star 数は「Claude Code にとって重要か」を
  測れないため、LLM 不在時は公式リリースと HackerNews だけを通す
- `r/ClaudeAI` は Actions の共有 IP から 429 になることがある。他ソースは止めず、
  失敗したソース名だけメール末尾に出す

## クレジット

スコアリングのルーブリック、閾値フィルタ、同一イベントの重複排除、
`whats_new` / `why_it_matters` という出力構造は
[Thysrael/Horizon](https://github.com/Thysrael/Horizon)（MIT License）の設計を参考にした。
コードは流用していない（Horizon は出力言語が en/zh 固定のため日本語化には使えなかった）。
