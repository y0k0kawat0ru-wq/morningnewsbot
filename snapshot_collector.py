from __future__ import annotations

import asyncio
import csv
import io
import os
import re
from calendar import timegm
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import feedparser
import httpx

JST = timezone(timedelta(hours=9))

# Tracking parameters to strip for canonical URL
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "mc_cid", "mc_eid",
})


def normalize_url(url: str) -> str:
    """Strip tracking/query parameters to produce a more stable canonical URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=False)
        cleaned = {k: v for k, v in params.items() if k.lower() not in _TRACKING_PARAMS}
        new_query = urlencode(cleaned, doseq=True)
        return urlunparse(parsed._replace(query=new_query, fragment=""))
    except Exception:
        return url


@dataclass(slots=True)
class NewsItem:
    title: str
    url: str
    canonical_url: str
    source: str
    snippet: str = ""
    published_at_jst: datetime | None = None
    retrieved_at_jst: datetime = field(default_factory=lambda: datetime.now(JST))
    category: str = "other"
    language: str = "en"


@dataclass(slots=True)
class IndexData:
    symbol: str
    label: str
    date: str
    close: float
    prev_date: str | None = None
    prev_close: float | None = None


STOOQ_SYMBOLS: dict[str, list[str]] = {
    "S&P500": ["^spx"],
    "Nasdaq100": ["^ndq"],
    "Dow": ["^dji"],
    "VIX": ["^vix", "vix"],
    "USDJPY": ["usdjpy"],
}
YAHOO_SYMBOLS: dict[str, list[str]] = {
    "S&P500": ["^GSPC"],
    "Nasdaq100": ["^NDX"],
    "Dow": ["^DJI"],
    "VIX": ["^VIX"],
    "USDJPY": ["USDJPY=X", "JPY=X"],
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
RSS_FEEDS = [
    "https://news.google.com/rss/search?q=%E6%97%A5%E6%9C%AC%E6%A0%AA+%E5%B8%82%E5%A0%B4&hl=ja&gl=JP&ceid=JP:ja",
    "https://news.google.com/rss/search?q=global+markets&hl=en-US&gl=US&ceid=US:en",
]
INDEX_LABELS = ("S&P500", "Nasdaq100", "Dow", "VIX", "USDJPY")


@dataclass(slots=True)
class TavilyQuery:
    category: str
    query: str
    domains: list[str]
    language: str = "en"
    max_results: int = 4


def _now_jst() -> datetime:
    return datetime.now(JST)


def _parse_domain(url: str) -> str:
    if not url:
        return "unknown"
    return urlparse(url).netloc.lower() or "unknown"


def _parse_published_date(date_str: str | None) -> datetime | None:
    """Try to parse a date string into a JST datetime."""
    if not date_str:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
    ):
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(JST)
        except ValueError:
            continue
    return None


def _struct_time_to_jst(st: Any) -> datetime | None:
    """Convert feedparser's time.struct_time to JST datetime."""
    if st is None:
        return None
    try:
        ts = timegm(st)
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(JST)
    except Exception:
        return None


def _date_from_unix_timestamp(ts: Any) -> str | None:
    """Convert a Unix timestamp to an ISO date string."""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
    except Exception:
        return None


def _parse_yahoo_chart_payload(
    label: str,
    symbol: str,
    payload: dict[str, Any],
) -> tuple[IndexData | None, str | None]:
    """Parse Yahoo Finance chart payload into IndexData."""
    chart = payload.get("chart") or {}
    result = chart.get("result") or []
    if not result:
        error = chart.get("error")
        if isinstance(error, dict) and error.get("description"):
            return None, str(error["description"])
        return None, f"no result for {symbol}"

    series = result[0] or {}
    indicators = series.get("indicators") or {}
    quotes = indicators.get("quote") or []
    if not quotes:
        return None, f"no quotes for {symbol}"

    timestamps = series.get("timestamp") or []
    closes = quotes[0].get("close") or []
    valid_points: list[tuple[str, float]] = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        try:
            close_val = float(close)
        except (TypeError, ValueError):
            continue
        date_val = _date_from_unix_timestamp(ts)
        if date_val is None:
            continue
        valid_points.append((date_val, close_val))

    if not valid_points:
        return None, f"no rows for {symbol}"

    current_date, current_close = valid_points[-1]
    prev_date: str | None = None
    prev_close: float | None = None
    if len(valid_points) >= 2:
        prev_date, prev_close = valid_points[-2]

    return (
        IndexData(
            symbol=symbol,
            label=label,
            date=current_date,
            close=current_close,
            prev_date=prev_date,
            prev_close=prev_close,
        ),
        None,
    )


async def _fetch_yahoo_chart_data(
    client: httpx.AsyncClient,
    label: str,
    symbol_candidates: list[str],
) -> tuple[str, IndexData | None, str | None]:
    """Fetch index data from Yahoo Finance chart API."""
    last_error: str | None = None
    for symbol in symbol_candidates:
        encoded_symbol = quote(symbol, safe="")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}"
        params = {
            "range": "5d",
            "interval": "1d",
            "includePrePost": "false",
            "events": "div,splits",
        }
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data, error = _parse_yahoo_chart_payload(label, symbol, response.json())
            if data is not None:
                return label, data, None
            last_error = error
        except Exception as exc:  # noqa: BLE001
            last_error = f"{symbol}: {exc}"
    return label, None, last_error


async def _fetch_index_data(
    client: httpx.AsyncClient,
    label: str,
) -> tuple[str, IndexData | None, str | None]:
    """Fetch index data with Yahoo primary and Stooq fallback."""
    errors: list[str] = []

    yahoo_candidates = YAHOO_SYMBOLS.get(label, [])
    if yahoo_candidates:
        _, data, error = await _fetch_yahoo_chart_data(client, label, yahoo_candidates)
        if data is not None:
            return label, data, None
        if error:
            errors.append(f"yahoo {error}")

    stooq_candidates = STOOQ_SYMBOLS.get(label, [])
    if stooq_candidates:
        _, data, error = await _fetch_stooq_data(client, label, stooq_candidates)
        if data is not None:
            return label, data, None
        if error:
            errors.append(f"stooq {error}")

    return label, None, " | ".join(errors) if errors else "no data sources configured"


async def _fetch_stooq_data(
    client: httpx.AsyncClient,
    label: str,
    symbol_candidates: list[str],
) -> tuple[str, IndexData | None, str | None]:
    """Fetch index data from Stooq, returning current and previous close."""
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
            current = rows[-1]
            prev = rows[-2] if len(rows) >= 2 else None
            try:
                close_val = float(current["Close"])
            except (ValueError, TypeError):
                last_error = f"invalid close for {symbol}"
                continue
            prev_close_val: float | None = None
            prev_date_val: str | None = None
            if prev:
                try:
                    prev_close_val = float(prev["Close"])
                    prev_date_val = prev["Date"]
                except (ValueError, TypeError):
                    pass
            return (
                label,
                IndexData(
                    symbol=symbol,
                    label=label,
                    date=current["Date"],
                    close=close_val,
                    prev_date=prev_date_val,
                    prev_close=prev_close_val,
                ),
                None,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"{symbol}: {exc}"
    return label, None, last_error


async def _search_tavily(
    client: httpx.AsyncClient,
    query: TavilyQuery,
    now: datetime,
) -> tuple[str, list[NewsItem], str | None]:
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return query.category, [], "TAVILY_API_KEY is not set"

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
        items: list[NewsItem] = []
        for item in data.get("results", []):
            raw_url = item.get("url", "").strip()
            pub_date = _parse_published_date(item.get("published_date"))
            items.append(
                NewsItem(
                    title=item.get("title", "").strip(),
                    url=raw_url,
                    canonical_url=normalize_url(raw_url),
                    source=_parse_domain(raw_url),
                    snippet=item.get("content", "").strip(),
                    published_at_jst=pub_date,
                    retrieved_at_jst=now,
                    category=query.category,
                    language=query.language,
                )
            )
        return query.category, items, None
    except Exception as exc:  # noqa: BLE001
        return query.category, [], str(exc)


async def _parse_rss_feed(url: str, now: datetime) -> list[NewsItem]:
    feed = await asyncio.to_thread(feedparser.parse, url)
    is_jp = "hl=ja" in url
    items: list[NewsItem] = []
    for entry in feed.entries[:4]:
        raw_url = getattr(entry, "link", "").strip()
        pub_date = _struct_time_to_jst(getattr(entry, "published_parsed", None))
        items.append(
            NewsItem(
                title=getattr(entry, "title", "").strip(),
                url=raw_url,
                canonical_url=normalize_url(raw_url),
                source=_parse_domain(raw_url),
                snippet=getattr(entry, "summary", "").strip(),
                published_at_jst=pub_date,
                retrieved_at_jst=now,
                category="jp_market" if is_jp else "us_macro",
                language="ja" if is_jp else "en",
            )
        )
    return items


def _dedupe_news_items(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in items:
        key = item.canonical_url or item.url or f"{item.title}|{item.source}"
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


async def collect_morning_snapshot() -> dict[str, Any]:
    now = _now_jst()
    diagnostics: dict[str, Any] = {
        "tavilyHits": 0,
        "rssHits": 0,
        "rssUsed": False,
        "uniqueDomains": {},
        "errors": [],
    }

    timeout = httpx.Timeout(12.0, connect=8.0)
    tavily_queries = [
        TavilyQuery(
            "us_macro",
            "global market stocks bonds inflation central bank Fed",
            TAVILY_DOMAINS_GLOBAL,
            "en",
        ),
        TavilyQuery(
            "us_equity",
            "US stocks earnings tech sector S&P Nasdaq",
            TAVILY_DOMAINS_GLOBAL,
            "en",
        ),
        TavilyQuery(
            "jp_market",
            "日本株 日経平均 TOPIX 東証 為替 円",
            TAVILY_DOMAINS_JAPAN,
            "ja",
            5,
        ),
        TavilyQuery(
            "jp_stock",
            "Japan market Nikkei TOPIX Bank of Japan yen",
            TAVILY_DOMAINS_JAPAN + TAVILY_DOMAINS_GLOBAL[:2],
            "en",
            3,
        ),
    ]

    indices: dict[str, IndexData] = {}
    all_news: list[NewsItem] = []

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        index_tasks = [
            _fetch_index_data(client=client, label=label)
            for label in INDEX_LABELS
        ]
        tavily_tasks = [
            _search_tavily(client=client, query=q, now=now)
            for q in tavily_queries
        ]

        index_results, tavily_results = await asyncio.gather(
            asyncio.gather(*index_tasks),
            asyncio.gather(*tavily_tasks),
        )

    for label, data, error in index_results:
        if data:
            indices[label] = data
        elif error:
            diagnostics["errors"].append(f"indices[{label}] {error}")

    for category, items, error in tavily_results:
        deduped = _dedupe_news_items(items)
        all_news.extend(deduped)
        diagnostics["tavilyHits"] += len(deduped)
        if error:
            diagnostics["errors"].append(f"tavily[{category}] {error}")

    # RSS fallback: only use when Tavily results are insufficient
    rss_tasks = [_parse_rss_feed(url, now) for url in RSS_FEEDS]
    rss_results = await asyncio.gather(*rss_tasks, return_exceptions=True)
    rss_items: list[NewsItem] = []
    for result in rss_results:
        if isinstance(result, Exception):
            diagnostics["errors"].append(f"rss {result}")
            continue
        rss_items.extend(result)
    rss_deduped = _dedupe_news_items(rss_items)
    diagnostics["rssHits"] = len(rss_deduped)

    if diagnostics["tavilyHits"] < 3:
        all_news.extend(rss_deduped)
        diagnostics["rssUsed"] = True

    # Domain stats
    domain_counter: Counter[str] = Counter()
    for item in all_news:
        domain_counter[item.source] += 1
    diagnostics["uniqueDomains"] = dict(domain_counter)

    return {
        "fetchedAtJST": now.replace(microsecond=0).isoformat(),
        "indices": indices,
        "news": all_news,
        "diagnostics": diagnostics,
    }
