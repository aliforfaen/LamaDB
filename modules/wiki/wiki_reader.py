"""Wiki filesystem reader helpers."""
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator

from app.config import settings


WIKI_PATH = settings.wiki_path

# Sections (top-level directories) that make up the wiki structure
KNOWN_SECTIONS = ["entities", "concepts", "projects", "queries", "raw"]


def list_pages(wiki_path: str | None = None) -> list[dict]:
    """
    Scan the wiki directory recursively for .md files.

    Returns a list of dicts with keys: path, title, section, size.
    Gracefully returns [] if the wiki directory does not exist.
    """
    wp = Path(wiki_path or WIKI_PATH)
    if not wp.exists() or not wp.is_dir():
        return []

    pages = []
    for md_file in sorted(wp.rglob("*.md")):
        rel = md_file.relative_to(wp)
        # Skip the root index.md (it's the wiki index)
        if rel.name == "index.md" and len(rel.parts) == 1:
            continue

        section = rel.parts[0] if len(rel.parts) > 1 else ""
        title = _title_from_file(md_file) or rel.stem.replace("-", " ").replace("_", " ").title()

        pages.append({
            "path": str(rel),
            "title": title,
            "section": section,
            "size": md_file.stat().st_size,
        })

    return pages


def read_page(wiki_path: str | None, page_path: str) -> dict | None:
    """
    Read a single wiki page file.

    page_path is relative to wiki root (e.g. "entities/homelab-services.md").

    Returns dict with keys: path, title, content, last_modified, or None if not found.
    """
    wp = Path(wiki_path or WIKI_PATH)
    file_path = wp / page_path

    if not file_path.exists() or not file_path.is_file():
        return None

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    title = _title_from_file(file_path) or Path(page_path).stem.replace("-", " ").replace("_", " ").title()
    last_modified = datetime.fromtimestamp(file_path.stat().st_mtime)

    return {
        "path": page_path,
        "title": title,
        "content": content,
        "last_modified": last_modified,
    }


def parse_index(wiki_path: str | None = None) -> dict:
    """
    Parse wiki/index.md to extract structured metadata.

    Returns a dict: {sections: {name: [items]}, pages: [all page paths]}
    """
    wp = Path(wiki_path or WIKI_PATH)
    index_file = wp / "index.md"
    if not index_file.exists():
        return {"sections": {}, "pages": []}

    content = index_file.read_text(encoding="utf-8")
    sections = {}
    current_section = None

    for line in content.split("\n"):
        line = line.rstrip()
        # Detect section headers: ## Section Name
        m = re.match(r"^##\s+(.+)", line)
        if m:
            current_section = m.group(1).strip().lower()
            sections[current_section] = []
        elif current_section is not None and line.startswith("- "):
            link_match = re.match(r"^\-\s+\[([^\]]+)\]\(([^\)]+)\)", line)
            if link_match:
                sections[current_section].append({
                    "label": link_match.group(1),
                    "path": link_match.group(2).lstrip("/"),
                })

    all_pages = [p["path"] for p in list_pages(wiki_path or WIKI_PATH)]
    return {"sections": sections, "pages": all_pages}


def search_wiki(wiki_path: str | None, query: str, limit: int = 20) -> list[dict]:
    """
    Search wiki content by scanning .md files for the query string (case-insensitive).

    Returns a list of dicts: {path, title, snippet}.
    """
    wp = Path(wiki_path or WIKI_PATH)
    if not wp.exists() or not wp.is_dir():
        return []

    query_lower = query.lower()
    results = []
    query_re = re.compile(re.escape(query), re.IGNORECASE)

    for md_file in sorted(wp.rglob("*.md")):
        rel = md_file.relative_to(wp)
        if rel.name == "index.md" and len(rel.parts) == 1:
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Find line with match
        lines = content.split("\n")
        for i, line in enumerate(lines):
            if query_lower in line.lower():
                # Extract a snippet: the matching line ± 1 line of context
                start = max(0, i - 1)
                end = min(len(lines), i + 2)
                snippet = " ... ".join(lines[start:end]).strip()
                # Truncate long snippets
                if len(snippet) > 200:
                    snippet = snippet[:200] + "..."

                title = _title_from_file(md_file) or rel.stem.replace("-", " ").replace("_", " ").title()

                results.append({
                    "path": str(rel),
                    "title": title,
                    "snippet": snippet,
                })
                break  # one result per file

        if len(results) >= limit:
            break

    return results


def _title_from_file(file_path: Path) -> str | None:
    """Extract title from the first H1 heading in a markdown file, or None."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    for line in content.split("\n")[:10]:
        m = re.match(r"^#\s+(.+)", line.strip())
        if m:
            return m.group(1).strip()
    return None
