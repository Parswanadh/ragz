#!/usr/bin/env python3
"""Build copyright-safe metadata for the networking PDF benchmark.

The output contains hashes, page counts, query-set identity and configuration;
it never copies or extracts textbook content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pypdfium2  # type: ignore[import-untyped]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_pdf_arg(value: str) -> tuple[str, Path]:
    book_id, separator, raw_path = value.partition("=")
    path = Path(raw_path).expanduser().resolve()
    if not separator or not book_id or not raw_path:
        raise argparse.ArgumentTypeError("PDF must be BOOK_ID=/absolute/path.pdf")
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"PDF does not exist: {path}")
    return book_id, path


def load_query_set(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("query set must be a non-empty JSON array")
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("every query record must be an object")
        query_id = raw.get("query_id")
        query = raw.get("query")
        alternatives = raw.get("alternatives")
        relevant = raw.get("relevant")
        if not isinstance(query_id, str) or not query_id or query_id in seen:
            raise ValueError("query_id must be unique and non-empty")
        if not isinstance(query, str) or not query.strip() or len(query) > 2_000:
            raise ValueError(f"{query_id}: query must be 1-2000 characters")
        if (
            not isinstance(alternatives, list)
            or len(alternatives) != 2
            or any(not isinstance(item, str) or not item.strip() for item in alternatives)
        ):
            raise ValueError(f"{query_id}: exactly two alternatives are required")
        if not isinstance(relevant, list) or not relevant:
            raise ValueError(f"{query_id}: page-level relevance labels are required")
        normalized_relevant: list[dict[str, Any]] = []
        for item in relevant:
            if not isinstance(item, dict) or not isinstance(item.get("book_id"), str):
                raise ValueError(f"{query_id}: invalid relevant book")
            pages = item.get("pages")
            if (
                not isinstance(pages, list)
                or not pages
                or any(not isinstance(page, int) or page < 1 for page in pages)
            ):
                raise ValueError(f"{query_id}: relevant pages must be positive integers")
            normalized_relevant.append(
                {"book_id": item["book_id"], "pages": sorted(set(pages))}
            )
        seen.add(query_id)
        validated.append(
            {
                "query_id": query_id,
                "query": query.strip(),
                "alternatives": [str(item).strip() for item in alternatives],
                "relevant": normalized_relevant,
                "query_type": str(raw.get("query_type") or "unspecified"),
            }
        )
    return validated


def pdf_metadata(book_id: str, path: Path) -> dict[str, Any]:
    document = pypdfium2.PdfDocument(path)
    try:
        pages = len(document)
    finally:
        document.close()
    return {
        "book_id": book_id,
        "filename": path.name,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "pages": pages,
    }


def build_manifest(
    pdfs: list[tuple[str, Path]], query_path: Path
) -> dict[str, Any]:
    queries = load_query_set(query_path)
    return {
        "schema_version": "1.0",
        "dataset_id": "networking-pdfs-v1",
        "copyright_safe": True,
        "document_text_persisted": False,
        "pdfs": [pdf_metadata(book_id, path) for book_id, path in pdfs],
        "query_set": {
            "filename": query_path.name,
            "sha256": sha256_file(query_path),
            "count": len(queries),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", action="append", required=True, type=parse_pdf_arg)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    if len(args.pdf) != 3 or len({book_id for book_id, _ in args.pdf}) != 3:
        raise ValueError("exactly three uniquely named PDFs are required")
    manifest = build_manifest(args.pdf, args.queries.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
