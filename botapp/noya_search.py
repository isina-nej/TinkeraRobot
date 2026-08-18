"""Lightweight live web search for Noya. Fail-open; never required to answer."""

from __future__ import annotations

import logging
import os
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT = float(os.getenv("NOYA_SEARCH_TIMEOUT", "8"))
_MAX_RESULTS = 5
_MAX_BLOCK_CHARS = 1800

_EXPLICIT = (
    "سرچ کن",
    "سرچش کن",
    "جستجو کن",
    "جست‌وجو",
    "گوگل کن",
    "تو گوگل",
    "بگرد ببین",
    "پیدا کن",
    "search",
    "google",
)
_LIVE = (
    "اخبار",
    "خبر",
    "قیمت دلار",
    "قیمت طلا",
    "نرخ ارز",
    "نرخ دلار",
    "آب و هوا",
    "هواشناسی",
    "نتیجه بازی",
    "جدول لیگ",
    "امشب چی",
    "امروز چه خبر",
    "آخرین خبر",
    "کی برد",
    "برنده انتخابات",
    "قیمت بیت",
    "crypto",
    "bitcoin",
)
_SKIP_PREFIX = (
    "سلام",
    "خوبی",
    "چطوری",
    "چخبر",
    "چه خبر",
    "جونم",
    "قربون",
    "عشقم",
    "صبح بخیر",
    "شب بخیر",
)
_CLOCK_ONLY = (
    "ساعت چنده",
    "ساعت چند است",
    "تاریخ امروز",
    "امروز چندمه",
    "امروز چندم",
    "چه روزیه",
    "چه روزی است",
)


def search_enabled() -> bool:
    return os.getenv("NOYA_SEARCH_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def needs_web_search(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    lowered = raw.casefold()
    if any(token in lowered for token in _CLOCK_ONLY):
        return False
    compact = re.sub(r"\s+", " ", lowered)
    if len(compact) <= 24 and any(compact.startswith(p) or compact == p for p in _SKIP_PREFIX):
        return False
    if any(token in lowered for token in _EXPLICIT):
        return True
    if any(token in lowered for token in _LIVE):
        return True
    return False


class _LiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_link = False
        self._href = ""
        self._buf: list[str] = []
        self.results: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        data = dict(attrs)
        href = data.get("href") or ""
        if "uddg=" in href or data.get("class") == "result-link":
            self._in_link = True
            self._href = href
            self._buf = []

    def handle_endtag(self, tag):
        if tag != "a" or not self._in_link:
            return
        self._in_link = False
        title = unescape("".join(self._buf)).strip()
        url = _decode_ddg_url(self._href)
        if title and url and not url.startswith("https://duckduckgo.com"):
            self.results.append((title, url))

    def handle_data(self, data):
        if self._in_link:
            self._buf.append(data)


def _decode_ddg_url(href: str) -> str:
    href = unescape(href or "")
    if "uddg=" in href:
        qs = parse_qs(urlparse(href).query)
        target = (qs.get("uddg") or [""])[0]
        return unquote(target)
    if href.startswith("http"):
        return href
    return ""


def _format_block(lines: list[str]) -> str:
    body = "\n".join(line for line in lines if line).strip()
    if not body:
        return ""
    if len(body) > _MAX_BLOCK_CHARS:
        body = body[: _MAX_BLOCK_CHARS - 20] + "\n…[truncated]"
    return f"[WEB]\n{body}\n[/WEB]"


async def web_search(query: str) -> str:
    q = re.sub(r"\s+", " ", (query or "").strip())
    if not q:
        return ""
    headers = {
        "User-Agent": "TinkeraRobot-Noya/1.0 (+https://nodia.ir)",
        "Accept-Language": "fa,en;q=0.8",
    }
    timeout = httpx.Timeout(_SEARCH_TIMEOUT)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            instant = await _duckduckgo_instant(client, q)
            if instant:
                return instant
            return await _duckduckgo_lite(client, q)
    except (httpx.HTTPError, ValueError, OSError):
        logger.info("noya_search_failed query=%s", q[:80])
        return ""


async def _duckduckgo_instant(client: httpx.AsyncClient, query: str) -> str:
    response = await client.get(
        "https://api.duckduckgo.com/",
        params={
            "q": query,
            "format": "json",
            "no_html": "1",
            "no_redirect": "1",
            "skip_disambig": "1",
            "kl": "ir-fa",
        },
    )
    response.raise_for_status()
    data = response.json()
    lines: list[str] = []
    heading = (data.get("Heading") or "").strip()
    abstract = (data.get("AbstractText") or data.get("Abstract") or "").strip()
    source = (data.get("AbstractURL") or "").strip()
    if abstract:
        label = heading or "خلاصه"
        lines.append(f"• {label}: {abstract}")
        if source:
            lines.append(f"  {source}")
    for item in (data.get("RelatedTopics") or [])[:_MAX_RESULTS]:
        if not isinstance(item, dict):
            continue
        text = (item.get("Text") or "").strip()
        url = (item.get("FirstURL") or "").strip()
        if text:
            lines.append(f"• {text}")
            if url:
                lines.append(f"  {url}")
        if len(lines) >= _MAX_RESULTS * 2:
            break
    return _format_block(lines)


async def _duckduckgo_lite(client: httpx.AsyncClient, query: str) -> str:
    response = await client.get(
        "https://lite.duckduckgo.com/lite/",
        params={"q": query, "kl": "ir-fa"},
    )
    response.raise_for_status()
    parser = _LiteParser()
    parser.feed(response.text)
    lines: list[str] = []
    seen: set[str] = set()
    for title, url in parser.results:
        if url in seen:
            continue
        seen.add(url)
        lines.append(f"• {title}")
        lines.append(f"  {url}")
        if len(seen) >= _MAX_RESULTS:
            break
    return _format_block(lines)


async def maybe_web_search(question: str) -> str:
    if not search_enabled() or not needs_web_search(question):
        return ""
    block = await web_search(question)
    if block:
        logger.info("noya_search_hit qlen=%s", len(question or ""))
    return block
