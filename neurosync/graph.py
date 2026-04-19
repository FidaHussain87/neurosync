"""Neo4j GraphStore — optional knowledge graph layer for NeuroSync.

Syncs SQLite data to Neo4j on demand. Install with: pip install neurosync[neo4j]
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from neurosync.config import NeuroSyncConfig

logger = logging.getLogger("neurosync.graph")

try:
    from neo4j import GraphDatabase  # type: ignore[import-untyped]

    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False

BATCH_SIZE = 500
SYNC_LIMIT = 100000

# ---------------------------------------------------------------------------
# Schema — constraints and indexes
# ---------------------------------------------------------------------------

_SCHEMA_STATEMENTS = [
    "CREATE CONSTRAINT session_id IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT episode_id IF NOT EXISTS FOR (e:Episode) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT theory_id IF NOT EXISTS FOR (t:Theory) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT concept_text IF NOT EXISTS FOR (c:Concept) REQUIRE c.text IS UNIQUE",
    "CREATE CONSTRAINT pattern_name IF NOT EXISTS FOR (p:StructuralPattern) REQUIRE p.name IS UNIQUE",
    "CREATE CONSTRAINT failure_id IF NOT EXISTS FOR (f:FailureRecord) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT contradiction_id IF NOT EXISTS FOR (c:Contradiction) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT user_knowledge_id IF NOT EXISTS FOR (u:UserKnowledge) REQUIRE u.id IS UNIQUE",
    "CREATE INDEX episode_type IF NOT EXISTS FOR (e:Episode) ON (e.event_type)",
    "CREATE INDEX theory_scope IF NOT EXISTS FOR (t:Theory) ON (t.scope)",
    "CREATE INDEX theory_active IF NOT EXISTS FOR (t:Theory) ON (t.active)",
    "CREATE INDEX session_project IF NOT EXISTS FOR (s:Session) ON (s.project)",
    "CREATE INDEX concept_projects IF NOT EXISTS FOR (c:Concept) ON (c.projects)",
]

# ---------------------------------------------------------------------------
# Pre-built queries
# ---------------------------------------------------------------------------

PREBUILT_QUERIES: dict[str, dict[str, str]] = {
    "theory_network": {
        "description": "All active theories and their relationships",
        "cypher": (
            "MATCH (t:Theory {active: true}) "
            "OPTIONAL MATCH (t)-[r:RELATED_TO|PARENT_OF|SUPERSEDED_BY]->(t2:Theory) "
            "RETURN t, r, t2"
        ),
    },
    "causal_chains": {
        "description": "All cause-effect chains with strength",
        "cypher": (
            "MATCH (c1:Concept)-[r:CAUSES]->(c2:Concept) "
            "RETURN c1.text AS cause, c2.text AS effect, "
            "r.strength AS strength, r.observation_count AS observations "
            "ORDER BY r.strength DESC"
        ),
    },
    "causal_chain_from": {
        "description": "Trace downstream effects from a concept (set $concept parameter)",
        "cypher": (
            "MATCH path = (c:Concept {text: $concept})-[:CAUSES*1..5]->(effect:Concept) "
            "RETURN [n IN nodes(path) | n.text] AS chain, "
            "length(path) AS depth "
            "ORDER BY depth"
        ),
    },
    "high_confidence_theories": {
        "description": "Theories with confidence > 0.7 and their structural patterns",
        "cypher": (
            "MATCH (t:Theory) WHERE t.confidence > 0.7 AND t.active = true "
            "OPTIONAL MATCH (t)-[:HAS_PATTERN]->(p:StructuralPattern) "
            "RETURN t.id AS id, t.content AS content, t.confidence AS confidence, "
            "collect(p.name) AS patterns "
            "ORDER BY t.confidence DESC"
        ),
    },
    "theory_hierarchy": {
        "description": "Parent-child tree structure of theories",
        "cypher": (
            "MATCH (parent:Theory)-[:PARENT_OF]->(child:Theory) "
            "WHERE parent.active = true "
            "RETURN parent.id AS parent_id, parent.content AS parent_content, "
            "child.id AS child_id, child.content AS child_content, "
            "parent.confidence AS parent_confidence"
        ),
    },
    "failure_hotspots": {
        "description": "Failures linked to episodes and sessions",
        "cypher": (
            "MATCH (f:FailureRecord)-[:FAILED_IN]->(e:Episode)<-[:CONTAINS]-(s:Session) "
            "RETURN f.what_failed AS failure, f.category AS category, "
            "f.severity AS severity, s.project AS project, "
            "f.occurrence_count AS occurrences "
            "ORDER BY f.occurrence_count DESC"
        ),
    },
    "pattern_clusters": {
        "description": "Structural patterns shared across entities",
        "cypher": (
            "MATCH (entity)-[:HAS_PATTERN]->(p:StructuralPattern) "
            "WITH p, collect(entity) AS entities, count(entity) AS entity_count "
            "WHERE entity_count > 1 "
            "RETURN p.name AS pattern, entity_count, "
            "[e IN entities | labels(e)[0] + ':' + coalesce(e.id, '')] AS entities "
            "ORDER BY entity_count DESC"
        ),
    },
    "project_timeline": {
        "description": "Sessions and episode counts per project",
        "cypher": (
            "MATCH (s:Session)-[:CONTAINS]->(e:Episode) "
            "RETURN s.project AS project, count(DISTINCT s) AS sessions, "
            "count(e) AS episodes, min(s.started_at) AS first_session, "
            "max(s.started_at) AS last_session "
            "ORDER BY sessions DESC"
        ),
    },
    "contradiction_analysis": {
        "description": "Theories with contradictions and their resolution status",
        "cypher": (
            "MATCH (c:Contradiction)-[:CONTRADICTS]->(t:Theory) "
            "OPTIONAL MATCH (c)-[:OBSERVED_IN]->(e:Episode) "
            "RETURN t.id AS theory_id, t.content AS theory_content, "
            "t.confidence AS confidence, c.description AS contradiction, "
            "c.resolved_at AS resolved, e.content AS episode_content "
            "ORDER BY t.confidence ASC"
        ),
    },
    "cross_project_patterns": {
        "description": "Patterns and theories spanning multiple projects",
        "cypher": (
            "MATCH (t:Theory)-[:EXTRACTED_FROM]->(e:Episode)<-[:CONTAINS]-(s:Session) "
            "WITH t, collect(DISTINCT s.project) AS projects "
            "WHERE size(projects) > 1 "
            "RETURN t.id AS theory_id, t.content AS content, "
            "t.confidence AS confidence, projects "
            "ORDER BY size(projects) DESC"
        ),
    },
    "knowledge_graph_overview": {
        "description": "Node and relationship counts by type",
        "cypher": (
            "CALL () { MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count } "
            "RETURN label, count ORDER BY count DESC"
        ),
    },
    "episode_to_theory_lineage": {
        "description": "How episodes consolidated into theories",
        "cypher": (
            "MATCH (t:Theory)-[:EXTRACTED_FROM]->(e:Episode)<-[:CONTAINS]-(s:Session) "
            "RETURN t.id AS theory_id, t.content AS theory, "
            "collect({episode: e.content, session: s.project, type: e.event_type}) AS sources "
            "ORDER BY size(sources) DESC LIMIT 20"
        ),
    },
}

# Write keywords that are blocked in user queries for safety
_WRITE_KEYWORDS = frozenset({"CREATE", "DELETE", "DETACH", "SET", "REMOVE", "MERGE", "DROP", "FOREACH"})


def _is_write_query(cypher: str) -> bool:
    """Check if a Cypher query contains write operations."""
    upper = cypher.upper()
    for kw in _WRITE_KEYWORDS:
        # Match keyword as a whole word (not part of another word)
        idx = 0
        while True:
            idx = upper.find(kw, idx)
            if idx == -1:
                break
            before_ok = idx == 0 or not upper[idx - 1].isalpha()
            after_ok = (idx + len(kw)) >= len(upper) or not upper[idx + len(kw)].isalpha()
            if before_ok and after_ok:
                return True
            idx += 1
    # Check for CALL ... IN TRANSACTIONS pattern
    return bool(re.search(r'\bCALL\b.*\bIN\s+TRANSACTIONS\b', upper))


class GraphStore:
    """Neo4j graph store for NeuroSync knowledge graph visualization.

    This is a read-from-SQLite, write-to-Neo4j sync layer. SQLite remains
    the source of truth. Neo4j is populated via explicit sync calls.
    """

    def __init__(self, config: NeuroSyncConfig) -> None:
        if not HAS_NEO4J:
            raise ImportError(
                "Neo4j driver not installed. Install with: pip install neurosync[neo4j]"
            )
        auth = (config.neo4j_user, config.neo4j_password) if config.neo4j_password else None
        self._driver = GraphDatabase.driver(config.neo4j_uri, auth=auth)
        self._database = config.neo4j_database or None
        # Verify connectivity
        self._driver.verify_connectivity()
        self._ensure_schema()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def close(self) -> None:
        """Close the Neo4j driver."""
        if self._driver:
            self._driver.close()

    def _ensure_schema(self) -> None:
        """Create constraints and indexes if they don't exist."""
        with self._driver.session(database=self._database) as session:
            for stmt in _SCHEMA_STATEMENTS:
                try:
                    session.run(stmt)
                except Exception as e:
                    logger.warning("Schema statement skipped: %s (%s)", stmt[:60], e)

    # ------------------------------------------------------------------
    # Sync — SQLite → Neo4j
    # ------------------------------------------------------------------

    def sync(self, db: Any, project: Optional[str] = None) -> dict[str, Any]:
        """Full idempotent sync from SQLite to Neo4j.

        Uses MERGE for all operations so re-running is safe.
        Returns a stats dict with counts of synced entities.
        """
        logger.info("Graph sync started (project=%s)", project)
        stats: dict[str, int] = {}

        # Pre-fetch shared data to avoid redundant queries
        if project:
            sessions = db.list_sessions(project=project, limit=SYNC_LIMIT)
            if len(sessions) >= SYNC_LIMIT:
                logger.warning("Sync limit reached for %s (%d items). Some data may be missing.", "sessions", SYNC_LIMIT)
            episodes = []
            for s in sessions:
                episodes.extend(db.list_episodes(session_id=s.id, limit=SYNC_LIMIT))
        else:
            sessions = db.list_sessions(limit=SYNC_LIMIT)
            if len(sessions) >= SYNC_LIMIT:
                logger.warning("Sync limit reached for %s (%d items). Some data may be missing.", "sessions", SYNC_LIMIT)
            episodes = db.list_episodes(limit=SYNC_LIMIT)
            if len(episodes) >= SYNC_LIMIT:
                logger.warning("Sync limit reached for %s (%d items). Some data may be missing.", "episodes", SYNC_LIMIT)

        theories = db.list_theories(active_only=False, project=project, limit=SYNC_LIMIT)
        if len(theories) >= SYNC_LIMIT:
            logger.warning("Sync limit reached for %s (%d items). Some data may be missing.", "theories", SYNC_LIMIT)

        contradictions = db.list_contradictions(limit=SYNC_LIMIT)
        if len(contradictions) >= SYNC_LIMIT:
            logger.warning("Sync limit reached for %s (%d items). Some data may be missing.", "contradictions", SYNC_LIMIT)

        causal_links = db.list_causal_links(project=project, limit=SYNC_LIMIT)
        if len(causal_links) >= SYNC_LIMIT:
            logger.warning("Sync limit reached for %s (%d items). Some data may be missing.", "causal_links", SYNC_LIMIT)
        causal_links_by_id = {link.id: link for link in causal_links}

        failure_records = db.list_failure_records(project=project, min_severity=1, limit=SYNC_LIMIT)
        if len(failure_records) >= SYNC_LIMIT:
            logger.warning("Sync limit reached for %s (%d items). Some data may be missing.", "failure_records", SYNC_LIMIT)

        entity_fingerprints = db.list_all_entity_fingerprints()

        # --- Nodes ---
        stats["sessions"] = self._sync_sessions(sessions)
        stats["episodes"] = self._sync_episodes(episodes)
        stats["theories"] = self._sync_theories(theories)
        stats["concepts"] = self._sync_concepts(causal_links)
        stats["structural_patterns"] = self._sync_structural_patterns(entity_fingerprints)
        stats["failure_records"] = self._sync_failure_records(failure_records)
        stats["contradictions"] = self._sync_contradictions(contradictions)
        stats["user_knowledge"] = self._sync_user_knowledge(db, project)

        # --- Relationships ---
        stats["rel_contains"] = self._sync_rel_contains(episodes)
        stats["rel_extracted_from"] = self._sync_rel_extracted_from(db)
        stats["rel_related_to"] = self._sync_rel_related_to(db)
        stats["rel_parent_of"] = self._sync_rel_parent_of(theories)
        stats["rel_superseded_by"] = self._sync_rel_superseded_by(theories)
        stats["rel_causes"] = self._sync_rel_causes(causal_links)
        stats["rel_evidences"] = self._sync_rel_evidences(db, causal_links_by_id=causal_links_by_id)
        stats["rel_contradicts"] = self._sync_rel_contradicts(contradictions)
        stats["rel_observed_in"] = self._sync_rel_observed_in(contradictions)
        stats["rel_failed_in"] = self._sync_rel_failed_in(failure_records)
        stats["rel_has_pattern"] = self._sync_rel_has_pattern(entity_fingerprints)

        # --- Cleanup stale data ---
        stats["cleaned"] = self._cleanup_stale(
            sessions=sessions, episodes=episodes, theories=theories, project=project,
        )

        logger.info("Graph sync completed: %s", stats)

        return {"synced": stats, "project_filter": project}

    def _run_batched(self, cypher: str, rows: list[dict], key: str = "batch") -> int:
        """Execute a Cypher statement in batches using UNWIND."""
        total = 0
        with self._driver.session(database=self._database) as session:
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                session.run(cypher, {key: batch})
                total += len(batch)
        return total

    # --- Node sync methods ---

    def _sync_sessions(self, sessions: list) -> int:
        if not sessions:
            return 0
        rows = [
            {
                "id": s.id,
                "project": s.project,
                "branch": s.branch,
                "started_at": s.started_at,
                "ended_at": s.ended_at or "",
                "duration_seconds": s.duration_seconds,
                "summary": s.summary,
            }
            for s in sessions
        ]
        cypher = (
            "UNWIND $batch AS row "
            "MERGE (s:Session {id: row.id}) "
            "SET s.project = row.project, s.branch = row.branch, "
            "s.started_at = row.started_at, s.ended_at = row.ended_at, "
            "s.duration_seconds = row.duration_seconds, s.summary = row.summary"
        )
        return self._run_batched(cypher, rows)

    def _sync_episodes(self, episodes: list) -> int:
        if not episodes:
            return 0
        rows = [
            {
                "id": e.id,
                "session_id": e.session_id,
                "timestamp": e.timestamp,
                "event_type": e.event_type,
                "content": e.content,
                "signal_weight": e.signal_weight,
                "consolidated": e.consolidated,
                "cause": e.cause,
                "effect": e.effect,
                "reasoning": e.reasoning,
                "quality_score": e.quality_score,
                "files_touched": e.files_touched if e.files_touched else [],
                "layers_touched": e.layers_touched if e.layers_touched else [],
            }
            for e in episodes
        ]
        cypher = (
            "UNWIND $batch AS row "
            "MERGE (e:Episode {id: row.id}) "
            "SET e.session_id = row.session_id, e.timestamp = row.timestamp, "
            "e.event_type = row.event_type, e.content = row.content, "
            "e.signal_weight = row.signal_weight, e.consolidated = row.consolidated, "
            "e.cause = row.cause, e.effect = row.effect, "
            "e.reasoning = row.reasoning, e.quality_score = row.quality_score, "
            "e.files_touched = row.files_touched, e.layers_touched = row.layers_touched"
        )
        return self._run_batched(cypher, rows)

    def _sync_theories(self, theories: list) -> int:
        if not theories:
            return 0
        rows = [
            {
                "id": t.id,
                "content": t.content,
                "scope": t.scope,
                "scope_qualifier": t.scope_qualifier,
                "confidence": t.confidence,
                "confirmation_count": t.confirmation_count,
                "contradiction_count": t.contradiction_count,
                "first_observed": t.first_observed,
                "last_confirmed": t.last_confirmed or "",
                "active": t.active,
                "validation_status": t.validation_status,
                "application_count": t.application_count,
                "hierarchy_depth": t.hierarchy_depth,
                "parent_theory_id": t.parent_theory_id or "",
                "superseded_by": t.superseded_by or "",
            }
            for t in theories
        ]
        cypher = (
            "UNWIND $batch AS row "
            "MERGE (t:Theory {id: row.id}) "
            "SET t.content = row.content, t.scope = row.scope, "
            "t.scope_qualifier = row.scope_qualifier, t.confidence = row.confidence, "
            "t.confirmation_count = row.confirmation_count, "
            "t.contradiction_count = row.contradiction_count, "
            "t.first_observed = row.first_observed, t.last_confirmed = row.last_confirmed, "
            "t.active = row.active, t.validation_status = row.validation_status, "
            "t.application_count = row.application_count, "
            "t.hierarchy_depth = row.hierarchy_depth"
        )
        return self._run_batched(cypher, rows)

    def _sync_concepts(self, causal_links: list) -> int:
        if not causal_links:
            return 0
        # Collect unique concepts from both cause and effect, tracking all projects
        concepts: dict[str, list[str]] = {}
        for link in causal_links:
            cause_norm = link.cause_text.strip().lower()
            effect_norm = link.effect_text.strip().lower()
            proj = link.project or ""
            if cause_norm:
                concepts.setdefault(cause_norm, [])
                if proj and proj not in concepts[cause_norm]:
                    concepts[cause_norm].append(proj)
            if effect_norm:
                concepts.setdefault(effect_norm, [])
                if proj and proj not in concepts[effect_norm]:
                    concepts[effect_norm].append(proj)
        rows = [{"text": text, "projects": projects} for text, projects in concepts.items()]
        if not rows:
            return 0
        cypher = (
            "UNWIND $batch AS row "
            "MERGE (c:Concept {text: row.text}) "
            "SET c.projects = row.projects"
        )
        return self._run_batched(cypher, rows)

    def _sync_structural_patterns(self, fps: list[dict[str, str]]) -> int:
        if not fps:
            return 0
        unique_patterns = list({fp["pattern"] for fp in fps})
        rows = [{"name": p} for p in unique_patterns]
        cypher = "UNWIND $batch AS row MERGE (p:StructuralPattern {name: row.name})"
        return self._run_batched(cypher, rows)

    def _sync_failure_records(self, records: list) -> int:
        if not records:
            return 0
        rows = [
            {
                "id": str(r.id),
                "what_failed": r.what_failed,
                "why_failed": r.why_failed,
                "what_worked": r.what_worked,
                "category": r.category,
                "project": r.project,
                "severity": r.severity,
                "occurrence_count": r.occurrence_count,
            }
            for r in records
        ]
        cypher = (
            "UNWIND $batch AS row "
            "MERGE (f:FailureRecord {id: row.id}) "
            "SET f.what_failed = row.what_failed, f.why_failed = row.why_failed, "
            "f.what_worked = row.what_worked, f.category = row.category, "
            "f.project = row.project, f.severity = row.severity, "
            "f.occurrence_count = row.occurrence_count"
        )
        return self._run_batched(cypher, rows)

    def _sync_contradictions(self, contradictions: list) -> int:
        if not contradictions:
            return 0
        rows = [
            {
                "id": str(c.id),
                "description": c.description,
                "resolution": c.resolution or "",
                "resolved_at": c.resolved_at or "",
                "created_at": c.created_at,
            }
            for c in contradictions
        ]
        cypher = (
            "UNWIND $batch AS row "
            "MERGE (c:Contradiction {id: row.id}) "
            "SET c.description = row.description, c.resolution = row.resolution, "
            "c.resolved_at = row.resolved_at, c.created_at = row.created_at"
        )
        return self._run_batched(cypher, rows)

    def _sync_user_knowledge(self, db: Any, project: Optional[str]) -> int:
        knowledge = db.list_user_knowledge(project=project)
        if not knowledge:
            return 0
        rows = [
            {
                "id": str(uk.id),
                "topic": uk.topic,
                "project": uk.project,
                "familiarity": uk.familiarity,
                "times_seen": uk.times_seen,
                "times_explained": uk.times_explained,
            }
            for uk in knowledge
        ]
        cypher = (
            "UNWIND $batch AS row "
            "MERGE (u:UserKnowledge {id: row.id}) "
            "SET u.topic = row.topic, u.project = row.project, "
            "u.familiarity = row.familiarity, u.times_seen = row.times_seen, "
            "u.times_explained = row.times_explained"
        )
        return self._run_batched(cypher, rows)

    # --- Relationship sync methods ---

    def _sync_rel_contains(self, episodes: list) -> int:
        if not episodes:
            return 0
        rows = [{"session_id": e.session_id, "episode_id": e.id} for e in episodes]
        cypher = (
            "UNWIND $batch AS row "
            "MATCH (s:Session {id: row.session_id}) "
            "MATCH (e:Episode {id: row.episode_id}) "
            "MERGE (s)-[:CONTAINS]->(e)"
        )
        return self._run_batched(cypher, rows)

    def _sync_rel_extracted_from(self, db: Any) -> int:
        te_rows = db.list_all_theory_episodes()
        if not te_rows:
            return 0
        cypher = (
            "UNWIND $batch AS row "
            "MATCH (t:Theory {id: row.theory_id}) "
            "MATCH (e:Episode {id: row.episode_id}) "
            "MERGE (t)-[:EXTRACTED_FROM]->(e)"
        )
        return self._run_batched(cypher, te_rows)

    def _sync_rel_related_to(self, db: Any) -> int:
        tr_rows = db.list_all_theory_relations()
        if not tr_rows:
            return 0
        cypher = (
            "UNWIND $batch AS row "
            "MATCH (t1:Theory {id: row.theory_id}) "
            "MATCH (t2:Theory {id: row.related_theory_id}) "
            "MERGE (t1)-[:RELATED_TO]->(t2)"
        )
        return self._run_batched(cypher, tr_rows)

    def _sync_rel_parent_of(self, theories: list) -> int:
        rows = [
            {"parent_id": t.parent_theory_id, "child_id": t.id}
            for t in theories
            if t.parent_theory_id
        ]
        if not rows:
            return 0
        cypher = (
            "UNWIND $batch AS row "
            "MATCH (parent:Theory {id: row.parent_id}) "
            "MATCH (child:Theory {id: row.child_id}) "
            "MERGE (parent)-[:PARENT_OF]->(child)"
        )
        return self._run_batched(cypher, rows)

    def _sync_rel_superseded_by(self, theories: list) -> int:
        rows = [
            {"old_id": t.id, "new_id": t.superseded_by}
            for t in theories
            if t.superseded_by
        ]
        if not rows:
            return 0
        cypher = (
            "UNWIND $batch AS row "
            "MATCH (old:Theory {id: row.old_id}) "
            "MATCH (new:Theory {id: row.new_id}) "
            "MERGE (old)-[:SUPERSEDED_BY]->(new)"
        )
        return self._run_batched(cypher, rows)

    def _sync_rel_causes(self, causal_links: list) -> int:
        if not causal_links:
            return 0
        rows = [
            {
                "cause": link.cause_text.strip().lower(),
                "effect": link.effect_text.strip().lower(),
                "mechanism": link.mechanism,
                "strength": link.strength,
                "observation_count": link.observation_count,
                "causal_link_id": link.id,
            }
            for link in causal_links
            if link.cause_text.strip() and link.effect_text.strip()
        ]
        if not rows:
            return 0
        cypher = (
            "UNWIND $batch AS row "
            "MATCH (c1:Concept {text: row.cause}) "
            "MATCH (c2:Concept {text: row.effect}) "
            "MERGE (c1)-[r:CAUSES]->(c2) "
            "SET r.mechanism = row.mechanism, r.strength = row.strength, "
            "r.observation_count = row.observation_count, "
            "r.causal_link_id = row.causal_link_id"
        )
        return self._run_batched(cypher, rows)

    def _sync_rel_evidences(self, db: Any, causal_links_by_id: Optional[dict] = None) -> int:
        cle_rows = db.list_all_causal_link_episodes()
        if not cle_rows:
            return 0
        # Batch load all causal links if not provided
        if causal_links_by_id is None:
            all_links = db.list_causal_links(limit=SYNC_LIMIT)
            causal_links_by_id = {link.id: link for link in all_links}
        rows = []
        for cle in cle_rows:
            link = causal_links_by_id.get(cle["causal_link_id"])
            if link and link.cause_text.strip():
                rows.append({
                    "episode_id": cle["episode_id"],
                    "concept_text": link.cause_text.strip().lower(),
                })
        if not rows:
            return 0
        cypher = (
            "UNWIND $batch AS row "
            "MATCH (e:Episode {id: row.episode_id}) "
            "MATCH (c:Concept {text: row.concept_text}) "
            "MERGE (e)-[:EVIDENCES]->(c)"
        )
        return self._run_batched(cypher, rows)

    def _sync_rel_contradicts(self, contradictions: list) -> int:
        rows = [
            {"contradiction_id": str(c.id), "theory_id": c.theory_id}
            for c in contradictions
            if c.theory_id
        ]
        if not rows:
            return 0
        cypher = (
            "UNWIND $batch AS row "
            "MATCH (c:Contradiction {id: row.contradiction_id}) "
            "MATCH (t:Theory {id: row.theory_id}) "
            "MERGE (c)-[:CONTRADICTS]->(t)"
        )
        return self._run_batched(cypher, rows)

    def _sync_rel_observed_in(self, contradictions: list) -> int:
        rows = [
            {"contradiction_id": str(c.id), "episode_id": c.episode_id}
            for c in contradictions
            if c.episode_id
        ]
        if not rows:
            return 0
        cypher = (
            "UNWIND $batch AS row "
            "MATCH (c:Contradiction {id: row.contradiction_id}) "
            "MATCH (e:Episode {id: row.episode_id}) "
            "MERGE (c)-[:OBSERVED_IN]->(e)"
        )
        return self._run_batched(cypher, rows)

    def _sync_rel_failed_in(self, records: list) -> int:
        rows = [
            {"failure_id": str(r.id), "episode_id": r.source_episode_id}
            for r in records
            if r.source_episode_id
        ]
        if not rows:
            return 0
        cypher = (
            "UNWIND $batch AS row "
            "MATCH (f:FailureRecord {id: row.failure_id}) "
            "MATCH (e:Episode {id: row.episode_id}) "
            "MERGE (f)-[:FAILED_IN]->(e)"
        )
        return self._run_batched(cypher, rows)

    def _sync_rel_has_pattern(self, fps: list[dict[str, str]]) -> int:
        if not fps:
            return 0
        # Group by entity type to use correct node labels
        episode_fps = [fp for fp in fps if fp["entity_type"] == "episode"]
        theory_fps = [fp for fp in fps if fp["entity_type"] == "theory"]
        total = 0
        if episode_fps:
            rows = [{"entity_id": fp["entity_id"], "pattern": fp["pattern"]} for fp in episode_fps]
            cypher = (
                "UNWIND $batch AS row "
                "MATCH (e:Episode {id: row.entity_id}) "
                "MATCH (p:StructuralPattern {name: row.pattern}) "
                "MERGE (e)-[:HAS_PATTERN]->(p)"
            )
            total += self._run_batched(cypher, rows)
        if theory_fps:
            rows = [{"entity_id": fp["entity_id"], "pattern": fp["pattern"]} for fp in theory_fps]
            cypher = (
                "UNWIND $batch AS row "
                "MATCH (t:Theory {id: row.entity_id}) "
                "MATCH (p:StructuralPattern {name: row.pattern}) "
                "MERGE (t)-[:HAS_PATTERN]->(p)"
            )
            total += self._run_batched(cypher, rows)
        return total

    # ------------------------------------------------------------------
    # Stale data cleanup
    # ------------------------------------------------------------------

    def _cleanup_stale(
        self,
        sessions: list,
        episodes: list,
        theories: list,
        project: Optional[str] = None,
    ) -> dict[str, int]:
        """Remove nodes from Neo4j that no longer exist in SQLite.

        Accepts pre-fetched data from sync() to avoid redundant queries.
        Uses execute_write for proper write-transaction routing and retry.
        """
        cleaned: dict[str, int] = {}

        session_ids = list({s.id for s in sessions})
        episode_ids = list({e.id for e in episodes})
        theory_ids = list({t.id for t in theories})

        with self._driver.session(database=self._database) as neo_session:
            # Delete stale sessions
            if project:
                def _del_sessions_proj(tx: Any) -> int:
                    result = tx.run(
                        "MATCH (s:Session {project: $project}) WHERE NOT s.id IN $ids "
                        "DETACH DELETE s RETURN count(s) AS deleted",
                        {"project": project, "ids": session_ids},
                    )
                    record = result.single()
                    return record["deleted"] if record else 0
                cleaned["sessions"] = neo_session.execute_write(_del_sessions_proj)
            else:
                def _del_sessions_all(tx: Any) -> int:
                    result = tx.run(
                        "MATCH (s:Session) WHERE NOT s.id IN $ids "
                        "DETACH DELETE s RETURN count(s) AS deleted",
                        {"ids": session_ids},
                    )
                    record = result.single()
                    return record["deleted"] if record else 0
                cleaned["sessions"] = neo_session.execute_write(_del_sessions_all)

            # Delete stale episodes
            if project:
                def _del_episodes_proj(tx: Any) -> int:
                    result = tx.run(
                        "MATCH (e:Episode) WHERE e.session_id IN $session_ids AND NOT e.id IN $ids "
                        "DETACH DELETE e RETURN count(e) AS deleted",
                        {"session_ids": session_ids, "ids": episode_ids},
                    )
                    record = result.single()
                    return record["deleted"] if record else 0
                cleaned["episodes"] = neo_session.execute_write(_del_episodes_proj)
            else:
                def _del_episodes_all(tx: Any) -> int:
                    result = tx.run(
                        "MATCH (e:Episode) WHERE NOT e.id IN $ids "
                        "DETACH DELETE e RETURN count(e) AS deleted",
                        {"ids": episode_ids},
                    )
                    record = result.single()
                    return record["deleted"] if record else 0
                cleaned["episodes"] = neo_session.execute_write(_del_episodes_all)

            # Delete stale theories
            if project:
                def _del_theories_proj(tx: Any) -> int:
                    result = tx.run(
                        "MATCH (t:Theory) WHERE t.scope_qualifier = $project AND NOT t.id IN $ids "
                        "DETACH DELETE t RETURN count(t) AS deleted",
                        {"project": project, "ids": theory_ids},
                    )
                    record = result.single()
                    return record["deleted"] if record else 0
                cleaned["theories"] = neo_session.execute_write(_del_theories_proj)
            else:
                def _del_theories_all(tx: Any) -> int:
                    result = tx.run(
                        "MATCH (t:Theory) WHERE NOT t.id IN $ids "
                        "DETACH DELETE t RETURN count(t) AS deleted",
                        {"ids": theory_ids},
                    )
                    record = result.single()
                    return record["deleted"] if record else 0
                cleaned["theories"] = neo_session.execute_write(_del_theories_all)

        return cleaned

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    def run_cypher(self, query: str, parameters: Optional[dict] = None) -> list[dict[str, Any]]:
        """Execute a read-only Cypher query and return results as list of dicts."""
        with self._driver.session(database=self._database) as session:
            result = session.execute_read(lambda tx: list(tx.run(query, parameters or {})))
            return [dict(record) for record in result]

    def get_prebuilt_queries(self) -> dict[str, dict[str, str]]:
        """Return the catalog of pre-built queries."""
        return dict(PREBUILT_QUERIES)

    # ------------------------------------------------------------------
    # Stats and maintenance
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return node and relationship counts by type."""
        node_counts = self.run_cypher(
            "CALL () { MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count } "
            "RETURN label, count ORDER BY count DESC"
        )
        rel_counts = self.run_cypher(
            "CALL () { MATCH ()-[r]->() RETURN type(r) AS type, count(r) AS count } "
            "RETURN type, count ORDER BY count DESC"
        )
        return {
            "nodes": {r["label"]: r["count"] for r in node_counts if r.get("label")},
            "relationships": {r["type"]: r["count"] for r in rel_counts if r.get("type")},
        }

    def reset(self) -> dict[str, str]:
        """Delete all nodes and relationships from the graph."""
        with self._driver.session(database=self._database) as session:
            session.run(
                "CALL () { MATCH (n) DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"
            )
        return {"message": "Graph cleared"}
