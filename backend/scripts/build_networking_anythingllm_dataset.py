#!/usr/bin/env python3
"""Build a temporary, non-redistributable page-segment dataset for AnythingLLM.

Unlike committed benchmark artifacts, this temporary adapter input contains
extracted textbook text. It therefore refuses output outside /tmp and must be
deleted after the native comparator run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from build_networking_benchmark import (
    load_query_set,
    parse_pdf_arg,
    sha256_file,
)


def segment_id(book_id: str, page: int, *, pages_per_segment: int) -> str:
    start = ((page - 1) // pages_per_segment) * pages_per_segment + 1
    end = start + pages_per_segment - 1
    return f"{book_id}-pages-{start:04d}-{end:04d}"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


async def build(args: argparse.Namespace) -> None:
    from ragz.modules.documents.parsers import LiteParseParser

    output = args.output.expanduser().resolve()
    if not output.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ValueError("copyrighted adapter input may only be written under /tmp")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    documents: list[dict[str, Any]] = []
    page_counts: dict[str, int] = {}
    for book_id, path in args.pdf:
        blocks = await LiteParseParser().parse(path.read_bytes(), path.name)
        by_page: dict[int, list[str]] = defaultdict(list)
        for block in blocks:
            if block.text.strip():
                by_page[block.page].append(block.text.strip())
        page_counts[book_id] = max(by_page, default=0)
        grouped: dict[str, list[tuple[int, str]]] = defaultdict(list)
        for page, texts in by_page.items():
            grouped[segment_id(book_id, page, pages_per_segment=args.pages_per_segment)].append(
                (page, "\n\n".join(texts))
            )
        for doc_id, pages in sorted(grouped.items()):
            ordered = sorted(pages)
            documents.append(
                {
                    "doc_id": doc_id,
                    "title": doc_id,
                    "text": "\n\n".join(text for _, text in ordered),
                    "metadata": {
                        "book_id": book_id,
                        "page_start": ordered[0][0],
                        "page_end": ordered[-1][0],
                    },
                }
            )
    query_set = load_query_set(args.queries.resolve())
    queries = [
        {
            "query_id": row["query_id"],
            "query": row["query"],
            "query_type": row["query_type"],
            "answerable": True,
            "reference_answer": "",
        }
        for row in query_set
    ]
    qrels: list[dict[str, Any]] = []
    for row in query_set:
        relevant_segments = {
            segment_id(item["book_id"], page, pages_per_segment=args.pages_per_segment)
            for item in row["relevant"]
            for page in item["pages"]
        }
        qrels.extend(
            {
                "query_id": row["query_id"],
                "doc_id": doc_id,
                "relevance": 1,
            }
            for doc_id in sorted(relevant_segments)
        )
    _write_jsonl(output / "documents.jsonl", documents)
    _write_jsonl(output / "queries.jsonl", queries)
    _write_jsonl(output / "qrels.jsonl", qrels)
    manifest = {
        "schema_version": "1.0",
        "dataset_id": "networking-pdfs-v1-anythingllm-temp",
        "temporary_copyrighted_adapter_input": True,
        "redistribution_permitted": False,
        "pages_per_segment": args.pages_per_segment,
        "document_count": len(documents),
        "query_count": len(queries),
        "qrel_count": len(qrels),
        "pdfs": [
            {
                "book_id": book_id,
                "filename": path.name,
                "sha256": sha256_file(path),
                "pages": page_counts[book_id],
            }
            for book_id, path in args.pdf
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "LICENSES.md").write_text(
        "# Local-only benchmark input\n\n"
        "This directory contains temporary extracted text from user-supplied "
        "copyrighted books. Do not redistribute or commit it. Delete it after "
        "the comparator run.\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", action="append", required=True, type=parse_pdf_arg)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pages-per-segment", type=int, default=20)
    args = parser.parse_args()
    if len(args.pdf) != 3 or len({book_id for book_id, _ in args.pdf}) != 3:
        raise ValueError("exactly three uniquely named PDFs are required")
    if not 1 <= args.pages_per_segment <= 100:
        raise ValueError("pages-per-segment must be between 1 and 100")
    asyncio.run(build(args))


if __name__ == "__main__":
    main()
