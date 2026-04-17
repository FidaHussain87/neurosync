# NeuroSync Architecture

## Three-Layer Memory Model

NeuroSync models developer memory using three layers inspired by human neuroscience:

### Layer 1: Episodic Memory
- **What**: Raw events from coding sessions
- **Storage**: SQLite `episodes` table + ChromaDB `neurosync_episodes` collection
- **Lifecycle**: Created during sessions → consolidated into theories → decayed from vector store
- **Event types**: decision, discovery, correction, pattern, frustration, question, file_change, architecture, debugging, explicit

### Layer 2: Semantic Memory
- **What**: Consolidated patterns and theories extracted from episodes
- **Storage**: SQLite `theories` table + ChromaDB `neurosync_theories` collection
- **Lifecycle**: Created by consolidation → confirmed/contradicted → confidence decayed → retired
- **Scopes**: project (single project), domain (shared domain), craft (general practice)

### Layer 3: Working Memory
- **What**: Context-aware recall assembled from theories and recent episodes
- **Algorithm**: Winner-take-all activation with user knowledge filtering
- **Output**: Primary theory + 2-3 supporting theories + recent episodes, within token budget

## Data Flow

```
Session Events → record() → Episodes (SQLite + ChromaDB)
                                 ↓
                          consolidate() → Theories (SQLite + ChromaDB)
                                 ↓
                            recall() → Working Memory Context
```

## Signal Weighting

Episodes are weighted by importance signals:

| Signal | Formula | Purpose |
|--------|---------|---------|
| CORRECTION | 2^N | Mistakes accumulate exponentially |
| DEPTH | N layers | Cross-cutting changes matter more |
| SURPRISE | x3 | Contradictions to existing theories |
| REPETITION | x5 | Things re-explained from past sessions |
| DURATION | ratio | Time proportion on topic |
| EXPLICIT | x10 | User explicitly flagged importance |

Composite weight = product of all multipliers, capped at 1000.

## Consolidation Pipeline

1. Gather unconsolidated episodes (min 5)
2. Cluster by ChromaDB cosine similarity (<0.8 threshold)
3. Extract candidate theory from each cluster (2+ episodes)
4. MDL prune: reject high description_length/coverage ratio
5. Contradiction check against existing theories
6. Merge (confirm existing) or create new theory
7. Classify scope: project → domain → craft
8. Decay old episodes from ChromaDB
9. Apply confidence decay on stale theories

## Winner-Take-All Recall

1. Build context embedding from project + branch + user context
2. Query theory collection (top 10)
3. Score: `confidence / (1 + cosine_distance)`
4. Pick highest as primary, next 2-3 as supporting
5. Filter by user knowledge model (suppress familiar topics)
6. Add recent episodes within token budget
