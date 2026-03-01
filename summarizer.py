from __future__ import annotations

import asyncio
import os
from typing import Any

from anthropic import AsyncAnthropic
from google import genai

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
CLAUDE_WEB_TOOL_TYPE = os.getenv("CLAUDE_WEB_TOOL_TYPE", "web_search_20250305")
CLAUDE_ALLOWED_DOMAINS = [
    domain.strip()
    for domain in os.getenv(
        "CLAUDE_ALLOWED_DOMAINS",
        "reuters.com,bloomberg.com,wsj.com,cnbc.com,nikkei.com,jp.reuters.com",
    ).split(",")
    if domain.strip()
]
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

SUMMARY_SYSTEM_PROMPT = """あなたは前場前の日本株投資家向けマーケット速報Botです。
次の条件で簡潔に要約してください。
- 全体で1000文字以内、理想は500-850文字
- 重要度順に整理
- 指数、マクロ、日本市場、個別テーマをバランス良く含める
- 重複やノイズは削る
- 断定しすぎず、事実と含意を分ける
- 日本語で書く
"""


def _extract_text_from_message(message: Any) -> str:
    blocks: list[str] = []
    for block in getattr(message, "content", []):
        text = getattr(block, "text", None)
        if text:
            blocks.append(text.strip())
    return "\n".join(part for part in blocks if part).strip()


async def summarize_with_claude(prompt_input: str, enable_web_tool: bool = False) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = AsyncAnthropic(api_key=api_key)
    request_args: dict[str, Any] = {
        "model": CLAUDE_MODEL,
        "max_tokens": 900,
        "system": SUMMARY_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt_input}],
    }
    if enable_web_tool:
        request_args["tools"] = [
            {
                "type": CLAUDE_WEB_TOOL_TYPE,
                "name": "web_search",
                "max_uses": 3,
                "allowed_domains": CLAUDE_ALLOWED_DOMAINS,
            }
        ]

    message = await client.messages.create(**request_args)
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


def should_use_claude_web_tool(snapshot: dict[str, Any], summary: str) -> bool:
    diagnostics = snapshot.get("diagnostics", {})
    tavily_hits = int(diagnostics.get("tavilyHits", 0))
    unique_domains = diagnostics.get("uniqueDomains", {})
    domain_count = len(unique_domains) if isinstance(unique_domains, dict) else 0
    important_keywords = ("FOMC", "CPI", "PCE", "日銀", "BOJ", "雇用統計", "利下げ", "関税")
    has_important_keyword = any(keyword in summary for keyword in important_keywords)

    return (
        tavily_hits < 2
        or domain_count < 2
        or (has_important_keyword and tavily_hits < 4)
        or len(summary) < 350
    )


async def generate_summary(prompt_input: str, snapshot: dict[str, Any]) -> str:
    use_web = should_use_claude_web_tool(snapshot, prompt_input)

    try:
        return await summarize_with_claude(prompt_input=prompt_input, enable_web_tool=use_web)
    except Exception as first_error:  # noqa: BLE001
        try:
            return await summarize_with_claude(prompt_input=prompt_input, enable_web_tool=False)
        except Exception as second_error:  # noqa: BLE001
            try:
                return await summarize_with_gemini(prompt_input)
            except Exception as third_error:  # noqa: BLE001
                raise RuntimeError(
                    "All summary backends failed: "
                    f"claude_web={first_error}; "
                    f"claude_plain={second_error}; "
                    f"gemini={third_error}"
                ) from third_error
