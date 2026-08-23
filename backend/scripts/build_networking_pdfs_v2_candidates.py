#!/usr/bin/env python3
"""Emit networking-pdfs-v2 draft candidates from structural metadata only."""

from __future__ import annotations

import argparse
from pathlib import Path

from ragz.evals.networking_pdfs_v2 import (
    build_candidate_manifest,
    load_book_metadata,
    validate_dataset,
    write_manifest,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--locked-count", type=int, default=360)
    parser.add_argument("--dev-count", type=int, default=60)
    args = parser.parse_args()
    manifest = build_candidate_manifest(
        load_book_metadata(args.metadata.resolve()),
        locked_count=args.locked_count,
        dev_count=args.dev_count,
    )
    report = validate_dataset(manifest, require_targets=True)
    report.raise_for_errors()
    write_manifest(manifest, args.output)


if __name__ == "__main__":
    main()
