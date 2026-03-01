from __future__ import annotations

from hashlib import sha256
from typing import Any


def _stable_digest(*parts: str) -> str:
    return sha256("||".join(parts).encode("utf-8")).hexdigest()


def collect_all_content_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for label, payload in snapshot.get("indices", {}).items():
        date = str(payload.get("date", ""))
        key = f"econ|{date}|global|{label}"
        items.append(
            {
                "key": key,
                "kind": "econ",
                "label": f"{label} {payload.get('close', 'n/a')} ({date})",
                "raw": payload,
            }
        )

    for bucket, bucket_items in snapshot.get("news", {}).items():
        prefix = "rss" if bucket == "rssFallback" else "news"
        for item in bucket_items:
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            digest = _stable_digest(url, title)
            items.append(
                {
                    "key": f"{prefix}|{digest}",
                    "kind": prefix,
                    "label": title or url or "(untitled)",
                    "bucket": bucket,
                    "raw": item,
                }
            )

    return items


def compute_diff_from_previous(snapshot: dict[str, Any], prev_state: dict[str, Any]) -> dict[str, Any]:
    current_items = collect_all_content_items(snapshot)
    current_keys = [item["key"] for item in current_items]
    prev_keys = set(prev_state.get("last_keys", []))

    new_items = [item for item in current_items if item["key"] not in prev_keys]
    repeated_count = max(0, len(current_items) - len(new_items))
    fallback_items = new_items if new_items else current_items[:4]

    return {
        "currentKeys": current_keys,
        "newItems": new_items,
        "repeatedCount": repeated_count,
        "fallbackItems": fallback_items,
    }


def append_dedup_note_if_needed(summary: str, diff_info: dict[str, Any]) -> str:
    if diff_info.get("newItems"):
        return summary
    note = "※ 新規性は限定的（前回配信時と同一の材料が中心）"
    if note in summary:
        return summary
    return f"{summary.rstrip()}\n\n{note}"
