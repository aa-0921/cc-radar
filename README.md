# cc-radar

Claude Code とその周辺エコシステム（MCP サーバー / スキル / サブエージェント / CLI）の新着情報を
毎日集めて、**重要度順に並べた日本語のメール**を朝に届ける仕組み。

英語ソースの方が数日〜数週間早いが毎日巡回するのは現実的でないので、
英語・日本語の両方を自動で集めて要約する。ランニングコストは 0 円。

## 仕組み

```
収集 → 既報/時間窓フィルタ → LLM で採点(0-10)+重複統合 → 閾値7.0で選抜(最大20件) → 日本語化 → メール
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

`source_caps` はソース別の掲載上限。GitHub 新着は同点が大量に並ぶため、素のスコア順だと
上位を占めて他ソースが押し出される（実測で 20 件中 18 件）。枠から溢れたぶんは、
全体の上限に余りがあれば埋め合わせに使うので、GitHub しか新着が無い日でも枠は無駄にならない。

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

cron は `5 22 * * *` UTC（7:05 JST）。Actions の schedule は高負荷時に遅延・スキップする
（実測で 54 分遅れ）ため、遅れても 7 時台に収まる時刻に置き、`workflow_dispatch` も併記している。

## 運用メモ

- 閾値 7.0 で 0 件の日はメールを送らない。届かない日が続くなら `config.json` の
  `score_threshold` を 6.5 に下げる。多すぎるなら 7.5 に上げる。
  判断材料としてメール末尾に「スコア分布」（9以上/8台/7台/6台/5以下の件数）を出している
- 採点済みの記事は低スコアでも `data/seen.json` に記録し、翌日以降 再採点しない
- LLM が落ちた日は機械的なスコアにフォールバックし、メール末尾に「注意」として明示する。
  機械スコアでは GitHub 新着を 6.0（閾値未満）に抑える — star 数は「Claude Code にとって重要か」を
  測れないため、LLM 不在時は公式リリースと HackerNews だけを通す
- Reddit は 1 本取ると約 60 秒 429 が返り続ける（`old.reddit.com` も同じ制限を共有していて
  ホストを変えても回避できない）。サブレディットは並列にせず 60 秒間隔で 1 本ずつ取る。
  他ソースとは並列に走るので全体は待たされない。それでも失敗したらソース名をメール末尾に出す
- 日本語化は JSON 配列が返るまで最大 2 回撃つ。free モデルは同じ入力でも配列を返したり
  地の文を返したりするため（実測で日本語化が丸ごと落ちる日があった）。
  リトライ込みでも 1 実行あたり最大 4 リクエストで、free 枠の 50req/日 には収まる

## クレジット

スコアリングのルーブリック、閾値フィルタ、同一イベントの重複排除、
`whats_new` / `why_it_matters` という出力構造は
[Thysrael/Horizon](https://github.com/Thysrael/Horizon)（MIT License）の設計を参考にした。
コードは流用していない（Horizon は出力言語が en/zh 固定のため日本語化には使えなかった）。
