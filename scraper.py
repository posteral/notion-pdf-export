"""
web-to-pdf: crawl any public website and produce a single PDF.

Uses Playwright (headless Chromium) to handle JavaScript-rendered pages.
Has enhanced support for Notion-hosted sites.

Usage:
    python scraper.py <root_url> [--output FILE] [--max-pages N] [--delay SECS]
"""
from __future__ import annotations

import argparse
import logging
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

SKIP_PATH_FRAGMENTS = (
    "/login", "/signup", "/sign-up", "/sign-in",
    "/register", "/logout", "/pricing", "/blog",
    "/cookie", "/report", "/abuse", "/template",
)

# Notion-specific junk UI strings
_NOTION_JUNK = {
    "get notion free", "try notion free", "duplicate page",
    "powered by notion", "notion – the all-in-one workspace", "notion",
    "try it free",
}

# Generic junk strings present on most sites
_GENERIC_JUNK = {
    "skip to content", "sign up", "sign in", "log in", "login",
    "get started", "cookie settings", "report page",
    "accept cookies", "accept all", "privacy policy", "terms of service",
    "subscribe", "newsletter",
}

JUNK_STRINGS = _NOTION_JUNK | _GENERIC_JUNK


def _is_notion_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "notion.site" in host or "notion.so" in host


def normalize_url(url: str) -> str:
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, p.params, p.query, ""))


def same_host(url: str, root: str) -> bool:
    return urlparse(url).netloc.lower() == urlparse(root).netloc.lower()


def should_follow(url: str, root: str) -> bool:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    if not same_host(url, root):
        return False
    path_lower = p.path.lower()
    if any(skip in path_lower for skip in SKIP_PATH_FRAGMENTS):
        return False
    return True


# ---------------------------------------------------------------------------
# Page fetching with Playwright
# ---------------------------------------------------------------------------

_NOTION_SELECTORS = ".notion-page-content, .notion-body, main, [class*='notionFrame']"
_GENERIC_SELECTORS = "main, article, [role='main'], #content, #main, .content, .post, .article"


def fetch_rendered(page: Page, url: str) -> str | None:
    """Navigate to url, wait for content to load, return full HTML.

    Tries Notion-specific selectors first, then falls back to generic ones.
    """
    try:
        log.info("  → Navigating (domcontentloaded)...")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        log.info("  → DOM loaded, waiting for content selector...")
        found = False
        for selectors, label in (
            (_NOTION_SELECTORS, "Notion"),
            (_GENERIC_SELECTORS, "generic"),
        ):
            try:
                page.wait_for_selector(selectors, timeout=10000)
                log.info("  → %s content selector found", label)
                found = True
                break
            except PWTimeout:
                pass
        if not found:
            log.warning("  → No content selector matched, proceeding with whatever loaded")
        log.info("  → Waiting 2s for lazy blocks...")
        page.wait_for_timeout(2000)
        html = page.content()
        log.info("  → Got %d bytes of HTML", len(html))
        return html
    except PWTimeout:
        log.warning("  → Timeout fetching %s", url)
        return None
    except Exception as e:
        log.warning("  → Error fetching %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------

def is_junk(text: str) -> bool:
    t = text.strip().lower()
    return not t or t in JUNK_STRINGS or len(t) < 2


def extract_title(soup: BeautifulSoup, url: str) -> str:
    # Notion-specific selectors (highest priority on Notion pages)
    for sel in (
        ".notion-page-block .notranslate",
        ".notion-title",
        "h1.notion-header__title",
        "[class*='notionTitle']",
    ):
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)

    # Generic: first visible h1
    for h1 in soup.find_all("h1"):
        t = h1.get_text(strip=True)
        if t and not is_junk(t):
            return t

    # <title> tag with common suffixes stripped
    title_tag = soup.find("title")
    if title_tag:
        t = title_tag.get_text(strip=True)
        for suffix in (
            " - Notion", " | Notion", " – Notion",
            " | Home", " - Home",
        ):
            t = t.removesuffix(suffix)
        # Strip everything after the last common separator if the remainder is short
        for sep in (" | ", " – ", " - "):
            if sep in t:
                candidate = t.split(sep)[0].strip()
                if candidate and not is_junk(candidate):
                    t = candidate
                    break
        if t and not is_junk(t):
            return t

    # Fallback: humanise the URL slug
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    # Strip Notion page ID (last 32 hex chars) if present
    parts = slug.split("-")
    if parts and len(parts[-1]) == 32:
        parts = parts[:-1]
    return " ".join(parts).title() or url


def extract_content(soup: BeautifulSoup) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []

    # Notion-specific containers take priority; fall back to generic semantic HTML
    container = (
        soup.select_one(".notion-page-content")
        or soup.select_one(".notion-body")
        or soup.select_one("article")
        or soup.select_one("[role='main']")
        or soup.select_one("main")
        or soup.select_one("#content")
        or soup.select_one("#main")
        or soup.find("body")
    )
    if not container:
        return items

    seen_texts: set[str] = set()

    for el in container.find_all(True):
        tag = el.name
        classes = " ".join(el.get("class", []))
        text = el.get_text(" ", strip=True)

        if is_junk(text):
            continue
        if text in seen_texts:
            continue

        kind = None

        # Headings — Notion classes first, then standard HTML tags
        if any(c in classes for c in ("notion-header-block", "notion-heading1")) or tag == "h1":
            kind = "h1"
        elif any(c in classes for c in ("notion-sub_header-block", "notion-heading2")) or tag == "h2":
            kind = "h2"
        elif any(c in classes for c in ("notion-sub_sub_header-block", "notion-heading3")) or tag in ("h3", "h4", "h5", "h6"):
            kind = "h3"

        # Lists — Notion classes first, then standard HTML
        elif any(c in classes for c in ("notion-bulleted_list-block", "notion-to_do-block")) or tag == "li":
            kind = "bullet"

        # Quotes / callouts
        elif any(c in classes for c in ("notion-quote-block", "notion-callout-block")) or tag == "blockquote":
            kind = "quote"

        # Dividers
        elif "notion-divider-block" in classes or tag == "hr":
            kind = "divider"

        # Body text — p/span/div that aren't just wrappers
        elif tag in ("p", "span", "div") and text:
            child_texts = {c.get_text(" ", strip=True) for c in el.find_all(True)}
            if text not in child_texts:
                kind = "body"

        if kind:
            items.append((kind, text))
            seen_texts.add(text)

    return items


def extract_links(soup: BeautifulSoup, page_url: str) -> list[str]:
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#"):
            continue
        absolute = normalize_url(urljoin(page_url, href))
        links.append(absolute)
    return links


# ---------------------------------------------------------------------------
# Crawl
# ---------------------------------------------------------------------------

def crawl(root_url: str, max_pages: int, delay: float) -> list[dict]:
    root_url = normalize_url(root_url)
    visited: set[str] = set()
    queue: deque[str] = deque([root_url])
    pages: list[dict] = []

    with sync_playwright() as pw:
        log.info("Launching headless Chromium...")
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        while queue and len(pages) < max_pages:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            log.info("[%d/%d] Fetching %s", len(pages) + 1, max_pages, url)
            html_content = fetch_rendered(page, url)
            if not html_content:
                continue

            soup = BeautifulSoup(html_content, "lxml")
            title = extract_title(soup, url)
            content = extract_content(soup)

            log.info("  → \"%s\" (%d content blocks)", title, len(content))
            pages.append({"url": url, "title": title, "content": content})

            new_links = [
                link for link in extract_links(soup, url)
                if link not in visited and should_follow(link, root_url)
            ]
            log.info("  → Found %d new links to follow", len(new_links))
            for link in new_links:
                log.info("    + %s", link)
                queue.append(link)

            if queue:
                log.info("  → Sleeping %.1fs before next page...", delay)
                time.sleep(delay)

        browser.close()

    log.info("Crawl complete. %d pages collected.", len(pages))
    return pages


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Crawl any public website and export to PDF.")
    p.add_argument("url", help="Root URL to crawl")
    p.add_argument("--output", default="export.pdf", help="Output PDF filename")
    p.add_argument("--max-pages", type=int, default=100, help="Maximum pages to crawl")
    p.add_argument("--delay", type=float, default=1.5, help="Delay between requests (seconds)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    pages = crawl(args.url, args.max_pages, args.delay)
    if not pages:
        log.error("No pages collected. Check the URL and try again.")
        return

    from pdf_builder import build_pdf
    build_pdf(pages, args.output)
    log.info("PDF written to %s", args.output)


if __name__ == "__main__":
    main()
