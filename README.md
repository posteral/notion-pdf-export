# notion-pdf-export

Crawls a public Notion site (notion.site or notion.so public workspace) and produces a single consolidated PDF containing the readable content of every reachable page.

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
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--output` | `notion_export.pdf` | Output PDF filename |
| `--max-pages` | `100` | Maximum number of pages to crawl |
| `--delay` | `1.0` | Seconds to wait between requests |

### Examples

```bash
# Basic export
python scraper.py "https://mycompany.notion.site/Handbook-abc123"

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
- **JavaScript-rendered content may be missing.** Notion sometimes lazy-loads content via JS. This scraper uses plain HTTP requests and will miss content that requires a real browser to render. Most classic Notion public pages work fine; newer Next.js-rendered pages may return less content.
- **Text-oriented output.** The PDF is clean and readable but does not reproduce Notion's visual layout, images, tables, or embedded media.
- **Best-effort extraction.** Notion's HTML structure varies across page types; some pages may produce sparse output.

## Tweaking the code

| Goal | Where to change |
|------|----------------|
| Stricter link filtering | `should_follow()` in `scraper.py` — add more entries to `SKIP_PATH_FRAGMENTS` or add domain-specific rules |
| Better Notion UI junk removal | `JUNK_STRINGS` set and `is_junk()` in `scraper.py`, and the `extract_content()` function — add more class names or text patterns to skip |
| Different PDF layout | `pdf_builder.py` — adjust `ParagraphStyle` definitions at the top, or change the flowable pipeline in `_page_flowables()` |
