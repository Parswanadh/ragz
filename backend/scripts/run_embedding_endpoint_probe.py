#!/usr/bin/env python3
"""Privacy-safe direct-OpenAI versus LiteLLM embedding latency probe."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

MODEL = "text-embedding-3-small"
DIMENSION = 1536
DIRECT_ENDPOINT = "https://api.openai.com/v1/embeddings"
PROXY_ENDPOINT = "http://127.0.0.1:54000/v1/embeddings"
_SYNTHETIC_INPUTS = (
    "synthetic networking latency probe",
    "synthetic protocol retrieval alternative",
    "synthetic packet routing comparison",
)
_CONDITIONS = ("direct_1", "proxy_1", "direct_3", "proxy_3")


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def validate_proxy_fingerprint(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("proxy fingerprint must be a lowercase SHA-256")
    return value


def summarize(records: list[dict[str, Any]], *, repetitions: int) -> dict[str, Any]:
    if len(records) != len(_CONDITIONS) * repetitions:
        raise ValueError("endpoint probe has an incomplete observation denominator")
    if any(record.get("error") is not None for record in records):
        raise ValueError("endpoint probe contains a failed scored observation")
    if [int(record["sequence"]) for record in records] != list(range(1, len(records) + 1)):
        raise ValueError("endpoint probe sequence is not contiguous")
    output: dict[str, Any] = {}
    for condition in _CONDITIONS:
        rows = [record for record in records if record["condition"] == condition]
        if len(rows) != repetitions or {int(row["repetition"]) for row in rows} != set(
            range(1, repetitions + 1)
        ):
            raise ValueError(f"endpoint probe condition {condition} is incomplete")
        if any(int(row["dimension"]) != DIMENSION for row in rows):
            raise ValueError("endpoint probe returned an unexpected vector dimension")
        values = [float(row["elapsed_ms"]) for row in rows]
        output[condition] = {
            "path": rows[0]["path"],
            "input_count": int(rows[0]["input_count"]),
            "observations": len(rows),
            "mean_ms": statistics.mean(values),
            "p50_ms": percentile(values, 0.50),
            "p95_ms": percentile(values, 0.95),
            "tokens_per_request": int(rows[0]["total_tokens"]),
        }
    return {
        "conditions": output,
        "proxy_minus_direct_mean_ms": {
            "one_input": output["proxy_1"]["mean_ms"] - output["direct_1"]["mean_ms"],
            "three_inputs": output["proxy_3"]["mean_ms"] - output["direct_3"]["mean_ms"],
        },
    }


async def _request(
    *, endpoint: str, key: str, input_count: int
) -> tuple[float, int, int, int]:
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        response = await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": MODEL, "input": list(_SYNTHETIC_INPUTS[:input_count])},
        )
    elapsed_ms = (time.perf_counter() - started) * 1000
    if response.status_code != 200:
        raise RuntimeError(f"embedding endpoint returned HTTP {response.status_code}")
    body = response.json()
    data = body.get("data") or []
    if not data:
        raise RuntimeError("embedding endpoint returned no vectors")
    dimension = len(data[0].get("embedding") or [])
    tokens = int((body.get("usage") or {}).get("total_tokens") or 0)
    return elapsed_ms, dimension, tokens, response.status_code


def _condition(name: str, direct_key: str, proxy_key: str) -> tuple[str, str, int, str]:
    path, raw_count = name.rsplit("_", 1)
    if path == "direct":
        return DIRECT_ENDPOINT, direct_key, int(raw_count), "direct OpenAI"
    return PROXY_ENDPOINT, proxy_key, int(raw_count), "LiteLLM to OpenAI"


async def run(args: argparse.Namespace) -> Path:
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    fingerprint = validate_proxy_fingerprint(args.proxy_fingerprint)
    direct_key = os.environ.get("OPENAI_EMBEDDING_API_KEY") or os.environ.get(
        "OPENAI_API_KEY"
    )
    proxy_key = os.environ.get("RAGZ_LITELLM_MASTER_KEY") or os.environ.get(
        "LITELLM_MASTER_KEY"
    )
    if not direct_key or not proxy_key:
        raise RuntimeError("endpoint probe credentials are unavailable")
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git executable not found")
    commit = subprocess.check_output([git, "rev-parse", "HEAD"], text=True).strip()  # noqa: S603
    status = subprocess.check_output([git, "status", "--porcelain"], text=True)  # noqa: S603
    if status:
        raise RuntimeError("endpoint probe requires a clean worktree")
    output.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "runner_version": "1.0",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "running",
        "git_commit": commit,
        "git_dirty": False,
        "model": MODEL,
        "dimension": DIMENSION,
        "warmups_per_condition": args.warmups,
        "scored_repetitions_per_condition": args.repetitions,
        "condition_order": "counterbalanced forward/reverse",
        "http_client_lifecycle": "new client per request",
        "embedding_proxy_fingerprint_sha256": fingerprint,
        "synthetic_input": True,
        "input_text_persisted": False,
        "credentials_persisted": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name in _CONDITIONS:
        endpoint, key, count, _ = _condition(name, direct_key, proxy_key)
        for _ in range(args.warmups):
            await _request(endpoint=endpoint, key=key, input_count=count)
    records: list[dict[str, Any]] = []
    sequence = 0
    for repetition in range(1, args.repetitions + 1):
        order = _CONDITIONS if repetition % 2 else tuple(reversed(_CONDITIONS))
        for order_index, name in enumerate(order, 1):
            endpoint, key, count, path = _condition(name, direct_key, proxy_key)
            sequence += 1
            error: str | None = None
            elapsed_ms = 0.0
            dimension = 0
            total_tokens = 0
            status_code: int | None = None
            try:
                elapsed_ms, dimension, total_tokens, status_code = await _request(
                    endpoint=endpoint, key=key, input_count=count
                )
            except Exception as exc:  # noqa: BLE001 - sanitized typed evidence
                error = type(exc).__name__
            records.append(
                {
                    "sequence": sequence,
                    "repetition": repetition,
                    "order_index": order_index,
                    "condition": name,
                    "path": path,
                    "input_count": count,
                    "elapsed_ms": round(elapsed_ms, 4),
                    "dimension": dimension,
                    "total_tokens": total_tokens,
                    "status_code": status_code,
                    "error": error,
                }
            )
            if error is not None:
                break
        if records[-1]["error"] is not None:
            break
    with (output / "per_request.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    try:
        summary = summarize(records, repetitions=args.repetitions)
    except ValueError as exc:
        manifest["status"] = "failed"
        manifest["failure"] = {
            "stage": "scored_probe",
            "error_type": type(exc).__name__,
            "message_persisted": False,
            "provider_calls_attempted": args.warmups * len(_CONDITIONS) + len(records),
        }
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise
    provider_calls = args.warmups * len(_CONDITIONS) + len(records)
    scored_tokens = sum(int(record["total_tokens"]) for record in records)
    warmup_tokens = args.warmups * (5 + 5 + 15 + 15)
    manifest.update(
        {
            "status": "completed",
            "provider_calls_including_warmups": provider_calls,
            "provider_input_tokens_including_warmups": scored_tokens + warmup_tokens,
            "scored_errors": 0,
            "conditions": summary["conditions"],
            "proxy_minus_direct_mean_ms": summary["proxy_minus_direct_mean_ms"],
            "per_request_sha256": hashlib.sha256(
                (output / "per_request.jsonl").read_bytes()
            ).hexdigest(),
        }
    )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--proxy-fingerprint", required=True)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--repetitions", type=int, default=10)
    args = parser.parse_args()
    if args.warmups < 0 or args.repetitions < 1:
        raise ValueError("warmups must be nonnegative and repetitions positive")
    print(json.dumps({"output": str(asyncio.run(run(args)))}, sort_keys=True))


if __name__ == "__main__":
    main()
