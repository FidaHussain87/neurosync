# NeuroSync — Agent Protocol

NeuroSync is a 9-layer developer memory MCP server. Most behavior is automatic. Follow these rules exactly.

## Rules

### Rule 1: Recall at session start
Call `neurosync_recall` before any work. Apply recalled theories as ground truth — confirmed lessons, not suggestions. Check for continuation episodes and resume unfinished work.

### Rule 2: Record corrections immediately
Call `neurosync_correct` the moment you realize something was wrong. Corrections compound (2^N weight). Pass `theory_id` to directly contradict an existing theory (−0.15 confidence).

### Rule 3: Query before guessing
Call `neurosync_query` before researching externally or answering uncertainly.
- `semantic` — general lookup (default)
- `failures` — known anti-patterns before suggesting an approach
- `causal` — trace cause/effect when debugging
- `analogy` — structurally similar past situations

### Rule 4: Remember discoveries mid-session
Call `neurosync_remember` (without being asked) when: you didn't know something, a user preference is revealed, or an environment constraint is discovered. Always include `reasoning` and `importance` (1–5).

### Rule 5: Record at session end
Call `neurosync_record` with causal statements — include `cause`, `effect`, `reasoning`. Use `importance` (1–5), `files`, `layers`. Call `neurosync_handoff` if work is unfinished.

### Rule 6: Consult theories before design decisions
Call `neurosync_theories action=list` before significant decisions. Follow existing theories or record a correction if contradicting one.

## Tools

| Tool | When |
|------|------|
| `neurosync_recall` | Session start — load memory |
| `neurosync_correct` | Immediately on any correction (2^N weight) |
| `neurosync_query` | Before guessing or researching |
| `neurosync_remember` | Mid-session discovery / preference / constraint (10x weight) |
| `neurosync_record` | Session end — structured episodes with causal language |
| `neurosync_handoff` | Unfinished work at session end |
| `neurosync_theories` | Before design decisions |
| `neurosync_poll` | Periodically during long sessions — warnings + fatigue signals |
| `neurosync_insights` | Developer intelligence — peak hours, file hotspots, learning velocity |
| `neurosync_status` | Health check |
| `neurosync_consolidate` | Rarely — auto-consolidation handles this |
| `neurosync_graph` | Neo4j knowledge graph (optional) |

## Signal weights (episode value multipliers)

| Signal | Multiplier | Trigger |
|--------|-----------|---------|
| CORRECTION | 2^N | Correction (N = count this session) |
| EXPLICIT | ×10 | `neurosync_remember` called |
| REPETITION | ×5 | Re-explained from a past session |
| SURPRISE | ×3 | Contradicts an existing theory |
| INTUITION | importance × 0.4 | `importance` field set 1–5 |
| DEPTH | N layers | `layers` array spans N architecture layers |
| PASSIVE | ×0.3 | Auto-observed git events |

**Maximise episode value**: causal language + file references + `importance` + `layers`.

## What is automatic (no action needed)

- Auto-consolidation into theories when episodes reach threshold
- Confidence lifecycle: +0.1 on confirmation, −0.15 on contradiction, −0.01/day decay, auto-retire < 0.05
- Domain classification (32 domains, cross-project transfer)
- Cognitive Replay capture and surfacing (debugging chain → "skip to step N" advice)
- Cognitive Lensing Protocol: theories compressed to ~80-token imperative lens set per recall
- Intelligence layer: peak hours, fatigue, file co-occurrence, learning velocity (background, zero LLM cost)
- Self-learning feedback loop (Layer 9): Bayesian usefulness scoring, greedy knapsack token packing, imperative distillation — recall budget shrinks as memory quality improves
- Topological Knowledge Health: β₀/β₁ Betti numbers, articulation points, health score 0–100 in `neurosync_status`
- Reflexive Calibration Network: per-domain accuracy tracking, isotonic regression, hazard rates, metacognitive warnings
- Ebbinghaus forgetting pass, user familiarity filtering, passive git observation

## Development

```bash
pip install -e ".[dev]"
pytest --cov=neurosync -v
ruff check neurosync/
python -m neurosync.mcp_server   # run MCP server
neurosync status
```

Full architecture reference: `docs/architecture.md`
