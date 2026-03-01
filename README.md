# morningnewsbot

GitHub Actions + Python で動かす前場前マーケットサマリーBotです。

## Files

- `main.py`: 収集、差分、要約、送信、state 保存のオーケストレーション
- `snapshot_collector.py`: Stooq、Tavily、RSS の収集
- `deduper.py`: 前回 state との差分検出
- `summarizer.py`: Claude 優先、Gemini フォールバックの要約
- `notifier.py`: Discord Webhook 送信
- `state_store.py`: `state.json` の原子的な保存

## Environment Variables

- `TAVILY_API_KEY`
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `DISCORD_WEBHOOK_URL`
- `CLAUDE_ALLOWED_DOMAINS` (comma-separated, optional)
- `CLAUDE_WEB_TOOL_TYPE` (optional, defaults to `web_search_20250305`)

## Local Run

```powershell
python -m pip install -r requirements.txt
python main.py
```

## Notes

- Python 側は `state.json` の読み書きだけを行い、Git 操作はしません。
- `CLAUDE_WEB_TOOL_TYPE` の既定値は、2026-03-01 時点の Anthropic 公開ドキュメントに合わせて `web_search_20250305` にしています。実アカウントで別の識別子が有効なら上書きしてください。
