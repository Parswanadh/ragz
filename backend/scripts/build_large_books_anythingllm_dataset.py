#!/usr/bin/env python3
"""Build private one-page AnythingLLM adapter input for large-books-v1."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_networking_benchmark import parse_pdf_arg, sha256_file  # noqa: E402


def page_id(book_id: str, page: int) -> str:
    if page < 1:
        raise ValueError("page must be positive")
    return f"{book_id}-page-{page:04d}"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError("queries must be non-empty JSONL objects")
    return rows


def query_and_qrel_rows(
    source: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    queries: list[dict[str, Any]] = []
    qrels: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in source:
        query_id = str(row.get("query_id", "")).strip()
        query = str(row.get("query", "")).strip()
        answerable = row.get("answerable")
        documents = row.get("expected_doc_ids")
        pages = row.get("evidence_pages")
        if (
            not query_id
            or query_id in seen
            or not query
            or not isinstance(answerable, bool)
            or not isinstance(documents, list)
            or not isinstance(pages, list)
        ):
            raise ValueError("large-books query contract failed")
        seen.add(query_id)
        queries.append(
            {
                "query_id": query_id,
                "query": query,
                "query_type": str(row.get("question_type") or "unspecified"),
                "answerable": answerable,
                "reference_answer": "",
            }
        )
        if answerable:
            if len(documents) != 1 or any(
                not isinstance(page, int) or page < 1 for page in pages
            ):
                raise ValueError("answerable query evidence contract failed")
            qrels.extend(
                {
                    "query_id": query_id,
                    "doc_id": page_id(str(documents[0]), page),
                    "relevance": 1,
                }
                for page in sorted(set(pages))
            )
        elif documents or pages:
            raise ValueError("off-corpus query must not contain evidence")
    return queries, qrels


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True) + "\n")


async def build(args: argparse.Namespace) -> Path:
    from ragz.modules.documents.parsers import LiteParseParser

    output = Path(args.output).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not output.is_relative_to(temp_root):
        raise ValueError("private extracted page text may only be written under /tmp")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True, mode=0o700)
    documents: list[dict[str, Any]] = []
    pdf_manifest: list[dict[str, Any]] = []
    for book_id, path in args.pdf:
        blocks = await LiteParseParser().parse(path.read_bytes(), path.name)
        by_page: dict[int, list[str]] = defaultdict(list)
        for block in blocks:
            text = block.text.strip()
            if text:
                by_page[block.page].append(text)
        max_page = max((block.page for block in blocks), default=0)
        for page in range(1, max_page + 1):
            # Preserve the physical-page denominator even when the text layer is
            # empty. AnythingLLM requires non-empty raw text, so use a neutral
            # marker that carries no query-specific evidence.
            text = "\n\n".join(by_page.get(page, ())) or "[empty PDF page]"
            identifier = page_id(book_id, page)
            documents.append(
                {
                    "doc_id": identifier,
                    "title": identifier,
                    "text": text,
                    "metadata": {"book_id": book_id, "page": page},
                }
            )
        pdf_manifest.append(
            {
                "book_id": book_id,
                "filename": path.name,
                "sha256": sha256_file(path),
                "pages": max_page,
            }
        )
    source_queries = _read_jsonl(args.queries.resolve())
    queries, qrels = query_and_qrel_rows(source_queries)
    existing_ids = {str(row["doc_id"]) for row in documents}
    missing = {str(row["doc_id"]) for row in qrels} - existing_ids
    if missing:
        raise ValueError("qrels reference pages absent from parsed documents")
    _write_jsonl(output / "documents.jsonl", documents)
    _write_jsonl(output / "queries.jsonl", queries)
    _write_jsonl(output / "qrels.jsonl", qrels)
    manifest = {
        "schema_version": 1,
        "dataset_id": "large-books-v1-page-normalized",
        "source_dataset_id": "large-books-v1",
        "temporary_private_adapter_input": True,
        "redistribution_permitted": False,
        "evaluation_unit": "physical_pdf_page",
        "document_count": len(documents),
        "query_count": len(queries),
        "answerable_count": sum(bool(row["answerable"]) for row in queries),
        "off_corpus_count": sum(not bool(row["answerable"]) for row in queries),
        "qrel_count": len(qrels),
        "source_queries_sha256": hashlib.sha256(
            args.queries.resolve().read_bytes()
        ).hexdigest(),
        "pdfs": pdf_manifest,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "PRIVATE.md").write_text(
        "# Private adapter input\n\nContains extracted page text. Do not commit.\n",
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", action="append", required=True, type=parse_pdf_arg)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if len(args.pdf) != 3 or len({book_id for book_id, _path in args.pdf}) != 3:
        raise ValueError("exactly three uniquely named PDFs are required")
    output = asyncio.run(build(args))
    print(json.dumps({"status": "completed", "output": str(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
