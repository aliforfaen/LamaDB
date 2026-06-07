#!/usr/bin/env python3
"""Migrate filesystem wiki into LamaDB documents table.

One-time import of .md files from WIKI_PATH into the documents table.
Idempotent: skips files whose path already exists in the DB.

Usage:
    docker exec lamadb_api python3 scripts/migrate_wiki.py

Environment:
    WIKI_PATH   Path to wiki root (default: /wiki)
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

WIKI_ROOT = Path(os.environ.get("WIKI_PATH", "/wiki"))
SKIP_DIRS = {"_archive", "raw", ".git", ".obsidian", "_meta", "assets"}
SKIP_FILES = {"SCHEMA.md", "index.md", "log.md"}


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from markdown. Returns (frontmatter_dict, body).

    Simple key:value parser — no PyYAML dependency.
    Handles quoted values and basic list formats.
    """
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm = {}
            for line in parts[1].strip().split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    key, _, val = line.partition(":")
                    val = val.strip().strip('"').strip("'")
                    fm[key.strip()] = val
            return fm, parts[2].strip()
    return {}, text


def parse_tags(fm_tags: str | list | None) -> list[str]:
    """Parse tags from frontmatter into a list of strings."""
    if not fm_tags:
        return []
    if isinstance(fm_tags, list):
        return [str(t).strip() for t in fm_tags if t]
    if isinstance(fm_tags, str):
        # Handle "[tag1, tag2]" or "tag1, tag2" formats
        cleaned = fm_tags.strip("[]'\"")
        return [t.strip() for t in cleaned.split(",") if t.strip()]
    return []


def main() -> int:
    """Run the migration. Returns the number of pages imported."""
    from app.db import get_pool
    import asyncio

    async def migrate_one_page(pool, md_file: Path, rel_path: str) -> bool:
        """Import a single .md file. Returns True if imported, False if skipped."""
        async with pool.acquire() as conn:
            # Idempotency check
            existing = await conn.fetchval(
                """SELECT id FROM documents
                   WHERE source_type = 'wiki_page'
                     AND metadata->>'path' = $1""",
                rel_path,
            )
            if existing:
                return False

            # Read and parse
            try:
                text = md_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return False

            fm, body = parse_frontmatter(text)

            title = fm.get("title", "") or md_file.stem.replace("-", " ").replace("_", " ").title()
            tags = parse_tags(fm.get("tags"))

            # Build metadata
            metadata = {
                "path": rel_path,
                "type": "wiki_page",
                "frontmatter": fm,
                "migrated_from": "filesystem",
            }

            await conn.execute(
                """INSERT INTO documents (id, source_type, title, content, metadata, tags)
                   VALUES ($1, 'wiki_page', $2, $3, $4, $5)""",
                str(uuid.uuid4()),
                title,
                body,
                json.dumps(metadata),
                tags,
            )
            return True

    async def run():
        pool = get_pool()
        count = 0
        skipped = 0

        if not WIKI_ROOT.exists():
            print(f"WIKI_ROOT does not exist: {WIKI_ROOT}")
            return 0

        md_files = sorted(WIKI_ROOT.rglob("*.md"))
        print(f"Found {len(md_files)} .md files in {WIKI_ROOT}")

        for md_file in md_files:
            rel_path = str(md_file.relative_to(WIKI_ROOT))

            # Skip excluded dirs
            parts = Path(rel_path).parts
            if parts and parts[0] in SKIP_DIRS:
                skipped += 1
                continue
            if md_file.name in SKIP_FILES:
                skipped += 1
                continue

            imported = await migrate_one_page(pool, md_file, rel_path)
            if imported:
                count += 1
            else:
                skipped += 1

            if count > 0 and count % 20 == 0:
                print(f"  Migrated {count} pages...")

        print(f"\nDone. {count} pages imported, {skipped} already existed or skipped.")
        return count

    return asyncio.run(run())


if __name__ == "__main__":
    main()
