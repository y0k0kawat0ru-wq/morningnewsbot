from __future__ import annotations

import asyncio
from hashlib import sha256
from pathlib import Path
from typing import Any


def _load_local_env() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            import os

            os.environ[key] = value


_load_local_env()

from deduper import append_dedup_note_if_needed, compute_diff_from_previous
from notifier import post_to_discord, truncate_for_discord
from snapshot_collector import collect_morning_snapshot
from state_store import load_state, save_state
from summarizer import generate_summary


def _format_indices(snapshot: dict[str, Any]) -> list[str]:
    lines: list[str] = ["[指数]"]
    for label, payload in snapshot.get("indices", {}).items():
        lines.append(f"- {label}: {payload.get('close', 'n/a')} ({payload.get('date', 'n/a')})")
    if len(lines) == 1:
        lines.append("- 取得データなし")
    return lines


def _format_news(snapshot: dict[str, Any], diff_info: dict[str, Any]) -> list[str]:
    lines: list[str] = ["[注目材料]"]
    source_items = diff_info["newItems"] or diff_info["fallbackItems"]
    if not source_items:
        lines.append("- 取得データなし")
        return lines

    for item in source_items[:8]:
        kind = item.get("kind", "item")
        label = item.get("label", "(untitled)")
        lines.append(f"- {kind}: {label}")
    return lines


def _format_diagnostics(snapshot: dict[str, Any], diff_info: dict[str, Any]) -> list[str]:
    diagnostics = snapshot.get("diagnostics", {})
    lines = [
        "[診断]",
        f"- Tavily hits: {diagnostics.get('tavilyHits', 0)}",
        f"- Unique domains: {len(diagnostics.get('uniqueDomains', {}))}",
        f"- Repeated items: {diff_info.get('repeatedCount', 0)}",
    ]
    errors = diagnostics.get("errors", [])
    if errors:
        lines.append(f"- Errors: {' | '.join(errors[:3])}")
    return lines


def build_prompt_input(snapshot: dict[str, Any], diff_info: dict[str, Any]) -> str:
    parts = [
        "前場前のマーケットサマリーを作成してください。",
        "\n".join(_format_indices(snapshot)),
        "\n".join(_format_news(snapshot, diff_info)),
        "\n".join(_format_diagnostics(snapshot, diff_info)),
    ]
    return "\n\n".join(parts)


async def run() -> None:
    prev_state = load_state()
    snapshot = await collect_morning_snapshot()
    diff_info = compute_diff_from_previous(snapshot, prev_state)

    prompt_input = build_prompt_input(snapshot=snapshot, diff_info=diff_info)
    summary = await generate_summary(prompt_input=prompt_input, snapshot=snapshot)
    summary = append_dedup_note_if_needed(summary, diff_info)
    summary = truncate_for_discord(summary)

    await post_to_discord(summary)

    next_state = {
        "last_keys": diff_info["currentKeys"],
        "last_summary_hash": sha256(summary.encode("utf-8")).hexdigest(),
        "last_run_jst": snapshot["fetchedAtJST"],
    }
    save_state(next_state)


async def main() -> None:
    try:
        await run()
    except Exception as exc:  # noqa: BLE001
        error_message = truncate_for_discord(f"Morning Market Bot failed: {exc}")
        try:
            await post_to_discord(error_message)
        except Exception:  # noqa: BLE001
            pass
        raise


if __name__ == "__main__":
    asyncio.run(main())
