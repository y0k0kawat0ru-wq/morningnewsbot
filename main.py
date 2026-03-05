from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
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

from deduper import compute_diff_from_previous
from freshness import FreshnessStats, filter_fresh_news
from notifier import post_to_discord, truncate_for_discord
from snapshot_collector import IndexData, NewsItem, collect_morning_snapshot
from state_store import load_state, save_state
from summarizer import generate_summary

JST = timezone(timedelta(hours=9))


# ---------------------------------------------------------------------------
# Index formatting (day-over-day change)
# ---------------------------------------------------------------------------

def format_index_line(label: str, data: IndexData) -> str:
    """Format a single index line with day-over-day change."""
    close_str = f"{data.close:,.2f}"
    if data.prev_close is not None and data.prev_close != 0:
        diff = data.close - data.prev_close
        pct = (diff / data.prev_close) * 100
        sign = "+" if diff >= 0 else ""
        return f"{label}: {close_str}（{sign}{diff:,.2f} / {sign}{pct:.2f}%）"
    return f"{label}: {close_str}（前日比取得不可）"


def format_indices_section(indices: dict[str, IndexData]) -> str:
    """Build the market indices section for Discord."""
    lines = ["\U0001F4CA 米国市場概況"]
    display_order = ["S&P500", "Nasdaq100", "Dow", "VIX", "USDJPY"]
    label_map = {"USDJPY": "ドル円"}

    for key in display_order:
        if key in indices:
            display_label = label_map.get(key, key)
            lines.append(format_index_line(display_label, indices[key]))

    if len(lines) == 1:
        lines.append("指数データ取得不可")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# News categorization & LLM prompt
# ---------------------------------------------------------------------------

def categorize_news(items: list[NewsItem]) -> dict[str, list[NewsItem]]:
    categories: dict[str, list[NewsItem]] = {
        "global": [],
        "japan": [],
    }
    for item in items:
        if item.category.startswith("jp_"):
            categories["japan"].append(item)
        else:
            categories["global"].append(item)
    return categories


def build_llm_prompt(news_items: list[NewsItem]) -> str:
    """Build a prompt for the LLM from filtered news items only."""
    if not news_items:
        return (
            "ニュース記事が取得できませんでした。以下のように出力してください：\n\n"
            "📰 主要ニュース\n"
            "- 24時間以内の主要新規ヘッドラインは限定的です。\n\n"
            "🇯🇵 日本株関連\n"
            "- 24時間以内の主要新規ヘッドラインは限定的です。"
        )

    lines = [
        "以下のニュース一覧のみを根拠に要約してください。",
        "入力にない情報は絶対に追加しないでください。\n",
    ]

    categorized = categorize_news(news_items)

    if categorized["global"]:
        lines.append("[グローバル・米国ニュース]")
        for item in categorized["global"]:
            pub = ""
            if item.published_at_jst:
                pub = f" ({item.published_at_jst.strftime('%m/%d %H:%M')})"
            lines.append(f"- [{item.source}]{pub} {item.title}")
            if item.snippet:
                lines.append(f"  {item.snippet[:200]}")
        lines.append("")

    if categorized["japan"]:
        lines.append("[日本株関連ニュース]")
        for item in categorized["japan"]:
            pub = ""
            if item.published_at_jst:
                pub = f" ({item.published_at_jst.strftime('%m/%d %H:%M')})"
            lines.append(f"- [{item.source}]{pub} {item.title}")
            if item.snippet:
                lines.append(f"  {item.snippet[:200]}")
        lines.append("")

    if not categorized["japan"]:
        lines.append(
            "[日本株関連ニュース]\n"
            "該当記事なし。「🇯🇵 日本株関連」セクションには"
            "「24時間以内の主要新規ヘッドラインは限定的です。」と記載してください。"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Discord message assembly
# ---------------------------------------------------------------------------

def build_discord_message(
    indices: dict[str, IndexData],
    summary: str,
    now_jst: datetime,
) -> str:
    date_str = f"{now_jst.month}/{now_jst.day}"
    parts = [
        f"前場前マーケット速報（{date_str}）\n",
        format_indices_section(indices),
        "",
        summary,
        "",
        "※本Botはニュース整理を目的とした情報提供です。投資判断は自己責任でお願いします。",
    ]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Diagnostics logging
# ---------------------------------------------------------------------------

def log_diagnostics(
    snapshot_diag: dict[str, Any],
    freshness_stats: FreshnessStats,
    diff_info: dict[str, Any],
    final_items: list[NewsItem],
    indices: dict[str, IndexData],
) -> None:
    print("=" * 50)
    print("[診断ログ]")
    print(f"  取得ニュース総数: {freshness_stats.total_input}")
    print(f"  鮮度フィルタ通過数: {freshness_stats.passed}")
    print(f"  古い記事除外数: {freshness_stats.excluded_stale}")
    print(f"  日付不明(JP)除外数: {freshness_stats.excluded_no_date_jp}")
    if freshness_stats.jp_fallback_used:
        print(f"  JP fallback発動: {freshness_stats.jp_fallback_added}件救済")
    print(f"  重複除外数: {diff_info['repeatedCount']}")
    print(f"  Tavily取得数: {snapshot_diag.get('tavilyHits', 0)}")
    print(f"  RSS取得数: {snapshot_diag.get('rssHits', 0)}")
    print(f"  RSSフォールバック使用: {snapshot_diag.get('rssUsed', False)}")
    print(f"  ユニークドメイン数: {len(snapshot_diag.get('uniqueDomains', {}))}")

    # Index diff status
    index_success = sum(1 for d in indices.values() if d.prev_close is not None)
    index_fail = len(indices) - index_success
    print(f"  指数前日比: 成功={index_success}, 失敗={index_fail}")

    categorized = categorize_news(final_items)
    print(
        f"  最終要約対象 - グローバル: {len(categorized['global'])}件, "
        f"日本: {len(categorized['japan'])}件"
    )

    if final_items:
        print("  [要約対象記事]")
        for item in final_items:
            pub = item.published_at_jst.isoformat() if item.published_at_jst else "N/A"
            print(f"    - {item.title[:60]} | {item.source} | {pub}")

    errors = snapshot_diag.get("errors", [])
    if errors:
        print(f"  [エラー] {' | '.join(errors[:5])}")

    if freshness_stats.excluded_items:
        print("  [除外記事サンプル]")
        for exc in freshness_stats.excluded_items[:5]:
            print(f"    - {exc.get('title', '')[:50]} ({exc.get('reason', '')})")

    print("=" * 50)


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

async def run() -> None:
    prev_state = load_state()

    # 1. Collect market data and news
    snapshot = await collect_morning_snapshot()
    now_jst = datetime.fromisoformat(snapshot["fetchedAtJST"])
    indices: dict[str, IndexData] = snapshot["indices"]
    all_news: list[NewsItem] = snapshot["news"]

    # 2. Freshness filter
    fresh_news, freshness_stats = filter_fresh_news(all_news, now_jst)

    # 3. Dedup against previous state
    diff_info = compute_diff_from_previous(fresh_news, prev_state)
    new_items: list[NewsItem] = diff_info["newItems"]

    # 4. Final items: only new items (no fallback to old articles)
    final_items = new_items

    # 5. Log diagnostics
    log_diagnostics(
        snapshot["diagnostics"], freshness_stats, diff_info, final_items, indices,
    )

    # 6. Build LLM prompt and generate summary
    llm_prompt = build_llm_prompt(final_items)
    summary = await generate_summary(prompt_input=llm_prompt)

    # 7. Build Discord message
    message = build_discord_message(indices, summary, now_jst)
    message = truncate_for_discord(message)

    # 8. Send to Discord
    await post_to_discord(message)

    # 9. Save state
    next_state = {
        "last_keys": diff_info["currentKeys"],
        "last_summary_hash": sha256(message.encode("utf-8")).hexdigest(),
        "last_run_jst": snapshot["fetchedAtJST"],
    }
    save_state(next_state)


async def main() -> None:
    try:
        await run()
    except Exception as exc:  # noqa: BLE001
        error_message = truncate_for_discord(f"Morning Market Bot 実行エラー: {exc}")
        try:
            await post_to_discord(error_message)
        except Exception:  # noqa: BLE001
            pass
        raise


if __name__ == "__main__":
    asyncio.run(main())
