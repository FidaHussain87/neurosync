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

## Neo4j Graph Sync

```
neurosync graph-sync
  → Read all Sessions, Episodes, Theories, Concepts,
    Contradictions, FailureRecords, StructuralPatterns,
    UserKnowledge from SQLite
  → MERGE into Neo4j nodes (idempotent, upsert)
  → Create relationships: CONTAINS, EXTRACTED_FROM, CAUSES,
    CONTRADICTS, OBSERVED_IN, PARENT_OF, HAS_PATTERN, etc.
  → Clean up stale nodes not present in SQLite
```

## Frontend Visualization

```
User opens frontend (localhost:5173)
  → Enters Neo4j credentials → Bolt WebSocket connection
  → Load Overview → Two parallel Cypher queries (Sessions+Episodes, Theories+relationships)
  → Nodes assigned to Louvain communities → Cluster view at zoom < 3x
  → Click node → expandNode() fetches 1-hop neighborhood → Merge into graph
  → Run pre-built/custom query → Full graph replacement with zoomToFit
  → Click node → Detail panel slides in (properties, connections, navigation)
```
