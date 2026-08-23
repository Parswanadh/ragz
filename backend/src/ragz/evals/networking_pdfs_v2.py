"""Schema, validation, and metadata-only candidate generation for v2.

This module deliberately does not read PDF text or call an embedding/LLM
provider.  A candidate is a review work item until a human supplies the
question, answer, claims, and page qrels.  The source metadata contains only
book identity, chapter identity, and page bounds.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

Split = Literal["dev", "locked"]
Status = Literal["draft_unverified", "reviewed", "adjudicated", "locked"]
Decision = Literal["approve", "reject"]
QueryType = Literal[
    "definition",
    "comparison",
    "procedure",
    "troubleshooting",
    "design",
    "calculation",
]
NegativeStratum = Literal[
    "out_of_scope",
    "insufficient_evidence",
    "false_premise",
    "ambiguous",
]
Difficulty = Literal["easy", "medium", "hard"]
SourceScope = Literal["single_book", "pairwise", "all_three", "off_corpus"]

TAXONOMY: tuple[QueryType, ...] = (
    "definition",
    "comparison",
    "procedure",
    "troubleshooting",
    "design",
    "calculation",
)
NEGATIVE_STRATA: tuple[NegativeStratum, ...] = (
    "out_of_scope",
    "insufficient_evidence",
    "false_premise",
    "ambiguous",
)
DIFFICULTIES: tuple[Difficulty, ...] = ("easy", "medium", "hard")
SOURCE_SCOPES: tuple[SourceScope, ...] = (
    "single_book",
    "pairwise",
    "all_three",
    "off_corpus",
)
DEFAULT_TARGETS: dict[Split, dict[QueryType, int]] = {
    "locked": {query_type: 60 for query_type in TAXONOMY},
    "dev": {query_type: 10 for query_type in TAXONOMY},
}
DEFAULT_ANSWERABILITY_TARGETS: dict[Split, dict[str, int]] = {
    "locked": {"answerable": 240, "negative": 120},
    "dev": {"answerable": 40, "negative": 20},
}
DEFAULT_NEGATIVE_STRATA_TARGETS: dict[Split, dict[NegativeStratum, int]] = {
    "locked": {stratum: 30 for stratum in NEGATIVE_STRATA},
    "dev": {stratum: 5 for stratum in NEGATIVE_STRATA},
}
DEFAULT_DIFFICULTY_TARGETS: dict[Split, dict[Difficulty, int]] = {
    "locked": {"easy": 120, "medium": 150, "hard": 90},
    "dev": {"easy": 20, "medium": 25, "hard": 15},
}
DEFAULT_SOURCE_SCOPE_TARGETS: dict[Split, dict[SourceScope, int]] = {
    "locked": {"single_book": 240, "pairwise": 60, "all_three": 30, "off_corpus": 30},
    "dev": {"single_book": 40, "pairwise": 10, "all_three": 5, "off_corpus": 5},
}
_QUESTION_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class ChapterMetadata:
    """Copyright-safe chapter metadata used to create review work items."""

    chapter_id: str
    title: str
    page_start: int
    page_end: int
    concept_cluster: str


@dataclass(frozen=True)
class BookMetadata:
    """Identity and structural metadata for one source PDF."""

    book_id: str
    title: str
    sha256: str
    page_count: int
    chapters: tuple[ChapterMetadata, ...]


@dataclass(frozen=True)
class SourceMetadataRef:
    """A candidate's source pointer; it intentionally has no page text."""

    book_id: str
    chapter_id: str
    chapter_title: str
    page_start: int
    page_end: int
    concept_cluster: str


@dataclass(frozen=True)
class Qrel:
    """Graded, exact-page relevance judgment.

    ``page`` is a physical 1-based PDF page.  Ranges are not allowed because
    evaluation must be reproducible at exact-page granularity.
    """

    evidence_id: str
    book_id: str
    page: int
    grade: int


@dataclass(frozen=True)
class AtomicClaim:
    claim_id: str
    text: str


@dataclass(frozen=True)
class ClaimEvidenceLink:
    claim_id: str
    evidence_id: str
    relation: Literal["supports", "contradicts"] = "supports"


@dataclass(frozen=True)
class Review:
    reviewer_id: str
    decision: Decision
    reviewed_at: str
    notes: str = ""


@dataclass(frozen=True)
class Adjudication:
    adjudicator_id: str
    decision: Decision
    adjudicated_at: str
    notes: str = ""


@dataclass
class QuestionRecord:
    """One query and its human-authored answer/evidence package."""

    question_id: str
    split: Split
    query_type: QueryType | None
    concept_cluster: str
    query: str = ""
    alternatives: list[str] = field(default_factory=list)
    answerable: bool | None = None
    negative_stratum: NegativeStratum | None = None
    difficulty: Difficulty | None = None
    source_scope: SourceScope = "single_book"
    reference_answer: str = ""
    claims: list[AtomicClaim] = field(default_factory=list)
    claim_evidence_links: list[ClaimEvidenceLink] = field(default_factory=list)
    qrels: list[Qrel] = field(default_factory=list)
    source_metadata: list[SourceMetadataRef] = field(default_factory=list)
    status: Status = "draft_unverified"
    reviews: list[Review] = field(default_factory=list)
    adjudication: Adjudication | None = None
    content_sha256: str | None = None


@dataclass
class DatasetManifest:
    """Top-level v2 dataset envelope."""

    schema_version: str = "networking-pdfs-v2"
    dataset_id: str = "networking-pdfs-v2"
    status: Status = "draft_unverified"
    source_books: list[BookMetadata] = field(default_factory=list)
    questions: list[QuestionRecord] = field(default_factory=list)
    targets: dict[Split, dict[QueryType, int]] = field(
        default_factory=lambda: {split: dict(targets) for split, targets in DEFAULT_TARGETS.items()}
    )
    answerability_targets: dict[Split, dict[str, int]] = field(
        default_factory=lambda: {
            split: dict(targets) for split, targets in DEFAULT_ANSWERABILITY_TARGETS.items()
        }
    )
    negative_strata_targets: dict[Split, dict[NegativeStratum, int]] = field(
        default_factory=lambda: {
            split: dict(targets) for split, targets in DEFAULT_NEGATIVE_STRATA_TARGETS.items()
        }
    )
    difficulty_targets: dict[Split, dict[Difficulty, int]] = field(
        default_factory=lambda: {
            split: dict(targets) for split, targets in DEFAULT_DIFFICULTY_TARGETS.items()
        }
    )
    source_scope_targets: dict[Split, dict[SourceScope, int]] = field(
        default_factory=lambda: {
            split: dict(targets) for split, targets in DEFAULT_SOURCE_SCOPE_TARGETS.items()
        }
    )
    book_coverage_targets: dict[Split, dict[str, int]] = field(
        default_factory=lambda: {"dev": {}, "locked": {}}
    )
    dataset_sha256: str | None = None


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def valid(self) -> bool:
        return not self.errors

    def add(self, path: str, code: str, message: str, *, warning: bool = False) -> None:
        self.issues.append(
            ValidationIssue(path, code, message, "warning" if warning else "error")
        )

    def raise_for_errors(self) -> None:
        if self.errors:
            detail = "; ".join(f"{issue.path}: {issue.message}" for issue in self.errors)
            raise ValueError(detail)


def _normalized_question(value: str) -> str:
    return _QUESTION_SPACE.sub(" ", value.strip()).casefold()


def _canonical(value: Any) -> Any:
    """Convert dataclasses to stable JSON-compatible values."""

    if hasattr(value, "__dataclass_fields__"):
        return {key: _canonical(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda x: str(x[0]))}  # noqa: E501
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def record_payload(record: QuestionRecord) -> dict[str, Any]:
    """Return canonical record data excluding its derived content hash."""

    payload = cast(dict[str, Any], _canonical(record))
    payload.pop("content_sha256", None)
    return payload


def record_sha256(record: QuestionRecord) -> str:
    raw = json.dumps(record_payload(record), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def manifest_payload(manifest: DatasetManifest) -> dict[str, Any]:
    payload = cast(dict[str, Any], _canonical(manifest))
    payload.pop("dataset_sha256", None)
    return payload


def dataset_sha256(manifest: DatasetManifest) -> str:
    raw = json.dumps(manifest_payload(manifest), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _book_map(manifest: DatasetManifest) -> dict[str, BookMetadata]:
    return {book.book_id: book for book in manifest.source_books}


def _record_source_books(record: QuestionRecord) -> set[str]:
    """Return books represented by evidence, or safe metadata for negatives."""

    if record.answerable is True:
        return {qrel.book_id for qrel in record.qrels}
    return {source.book_id for source in record.source_metadata}


def _validate_review_gate(record: QuestionRecord, report: ValidationReport, path: str) -> None:
    if record.status not in {"draft_unverified", "reviewed", "adjudicated", "locked"}:
        report.add(path, "invalid_status", "status is not a recognized v2 review status")
    reviewer_ids = [review.reviewer_id for review in record.reviews]
    for review in record.reviews:
        if review.decision not in {"approve", "reject"}:
            report.add(path, "invalid_review_decision", "review decision must be approve or reject")
    if len(reviewer_ids) != len(set(reviewer_ids)):
        report.add(path, "duplicate_reviewer", "reviews must come from distinct human reviewers")
    if any(not reviewer_id.strip() for reviewer_id in reviewer_ids):
        report.add(path, "empty_reviewer", "reviewer_id must be non-empty")
    if record.status in {"reviewed", "adjudicated", "locked"} and len(record.reviews) < 2:
        report.add(path, "two_reviews_required", "reviewed and locked records require two reviews")
    if record.status in {"adjudicated", "locked"}:
        if record.adjudication is None:
            report.add(path, "adjudication_required", "adjudicated and locked records require adjudication")  # noqa: E501
        elif record.adjudication.decision != "approve":
            report.add(path, "adjudication_not_approved", "adjudicated and locked records require approval")  # noqa: E501
    elif record.adjudication is not None and record.adjudication.decision not in {"approve", "reject"}:  # noqa: E501
        report.add(path, "invalid_adjudication_decision", "adjudication decision must be approve or reject")  # noqa: E501
    if record.status == "locked":
        if len(record.reviews) != 2 or any(review.decision != "approve" for review in record.reviews):  # noqa: E501
            report.add(path, "reviews_not_approved", "locked records require exactly two approving reviews")  # noqa: E501
        if record.adjudication is not None and record.adjudication.adjudicator_id.strip() in set(reviewer_ids):  # noqa: E501
            report.add(path, "adjudicator_is_reviewer", "adjudicator must be a third human")


def _validate_record(
    record: QuestionRecord,
    manifest: DatasetManifest,
    report: ValidationReport,
    index: int,
    *,
    strict_draft: bool,
) -> None:
    path = f"questions[{index}]"
    if not record.question_id.strip():
        report.add(path, "empty_id", "question_id must be non-empty")
    if record.split not in {"dev", "locked"}:
        report.add(path, "invalid_split", "split must be dev or locked")
    if record.query_type is not None and record.query_type not in TAXONOMY:
        report.add(path, "invalid_query_type", "query_type is outside the v2 taxonomy")
    if record.negative_stratum is not None and record.negative_stratum not in NEGATIVE_STRATA:
        report.add(path, "invalid_negative_stratum", "negative_stratum is outside the v2 taxonomy")
    if record.difficulty is not None and record.difficulty not in DIFFICULTIES:
        report.add(path, "invalid_difficulty", "difficulty must be easy, medium, or hard")
    if record.source_scope not in SOURCE_SCOPES:
        report.add(path, "invalid_source_scope", "source_scope is outside the v2 taxonomy")
    if not record.concept_cluster.strip():
        report.add(path, "empty_cluster", "concept_cluster must be non-empty")
    draft = record.status == "draft_unverified"
    if not draft or strict_draft:
        if len(record.alternatives) != 2 or any(not alternative.strip() for alternative in record.alternatives):  # noqa: E501
            report.add(path, "two_alternatives_required", "exactly two non-empty alternatives are required")  # noqa: E501
        if not record.query.strip() or len(record.query) > 2_000:
            report.add(path, "query_required", "query must be 1-2000 characters")
        if record.answerable is None:
            report.add(path, "answerability_required", "answerable must be set")
        if not record.reference_answer.strip():
            report.add(path, "reference_answer_required", "reference_answer must be non-empty")
    if record.answerable is True:
        if record.negative_stratum is not None:
            report.add(path, "answerable_negative_stratum", "answerable records cannot have a negative stratum")  # noqa: E501
        if not record.qrels:
            report.add(path, "qrels_required", "answerable records require exact-page qrels")
        elif not any(qrel.grade > 0 for qrel in record.qrels):
            report.add(path, "positive_qrel_required", "answerable records require at least one positive qrel")  # noqa: E501
        if not record.claims:
            report.add(path, "claims_required", "answerable records require atomic claims")
    elif record.answerable is False:
        if strict_draft and record.negative_stratum is None:
            report.add(path, "negative_stratum_required", "negative records require a negative stratum")  # noqa: E501
        if record.qrels:
            report.add(path, "off_corpus_qrels", "off-corpus records cannot have qrels")
        if record.claims or record.claim_evidence_links:
            report.add(path, "off_corpus_claims", "off-corpus records cannot assert corpus claims")
    if strict_draft:
        if record.difficulty is None:
            report.add(path, "difficulty_required", "locked records require difficulty")
        if record.answerable is not None and record.answerable is False and record.source_scope == "off_corpus":  # noqa: E501
            if record.negative_stratum != "out_of_scope":
                report.add(path, "off_corpus_stratum_mismatch", "off_corpus scope requires out_of_scope stratum")  # noqa: E501
    qrel_ids: set[str] = set()
    books = _book_map(manifest)
    for qrel_index, qrel in enumerate(record.qrels):
        qrel_path = f"{path}.qrels[{qrel_index}]"
        if not qrel.evidence_id.strip():
            report.add(qrel_path, "empty_evidence_id", "evidence_id must be non-empty")
        if qrel.evidence_id in qrel_ids:
            report.add(qrel_path, "duplicate_evidence_id", "evidence_id must be unique per question")  # noqa: E501
        qrel_ids.add(qrel.evidence_id)
        book = books.get(qrel.book_id)
        if book is None:
            report.add(qrel_path, "unknown_book", f"unknown source book {qrel.book_id!r}")
        elif qrel.page < 1 or qrel.page > book.page_count:
            report.add(qrel_path, "page_out_of_bounds", "qrel page is outside source PDF bounds")
        if qrel.grade not in {0, 1, 2, 3}:
            report.add(qrel_path, "invalid_grade", "qrel grade must be an integer from 0 to 3")
    for source_index, source in enumerate(record.source_metadata):
        source_path = f"{path}.source_metadata[{source_index}]"
        book = books.get(source.book_id)
        if book is None:
            report.add(source_path, "unknown_source_book", "source metadata references an unknown book")  # noqa: E501
        elif source.page_start < 1 or source.page_end < source.page_start or source.page_end > book.page_count:  # noqa: E501
            report.add(source_path, "source_pages_out_of_bounds", "source metadata page bounds are invalid")  # noqa: E501
    claim_ids: set[str] = set()
    for claim_index, claim in enumerate(record.claims):
        claim_path = f"{path}.claims[{claim_index}]"
        if not claim.claim_id.strip() or claim.claim_id in claim_ids:
            report.add(claim_path, "duplicate_claim_id", "claim_id must be unique and non-empty")
        claim_ids.add(claim.claim_id)
        if not claim.text.strip():
            report.add(claim_path, "empty_claim", "atomic claim text must be non-empty")
    links_seen: set[tuple[str, str]] = set()
    for link_index, link in enumerate(record.claim_evidence_links):
        link_path = f"{path}.claim_evidence_links[{link_index}]"
        key = (link.claim_id, link.evidence_id)
        if key in links_seen:
            report.add(link_path, "duplicate_claim_link", "claim-evidence links must be unique")
        links_seen.add(key)
        if link.claim_id not in claim_ids:
            report.add(link_path, "unknown_claim", "link references an unknown claim")
        if link.evidence_id not in qrel_ids:
            report.add(link_path, "unknown_evidence", "link references an unknown exact-page qrel")
        if link.relation not in {"supports", "contradicts"}:
            report.add(link_path, "invalid_relation", "relation must be supports or contradicts")
    if record.answerable is True:
        linked_claims = {link.claim_id for link in record.claim_evidence_links}
        if linked_claims != claim_ids:
            report.add(path, "claims_not_grounded", "every atomic claim must have a claim-evidence link")  # noqa: E501
        expected_books = {"single_book": 1, "pairwise": 2, "all_three": 3}.get(record.source_scope)
        if record.source_scope == "off_corpus":
            report.add(path, "answerable_off_corpus_scope", "answerable records cannot use off_corpus scope")  # noqa: E501
        if expected_books is not None and len(_record_source_books(record)) != expected_books:
            report.add(path, "source_scope_mismatch", "source_scope must match distinct qrel source-book count")  # noqa: E501
    elif record.answerable is False and strict_draft and record.source_scope != "off_corpus":
        expected_books = {"single_book": 1, "pairwise": 2, "all_three": 3}.get(record.source_scope)
        if expected_books is not None and len(_record_source_books(record)) != expected_books:
            report.add(path, "negative_scope_mismatch", "negative source_scope must match metadata source-book count")  # noqa: E501
    if record.content_sha256 is not None and record.content_sha256 != record_sha256(record):
        report.add(path, "content_hash_mismatch", "content_sha256 does not match canonical record")
    _validate_review_gate(record, report, path)


def validate_dataset(
    manifest: DatasetManifest,
    *,
    require_targets: bool = False,
    strict_draft: bool = False,
) -> ValidationReport:
    """Validate cross-record invariants and return machine-readable issues."""

    report = ValidationReport()
    if manifest.schema_version != "networking-pdfs-v2":
        report.add("schema_version", "unsupported_schema", "expected networking-pdfs-v2")
    if not manifest.source_books or len({book.book_id for book in manifest.source_books}) != len(manifest.source_books):  # noqa: E501
        report.add("source_books", "duplicate_or_missing_books", "source books must be present and uniquely identified")  # noqa: E501
    for book_index, book in enumerate(manifest.source_books):
        path = f"source_books[{book_index}]"
        if not re.fullmatch(r"[0-9a-f]{64}", book.sha256):
            report.add(path, "invalid_source_hash", "book sha256 must be lowercase hexadecimal SHA-256")  # noqa: E501
        if book.page_count < 1:
            report.add(path, "invalid_page_count", "page_count must be positive")
        chapter_ids: set[str] = set()
        for chapter in book.chapters:
            if chapter.chapter_id in chapter_ids:
                report.add(path, "duplicate_chapter_id", "chapter IDs must be unique per book")
            chapter_ids.add(chapter.chapter_id)
            if chapter.page_start < 1 or chapter.page_end < chapter.page_start or chapter.page_end > book.page_count:  # noqa: E501
                report.add(path, "invalid_chapter_pages", "chapter page bounds are invalid")
    ids: set[str] = set()
    questions: set[str] = set()
    clusters: dict[str, str] = {}
    counts: dict[Split, dict[QueryType, int]] = {"dev": {}, "locked": {}}
    answerability_counts: dict[Split, dict[str, int]] = {"dev": {}, "locked": {}}
    negative_counts: dict[Split, dict[NegativeStratum, int]] = {"dev": {}, "locked": {}}
    difficulty_counts: dict[Split, dict[Difficulty, int]] = {"dev": {}, "locked": {}}
    scope_counts: dict[Split, dict[SourceScope, int]] = {"dev": {}, "locked": {}}
    book_coverage: dict[Split, dict[str, int]] = {"dev": {}, "locked": {}}
    for index, record in enumerate(manifest.questions):
        _validate_record(record, manifest, report, index, strict_draft=strict_draft)
        if record.question_id in ids:
            report.add(f"questions[{index}]", "duplicate_question_id", "question_id must be globally unique")  # noqa: E501
        ids.add(record.question_id)
        normalized = _normalized_question(record.query)
        if normalized and normalized in questions:
            report.add(f"questions[{index}]", "duplicate_question", "normalized question text must be unique")  # noqa: E501
        if normalized:
            questions.add(normalized)
        previous_split = clusters.get(record.concept_cluster)
        if previous_split is not None and previous_split != record.split:
            report.add(f"questions[{index}]", "concept_cluster_leakage", "concept cluster may belong to only one split")  # noqa: E501
        clusters[record.concept_cluster] = record.split
        if record.query_type is not None:
            counts[record.split][record.query_type] = counts[record.split].get(record.query_type, 0) + 1  # noqa: E501
        if record.answerable is not None:
            answerability = "answerable" if record.answerable else "negative"
            answerability_counts[record.split][answerability] = (
                answerability_counts[record.split].get(answerability, 0) + 1
            )
        if record.negative_stratum is not None:
            negative_counts[record.split][record.negative_stratum] = (
                negative_counts[record.split].get(record.negative_stratum, 0) + 1
            )
        if record.difficulty is not None:
            difficulty_counts[record.split][record.difficulty] = (
                difficulty_counts[record.split].get(record.difficulty, 0) + 1
            )
        scope_counts[record.split][record.source_scope] = (
            scope_counts[record.split].get(record.source_scope, 0) + 1
        )
        for book_id in _record_source_books(record):
            book_coverage[record.split][book_id] = book_coverage[record.split].get(book_id, 0) + 1
    if require_targets:
        for split in ("locked", "dev"):
            targets = manifest.targets.get(split, {})
            for query_type in TAXONOMY:
                actual = counts[split].get(query_type, 0)
                expected = targets.get(query_type)
                if expected is not None and actual != expected:
                    report.add(
                        f"targets.{split}.{query_type}",
                        "taxonomy_imbalance",
                        f"expected {expected} records, found {actual}",
                    )
        expected_total = sum(manifest.targets.get("locked", {}).values()) + sum(
            manifest.targets.get("dev", {}).values()
        )
        if len(manifest.questions) != expected_total:
            report.add("questions", "target_count_mismatch", f"expected {expected_total} records")
    enforce_balance = require_targets and (strict_draft or manifest.status == "locked")
    if enforce_balance:
        splits: tuple[Split, ...] = ("locked", "dev")

        def exact_targets(
            name: str,
            split: Split,
            total: int,
            targets: Mapping[str, int],
            actual: Mapping[str, int],
            keys: Sequence[str],
        ) -> None:
            missing = [key for key in keys if key not in targets]
            if missing:
                report.add(
                    f"{name}.{split}",
                    "explicit_targets_required",
                    f"missing targets: {', '.join(missing)}",
                )
                return
            if sum(targets.values()) != total:
                report.add(
                    f"{name}.{split}",
                    "target_total_mismatch",
                    f"targets must sum to {total}",
                )
            for key in keys:
                if actual.get(key, 0) != targets[key]:
                    report.add(
                        f"{name}.{split}.{key}",
                        "balance_imbalance",
                        f"expected {targets[key]} records, found {actual.get(key, 0)}",
                    )

        for split in splits:
            total = sum(manifest.targets.get(split, {}).values())

            exact_targets(
                "answerability_targets",
                split,
                total,
                manifest.answerability_targets.get(split, {}),
                cast(Mapping[str, int], answerability_counts[split]),
                ("answerable", "negative"),
            )
            negative_targets = manifest.negative_strata_targets.get(split, {})
            if sum(negative_targets.values()) != manifest.answerability_targets.get(split, {}).get("negative", -1):  # noqa: E501
                report.add(
                    f"negative_strata_targets.{split}",
                    "negative_target_total_mismatch",
                    "negative strata targets must sum to the negative answerability target",
                )
            for stratum in NEGATIVE_STRATA:
                if stratum not in negative_targets:
                    report.add(
                        f"negative_strata_targets.{split}",
                        "explicit_targets_required",
                        f"missing target: {stratum}",
                    )
                elif negative_counts[split].get(stratum, 0) != negative_targets[stratum]:
                    report.add(
                        f"negative_strata_targets.{split}.{stratum}",
                        "balance_imbalance",
                        f"expected {negative_targets[stratum]} records, found {negative_counts[split].get(stratum, 0)}",  # noqa: E501
                    )
            exact_targets(
                "difficulty_targets",
                split,
                total,
                cast(Mapping[str, int], manifest.difficulty_targets.get(split, {})),
                cast(Mapping[str, int], difficulty_counts[split]),
                DIFFICULTIES,
            )
            exact_targets(
                "source_scope_targets",
                split,
                total,
                cast(Mapping[str, int], manifest.source_scope_targets.get(split, {})),
                cast(Mapping[str, int], scope_counts[split]),
                SOURCE_SCOPES,
            )
            if split == "locked":
                coverage_targets = manifest.book_coverage_targets.get("locked", {})
                for book in manifest.source_books:
                    expected = coverage_targets.get(book.book_id)
                    if expected is None or expected < 1:
                        report.add(
                            f"book_coverage_targets.locked.{book.book_id}",
                            "book_coverage_target_required",
                            "every locked source book needs a positive predeclared coverage target",
                        )
                    elif book_coverage[split].get(book.book_id, 0) < expected:
                        report.add(
                            f"book_coverage_targets.locked.{book.book_id}",
                            "book_coverage_insufficient",
                            f"expected at least {expected} records, found {book_coverage[split].get(book.book_id, 0)}",  # noqa: E501
                        )
    if manifest.dataset_sha256 is not None and manifest.dataset_sha256 != dataset_sha256(manifest):
        report.add("dataset_sha256", "dataset_hash_mismatch", "dataset_sha256 does not match canonical manifest")  # noqa: E501
    if manifest.status == "locked":
        if manifest.dataset_sha256 is None:
            report.add("dataset_sha256", "dataset_hash_required", "locked datasets require dataset_sha256")  # noqa: E501
        if not manifest.questions:
            report.add("status", "empty_locked_dataset", "locked dataset cannot be empty")
        for index, record in enumerate(manifest.questions):
            if record.status != "locked":
                report.add(f"questions[{index}]", "record_not_locked", "locked manifest requires locked records")  # noqa: E501
            if record.content_sha256 is None:
                report.add(f"questions[{index}]", "content_hash_required", "locked records require content_sha256")  # noqa: E501
        if any(record.status == "draft_unverified" for record in manifest.questions):
            report.add("status", "draft_in_locked_dataset", "locked manifest cannot contain draft records")  # noqa: E501
        if not require_targets:
            report.add("status", "targets_required_for_lock", "locked validation must require taxonomy targets")  # noqa: E501
    return report


def _as_chapter(raw: Mapping[str, Any]) -> ChapterMetadata:
    return ChapterMetadata(
        chapter_id=str(raw["chapter_id"]),
        title=str(raw["title"]),
        page_start=int(raw["page_start"]),
        page_end=int(raw["page_end"]),
        concept_cluster=str(raw["concept_cluster"]),
    )


def load_book_metadata(path: Path) -> list[BookMetadata]:
    """Load only structural metadata from JSON; reject any text fields."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("book metadata must be a JSON array")
    books: list[BookMetadata] = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("each book metadata item must be an object")
        chapters_raw = raw.get("chapters", [])
        if not isinstance(chapters_raw, list):
            raise ValueError("chapters must be an array")
        books.append(
            BookMetadata(
                book_id=str(raw["book_id"]),
                title=str(raw["title"]),
                sha256=str(raw["sha256"]),
                page_count=int(raw["page_count"]),
                chapters=tuple(_as_chapter(chapter) for chapter in chapters_raw),
            )
        )
    return books


def build_candidate_manifest(
    books: Sequence[BookMetadata],
    *,
    locked_count: int = 360,
    dev_count: int = 60,
    query_types: Sequence[QueryType] = TAXONOMY,
) -> DatasetManifest:
    """Create blank candidates from chapter metadata only.

    Each source concept cluster is assigned to one split before candidates are
    emitted, preventing train/dev leakage.  There must be enough distinct
    chapter clusters to satisfy the requested counts; the builder never
    invents a cluster or a question to fill a quota.
    """

    if locked_count < 0 or dev_count < 0:
        raise ValueError("candidate counts must be non-negative")
    if len(books) != 3 or len({book.book_id for book in books}) != 3:
        raise ValueError(
            "networking-pdfs-v2 requires exactly three uniquely identified source books"
        )
    if not query_types or any(query_type not in TAXONOMY for query_type in query_types):
        raise ValueError("query_types must use the v2 taxonomy")
    rows: list[tuple[BookMetadata, ChapterMetadata]] = [
        (book, chapter) for book in books for chapter in book.chapters
    ]
    if len({chapter.concept_cluster for _, chapter in rows}) < 2 and locked_count and dev_count:
        raise ValueError("at least two distinct concept clusters are needed for split isolation")
    if not rows and locked_count + dev_count:
        raise ValueError("book metadata has no chapters")
    # Assign whole clusters to a split using deterministic round-robin, then
    # cycle within each split.  This uses no source text and is reproducible.
    cluster_rows: dict[str, tuple[BookMetadata, ChapterMetadata]] = {}
    for book, chapter in rows:
        cluster_rows.setdefault(chapter.concept_cluster, (book, chapter))
    ordered_clusters = sorted(cluster_rows)
    dev_clusters = {cluster for index, cluster in enumerate(ordered_clusters) if index % 2 == 0}
    split_rows: dict[Split, list[tuple[BookMetadata, ChapterMetadata]]] = {
        "dev": [cluster_rows[c] for c in ordered_clusters if c in dev_clusters],
        "locked": [cluster_rows[c] for c in ordered_clusters if c not in dev_clusters],
    }
    split_counts: tuple[tuple[Split, int], ...] = (("dev", dev_count), ("locked", locked_count))
    for split, count in split_counts:
        if count and not split_rows[split]:
            raise ValueError(f"metadata does not provide a concept cluster for {split}")
    targets: dict[Split, dict[QueryType, int]] = {"dev": {}, "locked": {}}
    for split, count in split_counts:
        base, remainder = divmod(count, len(query_types))
        for index, query_type in enumerate(query_types):
            targets[split][query_type] = base + (1 if index < remainder else 0)
    questions: list[QuestionRecord] = []
    sequence = 1
    for split, count in split_counts:
        available = split_rows[split]
        for offset in range(count):
            book, chapter = available[offset % len(available)]
            query_type = query_types[offset % len(query_types)]
            questions.append(
                QuestionRecord(
                    question_id=f"npv2-{split}-{sequence:04d}",
                    split=split,
                    query_type=query_type,
                    concept_cluster=chapter.concept_cluster,
                    source_metadata=[
                        SourceMetadataRef(
                            book_id=book.book_id,
                            chapter_id=chapter.chapter_id,
                            chapter_title=chapter.title,
                            page_start=chapter.page_start,
                            page_end=chapter.page_end,
                            concept_cluster=chapter.concept_cluster,
                        )
                    ],
                    status="draft_unverified",
                )
            )
            sequence += 1
    coverage_target = {
        split: {
            book.book_id: max(1, count // len(books)) if count else 0
            for book in books
        }
        for split, count in split_counts
    }
    manifest = DatasetManifest(
        source_books=list(books),
        questions=questions,
        targets=targets,
        book_coverage_targets=coverage_target,
    )
    manifest.dataset_sha256 = dataset_sha256(manifest)
    return manifest


def manifest_to_dict(manifest: DatasetManifest) -> dict[str, Any]:
    return cast(dict[str, Any], _canonical(manifest))


def _qrel_from_dict(raw: Mapping[str, Any]) -> Qrel:
    return Qrel(
        evidence_id=str(raw["evidence_id"]),
        book_id=str(raw["book_id"]),
        page=int(raw["page"]),
        grade=int(raw["grade"]),
    )


def _record_from_dict(raw: Mapping[str, Any]) -> QuestionRecord:
    claims = [AtomicClaim(str(item["claim_id"]), str(item["text"])) for item in raw.get("claims", [])]  # noqa: E501
    links = [
        ClaimEvidenceLink(
            claim_id=str(item["claim_id"]),
            evidence_id=str(item["evidence_id"]),
            relation=cast(Literal["supports", "contradicts"], str(item.get("relation", "supports"))),  # noqa: E501
        )
        for item in raw.get("claim_evidence_links", [])
    ]
    qrels = [_qrel_from_dict(item) for item in raw.get("qrels", [])]
    sources = [SourceMetadataRef(**cast(dict[str, Any], item)) for item in raw.get("source_metadata", [])]  # noqa: E501
    reviews = [Review(**cast(dict[str, Any], item)) for item in raw.get("reviews", [])]
    adjudication_raw = raw.get("adjudication")
    adjudication = Adjudication(**cast(dict[str, Any], adjudication_raw)) if adjudication_raw else None  # noqa: E501
    return QuestionRecord(
        question_id=str(raw["question_id"]),
        split=cast(Split, str(raw["split"])),
        query_type=cast(QueryType | None, raw.get("query_type")),
        concept_cluster=str(raw["concept_cluster"]),
        query=str(raw.get("query", "")),
        alternatives=[str(item) for item in raw.get("alternatives", [])],
        answerable=cast(bool | None, raw.get("answerable")),
        negative_stratum=cast(NegativeStratum | None, raw.get("negative_stratum")),
        difficulty=cast(Difficulty | None, raw.get("difficulty")),
        source_scope=cast(SourceScope, str(raw.get("source_scope", "single_book"))),
        reference_answer=str(raw.get("reference_answer", "")),
        claims=claims,
        claim_evidence_links=links,
        qrels=qrels,
        source_metadata=sources,
        status=cast(Status, str(raw.get("status", "draft_unverified"))),
        reviews=reviews,
        adjudication=adjudication,
        content_sha256=cast(str | None, raw.get("content_sha256")),
    )


def manifest_from_dict(raw: Mapping[str, Any]) -> DatasetManifest:
    """Parse a JSON-compatible manifest into the typed schema."""

    books: list[BookMetadata] = []
    for item in raw.get("source_books", []):
        item_map = cast(dict[str, Any], item)
        books.append(
            BookMetadata(
                book_id=str(item_map["book_id"]),
                title=str(item_map["title"]),
                sha256=str(item_map["sha256"]),
                page_count=int(item_map["page_count"]),
                chapters=tuple(_as_chapter(chapter) for chapter in item_map.get("chapters", [])),
            )
        )
    raw_targets = cast(Mapping[str, Any], raw.get("targets", {}))
    targets: dict[Split, dict[QueryType, int]] = {"dev": {}, "locked": {}}
    for split in ("dev", "locked"):
        targets[split] = {
            cast(QueryType, str(query_type)): int(value)
            for query_type, value in cast(Mapping[str, Any], raw_targets.get(split, {})).items()
        }
    def parse_nested(name: str) -> dict[Split, dict[str, int]]:
        raw_nested = cast(Mapping[str, Any], raw.get(name, {}))
        return {
            split: {
                str(key): int(value)
                for key, value in cast(Mapping[str, Any], raw_nested.get(split, {})).items()
            }
            for split in ("dev", "locked")
        }

    raw_book_targets = parse_nested("book_coverage_targets")
    return DatasetManifest(
        schema_version=str(raw.get("schema_version", "")),
        dataset_id=str(raw.get("dataset_id", "")),
        status=cast(Status, str(raw.get("status", "draft_unverified"))),
        source_books=books,
        questions=[_record_from_dict(item) for item in raw.get("questions", [])],
        targets=targets,
        answerability_targets=parse_nested("answerability_targets"),
        negative_strata_targets=cast(
            dict[Split, dict[NegativeStratum, int]], parse_nested("negative_strata_targets")
        ),
        difficulty_targets=cast(dict[Split, dict[Difficulty, int]], parse_nested("difficulty_targets")),  # noqa: E501
        source_scope_targets=cast(dict[Split, dict[SourceScope, int]], parse_nested("source_scope_targets")),  # noqa: E501
        book_coverage_targets=raw_book_targets,
        dataset_sha256=cast(str | None, raw.get("dataset_sha256")),
    )


def read_manifest(path: Path) -> DatasetManifest:
    """Read and parse a manifest; validation is an explicit caller decision."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest must be a JSON object")
    return manifest_from_dict(payload)


def lock_dataset(manifest: DatasetManifest) -> DatasetManifest:
    """Validate human review gates, then mark a dataset and records locked.

    This is the only convenience transition to ``locked``.  It refuses draft
    content, missing exact-page grounding, duplicate/leaking questions, and
    any record without two approving reviews plus approving adjudication.
    """

    copied_questions = deepcopy(manifest.questions)
    for record in copied_questions:
        # Validate the full lock gate before hashes are generated.  Using the
        # locked record status here makes adjudication mandatory during this
        # preflight without mutating the caller's draft object.
        record.status = "locked"
    candidate = DatasetManifest(
        schema_version=manifest.schema_version,
        dataset_id=manifest.dataset_id,
        status="adjudicated",
        source_books=list(manifest.source_books),
        questions=copied_questions,
        targets={split: dict(values) for split, values in manifest.targets.items()},
        answerability_targets={
            split: dict(values) for split, values in manifest.answerability_targets.items()
        },
        negative_strata_targets={
            split: dict(values) for split, values in manifest.negative_strata_targets.items()
        },
        difficulty_targets={split: dict(values) for split, values in manifest.difficulty_targets.items()},  # noqa: E501
        source_scope_targets={
            split: dict(values) for split, values in manifest.source_scope_targets.items()
        },
        book_coverage_targets={
            split: dict(values) for split, values in manifest.book_coverage_targets.items()
        },
    )
    report = validate_dataset(candidate, require_targets=True, strict_draft=True)
    report.raise_for_errors()
    candidate.status = "locked"
    for record in candidate.questions:
        record.status = "locked"
        record.content_sha256 = record_sha256(record)
    candidate.dataset_sha256 = dataset_sha256(candidate)
    return candidate


def write_manifest(manifest: DatasetManifest, path: Path) -> None:
    """Write a manifest without overwriting an existing artifact."""

    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    if manifest.status == "locked":
        report = validate_dataset(manifest, require_targets=True, strict_draft=True)
        report.raise_for_errors()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest_to_dict(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8")  # noqa: E501
