#!/usr/bin/env python3
"""Privacy-safe, fail-closed Open Manuals retrieval benchmark for RAGFlow.

The runner intentionally uses only RAGFlow's native ``POST /api/v1/retrieval``
endpoint.  Questions and response bodies exist only in memory while the run is
active.  The public artifact contains query IDs, local document IDs, scores,
timings, error codes, and aggregate retrieval metrics; it never contains
questions, document text, response bodies, or credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlparse

import httpx

EXPECTED_QUERY_IDS = tuple(f"q{number:03d}" for number in range(1, 71))
EXPECTED_DOCUMENT_COUNT = 22
EXPECTED_QUERY_COUNT = 70
EXPECTED_ANSWERABLE_COUNT = 60
EXPECTED_OFFCORPUS_COUNT = 10
RETRIEVAL_TOP_K = 50
RETRIEVAL_PAGE_SIZE = 5
RETRIEVAL_SIMILARITY_THRESHOLD = 0.0
RETRIEVAL_VECTOR_WEIGHT = 1.0


class RetrievalRunnerError(RuntimeError):
    """A safe contract or provider error (never includes provider body text)."""


class ContractError(RetrievalRunnerError):
    """An input, preflight, or output contract violation."""


class ResponseLike(Protocol):
    status_code: int

    def json(self) -> object: ...


class ClientLike(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, object],
        headers: Mapping[str, str] | None = None,
    ) -> ResponseLike: ...

    def post(
        self, url: str, *, headers: Mapping[str, str], json: Mapping[str, object]
    ) -> ResponseLike: ...


@dataclass(frozen=True)
class CorpusDocument:
    doc_id: str
    filename: str


@dataclass(frozen=True)
class QueryCase:
    query_id: str
    question: str
    answerable: bool
    required_doc_ids: frozenset[str]


@dataclass(frozen=True)
class Dataset:
    documents: tuple[CorpusDocument, ...]
    queries: tuple[QueryCase, ...]
    documents_sha256: str
    queries_sha256: str
    qrels_sha256: str


@dataclass(frozen=True)
class DocumentMapping:
    by_remote_id: Mapping[str, str]
    by_filename: Mapping[str, str]


@dataclass(frozen=True)
class RetrievalConfig:
    base_url: str
    auth_token_file: Path
    dataset_id_file: Path
    dataset_dir: Path
    private_output_dir: Path
    public_output_dir: Path
    expected_model_alias: str
    expected_dimension: int
    expected_proxy_fingerprint: str
    expected_source_commit: str
    expected_image_digest: str
    runtime_manifest: Path
    abstention_score_threshold: float = 0.0
    timeout_seconds: float = 30.0
    resource_recovery_note: str = "no recovery metadata supplied"
    warmup_artifacts: tuple[Path, ...] = ()


@dataclass(frozen=True)
class RuntimeProvenance:
    source_commit: str
    image_digest: str
    manifest_sha256: str


@dataclass(frozen=True)
class WarmupArtifact:
    name: str
    summary_sha256: str
    per_query_sha256: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ContractError(f"unable to hash input file: {path.name}") from exc
    return digest.hexdigest()


def _json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"unable to read JSON input: {path.name}") from exc


def _jsonl(path: Path) -> list[Mapping[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"unable to read JSONL input: {path.name}") from exc
    rows: list[Mapping[str, object]] = []
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid JSONL at {path.name}:{line_number}") from exc
        if not isinstance(value, Mapping):
            raise ContractError(f"JSONL row is not an object at {path.name}:{line_number}")
        rows.append(value)
    return rows


def _rows(path: Path, *, key: str) -> list[Mapping[str, object]]:
    if path.exists() and path.suffix == ".jsonl":
        return _jsonl(path)
    json_path = path if path.suffix == ".json" else path.with_suffix(".json")
    value = _json(json_path)
    if isinstance(value, list):
        rows = value
    elif isinstance(value, Mapping) and isinstance(value.get(key), list):
        rows = value[key]
    else:
        raise ContractError(f"{json_path.name} must contain a list of {key}")
    if not all(isinstance(row, Mapping) for row in rows):
        raise ContractError(f"{json_path.name} contains a non-object row")
    return [row for row in rows if isinstance(row, Mapping)]


def _first_text(row: Mapping[str, object], names: Sequence[str], label: str) -> str:
    for name in names:
        value = row.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ContractError(f"{label} is missing")


def _filename_keys(filename: str) -> tuple[str, ...]:
    path = Path(filename)
    name = path.name.casefold()
    stem = path.stem.casefold()
    return (name,) if stem == name else (name, stem)


def _doc_id_from_evidence(value: object) -> str:
    if isinstance(value, Mapping):
        for key in ("doc_id", "document_id", "id", "document"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""
    text = str(value).strip()
    return text.split(":", 1)[0] if text else ""


def _required_documents(row: Mapping[str, object]) -> frozenset[str]:
    names = (
        "required_document_ids",
        "required_documents",
        "relevant_document_ids",
        "relevant_doc_ids",
        "relevant_documents",
        "required_evidence_ids",
        "relevant_evidence_ids",
    )
    for name in names:
        value = row.get(name)
        if isinstance(value, list):
            return frozenset(item for item in (_doc_id_from_evidence(raw) for raw in value) if item)
    return frozenset()


def load_dataset(dataset_dir: Path) -> Dataset:
    """Load and validate the locked 22-document/70-query dataset contract."""

    dataset_dir = dataset_dir.resolve()
    documents_path = dataset_dir / "documents.jsonl"
    queries_path = dataset_dir / "queries.jsonl"
    qrels_path = dataset_dir / "qrels.jsonl"
    if not documents_path.exists():
        documents_path = dataset_dir / "documents.json"
    if not queries_path.exists():
        queries_path = dataset_dir / "queries.json"
    documents_rows = _rows(documents_path, key="documents")
    queries_rows = _rows(queries_path, key="queries")
    qrels_rows = _rows(qrels_path, key="qrels")

    documents: list[CorpusDocument] = []
    seen_ids: set[str] = set()
    seen_filenames: set[str] = set()
    for row in documents_rows:
        doc_id = _first_text(row, ("doc_id", "document_id", "id", "slug"), "doc_id")
        filename = next(
            (
                str(row[name]).strip()
                for name in ("filename", "file_name", "name", "path")
                if isinstance(row.get(name), str) and str(row[name]).strip()
            ),
            f"{doc_id}.txt",
        )
        filename = Path(filename).name
        if doc_id in seen_ids or any(key in seen_filenames for key in _filename_keys(filename)):
            raise ContractError("dataset document IDs and filenames must be unique")
        seen_ids.add(doc_id)
        seen_filenames.update(_filename_keys(filename))
        documents.append(CorpusDocument(doc_id=doc_id, filename=filename))
    if len(documents) != EXPECTED_DOCUMENT_COUNT:
        raise ContractError("dataset must contain exactly 22 documents")

    qrels_by_query: dict[str, set[str]] = {}
    for row in qrels_rows:
        query_id = _first_text(row, ("query_id",), "qrels.query_id")
        doc_id = _first_text(row, ("doc_id", "document_id"), "qrels.doc_id")
        if doc_id not in seen_ids:
            raise ContractError(f"{query_id} qrel references an unknown document")
        relevance = row.get("relevance", 0)
        if isinstance(relevance, bool) or not isinstance(relevance, int):
            raise ContractError(f"{query_id} qrel relevance must be an integer")
        if relevance > 0:
            qrels_by_query.setdefault(query_id, set()).add(doc_id)

    queries: list[QueryCase] = []
    for row in queries_rows:
        query_id = _first_text(row, ("query_id", "id"), "query_id")
        question = _first_text(row, ("question", "query", "text"), "question")
        answerable = row.get("answerable")
        if not isinstance(answerable, bool):
            raise ContractError(f"{query_id} answerable flag must be boolean")
        required = _required_documents(row) or frozenset(qrels_by_query.get(query_id, set()))
        unknown = required - seen_ids
        if unknown:
            raise ContractError(f"{query_id} references an unknown document")
        if answerable and not required:
            raise ContractError(f"{query_id} requires at least one document")
        if not answerable and required:
            raise ContractError(f"{query_id} off-corpus query cannot have required docs")
        queries.append(
            QueryCase(
                query_id=query_id,
                question=question,
                answerable=answerable,
                required_doc_ids=required,
            )
        )
    if tuple(query.query_id for query in queries) != EXPECTED_QUERY_IDS:
        raise ContractError("queries must be the complete ordered q001-q070 set")
    answerable = sum(query.answerable for query in queries)
    if answerable != EXPECTED_ANSWERABLE_COUNT:
        raise ContractError("queries must contain exactly 60 answerable queries")
    if len(queries) - answerable != EXPECTED_OFFCORPUS_COUNT:
        raise ContractError("queries must contain exactly 10 off-corpus queries")
    return Dataset(
        documents=tuple(documents),
        queries=tuple(queries),
        documents_sha256=sha256_file(documents_path),
        queries_sha256=sha256_file(queries_path),
        qrels_sha256=sha256_file(qrels_path),
    )


def _read_private_text(path: Path, label: str) -> str:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise ContractError(f"{label} file must not be group/world readable")
        value = path.read_text(encoding="utf-8").strip()
    except ContractError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"unable to read {label} file") from exc
    if not value or "\n" in value or "\r" in value:
        raise ContractError(f"{label} file is empty or malformed")
    return value


def _read_dataset_id(path: Path) -> str:
    value = _read_private_text(path, "dataset ID")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        decoded = value
    if isinstance(decoded, Mapping):
        decoded = decoded.get("dataset_id")
    if not isinstance(decoded, str) or not decoded.strip():
        raise ContractError("dataset ID file does not contain a dataset ID")
    dataset_id = decoded.strip()
    if len(dataset_id) > 256 or any(char.isspace() for char in dataset_id):
        raise ContractError("dataset ID is malformed")
    return dataset_id


def _validate_runtime_manifest(
    path: Path, *, expected_source_commit: str, expected_image_digest: str
) -> RuntimeProvenance:
    """Validate and extract provenance from the completed r6 smoke manifest."""

    if path.name != "manifest.json":
        raise ContractError("runtime manifest must be a manifest.json file")
    value = _json(path)
    if not isinstance(value, Mapping):
        raise ContractError("runtime manifest must be an object")
    if value.get("status") != "smoke_passed":
        raise ContractError("runtime manifest must have smoke_passed status")
    if value.get("memory_limit_bytes") != 5_000_000_000:
        raise ContractError("runtime manifest must record the executed 5 GB stack budget")
    if value.get("stack_left_running") is not False:
        raise ContractError("runtime manifest must record the project-scoped post-run stop")
    post_stop = value.get("post_smoke_stop")
    if not isinstance(post_stop, Mapping) or (
        post_stop.get("containers_left_running") != 0
        or post_stop.get("stop_scope") != "compose_project_only"
    ):
        raise ContractError("runtime manifest post-run stop evidence is incomplete")
    commit = value.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ContractError("runtime manifest source commit must be a 40-character SHA-1")
    if commit != expected_source_commit:
        raise ContractError("runtime manifest source commit does not match expected source commit")
    app_service = value.get("app_service")
    if not isinstance(app_service, str) or not app_service.strip():
        raise ContractError("runtime manifest app service is missing")
    image_provenance = value.get("image_provenance")
    if not isinstance(image_provenance, list):
        raise ContractError("runtime manifest image provenance is missing")
    app_digest: str | None = None
    for item in image_provenance:
        if not isinstance(item, Mapping):
            continue
        if item.get("role") != "app" or item.get("service") != app_service:
            continue
        candidate = item.get("digest", item.get("image_digest"))
        if isinstance(candidate, str):
            app_digest = candidate
            break
    if app_digest is None or not re.fullmatch(r"sha256:[0-9a-f]{64}", app_digest):
        raise ContractError("runtime manifest app image digest is missing or malformed")
    if app_digest != expected_image_digest:
        raise ContractError(
            "runtime manifest app image digest does not match expected image digest"
        )
    return RuntimeProvenance(
        source_commit=commit,
        image_digest=app_digest,
        manifest_sha256=sha256_file(path),
    )


def _validate_warmup_artifacts(
    paths: Sequence[Path], dataset: Dataset
) -> tuple[WarmupArtifact, ...]:
    """Validate completed, 70-query retrieval artifacts used as warmups."""

    seen_names: set[str] = set()
    validated: list[WarmupArtifact] = []
    expected_denominator = {
        "total": EXPECTED_QUERY_COUNT,
        "answerable": EXPECTED_ANSWERABLE_COUNT,
        "off_corpus": EXPECTED_OFFCORPUS_COUNT,
        "errors": 0,
    }
    for supplied_path in paths:
        root = supplied_path if supplied_path.is_dir() else supplied_path.parent
        name = supplied_path.name if supplied_path.is_dir() else root.name
        if name in seen_names:
            raise ContractError("warmup artifact names must be unique")
        seen_names.add(name)
        manifest = _json(root / "manifest.json")
        summary = _json(root / "summary.json")
        if not isinstance(manifest, Mapping) or not isinstance(summary, Mapping):
            raise ContractError(f"warmup artifact {name} metadata must be objects")
        for label, metadata in (("manifest", manifest), ("summary", summary)):
            if metadata.get("status") not in {"completed", "warmup_only"}:
                raise ContractError(f"warmup artifact {name} {label} is not completed")
            denominator = metadata.get("denominator")
            if denominator != expected_denominator:
                raise ContractError(f"warmup artifact {name} must contain 70 complete rows")
            dataset_hashes = metadata.get("dataset_sha256")
            if isinstance(dataset_hashes, Mapping) and dataset_hashes.get("qrels") not in (
                None,
                dataset.qrels_sha256,
            ):
                raise ContractError(f"warmup artifact {name} qrels hash does not match dataset")
        rows = _jsonl(root / "per_query.jsonl")
        query_ids = [row.get("query_id") for row in rows]
        if len(rows) != EXPECTED_QUERY_COUNT or tuple(query_ids) != EXPECTED_QUERY_IDS:
            raise ContractError(f"warmup artifact {name} must contain exactly 70 ordered rows")
        if any(row.get("error_codes") != [] for row in rows):
            raise ContractError(f"warmup artifact {name} contains retrieval errors")
        integrity = manifest.get("artifact_integrity")
        if isinstance(integrity, Mapping):
            expected_hash = integrity.get("per_query_sha256")
            if expected_hash is not None and expected_hash != sha256_file(root / "per_query.jsonl"):
                raise ContractError(f"warmup artifact {name} per-query hash does not match")
        validated.append(
            WarmupArtifact(
                name=name,
                summary_sha256=sha256_file(root / "summary.json"),
                per_query_sha256=sha256_file(root / "per_query.jsonl"),
            )
        )
    return tuple(validated)


def _validate_config(config: RetrievalConfig) -> None:
    parsed = urlparse(config.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise ContractError("base URL must be an HTTP(S) URL without credentials")
    if config.expected_dimension <= 0:
        raise ContractError("expected embedding dimension must be positive")
    if not config.expected_model_alias.strip():
        raise ContractError("expected model alias is required")
    if not re.fullmatch(r"[0-9a-f]{64}", config.expected_proxy_fingerprint):
        raise ContractError("expected proxy fingerprint must be a lowercase SHA-256")
    if not re.fullmatch(r"[0-9a-f]{40}", config.expected_source_commit):
        raise ContractError("expected source commit must be a 40-character SHA-1")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", config.expected_image_digest):
        raise ContractError("expected image digest must be sha256:<64 lowercase hex>")
    if not math.isfinite(config.abstention_score_threshold):
        raise ContractError("abstention threshold must be finite")
    if config.timeout_seconds <= 0 or not math.isfinite(config.timeout_seconds):
        raise ContractError("timeout must be positive and finite")
    if config.private_output_dir.resolve() == config.public_output_dir.resolve():
        raise ContractError("private and public output directories must differ")
    if config.private_output_dir.exists() or config.public_output_dir.exists():
        raise FileExistsError("refusing to overwrite an existing output directory")
    if not config.runtime_manifest.is_file():
        raise ContractError("runtime manifest is required")


def _url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _response_payload(response: ResponseLike, operation: str) -> Mapping[str, object]:
    if response.status_code < 200 or response.status_code >= 300:
        raise RetrievalRunnerError(f"{operation}_http_{response.status_code}")
    try:
        value = response.json()
    except (ValueError, TypeError):
        raise RetrievalRunnerError(f"{operation}_invalid_payload") from None
    if not isinstance(value, Mapping):
        raise RetrievalRunnerError(f"{operation}_invalid_payload")
    code = value.get("code")
    if code not in (None, 0, "0"):
        raise RetrievalRunnerError(f"{operation}_api_error")
    return value


def _api_data(payload: Mapping[str, object], operation: str) -> object:
    if "data" not in payload:
        raise RetrievalRunnerError(f"{operation}_invalid_payload")
    return payload["data"]


def _remote_docs(payload: Mapping[str, object]) -> list[Mapping[str, object]]:
    data = _api_data(payload, "preflight")
    if isinstance(data, Mapping):
        value = data.get("docs", data.get("documents"))
    else:
        value = data
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise RetrievalRunnerError("preflight_invalid_payload")
    return [item for item in value if isinstance(item, Mapping)]


def preflight_documents(
    client: ClientLike,
    *,
    base_url: str,
    dataset_id: str,
    headers: Mapping[str, str],
    documents: Sequence[CorpusDocument],
) -> DocumentMapping:
    """Verify exactly 22 DONE docs and return safe remote-to-local mappings."""

    try:
        response = client.get(
            _url(base_url, f"api/v1/datasets/{dataset_id}/documents"),
            params={"page": 1, "page_size": 100},
            headers=headers,
        )
        payload = _response_payload(response, "preflight")
        remote_docs = _remote_docs(payload)
    except RetrievalRunnerError:
        raise
    except Exception as exc:
        raise RetrievalRunnerError("preflight_request_failed") from exc
    if len(remote_docs) != EXPECTED_DOCUMENT_COUNT:
        raise ContractError("RAGFlow preflight must return exactly 22 documents")

    local_by_filename = {
        key: doc.doc_id for doc in documents for key in _filename_keys(doc.filename)
    }
    local_ids = {doc.doc_id for doc in documents}
    by_remote_id: dict[str, str] = {}
    by_filename: dict[str, str] = {}
    for remote in remote_docs:
        status = str(
            remote.get("run", remote.get("status", remote.get("process_status", "")))
        ).upper()
        if status != "DONE":
            raise ContractError("all RAGFlow documents must have DONE status")
        remote_id = str(remote.get("id", remote.get("doc_id", ""))).strip()
        filename_value = remote.get(
            "name", remote.get("filename", remote.get("document_keyword", remote.get("title", "")))
        )
        filename = Path(str(filename_value).strip()).name
        local_id = next(
            (
                local_by_filename[key]
                for key in _filename_keys(filename)
                if key in local_by_filename
            ),
            None,
        )
        if local_id is None and remote_id in local_ids:
            local_id = remote_id
        if not remote_id or local_id is None:
            raise ContractError("every RAGFlow document must map to a local document")
        if remote_id in by_remote_id or any(key in by_filename for key in _filename_keys(filename)):
            raise ContractError("RAGFlow document mapping is ambiguous")
        by_remote_id[remote_id] = local_id
        for key in _filename_keys(filename):
            by_filename[key] = local_id
    if set(by_remote_id.values()) != local_ids:
        raise ContractError("RAGFlow preflight did not map all local documents")
    return DocumentMapping(by_remote_id=by_remote_id, by_filename=by_filename)


def _score(hit: Mapping[str, object]) -> float:
    for key in ("similarity", "score", "vector_similarity"):
        value = hit.get(key)
        if isinstance(value, bool):
            continue
        try:
            parsed = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed):
            return parsed
    raise ValueError("score missing")


def _map_hit(hit: Mapping[str, object], mapping: DocumentMapping) -> str | None:
    remote_id = str(hit.get("document_id", hit.get("doc_id", ""))).strip()
    if remote_id and remote_id in mapping.by_remote_id:
        return mapping.by_remote_id[remote_id]
    for key in ("document_keyword", "filename", "file_name", "name", "title"):
        value = hit.get(key)
        if isinstance(value, str) and value.strip():
            for key in _filename_keys(value):
                local_id = mapping.by_filename.get(key)
                if local_id is not None:
                    return local_id
    return None


def dedupe_ranked_documents(
    ranked: Sequence[tuple[str, float]], top_k: int = RETRIEVAL_PAGE_SIZE
) -> tuple[list[str], list[float]]:
    """Deduplicate document IDs while preserving their first ranked occurrence.

    RAGFlow returns chunks, so repeated chunks from one document must not count
    as separate document ranks.  The first occurrence is retained because the
    endpoint's order is its relevance order; metrics are computed only over the
    resulting document ranking.
    """

    ids: list[str] = []
    scores: list[float] = []
    seen: set[str] = set()
    for doc_id, score in ranked:
        if doc_id in seen:
            continue
        seen.add(doc_id)
        ids.append(doc_id)
        scores.append(score)
        if len(ids) == top_k:
            break
    return ids, scores


def retrieve_one(
    client: ClientLike,
    *,
    base_url: str,
    dataset_id: str,
    headers: Mapping[str, str],
    query: QueryCase,
    mapping: DocumentMapping,
) -> dict[str, object]:
    """Issue one native retrieval request and return only privacy-safe fields."""

    started = time.perf_counter()
    body: dict[str, object] = {
        "question": query.question,
        "dataset_ids": [dataset_id],
        "page": 1,
        "page_size": RETRIEVAL_PAGE_SIZE,
        "similarity_threshold": RETRIEVAL_SIMILARITY_THRESHOLD,
        "vector_similarity_weight": RETRIEVAL_VECTOR_WEIGHT,
        "top_k": RETRIEVAL_TOP_K,
        "keyword": False,
    }
    errors: list[str] = []
    ranked_ids: list[str] = []
    ranked_scores: list[float] = []
    try:
        response = client.post(_url(base_url, "api/v1/retrieval"), headers=headers, json=body)
        payload = _response_payload(response, "retrieval")
        data = _api_data(payload, "retrieval")
        if isinstance(data, Mapping):
            raw_hits = data.get("chunks", data.get("results", []))
        else:
            raw_hits = data
        if not isinstance(raw_hits, list):
            raise RetrievalRunnerError("retrieval_invalid_payload")
        candidates: list[tuple[int, str, float]] = []
        for index, raw_hit in enumerate(raw_hits):
            if not isinstance(raw_hit, Mapping):
                errors.append("invalid_result")
                continue
            local_id = _map_hit(raw_hit, mapping)
            if local_id is None:
                errors.append("unmapped_document")
                continue
            try:
                score = _score(raw_hit)
            except ValueError:
                errors.append("invalid_score")
                continue
            candidates.append((index, local_id, score))
        candidates.sort(key=lambda item: (-item[2], item[0]))
        ranked_ids, ranked_scores = dedupe_ranked_documents(
            [(local_id, score) for _, local_id, score in candidates]
        )
    except RetrievalRunnerError as exc:
        errors.append(str(exc))
    except Exception:
        errors.append("request_failed")
    return {
        "query_id": query.query_id,
        "ranked_doc_ids": ranked_ids,
        "ranked_scores": [round(score, 8) for score in ranked_scores],
        "latency_ms": round((time.perf_counter() - started) * 1000, 4),
        "error_codes": sorted(set(errors)),
    }


def recall_at_5(required: set[str] | frozenset[str], ranked: Sequence[str]) -> float | None:
    if not required:
        return None
    return len(required & set(ranked[:5])) / len(required)


def mrr_at_5(required: set[str] | frozenset[str], ranked: Sequence[str]) -> float | None:
    if not required:
        return None
    for index, doc_id in enumerate(ranked[:5], 1):
        if doc_id in required:
            return 1.0 / index
    return 0.0


def ndcg_at_5(required: set[str] | frozenset[str], ranked: Sequence[str]) -> float | None:
    if not required:
        return None
    dcg = sum(
        1.0 / math.log2(index + 2) for index, doc_id in enumerate(ranked[:5]) if doc_id in required
    )
    ideal_count = min(5, len(required))
    ideal = sum(1.0 / math.log2(index + 2) for index in range(ideal_count))
    return dcg / ideal if ideal else 0.0


def _query_metrics(
    query: QueryCase, ranked: Sequence[str], scores: Sequence[float], threshold: float
) -> dict[str, object]:
    predicted_abstention = not scores or max(scores) < threshold
    result: dict[str, object] = {
        "abstention_expected": not query.answerable,
        "abstention_predicted": predicted_abstention,
        "abstention_correct": predicted_abstention is (not query.answerable),
    }
    if query.answerable:
        result.update(
            {
                "recall_at_5": recall_at_5(query.required_doc_ids, ranked),
                "mrr_at_5": mrr_at_5(query.required_doc_ids, ranked),
                "ndcg_at_5": ndcg_at_5(query.required_doc_ids, ranked),
                "required_doc_hit": bool(query.required_doc_ids & set(ranked[:5])),
            }
        )
    else:
        result.update(
            {"recall_at_5": None, "mrr_at_5": None, "ndcg_at_5": None, "required_doc_hit": None}
        )
    return result


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _latency_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, float | int]:
    values: list[float] = []
    for row in rows:
        value = row.get("latency_ms")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContractError("retrieval latency is missing or malformed")
        latency = float(value)
        if not math.isfinite(latency) or latency < 0:
            raise ContractError("retrieval latency is missing or malformed")
        values.append(latency)
    if len(values) != EXPECTED_QUERY_COUNT:
        raise ContractError("retrieval latency denominator is incomplete")
    ordered = sorted(values)

    def percentile(quantile: float) -> float:
        position = (len(ordered) - 1) * quantile
        low = int(position)
        high = math.ceil(position)
        if low == high:
            return ordered[low]
        return ordered[low] + (ordered[high] - ordered[low]) * (position - low)

    return {
        "observations": len(ordered),
        "mean": sum(ordered) / len(ordered),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
    }


def aggregate_metrics(
    queries: Sequence[QueryCase], rows: Sequence[Mapping[str, object]], threshold: float
) -> dict[str, object]:
    by_id = {str(row.get("query_id")): row for row in rows}
    metric_rows: list[dict[str, object]] = []
    for query in queries:
        row = by_id.get(query.query_id, {})
        ranked = row.get("ranked_doc_ids", [])
        scores = row.get("ranked_scores", [])
        if not isinstance(ranked, list) or not isinstance(scores, list):
            ranked, scores = [], []
        numeric_scores: list[float] = []
        for score in scores:
            if isinstance(score, bool):
                continue
            if isinstance(score, (int, float)):
                numeric_scores.append(float(score))
            elif isinstance(score, str):
                try:
                    numeric_scores.append(float(score))
                except ValueError:
                    continue
        metric_rows.append(_query_metrics(query, ranked, numeric_scores, threshold))
    answerable_rows = [
        row for query, row in zip(queries, metric_rows, strict=True) if query.answerable
    ]
    abstention_correct = sum(bool(row["abstention_correct"]) for row in metric_rows)
    required_hits = sum(bool(row["required_doc_hit"]) for row in answerable_rows)

    def values(name: str) -> list[float]:
        return [
            float(value)
            for row in answerable_rows
            for value in [row[name]]
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]

    recall = values("recall_at_5")
    mrr = values("mrr_at_5")
    ndcg = values("ndcg_at_5")
    recall_metric = {"mean": _mean(recall), "observations": len(recall)}
    mrr_metric = {"mean": _mean(mrr), "observations": len(mrr)}
    ndcg_metric = {"mean": _mean(ndcg), "observations": len(ndcg)}
    hit_metric = {
        "hits": required_hits,
        "observations": len(answerable_rows),
        "rate": required_hits / len(answerable_rows) if answerable_rows else None,
    }
    return {
        "recall_at_5": recall_metric,
        "doc_recall_at_5": recall_metric,
        "mrr_at_5": mrr_metric,
        "ndcg_at_5": ndcg_metric,
        "required_doc_hit": hit_metric,
        "required_doc_hit_rate": hit_metric["rate"],
        "abstention": {
            "policy": "abstain when no ranked document score is >= threshold",
            "threshold": threshold,
            "correct": abstention_correct,
            "observations": len(metric_rows),
            "accuracy": abstention_correct / len(metric_rows) if metric_rows else None,
        },
    }


def _config_hash(config: RetrievalConfig, dataset: Dataset, dataset_id: str) -> str:
    value = {
        "dataset_id": dataset_id,
        "dataset_sha256": {
            "documents": dataset.documents_sha256,
            "queries": dataset.queries_sha256,
            "qrels": dataset.qrels_sha256,
        },
        "expected_model_alias": config.expected_model_alias,
        "expected_dimension": config.expected_dimension,
        "expected_proxy_fingerprint": config.expected_proxy_fingerprint,
        "expected_source_commit": config.expected_source_commit,
        "expected_image_digest": config.expected_image_digest,
        "resource_recovery_note": config.resource_recovery_note,
        "threshold": config.abstention_score_threshold,
        "retrieval": {
            "page_size": RETRIEVAL_PAGE_SIZE,
            "top_k": RETRIEVAL_TOP_K,
            "similarity_threshold": RETRIEVAL_SIMILARITY_THRESHOLD,
            "vector_similarity_weight": RETRIEVAL_VECTOR_WEIGHT,
            "keyword": False,
        },
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _write_new(path: Path, value: object) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(_json_text(value))
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite {path}") from None
    except OSError as exc:
        raise RetrievalRunnerError("unable_to_write_output") from exc


def _json_text(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_text_new(path: Path, value: str) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(value)
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite {path}") from None
    except OSError as exc:
        raise RetrievalRunnerError("unable_to_write_output") from exc


def run_benchmark(
    config: RetrievalConfig,
    *,
    client: ClientLike | None = None,
    client_factory: Callable[[str, float], ClientLike] | None = None,
) -> Path:
    """Run the benchmark, writing artifacts only after preflight succeeds."""

    _validate_config(config)
    dataset = load_dataset(config.dataset_dir)
    runtime = _validate_runtime_manifest(
        config.runtime_manifest,
        expected_source_commit=config.expected_source_commit,
        expected_image_digest=config.expected_image_digest,
    )
    warmups = _validate_warmup_artifacts(config.warmup_artifacts, dataset)
    token = _read_private_text(config.auth_token_file, "auth token")
    dataset_id = _read_dataset_id(config.dataset_id_file)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    active_client: ClientLike
    if client is None:
        if client_factory is not None:
            active_client = client_factory(config.base_url, config.timeout_seconds)
        else:
            active_client = cast(
                ClientLike, httpx.Client(headers=headers, timeout=config.timeout_seconds)
            )
    else:
        active_client = client
    mapping = preflight_documents(
        active_client,
        base_url=config.base_url,
        dataset_id=dataset_id,
        headers=headers,
        documents=dataset.documents,
    )
    rows: list[dict[str, object]] = []
    for query in dataset.queries:
        row = retrieve_one(
            active_client,
            base_url=config.base_url,
            dataset_id=dataset_id,
            headers=headers,
            query=query,
            mapping=mapping,
        )
        rows.append(row)
    errors = sum(bool(row["error_codes"]) for row in rows)
    metrics = aggregate_metrics(dataset.queries, rows, config.abstention_score_threshold)
    runner_sha256 = sha256_file(Path(__file__).resolve())
    warmup_metadata = [
        {
            "name": warmup.name,
            "summary_sha256": warmup.summary_sha256,
            "per_query_sha256": warmup.per_query_sha256,
        }
        for warmup in warmups
    ]
    provenance = {
        "source_commit": runtime.source_commit,
        "expected_source_commit": config.expected_source_commit,
        "source_commit_sha256": hashlib.sha256(runtime.source_commit.encode()).hexdigest(),
        "image_digest": runtime.image_digest,
        "expected_image_digest": config.expected_image_digest,
        "image_digest_sha256": hashlib.sha256(runtime.image_digest.encode()).hexdigest(),
        "proxy_fingerprint_sha256": config.expected_proxy_fingerprint,
        "proxy_fingerprint_source": "caller_expected",
        "proxy": {
            "fingerprint_sha256": config.expected_proxy_fingerprint,
            "source": "caller_expected",
        },
        "runner_sha256": runner_sha256,
        "runtime_manifest_sha256": runtime.manifest_sha256,
        "qrels_sha256": dataset.qrels_sha256,
        "config_sha256": _config_hash(config, dataset, dataset_id),
    }
    denominator = {
        "total": EXPECTED_QUERY_COUNT,
        "answerable": EXPECTED_ANSWERABLE_COUNT,
        "off_corpus": EXPECTED_OFFCORPUS_COUNT,
        "errors": errors,
    }
    status = "completed" if errors == 0 and len(rows) == EXPECTED_QUERY_COUNT else "incomplete"
    created = datetime.now(UTC).isoformat()
    privacy = {
        "raw_artifacts_private_only": True,
        "questions_persisted": False,
        "document_content_persisted": False,
        "response_bodies_persisted": False,
        "credentials_persisted": False,
        "public_per_query_fields": [
            "query_id",
            "ranked_doc_ids",
            "ranked_scores",
            "latency_ms",
            "error_codes",
        ],
    }
    manifest = {
        "schema_version": 1,
        "runner": "open-manuals-ragflow-native-retrieval",
        "created_at_utc": created,
        "status": status,
        "dataset_id_sha256": hashlib.sha256(dataset_id.encode()).hexdigest(),
        "denominator": denominator,
        "model": {
            "alias": config.expected_model_alias,
            "dimension": config.expected_dimension,
        },
        "retrieval_config": {
            "endpoint": "/api/v1/retrieval",
            "page_size": RETRIEVAL_PAGE_SIZE,
            "top_k": RETRIEVAL_TOP_K,
            "similarity_threshold": RETRIEVAL_SIMILARITY_THRESHOLD,
            "vector_similarity_weight": RETRIEVAL_VECTOR_WEIGHT,
            "keyword": False,
        },
        "dataset_sha256": {
            "documents": dataset.documents_sha256,
            "queries": dataset.queries_sha256,
            "qrels": dataset.qrels_sha256,
        },
        "provenance": provenance,
        "privacy": privacy,
        "resource_recovery_caveat": config.resource_recovery_note,
        "warmups_per_query": len(warmups),
        "warmup_artifacts": warmup_metadata,
        "warmup_protocol": {"cache_reset": False, "artifacts": warmup_metadata},
    }
    per_query_text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    per_query_sha256 = hashlib.sha256(per_query_text.encode()).hexdigest()
    summary = {
        **manifest,
        "metrics": metrics,
        "latency_ms": _latency_summary(rows),
        "preflight": {
            "documents_expected": EXPECTED_DOCUMENT_COUNT,
            "documents_mapped": len(mapping.by_remote_id),
            "all_done": True,
        },
        "artifact_integrity": {"per_query_sha256": per_query_sha256},
    }
    summary_sha256 = hashlib.sha256(_json_text(summary).encode()).hexdigest()
    manifest = {
        **manifest,
        "artifact_integrity": {
            "per_query_sha256": per_query_sha256,
            "summary_sha256": summary_sha256,
        },
    }
    # Construct output trees only after all external work has finished.  ``x``
    # writes retain the no-overwrite guarantee if a race creates a file.
    try:
        config.private_output_dir.mkdir(parents=True)
        config.public_output_dir.mkdir(parents=True)
        _write_new(config.private_output_dir / "summary.json", summary)
        _write_new(config.public_output_dir / "summary.json", summary)
        _write_text_new(config.public_output_dir / "per_query.jsonl", per_query_text)
        _write_new(config.private_output_dir / "manifest.json", manifest)
        _write_new(config.public_output_dir / "manifest.json", manifest)
    except FileExistsError:
        raise FileExistsError("refusing to overwrite output artifact") from None
    except OSError as exc:
        raise RetrievalRunnerError("unable_to_write_output") from exc
    return config.public_output_dir


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--auth-token-file", "--token-file", required=True, type=Path)
    parser.add_argument("--dataset-id-file", required=True, type=Path)
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--private-output-dir", "--private-output", required=True, type=Path)
    parser.add_argument("--public-output-dir", "--public-output", required=True, type=Path)
    parser.add_argument("--expected-model-alias", required=True)
    parser.add_argument("--expected-dimension", required=True, type=int)
    parser.add_argument("--expected-proxy-fingerprint", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-image-digest", required=True)
    parser.add_argument("--runtime-manifest", required=True, type=Path)
    parser.add_argument(
        "--warmup-artifact",
        action="append",
        type=Path,
        default=[],
        help="completed 70-query retrieval artifact directory; may be repeated",
    )
    parser.add_argument("--abstention-score-threshold", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--resource-recovery-note",
        default="no recovery metadata supplied",
        help="non-secret description of ingestion/runtime recovery preceding the run",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    config = RetrievalConfig(
        base_url=args.base_url,
        auth_token_file=args.auth_token_file,
        dataset_id_file=args.dataset_id_file,
        dataset_dir=args.dataset_dir,
        private_output_dir=args.private_output_dir,
        public_output_dir=args.public_output_dir,
        expected_model_alias=args.expected_model_alias,
        expected_dimension=args.expected_dimension,
        expected_proxy_fingerprint=args.expected_proxy_fingerprint,
        expected_source_commit=args.expected_source_commit,
        expected_image_digest=args.expected_image_digest,
        runtime_manifest=args.runtime_manifest,
        abstention_score_threshold=args.abstention_score_threshold,
        timeout_seconds=args.timeout_seconds,
        resource_recovery_note=args.resource_recovery_note,
        warmup_artifacts=tuple(args.warmup_artifact),
    )
    print(json.dumps({"output": str(run_benchmark(config))}))


if __name__ == "__main__":
    main()
