# Networking Single-Query vs Multi-Query Comparison Lab

## Corpus

The lab uses the three user-supplied networking textbooks below. PDF bytes are
read from local paths and are not committed to the repository.

| Book | PDF pages | Indexed chunks |
|---|---:|---:|
| Forouzan, *Data Communications and Networking with TCP/IP Protocol Suite* | 861 | 3,500 |
| Kurose and Ross, *Computer Networking: A Top-Down Approach* | 775 | 1,851 |
| Tanenbaum, Feamster and Wetherall, *Computer Networks* | 946 | 3,023 |
| **Total** | **2,582** | **8,374** |

The persistent lab seeder is
`backend/scripts/seed_networking_comparison_lab.py`. It requires exactly three
explicit PDF paths, `RAGZ_LAB_ADMIN_PASSWORD`, and `RAGZ_LAB_CHAT_API_KEY`; it
encrypts the model credential in PostgreSQL, never reads dotenv files, and never
prints credentials. `RAGZ_LAB_DATABASE_NAME` must exactly confirm a dedicated
`ragz_mq_lab*` database, the environment must be dev/test, and the database may
not contain another workspace. The lab creates dedicated model and collection
rows rather than modifying the fixed local embedding model. It uses local hash
dense vectors plus FastEmbed BM25 so indexing makes no hosted embedding calls.

## What the UI compares

Open the workspace gear, select **Evals**, enter a question, select the answer
model, and choose **Compare answers**. The result has three columns:

1. the fixed question and shared controls;
2. an answer using exactly one retrieval query;
3. an answer using the original plus up to two generated alternatives.

Each answer displays its citations, source pages, effective retrieval-query count,
retrieval/generation/total time, and token count. Both variants use the same
workspace, answer model, `top_k`, reranker setting, prompt and corpus. The endpoint
does not PATCH `Workspace.multi_query_enabled`, create temporary chats, use chat
history, invoke the agent, or use web search.

The API is:

```http
POST /api/v1/workspaces/{workspace_id}/evals/compare
Content-Type: application/json

{"question": "...", "model_id": "..."}
```

It requires `evals.run`, is limited to ten comparisons per user per minute, and
records incurred expansion, embedding, reranking and answer-generation usage. A
comparison normally costs two answer generations plus one utility-model expansion.
Generated alternative-query text is never returned or logged.

## Verified live example

Question:

> Why can a high-bandwidth, long-delay TCP path underuse the link unless its
> receive window is enlarged?

The verified local run returned one query for the control and three for the
multi-query variant. Multi-query retrieved Tanenbaum PDF page 627—the directly
annotated bandwidth-delay/window support page—while the control's top five did not.
The screenshot in
`docs/benchmarks/artifacts/2026-08-21-networking-comparison-ui.png` shows the
completed three-column result.

This is a manual qualitative comparison, not an additional scored benchmark cell.
The answer model and live expansion add provider latency and cost, while the larger
retrieval benchmark remains the fixed-alternative synthetic fusion pilot documented
in `2026-08-21-networking-multi-query-results.md`.
