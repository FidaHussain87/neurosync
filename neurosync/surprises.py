"""Knowledge Surprise Detection — finds unexpected connections in memory.

Adapted from Graphify's surprise analysis. Identifies theories that are
unexpectedly connected across domains, projects, or layers, and generates
actionable research questions from graph structure.

Zero LLM cost — pure local graph analysis.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from neurosync.logging import get_logger
from neurosync.models import Theory

logger = get_logger("surprises")


@dataclass
class SurprisingConnection:
    """An unexpected link between two theories."""

    theory_a_id: str
    theory_a_content: str
    theory_b_id: str
    theory_b_content: str
    surprise_score: float
    reasons: list[str] = field(default_factory=list)
    connection_type: str = ""  # cross-domain, cross-project, bridge, etc.


@dataclass
class SuggestedQuestion:
    """An auto-generated research question from graph structure."""

    question: str
    question_type: str  # ambiguous_link, bridge_node, knowledge_gap, weak_theory, isolated
    why: str
    related_theories: list[str] = field(default_factory=list)


@dataclass
class GodTheory:
    """A highly-connected theory that many other theories depend on."""

    theory_id: str
    content: str
    degree: int
    domains: list[str] = field(default_factory=list)
    connection_types: dict[str, int] = field(default_factory=dict)


@dataclass
class SurpriseReport:
    """Complete surprise analysis output."""

    surprises: list[SurprisingConnection] = field(default_factory=list)
    questions: list[SuggestedQuestion] = field(default_factory=list)
    god_theories: list[GodTheory] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "surprises": [
                {
                    "theory_a": {"id": s.theory_a_id, "content": s.theory_a_content[:120]},
                    "theory_b": {"id": s.theory_b_id, "content": s.theory_b_content[:120]},
                    "score": round(s.surprise_score, 2),
                    "reasons": s.reasons,
                    "connection_type": s.connection_type,
                }
                for s in self.surprises
            ],
            "questions": [
                {
                    "question": q.question,
                    "type": q.question_type,
                    "why": q.why,
                    "related_theories": q.related_theories[:3],
                }
                for q in self.questions
            ],
            "god_theories": [
                {
                    "id": g.theory_id,
                    "content": g.content[:120],
                    "degree": g.degree,
                    "domains": g.domains[:5],
                }
                for g in self.god_theories
            ],
            "stats": self.stats,
        }


# ---------------------------------------------------------------------------
# Domain extraction (shared with topology.py)
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "ought",
    "in", "on", "at", "to", "for", "with", "by", "from", "of", "about",
    "into", "through", "during", "before", "after", "above", "below",
    "and", "or", "but", "not", "no", "nor", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "than", "too", "very", "just", "also",
    "this", "that", "these", "those", "it", "its", "they", "them",
    "use", "using", "used", "always", "never", "when", "if", "then",
})

ALL_DOMAINS = frozenset({
    "api-design", "authentication", "authorization", "build-systems",
    "caching", "cli-tools", "cloud-infra", "concurrency",
    "configuration", "data-modeling", "data-pipeline", "database-access",
    "deployment", "documentation", "error-handling", "event-systems",
    "file-io", "frontend-ui", "graph-algorithms", "http-networking",
    "internationalization", "logging-observability", "machine-learning",
    "messaging-queues", "mobile-development", "orm-patterns",
    "performance-optimization", "security", "serialization",
    "state-management", "testing", "type-systems",
})


def _extract_domains(theory: Theory) -> set[str]:
    """Extract domains from theory content via keyword matching."""
    domains: set[str] = set()
    if theory.scope_qualifier:
        domains.add(theory.scope_qualifier)
    if theory.metadata:
        meta_domains = theory.metadata.get("domains", None)
        if isinstance(meta_domains, list):
            domains.update(meta_domains)
        elif isinstance(meta_domains, str) and meta_domains:
            domains.update(d.strip() for d in meta_domains.split(",") if d.strip())

    content_lower = theory.content.lower()
    for domain in ALL_DOMAINS:
        parts = domain.split("-")
        significant_parts = [p for p in parts if len(p) > 4]
        if not significant_parts:
            if re.search(r"\b" + re.escape(domain) + r"\b", content_lower):
                domains.add(domain)
            continue
        matching = [p for p in significant_parts if re.search(r"\b" + re.escape(p) + r"\b", content_lower)]
        required = min(2, len(significant_parts))
        if len(matching) >= required:
            domains.add(domain)
    return domains


def _extract_keywords(content: str) -> set[str]:
    """Extract meaningful keywords from content."""
    words = re.findall(r"[a-z_][a-z0-9_]*", content.lower())
    return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}


def _get_project(theory: Theory) -> str:
    """Get project scope from a theory."""
    if theory.scope == "project" and theory.scope_qualifier:
        return theory.scope_qualifier
    return ""


# ---------------------------------------------------------------------------
# Surprise Engine
# ---------------------------------------------------------------------------


class SurpriseEngine:
    """Detects surprising connections and generates questions from theory graph."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def analyze(
        self,
        project: str = "",
        top_surprises: int = 10,
        top_questions: int = 7,
        top_god: int = 5,
    ) -> SurpriseReport:
        """Run full surprise analysis pipeline."""
        theories = self._load_theories(project)
        if len(theories) < 3:
            return SurpriseReport(stats={"theories_analyzed": len(theories), "insufficient": True})

        # Build adjacency from theory relationships
        adj, edge_types = self._build_adjacency(theories)
        theory_domains = {t.id: _extract_domains(t) for t in theories}
        theory_keywords = {t.id: _extract_keywords(t.content) for t in theories}

        # Detect god theories (highest degree)
        god_theories = self._find_god_theories(theories, adj, theory_domains, top_god)

        # Find surprising connections
        surprises = self._find_surprises(
            theories, adj, edge_types, theory_domains, theory_keywords, top_surprises
        )

        # Generate questions
        questions = self._generate_questions(
            theories, adj, edge_types, theory_domains, god_theories, top_questions
        )

        stats = {
            "theories_analyzed": len(theories),
            "edges_analyzed": sum(len(v) for v in adj.values()) // 2,
            "domains_covered": len(set().union(*theory_domains.values())),
            "projects_covered": len({_get_project(t) for t in theories if _get_project(t)}),
        }

        return SurpriseReport(
            surprises=surprises,
            questions=questions,
            god_theories=god_theories,
            stats=stats,
        )

    def _load_theories(self, project: str) -> list[Theory]:
        try:
            if project:
                return self._db.list_theories(project=project, active_only=True, limit=300)
            return self._db.list_theories(active_only=True, limit=300)
        except Exception:
            return []

    def _build_adjacency(
        self, theories: list[Theory]
    ) -> tuple[dict[str, set[str]], dict[tuple[str, str], list[str]]]:
        """Build adjacency from explicit relations + shared domain/keyword connections."""
        adj: dict[str, set[str]] = defaultdict(set)
        edge_types: dict[tuple[str, str], list[str]] = defaultdict(list)
        id_set = {t.id for t in theories}

        # Explicit relations from DB (related_theories field)
        for theory in theories:
            if theory.related_theories:
                for related_id in theory.related_theories:
                    if related_id in id_set:
                        key = (min(theory.id, related_id), max(theory.id, related_id))
                        adj[theory.id].add(related_id)
                        adj[related_id].add(theory.id)
                        if "explicit_relation" not in edge_types[key]:
                            edge_types[key].append("explicit_relation")

            # Parent-child relationships
            if theory.parent_theory_id and theory.parent_theory_id in id_set:
                key = (min(theory.id, theory.parent_theory_id), max(theory.id, theory.parent_theory_id))
                adj[theory.id].add(theory.parent_theory_id)
                adj[theory.parent_theory_id].add(theory.id)
                if "parent_child" not in edge_types[key]:
                    edge_types[key].append("parent_child")

        # Shared domain connections
        domain_to_theories: dict[str, list[str]] = defaultdict(list)
        for theory in theories:
            for domain in _extract_domains(theory):
                domain_to_theories[domain].append(theory.id)

        for _domain, members in domain_to_theories.items():
            if len(members) < 2 or len(members) > 20:
                continue
            for i, tid_a in enumerate(members):
                for tid_b in members[i + 1:]:
                    key = (min(tid_a, tid_b), max(tid_a, tid_b))
                    adj[tid_a].add(tid_b)
                    adj[tid_b].add(tid_a)
                    if "shared_domain" not in edge_types[key]:
                        edge_types[key].append("shared_domain")

        # Shared keyword connections (at least 3 keywords in common)
        theory_kw = {t.id: _extract_keywords(t.content) for t in theories}
        theory_ids = [t.id for t in theories]
        n = len(theories)
        for i in range(n):
            kw_i = theory_kw[theory_ids[i]]
            if not kw_i:
                continue
            for j in range(i + 1, n):
                kw_j = theory_kw[theory_ids[j]]
                if not kw_j:
                    continue
                overlap = len(kw_i & kw_j)
                union = len(kw_i | kw_j)
                if overlap >= 3 and union > 0 and (overlap / union) > 0.15:
                    key = (min(theory_ids[i], theory_ids[j]), max(theory_ids[i], theory_ids[j]))
                    adj[theory_ids[i]].add(theory_ids[j])
                    adj[theory_ids[j]].add(theory_ids[i])
                    if "keyword_overlap" not in edge_types[key]:
                        edge_types[key].append("keyword_overlap")

        return adj, edge_types

    def _find_god_theories(
        self,
        theories: list[Theory],
        adj: dict[str, set[str]],
        theory_domains: dict[str, set[str]],
        top_n: int,
    ) -> list[GodTheory]:
        """Identify most-connected theories by degree."""
        degree_list = [(t.id, len(adj.get(t.id, set()))) for t in theories]
        degree_list.sort(key=lambda x: -x[1])

        god_theories: list[GodTheory] = []
        theory_map = {t.id: t for t in theories}

        for tid, degree in degree_list[:top_n]:
            if degree < 2:
                break
            theory = theory_map[tid]
            domains = sorted(theory_domains.get(tid, set()))

            # Count connection types to neighbors
            conn_types: Counter[str] = Counter()
            for neighbor_id in adj.get(tid, set()):
                n_domains = theory_domains.get(neighbor_id, set())
                my_domains = theory_domains.get(tid, set())
                if n_domains and my_domains and not (n_domains & my_domains):
                    conn_types["cross_domain"] += 1
                else:
                    conn_types["same_domain"] += 1

            god_theories.append(GodTheory(
                theory_id=tid,
                content=theory.content,
                degree=degree,
                domains=domains,
                connection_types=dict(conn_types),
            ))

        return god_theories

    def _find_surprises(
        self,
        theories: list[Theory],
        adj: dict[str, set[str]],
        edge_types: dict[tuple[str, str], list[str]],
        theory_domains: dict[str, set[str]],
        theory_keywords: dict[str, set[str]],
        top_n: int,
    ) -> list[SurprisingConnection]:
        """Find the most surprising connections in the theory graph.

        Surprise score = composite of:
        1. Cross-domain: +3 if theories share NO domains
        2. Cross-project: +2 if theories are from different projects
        3. Low keyword overlap: +2 if content similarity < 10%
        4. Confidence disparity: +1 if confidence gap > 0.3
        5. Connection distance: +1 if only connected via shared domain (not explicit)
        """
        theory_map = {t.id: t for t in theories}
        scored: list[tuple[float, str, str, list[str]]] = []

        seen_pairs: set[tuple[str, str]] = set()

        for theory in theories:
            for neighbor_id in adj.get(theory.id, set()):
                pair_key = (min(theory.id, neighbor_id), max(theory.id, neighbor_id))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                neighbor = theory_map.get(neighbor_id)
                if not neighbor:
                    continue

                score, reasons = self._compute_surprise_score(
                    theory, neighbor, edge_types, theory_domains, theory_keywords
                )

                if score >= 3.0:
                    scored.append((score, theory.id, neighbor_id, reasons))

        scored.sort(key=lambda x: -x[0])

        surprises: list[SurprisingConnection] = []
        for score, tid_a, tid_b, reasons in scored[:top_n]:
            ta = theory_map[tid_a]
            tb = theory_map[tid_b]

            # Classify connection type
            domains_a = theory_domains.get(tid_a, set())
            domains_b = theory_domains.get(tid_b, set())
            proj_a = _get_project(ta)
            proj_b = _get_project(tb)

            if proj_a and proj_b and proj_a != proj_b:
                conn_type = "cross_project"
            elif domains_a and domains_b and not (domains_a & domains_b):
                conn_type = "cross_domain"
            else:
                conn_type = "unexpected_similarity"

            surprises.append(SurprisingConnection(
                theory_a_id=tid_a,
                theory_a_content=ta.content,
                theory_b_id=tid_b,
                theory_b_content=tb.content,
                surprise_score=score,
                reasons=reasons,
                connection_type=conn_type,
            ))

        return surprises

    def _compute_surprise_score(
        self,
        theory_a: Theory,
        theory_b: Theory,
        edge_types: dict[tuple[str, str], list[str]],
        theory_domains: dict[str, set[str]],
        theory_keywords: dict[str, set[str]],
    ) -> tuple[float, list[str]]:
        """Compute composite surprise score for a pair of connected theories."""
        score = 0.0
        reasons: list[str] = []

        domains_a = theory_domains.get(theory_a.id, set())
        domains_b = theory_domains.get(theory_b.id, set())
        kw_a = theory_keywords.get(theory_a.id, set())
        kw_b = theory_keywords.get(theory_b.id, set())

        # 1. Cross-domain bonus
        if domains_a and domains_b and not (domains_a & domains_b):
            score += 3.0
            reasons.append(f"crosses domains: {sorted(domains_a)[:2]} <-> {sorted(domains_b)[:2]}")

        # 2. Cross-project bonus
        proj_a = _get_project(theory_a)
        proj_b = _get_project(theory_b)
        if proj_a and proj_b and proj_a != proj_b:
            score += 2.0
            reasons.append(f"crosses projects: {proj_a} <-> {proj_b}")

        # 3. Low keyword overlap (content dissimilarity)
        if kw_a and kw_b:
            overlap = len(kw_a & kw_b)
            union = len(kw_a | kw_b)
            jaccard = overlap / union if union > 0 else 0.0
            if jaccard < 0.10:
                score += 2.0
                reasons.append("very different content (low keyword overlap)")
            elif jaccard < 0.20:
                score += 1.0
                reasons.append("different content")

        # 4. Confidence disparity
        conf_gap = abs(theory_a.confidence - theory_b.confidence)
        if conf_gap > 0.3:
            score += 1.0
            reasons.append(f"confidence gap: {theory_a.confidence:.2f} vs {theory_b.confidence:.2f}")

        # 5. Connection is only via shared domain (weak/implicit connection)
        pair_key = (min(theory_a.id, theory_b.id), max(theory_a.id, theory_b.id))
        etypes = edge_types.get(pair_key, [])
        if etypes == ["shared_domain"] or etypes == ["keyword_overlap"]:
            score += 1.0
            reasons.append("connected only by implicit similarity")

        # 6. High application count disparity (one is well-tested, other is not)
        app_a = theory_a.application_count or 0
        app_b = theory_b.application_count or 0
        if max(app_a, app_b) > 5 and min(app_a, app_b) == 0:
            score += 0.5
            reasons.append("one theory well-applied, other untested")

        return score, reasons

    def _generate_questions(
        self,
        theories: list[Theory],
        adj: dict[str, set[str]],
        edge_types: dict[tuple[str, str], list[str]],
        theory_domains: dict[str, set[str]],
        god_theories: list[GodTheory],
        top_n: int,
    ) -> list[SuggestedQuestion]:
        """Generate actionable research questions from graph structure."""
        questions: list[SuggestedQuestion] = []

        # 1. Bridge nodes — theories that connect otherwise disconnected clusters
        if god_theories:
            for god in god_theories[:3]:
                neighbors = adj.get(god.theory_id, set())
                if len(neighbors) < 3:
                    continue
                # Check if neighbors form distinct groups
                neighbor_domains: list[set[str]] = []
                for nid in neighbors:
                    nd = theory_domains.get(nid, set())
                    if nd:
                        neighbor_domains.append(nd)
                if len(neighbor_domains) >= 2:
                    all_domains = set()
                    for ds in neighbor_domains:
                        all_domains.update(ds)
                    if len(all_domains) >= 3:
                        questions.append(SuggestedQuestion(
                            question=f"Why does '{god.content[:60]}' connect {len(all_domains)} different domains?",
                            question_type="bridge_node",
                            why=f"This theory has {god.degree} connections spanning diverse domains — it may be a fundamental pattern.",
                            related_theories=[god.theory_id],
                        ))

        # 2. Weak theories with many connections (high degree but low confidence)
        for theory in theories:
            degree = len(adj.get(theory.id, set()))
            if degree >= 3 and theory.confidence < 0.4:
                questions.append(SuggestedQuestion(
                    question=f"Is '{theory.content[:60]}' actually correct? It's widely connected but has low confidence ({theory.confidence:.2f}).",
                    question_type="weak_theory",
                    why="High connectivity + low confidence = high-impact if wrong.",
                    related_theories=[theory.id],
                ))

        # 3. Isolated theories (no connections but high importance)
        for theory in theories:
            degree = len(adj.get(theory.id, set()))
            if degree == 0 and theory.confirmation_count > 0:
                questions.append(SuggestedQuestion(
                    question=f"What connects '{theory.content[:60]}' to the rest of your knowledge?",
                    question_type="isolated",
                    why="This theory is confirmed but has no structural links — it may be missing connections.",
                    related_theories=[theory.id],
                ))

        # 4. Domain gaps — domains with very few theories
        domain_counts: Counter[str] = Counter()
        for t in theories:
            ds = theory_domains.get(t.id, set())
            for d in ds:
                domain_counts[d] += 1

        sparse_domains = [d for d, c in domain_counts.items() if c == 1]
        if sparse_domains:
            for domain in sparse_domains[:2]:
                questions.append(SuggestedQuestion(
                    question=f"You have only 1 theory about '{domain}' — is this domain well-understood or under-explored?",
                    question_type="knowledge_gap",
                    why="Single-theory domains are fragile — one contradiction retires all knowledge in the area.",
                    related_theories=[],
                ))

        # 5. Contradicted but still active theories
        for theory in theories:
            if theory.contradiction_count > 0 and theory.active and theory.confidence > 0.3:
                questions.append(SuggestedQuestion(
                    question=f"'{theory.content[:60]}' has been contradicted {theory.contradiction_count} time(s) but remains active — should it be revised?",
                    question_type="ambiguous_link",
                    why="Contradicted theories that persist may need refinement rather than retirement.",
                    related_theories=[theory.id],
                ))

        # Sort by importance heuristic (bridge > weak > gap > isolated > ambiguous)
        type_priority = {
            "bridge_node": 5,
            "weak_theory": 4,
            "knowledge_gap": 3,
            "isolated": 2,
            "ambiguous_link": 1,
        }
        questions.sort(key=lambda q: -type_priority.get(q.question_type, 0))

        return questions[:top_n]
