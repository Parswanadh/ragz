#!/usr/bin/env python3
"""Prepare private four-perspective MQR alternatives and a safe public attestation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from ragz.modules.retrieval.query_expansion import ExpandedQueries, LiteLLMQueryExpander

EXPECTED_TOTAL_QUERIES = 5
LUNA_INPUT_USD_PER_MILLION = Decimal("0.20")
LUNA_OUTPUT_USD_PER_MILLION = Decimal("1.20")
_FALLBACK_PREFIXES = (
    "Exact entities, numbers, scope, negation, and constraints",
    "Synonyms, acronyms, and formal documentation terminology",
    "Mechanisms, prerequisites, component relationships, and failure modes",
    "Definitions, headings, standards, configuration, and troubleshooting evidence",
)


class ExpansionPreparationError(RuntimeError):
    """Safe failure that never contains a query, alternative, or provider body."""


class ExpanderLike(Protocol):
    async def expand(self, query: str, *, model: str) -> ExpandedQueries: ...


@dataclass(frozen=True)
class SourceQuery:
    query_id: str
    query: str
    answerable: bool
    relevant: tuple[dict[str, object], ...]
    query_type: str
    expected_answer: str | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExpansionPreparationError(
                f"invalid JSONL at {path.name}:{line_number}"
            ) from exc
        if not isinstance(row, Mapping):
            raise ExpansionPreparationError(
                f"non-object JSONL row at {path.name}:{line_number}"
            )
        rows.append(row)
    if not rows:
        raise ExpansionPreparationError("query input is empty")
    return rows


def load_source_queries(path: Path) -> list[SourceQuery]:
    result: list[SourceQuery] = []
    seen: set[str] = set()
    for raw in _read_jsonl(path):
        query_id = raw.get("query_id")
        query = raw.get("query")
        answerable = raw.get("answerable")
        doc_ids = raw.get("expected_doc_ids", [])
        pages = raw.get("evidence_pages", [])
        if not isinstance(query_id, str) or not query_id or query_id in seen:
            raise ExpansionPreparationError("query IDs must be unique and non-empty")
        if not isinstance(query, str) or not query.strip() or len(query) > 2_000:
            raise ExpansionPreparationError(f"{query_id}: query must be 1-2000 characters")
        if not isinstance(answerable, bool):
            raise ExpansionPreparationError(f"{query_id}: answerable must be boolean")
        if not isinstance(doc_ids, list) or any(not isinstance(item, str) for item in doc_ids):
            raise ExpansionPreparationError(f"{query_id}: invalid expected_doc_ids")
        if not isinstance(pages, list) or any(
            not isinstance(page, int) or isinstance(page, bool) or page < 1 for page in pages
        ):
            raise ExpansionPreparationError(f"{query_id}: invalid evidence_pages")
        if answerable and (not doc_ids or not pages):
            raise ExpansionPreparationError(f"{query_id}: answerable query lacks qrels")
        if not answerable and (doc_ids or pages):
            raise ExpansionPreparationError(f"{query_id}: off-corpus query has qrels")
        relevant = tuple(
            {"book_id": doc_id, "pages": sorted(set(pages))}
            for doc_id in doc_ids
        )
        expected_answer = raw.get("expected_answer")
        result.append(
            SourceQuery(
                query_id=query_id,
                query=query.strip(),
                answerable=answerable,
                relevant=relevant,
                query_type=str(raw.get("question_type") or "unspecified"),
                expected_answer=(
                    expected_answer.strip()
                    if isinstance(expected_answer, str) and expected_answer.strip()
                    else None
                ),
            )
        )
        seen.add(query_id)
    return result


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def _cost(prompt_tokens: int, completion_tokens: int) -> Decimal:
    return (
        Decimal(prompt_tokens) * LUNA_INPUT_USD_PER_MILLION
        + Decimal(completion_tokens) * LUNA_OUTPUT_USD_PER_MILLION
    ) / Decimal(1_000_000)


def _token_total(rows: Sequence[Mapping[str, object]], field: str) -> int:
    total = 0
    for row in rows:
        value = row.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ExpansionPreparationError(f"public {field} is malformed")
        total += value
    return total


def _complete_missing_perspectives(
    original: str, expanded: ExpandedQueries
) -> tuple[ExpandedQueries, int]:
    queries = list(expanded.queries)
    seen = {" ".join(value.split()).casefold() for value in queries}
    added = 0
    for prefix in _FALLBACK_PREFIXES:
        if len(queries) == EXPECTED_TOTAL_QUERIES:
            break
        candidate = f"{prefix}: {original}"
        key = " ".join(candidate.split()).casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(candidate)
        added += 1
    return (
        ExpandedQueries(
            tuple(queries[:EXPECTED_TOTAL_QUERIES]),
            prompt_tokens=expanded.prompt_tokens,
            completion_tokens=expanded.completion_tokens,
        ),
        added,
    )


async def prepare_expansions(
    queries: Sequence[SourceQuery],
    *,
    expander: ExpanderLike,
    model: str,
    retries: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    private_rows: list[dict[str, object]] = []
    public_rows: list[dict[str, object]] = []
    for source in queries:
        error_code: str | None = None
        expanded: ExpandedQueries | None = None
        latency_ms = 0.0
        attempts = 0
        fallback_count = 0
        for attempt in range(retries + 1):
            attempts = attempt + 1
            started = time.perf_counter()
            try:
                candidate = await expander.expand(source.query, model=model)
                latency_ms += (time.perf_counter() - started) * 1000
                if len(candidate.queries) != EXPECTED_TOTAL_QUERIES:
                    if attempt < retries:
                        raise ExpansionPreparationError(
                            "provider returned fewer than five queries"
                        )
                    candidate, fallback_count = _complete_missing_perspectives(
                        source.query, candidate
                    )
                    if len(candidate.queries) != EXPECTED_TOTAL_QUERIES:
                        raise ExpansionPreparationError(
                            "perspective completion returned fewer than five queries"
                        )
                expanded = candidate
                error_code = None
                break
            except Exception as exc:  # noqa: BLE001 - typed public code only
                latency_ms += (time.perf_counter() - started) * 1000
                error_code = type(exc).__name__
                if attempt < retries:
                    await asyncio.sleep(min(2**attempt, 4))
        if expanded is None:
            public_rows.append(
                {
                    "query_id": source.query_id,
                    "expansion_count": 0,
                    "attempts": attempts,
                    "latency_ms": round(latency_ms, 4),
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "fallback_count": 0,
                    "error_code": error_code or "ExpansionPreparationError",
                }
            )
            continue
        private_rows.append(
            {
                "query_id": source.query_id,
                "query": source.query,
                "alternatives": list(expanded.queries[1:]),
                "relevant": list(source.relevant),
                "answerable": source.answerable,
                "query_type": source.query_type,
                "expected_answer": source.expected_answer,
            }
        )
        public_rows.append(
            {
                "query_id": source.query_id,
                "expansion_count": len(expanded.queries),
                "attempts": attempts,
                "latency_ms": round(latency_ms, 4),
                "prompt_tokens": expanded.prompt_tokens,
                "completion_tokens": expanded.completion_tokens,
                "fallback_count": fallback_count,
                "error_code": None,
            }
        )
    return private_rows, public_rows


def _write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", required=True, type=Path)
    parser.add_argument("--private-output", required=True, type=Path)
    parser.add_argument("--public-output", required=True, type=Path)
    parser.add_argument("--env", required=True, type=Path)
    parser.add_argument("--litellm-url", required=True)
    parser.add_argument("--proxy-fingerprint", required=True)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--budget-cap-usd", type=Decimal, default=Decimal("1.00"))
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.retries < 0 or args.retries > 5:
        raise ExpansionPreparationError("retries must be between 0 and 5")
    if (
        len(args.proxy_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in args.proxy_fingerprint)
    ):
        raise ExpansionPreparationError("proxy fingerprint must be a lowercase SHA-256")
    if args.private_output.exists() or args.public_output.exists():
        raise FileExistsError("refusing to overwrite expansion evidence")
    env = load_env_file(args.env)
    master_key = env.get("RAGZ_LITELLM_MASTER_KEY") or os.environ.get(
        "RAGZ_LITELLM_MASTER_KEY", ""
    )
    if not master_key:
        raise ExpansionPreparationError("RAGZ_LITELLM_MASTER_KEY is unavailable")
    queries = load_source_queries(args.queries.resolve())
    estimated_cost = _cost(len(queries) * 500, len(queries) * 300)
    if estimated_cost > args.budget_cap_usd:
        raise ExpansionPreparationError("expansion estimate exceeds the budget cap")
    expander = LiteLLMQueryExpander(
        base_url=args.litellm_url,
        master_key=master_key,
        max_queries=EXPECTED_TOTAL_QUERIES,
    )
    private_rows, public_rows = asyncio.run(
        prepare_expansions(
            queries,
            expander=expander,
            model=args.model,
            retries=args.retries,
        )
    )
    errors = sum(row["error_code"] is not None for row in public_rows)
    if len(private_rows) != len(queries) or errors:
        args.public_output.mkdir(parents=True)
        _write_new(args.public_output / "per_query.json", public_rows)
        _write_new(
            args.public_output / "failure.json",
            {
                "schema_version": 1,
                "status": "failed_incomplete",
                "created_at_utc": datetime.now(UTC).isoformat(),
                "query_count": len(queries),
                "completed_expansions": len(private_rows),
                "errors": errors,
                "error_codes": sorted(
                    {
                        str(row["error_code"])
                        for row in public_rows
                        if row["error_code"] is not None
                    }
                ),
                "private_output_written": False,
                "credentials_persisted": False,
                "query_or_alternative_text_persisted": False,
            },
        )
        raise ExpansionPreparationError("expansion denominator is incomplete")
    _write_new(args.private_output, private_rows)
    args.private_output.chmod(0o600)
    prompt_tokens = _token_total(public_rows, "prompt_tokens")
    completion_tokens = _token_total(public_rows, "completion_tokens")
    manifest = {
        "schema_version": 1,
        "status": "completed",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "model": args.model,
        "llm_top_p": "provider-default-1-not-sent",
        "temperature": "provider-default-not-sent",
        "reasoning_effort": "low",
        "query_count": len(queries),
        "total_query_lanes": EXPECTED_TOTAL_QUERIES,
        "perspectives": [
            "exact_constraints",
            "terminology",
            "mechanism_relationships",
            "evidence_source_phrasing",
        ],
        "provider_calls": len(public_rows),
        "deterministic_fallback_lanes": _token_total(
            public_rows, "fallback_count"
        ),
        "errors": errors,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "usage_derived_cost_usd": str(_cost(prompt_tokens, completion_tokens)),
        },
        "budget": {
            "preflight_estimate_usd": str(estimated_cost),
            "hard_cap_usd": str(args.budget_cap_usd),
        },
        "proxy_fingerprint_sha256": args.proxy_fingerprint,
        "input_queries_sha256": sha256_file(args.queries.resolve()),
        "private_output_sha256": sha256_file(args.private_output),
        "expander_code_sha256": sha256_file(
            Path(__file__).resolve().parents[1]
            / "src/ragz/modules/retrieval/query_expansion.py"
        ),
        "privacy": {
            "query_text_persisted_publicly": False,
            "alternatives_persisted_publicly": False,
            "provider_bodies_persisted": False,
            "credentials_persisted": False,
        },
    }
    args.public_output.mkdir(parents=True)
    _write_new(args.public_output / "per_query.json", public_rows)
    _write_new(args.public_output / "manifest.json", manifest)
    print(json.dumps({"status": "completed", "output": str(args.public_output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
