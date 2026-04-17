# Data Flow

## Recording (Session End)

```
neurosync_record({events, session_summary})
  → Create/reuse Session
  → For each event:
    → Create Episode (SQLite)
    → Compute signal weight
    → Embed in ChromaDB
  → For explicit_remember items:
    → Create Episode with EXPLICIT signal (weight x10)
```

## Recall (Session Start)

```
neurosync_recall({project, branch, context})
  → Build query embedding
  → Search theories (ChromaDB, top 10)
  → Score: confidence / (1 + distance)
  → Winner-take-all: pick highest
  → Filter by user familiarity (suppress >0.9)
  → Add 2-3 supporting theories
  → Add recent episodes from same project
  → Format within token budget (default 500)
```

## Correction

```
neurosync_correct({wrong, right, theory_id?})
  → Increment session correction counter
  → Create correction episode (weight = 2^N)
  → If theory_id: create Contradiction, reduce confidence
```

## Consolidation

```
neurosync_consolidate({project?, dry_run?})
  → Gather unconsolidated episodes
  → Cluster by semantic similarity
  → For each cluster (2+ episodes):
    → Extract candidate theory
    → MDL prune
    → Check for existing matching theory
    → Confirm or create theory
  → Mark episodes as consolidated
  → Apply confidence decay on stale theories
```

## Confidence Lifecycle

```
Theory created → confidence 0.5
  → Confirmed by consolidation → +0.1 * (1 - current) asymptotic
  → Contradicted → -0.15
  → No confirmation for 30+ days → -0.01/day
  → Confidence ≤ 0.05 → auto-retired
  → Manually retired → active = false
```
