# Data Flow

## Recording (Session End)

```
neurosync_record({events, session_summary})
  → Validate inputs (events ≤ 100, content ≤ 50K chars, files ≤ 50 per event)
  → Create/reuse Session (with TTL: auto-rotate after 2h)
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
  → Trigger non-blocking auto-consolidation (background thread)
  → Intelligence proactive warnings:
    → Check fatigue (session duration > threshold)
    → Append "proactive_warnings" array to response
```

## Recall (Session Start)

```
neurosync_recall({project, branch, context})
  → Validate inputs (context ≤ 10K chars)
  → Rotate session (end old, capture git delta)
  → RetrievalPipeline.recall():
    → Build query embedding
    → Search theories (ChromaDB, top 10)
    → Score: confidence / (1 + distance)
    → Winner-take-all: pick highest
    → Filter by UserModel familiarity (suppress >0.9)
    → Include parent context for hierarchical theories
    → Add 2-3 supporting theories
    → Discover cross-project theories (domain/craft from other projects)
    → Check for continuation episodes from prior sessions
    → Add recent episodes from same project
    → Format within token budget (default 500)
  → Track user exposure via UserModel
  → Refresh recalled theory retention via ForgettingEngine
  → Intelligence enrichment:
    → InsightSurfacer.select() → top 2 insights by relevance
    → Append to response as "insights" array
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
  → Gather unconsolidated episodes (up to 500)
  → Process in batches of 50 (caps memory, allows partial progress)
  → For each batch:
    → Cluster by semantic similarity (ChromaDB cosine <0.8)
    → For each cluster (2+ episodes):
      → Extract candidate theory (3 strategies):
        1. Causal merge: if episodes have cause/effect → "When X, then Y" rule
        2. TF-IDF keywords: for 3+ episodes → keyword extraction + representative
        3. Fallback: highest-weight episode content (truncated)
      → MDL prune: reject if theory length > 70% of cluster content
      → Check for existing matching theory
      → Confirm or create theory (initial confidence 0.5)
      → Save theory version snapshot for audit trail
  → Mark episodes as consolidated
  → Run ForgettingEngine pass:
    → Ebbinghaus retention curves prune low-retention episodes
    → Decay stale theories without recent confirmation
  → Auto-sync to Neo4j graph (if available)

Auto-consolidation (triggered by record/remember/correct):
  → Non-blocking: dispatched to background thread
  → Previous result returned immediately; new run starts async
  → Only triggers when pending episodes ≥ threshold (default 20)
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

## Intelligence Layer (Background)

```
IntelligenceEngine (daemon thread, checks every 60s)
  → For each registered analyzer:
    → Check if interval has elapsed (WorkPatterns: 1h, FileNetwork: 2h)
    → If due: run analyze(db, vs)
      → WorkPatternAnalyzer:
        → Mine episode timestamps for hour-of-day quality (weighted: signal_weight × quality_score)
        → Detect peak hours (hours with > mean + 0.3σ quality)
        → Compute session rhythm (median duration, fatigue rate via linear regression)
        → Find day-of-week correction patterns (correction_rate per weekday)
        → Store insights + update developer_profile
      → FileNetworkAnalyzer:
        → Parse files_touched from episodes (JSON arrays)
        → Compute file pair co-occurrence (Jaccard index ≥ 0.3, min 3 co-occurrences)
        → Compute per-file volatility (weighted by event_type: correction=3, debugging=2)
        → Identify hotspots (score > mean + 1σ, min 3 total touches)
        → Store insights
    → Upsert insights to DB (stable IDs, idempotent)
    → Record last_run timestamp (thread-safe)

InsightSurfacer (called during MCP responses, <10ms):
  → Query insights table (confidence ≥ 0.4, not dismissed, limit 20)
  → Filter already-surfaced this session
  → Score: confidence × recency_factor × novelty_factor × context_factor
    → recency: 1.0 − (days_since_updated / 30), min 0.3
    → novelty: 1.0 / (1 + surfaced_count)
    → context: 1.5 if project matches, 0.8 if different project
  → Return top 2 (for recall) or top 1 warning (for record)
  → Increment surfaced_count in DB
```

## Theory Versioning

```
Theory mutation (confirm, contradict, supersede, retire)
  → save_theory_version():
    → Snapshot current state (content, confidence, counts, scope, active)
    → Assign version_number (max + 1)
    → Store in theory_versions table
  → Then apply the mutation to the theory

Rollback:
  → neurosync_theories action=rollback theory_id=... version_number=N
  → Load version N from theory_versions
  → Overwrite theory fields from snapshot
  → Update ChromaDB (add if active, remove if inactive)
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
