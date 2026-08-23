# Agent token-usage policy

Status: active for the remaining benchmark/publication work.

## Confirmed cause

The rapid Codex quota decline came primarily from spawning multiple agents
with the full, already-large conversation history. Each full-history fork
reprocessed that context, multiplying input-token usage. Repeated review turns
added further context replay. Shell tests and Docker runtime consume machine
resources, not Codex model quota; OpenAI benchmark calls are a separate API
cost recorded in benchmark artifacts.

## Enforced workflow

- Work in the root agent by default; do not launch additional agents for the
  remaining task.
- If a future user explicitly re-enables delegation, allow at most one bounded
  worker at a time.
- Never use a full-history fork. Use no inherited turns (preferred) or at most
  three recent turns, with a self-contained prompt naming exact files and
  acceptance checks.
- Stop a worker immediately after it returns its result. Do not keep recurring
  reviewer agents alive.
- Do not paste raw benchmark bodies, long logs, or whole manifests into agent
  prompts. Pass paths and concise invariants instead.
- Filter terminal output to the fields required for the current decision.
- Do not repeat provider-backed benchmarks when existing source-bound evidence
  is sufficient; fix analysis or documentation locally.

This policy changes agent orchestration only. It does not alter product code,
benchmark metrics, or the platform's quota accounting.
