# `networking-pdfs-v2` dataset contract

This is the dataset-generation contract for the professional networking RAG
benchmark: 360 locked questions and 60 development questions over the three
networking books. It is a review protocol, not a generated gold set. The
builder creates only blank work items from safe PDF metadata (book hash,
page-count, chapter title/id, and page bounds). It never reads PDF text,
copies textbook prose, invents questions, or calls an LLM/embedding provider.

## Candidate plan

1. A curator supplies one structural metadata file for the three PDFs. Each
   chapter entry has a stable `chapter_id`, title, physical page bounds, and a
   concept-cluster identifier.
2. The builder assigns whole concept clusters to `dev` or `locked` by a stable
   round-robin partition. A cluster is never emitted in both splits.
3. It emits 360 locked and 60 dev work items, cycling through six balanced
   query types: `definition`, `comparison`, `procedure`, `troubleshooting`,
   `design`, and `calculation`. For the default target this is 60 of each type
   in locked and 10 of each type in dev.
4. The locked target is exactly 240 answerable and 120 negative records; dev
   is 40 answerable and 20 negative. The 120 locked negatives are stratified
   evenly across `out_of_scope`, `insufficient_evidence`, `false_premise`, and
   `ambiguous` (30 each; dev has 5 each).
5. Difficulty is predeclared as easy/medium/hard with locked 120/150/90 and
   dev 20/25/15. Source scope is explicit: locked has 240 single-book, 60
   pairwise, 30 all-three, and 30 off-corpus records (dev 40/10/5/5).
   Pairwise and all-three synthesis questions must have exactly two or three
   distinct source books in their exact-page qrels.
6. Every locked source book has a predeclared minimum coverage target (120 in
   the default manifest). Coverage counts questions whose qrels include that
   book; all-three questions count toward all three books.
7. Every item starts with `status=draft_unverified`, empty question content,
   and a source metadata pointer. A human writes the question, exactly two
   alternatives, reference answer, atomic claims, and exact-page qrels.
5. Two distinct reviewers approve each item. A third human adjudicator records
   an approving adjudication. Only then can `lock_dataset` promote records and
   compute their content hashes. A locked manifest must pass all validators.

If the metadata does not contain enough distinct concept clusters to keep the
two splits isolated, the builder fails rather than reusing or fabricating a
cluster. Curators should provide section/chapter-level clusters sufficient for
the target counts.

## Required evidence protocol

For an answerable question, the reference answer is decomposed into atomic
claims. Every claim has one or more `claim_evidence_links`, and every link
points to a qrel with a single physical page and integer relevance grade 0--3.
No page ranges or unsupported claims are accepted. An off-corpus question is
explicitly `answerable=false`, has an abstention reference answer, and has no
qrels, claims, or claim-evidence links.

The validator checks:

- taxonomy counts and exact 360/60 targets;
- answerability balance, four negative strata, and difficulty balance;
- explicit single-book/pairwise/all-three/off-corpus scope and qrel book counts;
- predeclared minimum coverage for every locked source book;
- exactly two alternatives and a non-empty reference answer;
- atomic claim IDs and complete claim-to-qrel grounding;
- qrel book/page bounds and grades;
- answerability/off-corpus invariants;
- duplicate IDs and normalized question text;
- concept-cluster split leakage;
- source, record, and manifest SHA-256 hashes;
- distinct two-review approval and adjudication before locking.

## Local usage

```bash
PYTHONPATH=backend/src python backend/scripts/build_networking_pdfs_v2_candidates.py \
  --metadata metadata/networking-books-v2.json \
  --output artifacts/networking-pdfs-v2-draft.json
```

The command refuses to overwrite an existing output. It writes no PDF text.
After human review, load the JSON with `read_manifest`, run
`validate_dataset(..., require_targets=True, strict_draft=True)`, and call
`lock_dataset` only when every review gate is satisfied.
