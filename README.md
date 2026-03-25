# notion-pdf-export

Crawls any public website and produces a single consolidated PDF containing the readable content of every reachable page. Has enhanced support for Notion-hosted sites (notion.site / notion.so).

## Setup

```bash
cd notion-pdf-export
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
python scraper.py "https://example.notion.site/Candidate-Book-abc123" --output candidate_book.pdf
python scraper.py "https://docs.example.com" --output docs.pdf
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--output` | `export.pdf` | Output PDF filename |
| `--max-pages` | `100` | Maximum number of pages to crawl |
| `--delay` | `1.5` | Seconds to wait between requests |

### Examples

```bash
# Notion site
python scraper.py "https://mycompany.notion.site/Handbook-abc123"

# Any public site
python scraper.py "https://docs.example.com" --output docs.pdf

# Custom output name and page limit
python scraper.py "https://mycompany.notion.site/Handbook-abc123" \
  --output handbook.pdf \
  --max-pages 50

# Faster crawl (be polite on public sites)
python scraper.py "https://mycompany.notion.site/Handbook-abc123" --delay 0.5
```

## How it works

1. Fetches the root URL and extracts text content and internal links.
2. Follows links within the same host in BFS order, skipping login/signup/cookie/external URLs.
3. Extracts titles, headings, body text, bullets, and blockquotes from each page.
4. Assembles everything into a single PDF, one section per page, in crawl order.

## Limitations

- **Public pages only.** Private or login-gated content will not be accessible.
- **Text-oriented output.** The PDF is clean and readable but does not reproduce the original visual layout, images, tables, or embedded media.
- **Best-effort extraction.** Sites with non-standard HTML structure or heavy client-side rendering may produce sparse output. Notion pages are the best-supported case.

## Tweaking the code

| Goal | Where to change |
|------|----------------|
| Stricter link filtering | `should_follow()` in `scraper.py` — add more entries to `SKIP_PATH_FRAGMENTS` or add domain-specific rules |
| Add site-specific junk removal | `_NOTION_JUNK` / `_GENERIC_JUNK` sets and `is_junk()` in `scraper.py` — add text patterns to skip; `extract_content()` for structural changes |
| Different PDF layout | `pdf_builder.py` — adjust `ParagraphStyle` definitions at the top, or change the flowable pipeline in `_page_flowables()` |
