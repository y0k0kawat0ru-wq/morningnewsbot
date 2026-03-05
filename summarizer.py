from __future__ import annotations

import asyncio
import os
from typing import Any

from anthropic import AsyncAnthropic
from google import genai

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

SUMMARY_SYSTEM_PROMPT = """\
あなたは前場前の日本株投資家向けニュース整理Botです。
以下のルールに厳密に従ってください。

【絶対ルール】
- 入力されたニュース一覧のみを根拠に要約すること
- 入力にない事実、外部知識、最新相場情報を絶対に追加しない
- 時価・株価予想・売買判断・相場予測を追加しない
- 「堅調が期待される」「調整に注意」「値固めに注意」等の相場予測調の表現は使わない
- 事実と解釈を分け、解釈は最小限にする
- 重複する論点は統合し、最新のものを優先する
- 古い記事や不明確な情報は採用しない

【出力形式】
- 全体で500〜850文字、最大1000文字
- 日本語で書く
- 重要度順に整理する
- 「何が起きたか」を中心に記述する

【構成】
以下の形式で出力してください：

📰 主要ニュース
- ニュース1の要約（重要度順）
- ニュース2の要約
- ...

🇯🇵 日本株関連
- 日本株ニュース1の要約
- 日本株ニュース2の要約
- ...

（補足がある場合のみ）
💡 補足
- 補足事項

※市場概況の数値（指数・前日比）は別途表示されるため、要約に含めないこと
"""


def _extract_text_from_message(message: Any) -> str:
    blocks: list[str] = []
    for block in getattr(message, "content", []):
        text = getattr(block, "text", None)
        if text:
            blocks.append(text.strip())
    return "\n".join(part for part in blocks if part).strip()


async def summarize_with_claude(prompt_input: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=900,
        system=SUMMARY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt_input}],
    )
    text = _extract_text_from_message(message)
    if not text:
        raise RuntimeError("Claude returned empty text")
    return text


def _generate_gemini_sync(prompt_input: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"{SUMMARY_SYSTEM_PROMPT}\n\n{prompt_input}",
    )
    text = getattr(response, "text", "") or ""
    if not text.strip():
        raise RuntimeError("Gemini returned empty text")
    return text.strip()


async def summarize_with_gemini(prompt_input: str) -> str:
    return await asyncio.to_thread(_generate_gemini_sync, prompt_input)


async def generate_summary(prompt_input: str) -> str:
    """Generate a news summary using Claude, falling back to Gemini."""
    try:
        return await summarize_with_claude(prompt_input=prompt_input)
    except Exception as first_error:  # noqa: BLE001
        try:
            return await summarize_with_gemini(prompt_input)
        except Exception as second_error:  # noqa: BLE001
            raise RuntimeError(
                f"All summary backends failed: claude={first_error}; gemini={second_error}"
            ) from second_error
