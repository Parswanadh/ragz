from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ragz.evals.networking_pdfs_v2 import (
    Adjudication,
    AtomicClaim,
    BookMetadata,
    ChapterMetadata,
    ClaimEvidenceLink,
    DatasetManifest,
    Qrel,
    Review,
    SourceMetadataRef,
    build_candidate_manifest,
    dataset_sha256,
    lock_dataset,
    manifest_from_dict,
    manifest_to_dict,
    record_sha256,
    validate_dataset,
    write_manifest,
)


def books() -> list[BookMetadata]:
    return [
        BookMetadata(
            book_id="book-a",
            title="A",
            sha256="a" * 64,
            page_count=100,
            chapters=(
                ChapterMetadata("a-1", "one", 1, 20, "cluster-a"),
                ChapterMetadata("a-2", "two", 21, 40, "cluster-b"),
            ),
        ),
        BookMetadata(
            book_id="book-b",
            title="B",
            sha256="b" * 64,
            page_count=100,
            chapters=(ChapterMetadata("b-1", "one", 1, 20, "cluster-c"),),
        ),
        BookMetadata(
            book_id="book-c",
            title="C",
            sha256="c" * 64,
            page_count=100,
            chapters=(ChapterMetadata("c-1", "one", 1, 20, "cluster-d"),),
        ),
    ]


def test_builder_emits_balanced_metadata_only_drafts() -> None:
    manifest = build_candidate_manifest(books(), locked_count=6, dev_count=6)

    assert manifest.status == "draft_unverified"
    assert len(manifest.questions) == 12
    assert all(record.status == "draft_unverified" for record in manifest.questions)
    assert all(record.query == "" for record in manifest.questions)
    assert all(not record.qrels for record in manifest.questions)
    assert manifest.targets["locked"] == {
        "definition": 1,
        "comparison": 1,
        "procedure": 1,
        "troubleshooting": 1,
        "design": 1,
        "calculation": 1,
    }
    report = validate_dataset(manifest, require_targets=True)
    assert report.valid, report.issues
    dev_clusters = {record.concept_cluster for record in manifest.questions if record.split == "dev"}  # noqa: E501
    locked_clusters = {record.concept_cluster for record in manifest.questions if record.split == "locked"}  # noqa: E501
    assert dev_clusters.isdisjoint(locked_clusters)


def test_builder_refuses_missing_split_cluster() -> None:
    only_one = [
        replace(
            book,
            chapters=tuple(
                replace(chapter, concept_cluster="single-cluster")
                for chapter in book.chapters
            ),
        )
        for book in books()
    ]
    with pytest.raises(ValueError, match="two distinct concept clusters"):
        build_candidate_manifest(only_one, locked_count=1, dev_count=1, query_types=("definition",))


def answerable_record(*, question_id: str = "q-1", split: str = "locked"):
    from ragz.evals.networking_pdfs_v2 import QuestionRecord

    return QuestionRecord(
        question_id=question_id,
        split=split,  # type: ignore[arg-type]
        query_type="definition",
        concept_cluster="cluster-a",
        query="What is the protocol role?",
        alternatives=["Which role?", "How does it differ?"],
        answerable=True,
        difficulty="easy",
        source_scope="all_three",
        reference_answer="The protocol performs the described role.",
        claims=[AtomicClaim("c-1", "The protocol performs the described role.")],
        claim_evidence_links=[ClaimEvidenceLink("c-1", "e-1")],
        qrels=[
            Qrel("e-1", "book-a", 10, 3),
            Qrel("e-2", "book-b", 10, 3),
            Qrel("e-3", "book-c", 10, 3),
        ],
        source_metadata=[
            SourceMetadataRef("book-a", "a-1", "one", 1, 20, "cluster-a"),
            SourceMetadataRef("book-b", "b-1", "one", 1, 20, "cluster-c"),
            SourceMetadataRef("book-c", "c-1", "one", 1, 20, "cluster-d"),
        ],
    )


def small_targets(*, answerable: int = 1, negative: int = 0) -> dict[str, dict]:
    return {
        "query": {"dev": {"definition": 0}, "locked": {"definition": answerable + negative}},
        "answerability": {
            "dev": {"answerable": 0, "negative": 0},
            "locked": {"answerable": answerable, "negative": negative},
        },
        "negative": {
            "dev": {stratum: 0 for stratum in ("out_of_scope", "insufficient_evidence", "false_premise", "ambiguous")},  # noqa: E501
            "locked": {stratum: 0 for stratum in ("out_of_scope", "insufficient_evidence", "false_premise", "ambiguous")},  # noqa: E501
        },
        "difficulty": {
            "dev": {"easy": 0, "medium": 0, "hard": 0},
            "locked": {"easy": answerable + negative, "medium": 0, "hard": 0},
        },
        "scope": {
            "dev": {"single_book": 0, "pairwise": 0, "all_three": 0, "off_corpus": 0},
            "locked": {"single_book": 0, "pairwise": 0, "all_three": answerable + negative, "off_corpus": 0},  # noqa: E501
        },
        "coverage": {
            "dev": {"book-a": 0, "book-b": 0, "book-c": 0},
            "locked": {"book-a": 1, "book-b": 1, "book-c": 1},
        },
    }


def manifest_with_small_targets(record, *, answerable: int = 1, negative: int = 0) -> DatasetManifest:  # noqa: E501
    targets = small_targets(answerable=answerable, negative=negative)
    return DatasetManifest(
        source_books=books(),
        questions=[record],
        targets=targets["query"],
        answerability_targets=targets["answerability"],
        negative_strata_targets=targets["negative"],
        difficulty_targets=targets["difficulty"],
        source_scope_targets=targets["scope"],
        book_coverage_targets=targets["coverage"],
    )


def test_validator_catches_grounding_and_exact_page_errors() -> None:
    record = answerable_record()
    record.qrels[0] = Qrel("e-1", "book-a", 101, 4)
    manifest = DatasetManifest(
        source_books=books(),
        questions=[record],
        targets={"dev": {"definition": 0}, "locked": {"definition": 1}},
    )
    report = validate_dataset(manifest, require_targets=True, strict_draft=True)
    codes = {issue.code for issue in report.errors}
    assert {"page_out_of_bounds", "invalid_grade"}.issubset(codes)


def test_duplicate_question_and_cluster_leakage_are_errors() -> None:
    first = answerable_record(question_id="same")
    second = answerable_record(question_id="same", split="dev")
    manifest = DatasetManifest(
        source_books=books(),
        questions=[first, second],
        targets={"dev": {"definition": 1}, "locked": {"definition": 1}},
    )
    report = validate_dataset(manifest, require_targets=True, strict_draft=True)
    codes = {issue.code for issue in report.errors}
    assert "duplicate_question_id" in codes
    assert "duplicate_question" in codes
    assert "concept_cluster_leakage" in codes


def test_lock_requires_two_reviews_and_adjudication() -> None:
    record = answerable_record()
    record.status = "adjudicated"
    manifest = manifest_with_small_targets(record)
    with pytest.raises(ValueError, match="two reviews"):
        lock_dataset(manifest)

    record.reviews = [
        Review("reviewer-a", "approve", "2026-08-23T00:00:00Z"),
        Review("reviewer-b", "approve", "2026-08-23T00:00:01Z"),
    ]
    record.adjudication = Adjudication("adjudicator", "approve", "2026-08-23T00:00:02Z")
    locked = lock_dataset(manifest)
    assert locked.status == "locked"
    assert locked.questions[0].status == "locked"
    assert locked.questions[0].content_sha256 == record_sha256(locked.questions[0])
    assert locked.dataset_sha256 == dataset_sha256(locked)
    assert validate_dataset(locked, require_targets=True, strict_draft=True).valid


def test_locked_write_refuses_missing_gate(tmp_path: Path) -> None:
    record = answerable_record()
    manifest = manifest_with_small_targets(record)
    manifest.status = "locked"
    with pytest.raises(ValueError, match="locked"):
        write_manifest(manifest, tmp_path / "locked.json")


def test_manifest_round_trip_is_canonical() -> None:
    manifest = build_candidate_manifest(books(), locked_count=2, dev_count=2, query_types=("definition",))  # noqa: E501
    round_tripped = manifest_from_dict(manifest_to_dict(manifest))
    assert manifest_to_dict(round_tripped) == manifest_to_dict(manifest)
    assert dataset_sha256(round_tripped) == dataset_sha256(manifest)


def test_lock_balance_rejects_answerability_imbalance() -> None:
    manifest = manifest_with_small_targets(answerable_record(), answerable=0, negative=1)
    report = validate_dataset(manifest, require_targets=True, strict_draft=True)
    codes = {issue.code for issue in report.errors}
    assert "balance_imbalance" in codes


def test_locked_balance_requires_explicit_book_coverage_targets() -> None:
    manifest = manifest_with_small_targets(answerable_record())
    manifest.book_coverage_targets["locked"].pop("book-c")
    report = validate_dataset(manifest, require_targets=True, strict_draft=True)
    assert any(issue.code == "book_coverage_target_required" for issue in report.errors)
