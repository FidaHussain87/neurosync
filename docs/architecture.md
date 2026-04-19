# NeuroSync Architecture

## Three-Layer Memory Model

NeuroSync models developer memory using three layers inspired by human neuroscience:

### Layer 1: Episodic Memory
- **What**: Raw events from coding sessions
- **Storage**: SQLite/PostgreSQL `episodes` table + ChromaDB `neurosync_episodes` collection
- **Lifecycle**: Created during sessions → consolidated into theories → decayed from vector store
- **Event types**: decision, discovery, correction, pattern, frustration, question, file_change, architecture, debugging, explicit

### Layer 2: Semantic Memory
- **What**: Consolidated patterns and theories extracted from episodes
- **Storage**: SQLite/PostgreSQL `theories` table + ChromaDB `neurosync_theories` collection
- **Lifecycle**: Created by consolidation → confirmed/contradicted → confidence decayed → retired
- **Scopes**: project (single project), domain (shared domain), craft (general practice)

### Layer 3: Working Memory
- **What**: Context-aware recall assembled from theories and recent episodes
- **Algorithm**: Winner-take-all activation via RetrievalPipeline with UserModel familiarity filtering
- **Output**: Primary theory + 2-3 supporting theories + recent episodes, within token budget

## Data Flow

```
Session Events → record() → Episodes (SQLite + ChromaDB)
                                 ↓
                          consolidate() → Theories (SQLite + ChromaDB)
                                 ↓
                            recall() → Working Memory Context
                                 ↓
                          graph-sync → Neo4j Knowledge Graph (optional)
                                 ↓
                           frontend → Interactive Visualization (optional)
```

## Neo4j Knowledge Graph (Optional)

SQLite data is synced to Neo4j on demand via `neurosync graph-sync`. Neo4j provides a connected graph representation of all memory entities (Sessions, Episodes, Theories, Concepts, Contradictions, Failures, Patterns, UserKnowledge) with relationships like CONTAINS, EXTRACTED_FROM, CAUSES, CONTRADICTS, and PARENT_OF.

## Frontend Visualization (Optional)

A standalone React + TypeScript web app (`frontend/`) connects directly to Neo4j via Bolt WebSocket and renders the knowledge graph using `react-force-graph-2d`. Features multi-layer parallax star field, space-time fabric curvature near massive nodes, mass-weighted gravitational physics, Louvain community detection for cluster view, progressive loading, and 12 pre-built Cypher queries.

## Database Backends

- **SQLite** (default) — WAL mode, thread-safe, zero setup. Source of truth for all data.
- **PostgreSQL** (optional) — Connection pooling via psycopg2, JSONB columns. Set `NEUROSYNC_DB_BACKEND=postgresql` and `NEUROSYNC_PG_DSN` to switch. Falls back to SQLite if unavailable.

## Signal Weighting

Episodes are weighted by importance signals (7 active, 1 defined but unwired):

| Signal | Formula | Purpose | Status |
|--------|---------|---------|--------|
| CORRECTION | 2^N | Mistakes accumulate exponentially | Active |
| DEPTH | N layers | Cross-cutting changes matter more | Active |
| SURPRISE | x3 | Contradictions to existing theories | Active |
| REPETITION | x5 | Things re-explained from past sessions | Active |
| EXPLICIT | x10 | User explicitly flagged importance | Active |
| INTUITION | importance x 0.4 | Agent rates episode importance 1-5 | Active |
| PASSIVE | x0.3 | Auto-observed events (git changes) | Active |
| DURATION | ratio x 2.0 | Time proportion spent on topic | Defined, unwired |

Composite weight = product of all multipliers, capped at 1000.

## Consolidation Pipeline

1. Gather unconsolidated episodes (min 5)
2. Cluster by ChromaDB cosine similarity (<0.8 threshold)
3. Extract candidate theory from each cluster (2+ episodes) using 3 strategies:
   - **Causal merge** — if cluster has episodes with cause/effect fields, merge into "When X, then Y" rule
   - **TF-IDF keyword extraction** — for clusters of 3+, extract shared vocabulary and pick representative episode
   - **Fallback** — use highest-weight episode as theory (truncated)
4. MDL prune: reject candidates where theory length > 70% of combined cluster content
5. Contradiction check against existing theories
6. Merge (confirm existing) or create new theory
7. Classify scope: project → domain → craft
8. Decay old episodes from ChromaDB
9. Run ForgettingEngine pass: Ebbinghaus retention curves prune low-value episodes and decay stale theories

## Winner-Take-All Recall (via RetrievalPipeline)

1. Build context embedding from project + branch + user context
2. Query theory collection (top 10)
3. Score: `confidence / (1 + cosine_distance)`
4. Pick highest as primary, next 2-3 as supporting
5. Filter by UserModel familiarity (suppress topics with familiarity > 0.9)
6. Include parent context for theories in a hierarchy
7. Check for continuation episodes from prior sessions
8. Add recent episodes within token budget
9. Track application of recalled theories for outcome-based confidence adjustment
