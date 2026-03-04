"""
notion-pdf-export: crawl a public Notion site and produce a single PDF.

Usage:
    python scraper.py <root_url> [--output FILE] [--max-pages N] [--delay SECS]
"""

import argparse
import html
import logging
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

# Link paths that are never worth following
SKIP_PATH_FRAGMENTS = (
    "/login", "/signup", "/sign-up", "/sign-in",
    "/register", "/logout", "/pricing", "/blog",
    "/cookie", "/report", "/abuse",
)

SKIP_QUERY_PARAMS = ("redirectTo", "utm_")

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)


def normalize_url(url: str) -> str:
    """Remove fragment, normalize trailing slash, lowercase scheme+host."""
    p = urlparse(url)
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, p.params, p.query, ""))


def same_host(url: str, root: str) -> bool:
    return urlparse(url).netloc.lower() == urlparse(root).netloc.lower()


def should_follow(url: str, root: str) -> bool:
    """Return True if this link is worth crawling."""
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return False
    if not same_host(url, root):
        return False
    path_lower = p.path.lower()
    if any(skip in path_lower for skip in SKIP_PATH_FRAGMENTS):
        return False
    if any(param in p.query for param in SKIP_QUERY_PARAMS):
        return False
    return True


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    return s


def fetch(session: requests.Session, url: str) -> BeautifulSoup | None:
    try:
        resp = session.get(url, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except requests.RequestException as e:
        log.warning("Failed to fetch %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Notion content extraction
# ---------------------------------------------------------------------------

# UI noise to strip (case-insensitive exact or prefix match)
JUNK_STRINGS = {
    "skip to content", "get notion free", "sign up", "sign in",
    "log in", "login", "try notion free", "duplicate page",
    "cookie settings", "report page", "powered by notion",
    "notion – the all-in-one workspace", "notion",
}


def is_junk(text: str) -> bool:
    t = text.strip().lower()
    return not t or t in JUNK_STRINGS or len(t) < 2


def extract_title(soup: BeautifulSoup, url: str) -> str:
    """Extract the page title with several fallback strategies."""
    # 1. Notion page title block
    for sel in (".notion-title", ".notion-page-block .notranslate",
                "[class*='notionTitle']", "h1.notion-header__title"):
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    # 2. <title> tag, strip common suffixes
    title_tag = soup.find("title")
    if title_tag:
        t = title_tag.get_text(strip=True)
        for suffix in (" - Notion", " | Notion", " – Notion"):
            t = t.removesuffix(suffix)
        if t:
            return t
    # 3. Derive from URL slug
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").title() or url


def extract_content(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """
    Return a list of (kind, text) tuples where kind is one of:
    h1, h2, h3, body, bullet, quote, divider.

    Tries Notion-specific containers first, falls back to generic HTML.
    """
    items: list[tuple[str, str]] = []

    # Try Notion's content container
    container = (
        soup.select_one(".notion-page-content")
        or soup.select_one(".notion-body")
        or soup.select_one("article")
        or soup.select_one("main")
        or soup.find("body")
    )
    if not container:
        return items

    for el in container.find_all(True):
        tag = el.name
        classes = " ".join(el.get("class", []))
        text = el.get_text(" ", strip=True)

        if is_junk(text):
            continue

        # Headings
        if tag == "h1" or "notion-header-block" in classes or "notion-heading1" in classes:
            items.append(("h1", text))
        elif tag == "h2" or "notion-sub_header-block" in classes or "notion-heading2" in classes:
            items.append(("h2", text))
        elif tag == "h3" or "notion-sub_sub_header-block" in classes or "notion-heading3" in classes:
            items.append(("h3", text))
        # Bullets
        elif tag in ("li",) or "notion-bulleted_list-block" in classes or "notion-to_do-block" in classes:
            items.append(("bullet", text))
        # Blockquote / callout
        elif tag == "blockquote" or "notion-quote-block" in classes or "notion-callout-block" in classes:
            items.append(("quote", text))
        # Divider
        elif tag == "hr" or "notion-divider-block" in classes:
            items.append(("divider", ""))
        # Paragraphs and generic text blocks
        elif tag in ("p", "span", "div") and text:
            # Avoid duplicating text already captured by a child element
            child_texts = {c.get_text(" ", strip=True) for c in el.find_all(True)}
            if text not in child_texts:
                items.append(("body", text))

    # Deduplicate consecutive identical entries
    deduped: list[tuple[str, str]] = []
    for item in items:
        if not deduped or deduped[-1] != item:
            deduped.append(item)

    return deduped


def extract_links(soup: BeautifulSoup, page_url: str) -> list[str]:
    """Return normalized absolute URLs found on this page."""
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
    """BFS crawl starting from root_url. Returns list of page records."""
    root_url = normalize_url(root_url)
    session = make_session()
    visited: set[str] = set()
    queue: deque[str] = deque([root_url])
    pages: list[dict] = []

    while queue and len(pages) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        log.info("[%d/%d] Fetching %s", len(pages) + 1, max_pages, url)
        soup = fetch(session, url)
        if soup is None:
            continue

        title = extract_title(soup, url)
        content = extract_content(soup)
        pages.append({"url": url, "title": title, "content": content})

        # Enqueue new links
        for link in extract_links(soup, url):
            if link not in visited and should_follow(link, root_url):
                queue.append(link)

        if queue:
            time.sleep(delay)

    log.info("Crawl complete. %d pages collected.", len(pages))
    return pages


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export a public Notion site to PDF.")
    p.add_argument("url", help="Root URL of the public Notion site")
    p.add_argument("--output", default="notion_export.pdf", help="Output PDF filename")
    p.add_argument("--max-pages", type=int, default=100, help="Maximum pages to crawl")
    p.add_argument("--delay", type=float, default=1.0, help="Delay between requests (seconds)")
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
