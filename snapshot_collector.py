from __future__ import annotations

import asyncio
import csv
import io
import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

JST = timezone(timedelta(hours=9))

STOOQ_SYMBOLS: dict[str, list[str]] = {
    "S&P500": ["^spx"],
    "Nasdaq100": ["^ndq"],
    "Dow": ["^dji"],
    "VIX": ["^vix", "vix"],
    "USDJPY": ["usdjpy"],
}

TAVILY_DOMAINS_GLOBAL = [
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "cnbc.com",
    "finance.yahoo.com",
]
TAVILY_DOMAINS_JAPAN = [
    "nikkei.com",
    "jp.reuters.com",
    "bloomberg.co.jp",
    "kabutan.jp",
    "moneyworld.jp",
]
RSS_FEEDS = {
    "rssFallback": [
        "https://news.google.com/rss/search?q=%E6%97%A5%E6%9C%AC%E6%A0%AA+%E5%B8%82%E5%A0%B4&hl=ja&gl=JP&ceid=JP:ja",
        "https://news.google.com/rss/search?q=global+markets&hl=en-US&gl=US&ceid=US:en",
    ]
}


@dataclass(slots=True)
class TavilyQuery:
    bucket: str
    query: str
    domains: list[str]
    max_results: int = 4


def _now_jst_iso() -> str:
    return datetime.now(JST).replace(microsecond=0).isoformat()


def _parse_domain(url: str) -> str:
    if not url:
        return "unknown"
    return urlparse(url).netloc.lower() or "unknown"


async def _fetch_stooq_close(
    client: httpx.AsyncClient,
    label: str,
    symbol_candidates: list[str],
) -> tuple[str, dict[str, Any], str | None]:
    last_error: str | None = None
    for symbol in symbol_candidates:
        url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
        try:
            response = await client.get(url)
            response.raise_for_status()
            reader = csv.DictReader(io.StringIO(response.text))
            rows = [row for row in reader if row.get("Date") and row.get("Close")]
            if not rows:
                last_error = f"no rows for {symbol}"
                continue
            row = rows[-1]
            return (
                label,
                {
                    "symbol": symbol,
                    "date": row["Date"],
                    "close": row["Close"],
                },
                None,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"{symbol}: {exc}"
    return label, {}, last_error


async def _search_tavily(
    client: httpx.AsyncClient,
    query: TavilyQuery,
) -> tuple[str, list[dict[str, str]], str | None]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return query.bucket, [], "TAVILY_API_KEY is not set"

    payload = {
        "api_key": api_key,
        "query": query.query,
        "max_results": query.max_results,
        "include_domains": query.domains,
        "search_depth": "basic",
        "topic": "news",
    }
    try:
        response = await client.post("https://api.tavily.com/search", json=payload)
        response.raise_for_status()
        data = response.json()
        results = []
        for item in data.get("results", []):
            results.append(
                {
                    "title": item.get("title", "").strip(),
                    "url": item.get("url", "").strip(),
                    "snippet": item.get("content", "").strip(),
                    "source": _parse_domain(item.get("url", "")),
                }
            )
        return query.bucket, results, None
    except Exception as exc:  # noqa: BLE001
        return query.bucket, [], str(exc)


async def _parse_rss_feed(url: str) -> list[dict[str, str]]:
    feed = await asyncio.to_thread(feedparser.parse, url)
    items: list[dict[str, str]] = []
    for entry in feed.entries[:4]:
        items.append(
            {
                "title": getattr(entry, "title", "").strip(),
                "url": getattr(entry, "link", "").strip(),
                "snippet": getattr(entry, "summary", "").strip(),
                "source": _parse_domain(getattr(entry, "link", "")),
            }
        )
    return items


def _dedupe_news_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique_items: list[dict[str, str]] = []
    for item in items:
        key = item.get("url") or f"{item.get('title')}|{item.get('source')}"
        if not key or key in seen:
            continue
        seen.add(key)
        unique_items.append(item)
    return unique_items


async def collect_morning_snapshot() -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "tavilyHits": 0,
        "uniqueDomains": {},
        "errors": [],
    }
    news: dict[str, list[dict[str, str]]] = {
        "macroGlobal": [],
        "japanMarket": [],
        "financeFocus": [],
        "rssFallback": [],
    }
    indices: dict[str, dict[str, str]] = {}

    timeout = httpx.Timeout(12.0, connect=8.0)
    tavily_queries = [
        TavilyQuery("macroGlobal", "global market stocks bonds inflation central bank", TAVILY_DOMAINS_GLOBAL),
        TavilyQuery("japanMarket", "Japan market Nikkei TOPIX Bank of Japan yen", TAVILY_DOMAINS_JAPAN),
        TavilyQuery("financeFocus", "earnings guidance sectors financial markets themes", TAVILY_DOMAINS_GLOBAL + TAVILY_DOMAINS_JAPAN),
    ]

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        stooq_tasks = [
            _fetch_stooq_close(client=client, label=label, symbol_candidates=candidates)
            for label, candidates in STOOQ_SYMBOLS.items()
        ]
        tavily_tasks = [_search_tavily(client=client, query=query) for query in tavily_queries]

        stooq_results, tavily_results = await asyncio.gather(
            asyncio.gather(*stooq_tasks),
            asyncio.gather(*tavily_tasks),
        )

    for label, payload, error in stooq_results:
        if payload:
            indices[label] = payload
        elif error:
            diagnostics["errors"].append(f"stooq[{label}] {error}")

    for bucket, items, error in tavily_results:
        news[bucket] = _dedupe_news_items(items)
        diagnostics["tavilyHits"] += len(news[bucket])
        if error:
            diagnostics["errors"].append(f"tavily[{bucket}] {error}")

    rss_tasks = [_parse_rss_feed(url) for url in RSS_FEEDS["rssFallback"]]
    rss_results = await asyncio.gather(*rss_tasks, return_exceptions=True)
    rss_items: list[dict[str, str]] = []
    for result in rss_results:
        if isinstance(result, Exception):
            diagnostics["errors"].append(f"rss {result}")
            continue
        rss_items.extend(result)
    news["rssFallback"] = _dedupe_news_items(rss_items)

    domain_counter: Counter[str] = Counter()
    for bucket_items in news.values():
        for item in bucket_items:
            domain_counter[item.get("source", "unknown")] += 1
    diagnostics["uniqueDomains"] = dict(domain_counter)

    return {
        "fetchedAtJST": _now_jst_iso(),
        "indices": indices,
        "news": news,
        "diagnostics": diagnostics,
    }
