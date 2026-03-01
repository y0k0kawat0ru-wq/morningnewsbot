from __future__ import annotations

import os
from textwrap import shorten

import httpx

DISCORD_MAX_CHARS = 1800


def truncate_for_discord(text: str, max_length: int = DISCORD_MAX_CHARS) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


async def post_to_discord(message: str) -> None:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not set")

    preview = shorten(message.replace("\n", " "), width=240, placeholder="...")
    print(f"[discord] sending ({len(message)} chars): {preview}")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(webhook_url, json={"content": message})
        response.raise_for_status()
    print("[discord] sent successfully")
