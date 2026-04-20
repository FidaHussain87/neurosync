# Data Flow

## Recording (Session End)

```
neurosync_record({events, session_summary})
  → Create/reuse Session
  → For each event:
    → Create Episode (SQLite/PostgreSQL)
    → Compute signal weights via compute_episode_signals():
      - CORRECTION (if correction_count > 0)
      - DEPTH (from layers_touched)
      - SURPRISE (if contradicts existing theory)
      - REPETITION (if times_explained > 1 via UserModel)
      - EXPLICIT (if event_type == "explicit")
      - INTUITION (if importance > 0)
      - PASSIVE (if event_type == "observed")
    → Save individual Signal records for audit trail
    → Embed in ChromaDB
  → For explicit_remember items:
    → Create Episode with EXPLICIT signal (weight x10)
  → Capture git delta → PASSIVE observed episodes (weight x0.3)
  → If corrections occurred: apply outcome-based confidence adjustment
    (only to theories whose content overlaps with correction topics)
```

## Recall (Session Start)

```
neurosync_recall({project, branch, context})
  → RetrievalPipeline.recall():
    → Build query embedding
    → Search theories (ChromaDB, top 10)
    → Score: confidence / (1 + distance)
    → Winner-take-all: pick highest
    → Filter by UserModel familiarity (suppress >0.9)
    → Include parent context for hierarchical theories
    → Add 2-3 supporting theories
    → Check for continuation episodes from prior sessions
    → Add recent episodes from same project
    → Format within token budget (default 500)
  → Track user exposure via UserModel
  → Refresh recalled theory retention via ForgettingEngine
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
  → Cluster by semantic similarity (ChromaDB cosine <0.8)
  → For each cluster (2+ episodes):
    → Extract candidate theory (3 strategies):
      1. Causal merge: if episodes have cause/effect → "When X, then Y" rule
      2. TF-IDF keywords: for 3+ episodes → keyword extraction + representative episode
      3. Fallback: highest-weight episode content (truncated)
    → MDL prune: reject if theory length > 70% of cluster content
    → Check for existing matching theory
    → Confirm or create theory (initial confidence 0.5)
  → Mark episodes as consolidated
  → Run ForgettingEngine pass:
    → Ebbinghaus retention curves prune low-retention episodes
    → Decay stale theories without recent confirmation
```

## Confidence Lifecycle

```
Theory created → confidence 0.5
  → Confirmed by consolidation → +0.1 * (1 - current) asymptotic
  → Contradicted → -0.15
  → Session corrections on related topics → outcome-based penalty (max -0.1)
  → Recalled and applied → retention refreshed via ForgettingEngine
  → Ebbinghaus decay: R = e^(-t/S) where S = base × weight × quality × 2^reinforcements
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
