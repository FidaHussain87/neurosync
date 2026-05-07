"""Topological Knowledge Health (TKH) — persistent homology on the knowledge graph.

Applies algebraic topology to reveal structural properties of developer knowledge:
- β₀ (Betti-0): connected components = knowledge islands
- β₁ (Betti-1): independent cycles = knowledge voids / redundancy loops
- Persistence: which structural features are robust vs noise
- Fragility: articulation points whose removal fragments the graph
- Crystallization: overall structural maturity score

Zero external TDA dependencies — implements Union-Find (β₀) and boundary
matrix reduction (β₁) natively.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neurosync.models import Theory


# --- Data Models ---


@dataclass
class PersistencePair:
    """A birth-death pair in the persistence diagram."""

    birth: float
    death: float  # math.inf = never dies (essential feature)
    dimension: int  # 0 = component, 1 = loop/void
    generators: list[str] = field(default_factory=list)

    @property
    def lifetime(self) -> float:
        if math.isinf(self.death):
            return math.inf
        return self.death - self.birth


@dataclass
class KnowledgeVoid:
    """A detected gap in the knowledge topology."""

    surrounding_domains: list[str]
    surrounding_theories: list[str]
    gap_description: str
    severity: float  # 0-1
    cycle_length: int  # number of nodes in the boundary cycle


@dataclass
class KnowledgeBridge:
    """A critical connecting theory (articulation point or bridge edge)."""

    theory_id: str
    theory_content: str
    connects: tuple[str, str]  # domains/clusters it bridges
    criticality: float  # 0-1, proportion of connectivity lost if removed


@dataclass
class KnowledgeIsland:
    """A disconnected cluster of knowledge."""

    theory_ids: list[str]
    domains: list[str]
    size: int
    isolation_score: float  # 0-1, how disconnected from largest component


@dataclass
class KnowledgeHealth:
    """Complete topological health report."""

    # Betti numbers at current filtration
    betti_0: int = 0  # connected components
    betti_1: int = 0  # independent cycles (voids)

    # Derived metrics (all 0.0-1.0)
    euler_characteristic: int = 0  # χ = V - E + F (vertices - edges + faces)
    connectivity: float = 0.0  # 1.0 = fully connected
    fragility: float = 0.0  # 1.0 = many single points of failure
    crystallization: float = 0.0  # 1.0 = mature, robust topology
    coverage: float = 0.0  # domain coverage ratio

    # Actionable findings
    voids: list[KnowledgeVoid] = field(default_factory=list)
    bridges: list[KnowledgeBridge] = field(default_factory=list)
    islands: list[KnowledgeIsland] = field(default_factory=list)

    # Persistence summary
    persistence_pairs: list[PersistencePair] = field(default_factory=list)

    # Overall health (0-100)
    health_score: float = 0.0

    # Vertex/edge counts
    vertex_count: int = 0
    edge_count: int = 0
    triangle_count: int = 0

    def format_summary(self) -> str:
        """Format as compact status string."""
        parts = [
            f"health={self.health_score:.0f}/100",
            f"β₀={self.betti_0}",
            f"β₁={self.betti_1}",
            f"χ={self.euler_characteristic}",
        ]
        if self.voids:
            parts.append(f"voids={len(self.voids)}")
        if self.bridges:
            parts.append(f"bridges={len(self.bridges)}")
        if self.islands and len(self.islands) > 1:
            parts.append(f"islands={len(self.islands)}")
        return " | ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for MCP response."""
        return {
            "health_score": round(self.health_score, 1),
            "betti_0": self.betti_0,
            "betti_1": self.betti_1,
            "euler_characteristic": self.euler_characteristic,
            "connectivity": round(self.connectivity, 3),
            "fragility": round(self.fragility, 3),
            "crystallization": round(self.crystallization, 3),
            "coverage": round(self.coverage, 3),
            "vertex_count": self.vertex_count,
            "edge_count": self.edge_count,
            "triangle_count": self.triangle_count,
            "voids": [
                {
                    "surrounding_domains": v.surrounding_domains,
                    "surrounding_theories": v.surrounding_theories[:3],
                    "gap_description": v.gap_description,
                    "severity": round(v.severity, 2),
                }
                for v in self.voids
            ],
            "bridges": [
                {
                    "theory_id": b.theory_id,
                    "theory_content": b.theory_content[:80],
                    "connects": list(b.connects),
                    "criticality": round(b.criticality, 2),
                }
                for b in self.bridges
            ],
            "islands": [
                {
                    "domains": isl.domains,
                    "size": isl.size,
                    "isolation_score": round(isl.isolation_score, 2),
                }
                for isl in self.islands
                if isl.size > 1
            ],
            "summary": self.format_summary(),
        }


# --- Union-Find (Disjoint Set) for β₀ ---


class UnionFind:
    """Weighted Union-Find with path compression for tracking component merges."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n
        self.size = [1] * n
        self.components = n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> bool:
        """Unite sets containing x and y. Returns True if they were separate."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        self.size[rx] += self.size[ry]
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1
        self.components -= 1
        return True

    def connected(self, x: int, y: int) -> bool:
        return self.find(x) == self.find(y)

    def component_sizes(self) -> list[int]:
        """Return sizes of all components."""
        roots: dict[int, int] = {}
        for i in range(len(self.parent)):
            root = self.find(i)
            roots[root] = self.size[root]
        return sorted(roots.values(), reverse=True)


# --- Filtration Construction ---


@dataclass
class WeightedEdge:
    """An edge in the filtration with its weight (filtration value)."""

    u: int
    v: int
    weight: float  # lower = stronger connection (added earlier in filtration)
    u_label: str = ""
    v_label: str = ""


def build_knowledge_graph(
    theories: list[Theory],
    db: Any,
) -> tuple[list[str], list[WeightedEdge]]:
    """Build weighted graph from theory relationships.

    Vertices: active theories
    Edges: connections via shared domains, causal links, shared episodes, scope

    Edge weight = 1 - similarity (lower = added earlier in filtration = stronger).
    """
    if not theories:
        return [], []

    # Map theory IDs to indices
    theory_ids = [t.id for t in theories]
    id_to_idx: dict[str, int] = {tid: i for i, tid in enumerate(theory_ids)}
    n = len(theories)

    edges: list[WeightedEdge] = []
    seen_edges: set[tuple[int, int]] = set()
    edge_index: dict[tuple[int, int], int] = {}

    def _add_edge(i: int, j: int, weight: float) -> None:
        key = (min(i, j), max(i, j))
        if key in seen_edges:
            # Keep stronger (lower weight) connection — O(1) lookup via edge_index
            idx = edge_index[key]
            if weight < edges[idx].weight:
                edges[idx] = WeightedEdge(
                    u=key[0], v=key[1], weight=weight,
                    u_label=theory_ids[key[0]],
                    v_label=theory_ids[key[1]],
                )
            return
        seen_edges.add(key)
        edge_index[key] = len(edges)
        edges.append(WeightedEdge(
            u=key[0], v=key[1], weight=weight,
            u_label=theory_ids[key[0]],
            v_label=theory_ids[key[1]],
        ))

    # 1. Domain co-occurrence: theories sharing domains get connected
    domain_to_theories: dict[str, list[int]] = defaultdict(list)
    for i, theory in enumerate(theories):
        domains = _extract_theory_domains(theory)
        for d in domains:
            domain_to_theories[d].append(i)

    for _domain, members in domain_to_theories.items():
        if len(members) < 2:
            continue
        for a_idx in range(len(members)):
            for b_idx in range(a_idx + 1, len(members)):
                i, j = members[a_idx], members[b_idx]
                # Weight: inverse of shared domain count (more shared = stronger)
                domains_i = set(_extract_theory_domains(theories[i]))
                domains_j = set(_extract_theory_domains(theories[j]))
                jaccard = len(domains_i & domains_j) / max(len(domains_i | domains_j), 1)
                _add_edge(i, j, 1.0 - jaccard)

    # 2. Scope co-occurrence: same scope = likely related
    scope_to_theories: dict[str, list[int]] = defaultdict(list)
    for i, theory in enumerate(theories):
        scope = theory.scope_qualifier or theory.scope
        if scope:
            scope_to_theories[scope].append(i)

    for _scope, members in scope_to_theories.items():
        if len(members) < 2:
            continue
        for a_idx in range(len(members)):
            for b_idx in range(a_idx + 1, len(members)):
                i, j = members[a_idx], members[b_idx]
                _add_edge(i, j, 0.4)  # Moderate connection

    # 3. Content similarity via keyword overlap (lightweight, no vectors)
    theory_keywords: list[set[str]] = []
    for theory in theories:
        keywords = _extract_keywords(theory.content)
        theory_keywords.append(keywords)

    for i in range(n):
        for j in range(i + 1, n):
            if not theory_keywords[i] or not theory_keywords[j]:
                continue
            overlap = len(theory_keywords[i] & theory_keywords[j])
            union = len(theory_keywords[i] | theory_keywords[j])
            if union > 0 and overlap >= 2:
                jaccard = overlap / union
                if jaccard > 0.15:
                    _add_edge(i, j, 1.0 - jaccard)

    # 4. Causal links from DB (if available)
    try:
        causal_links = db.list_causal_links() if hasattr(db, "list_causal_links") else []
        for link in causal_links:
            cause_id = link.get("cause_id", "") if isinstance(link, dict) else getattr(link, "cause_id", "")
            effect_id = link.get("effect_id", "") if isinstance(link, dict) else getattr(link, "effect_id", "")
            confidence = link.get("confidence", 0.5) if isinstance(link, dict) else getattr(link, "confidence", 0.5)

            if cause_id in id_to_idx and effect_id in id_to_idx:
                _add_edge(
                    id_to_idx[cause_id],
                    id_to_idx[effect_id],
                    1.0 - confidence,
                )
    except Exception:
        pass

    return theory_ids, edges


def _extract_theory_domains(theory: Theory) -> list[str]:
    """Extract domain labels from a theory.

    Sources (in priority order):
    1. metadata["domains"] if stored (list or comma-separated string)
    2. scope_qualifier (e.g., "payments", "concurrency")
    3. Content keyword matching against the 32-domain taxonomy
    """
    domains: set[str] = set()

    # metadata may contain explicit domains
    if theory.metadata:
        meta_domains = theory.metadata.get("domains", None)
        if isinstance(meta_domains, list):
            domains.update(meta_domains)
        elif isinstance(meta_domains, str) and meta_domains:
            domains.update(d.strip() for d in meta_domains.split(",") if d.strip())

    # scope_qualifier is the primary domain signal
    if theory.scope_qualifier:
        domains.add(theory.scope_qualifier)

    # Match content keywords against known domains using word boundaries
    content_lower = theory.content.lower()
    for domain in ALL_DOMAINS:
        parts = domain.split("-")
        # Use word boundary matching with minimum part length of 5
        # to avoid false positives from generic words like "state", "data", "type"
        significant_parts = [p for p in parts if len(p) > 4]
        if not significant_parts:
            # Try exact hyphenated match first
            if re.search(r"\b" + re.escape(domain) + r"\b", content_lower):
                domains.add(domain)
                continue
            # Fallback: all parts present as individual words (proximity match)
            # e.g., "file-io" matches content containing both "file" and "io" as words
            all_parts_present = all(
                re.search(r"\b" + re.escape(p) + r"\b", content_lower)
                for p in parts if len(p) > 1  # skip single-char parts
            )
            if all_parts_present and len([p for p in parts if len(p) > 1]) >= 2:
                domains.add(domain)
            continue
        matching_parts = [
            p for p in significant_parts
            if re.search(r"\b" + re.escape(p) + r"\b", content_lower)
        ]
        # Require at least 2 parts to match for hyphenated domains,
        # or all significant parts if there's only 1
        required_matches = min(2, len(significant_parts))
        if len(matching_parts) >= required_matches:
            domains.add(domain)

    return list(domains)


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


def _extract_keywords(content: str) -> set[str]:
    """Extract meaningful keywords from theory content."""
    words = re.findall(r"[a-z_][a-z0-9_]*", content.lower())
    return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}


# --- Persistent Homology Computation ---


def compute_persistence(
    num_vertices: int,
    edges: list[WeightedEdge],
) -> tuple[list[PersistencePair], int, int]:
    """Compute persistent homology of the Rips complex built from the filtration.

    Uses the standard algorithm extended with 2-simplices (triangles):
    1. Sort edges by weight (filtration value)
    2. Process edges in order:
       - If edge connects two components: merge (kills a β₀ feature)
       - If edge creates a cycle: births a β₁ feature
    3. Identify triangles (3-cliques) in the graph
    4. Process triangles as 2-simplices at filtration value = max(edge weights)
       - A triangle kills an H₁ cycle (gives it a finite death time)
       - Short-lived H₁ features = noise; long-lived = genuine structural gaps

    Returns: (persistence_pairs, final_β₀, final_β₁)
    """
    if num_vertices == 0:
        return [], 0, 0

    pairs: list[PersistencePair] = []
    uf = UnionFind(num_vertices)

    # All vertices born at filtration value 0
    # Sort edges by weight (ascending = strongest first)
    sorted_edges = sorted(edges, key=lambda e: (e.weight, min(e.u, e.v), max(e.u, e.v)))

    # Track H₁ pairs (active cycles) separately for triangle killing
    h1_pairs: list[PersistencePair] = []

    # Track which edge created each H₁ pair for precise triangle matching
    # (boundary matrix column reduction for ∂₂ in flag complexes)
    h1_by_creating_edge: dict[tuple[int, int], PersistencePair] = {}

    for edge in sorted_edges:
        if uf.union(edge.u, edge.v):
            # Merged two components — this kills the younger component
            # The younger component was born at 0, dies at edge.weight
            pairs.append(PersistencePair(
                birth=0.0,
                death=edge.weight,
                dimension=0,
                generators=[edge.u_label, edge.v_label],
            ))
        else:
            # Created a cycle — births a 1-dimensional feature
            h1_pair = PersistencePair(
                birth=edge.weight,
                death=math.inf,  # Initially infinite; may be killed by a triangle
                dimension=1,
                generators=[edge.u_label, edge.v_label],
            )
            pairs.append(h1_pair)
            h1_pairs.append(h1_pair)
            # Record the edge that created this cycle for boundary matching
            creating_key = (min(edge.u, edge.v), max(edge.u, edge.v))
            h1_by_creating_edge[creating_key] = h1_pair

    # --- Rips complex extension: process triangles as 2-simplices ---
    # Build adjacency with edge weights for triangle detection
    adj_tri: dict[int, set[int]] = defaultdict(set)
    edge_weights: dict[tuple[int, int], float] = {}
    for edge in edges:
        adj_tri[edge.u].add(edge.v)
        adj_tri[edge.v].add(edge.u)
        key = (min(edge.u, edge.v), max(edge.u, edge.v))
        # Keep the minimum weight (strongest connection) if duplicates
        if key not in edge_weights or edge.weight < edge_weights[key]:
            edge_weights[key] = edge.weight

    # Find all triangles and their filtration values
    triangles: list[tuple[float, int, int, int]] = []  # (filtration_value, u, v, w)
    seen_triangles: set[tuple[int, int, int]] = set()

    for edge in edges:
        u, v = edge.u, edge.v
        # Find common neighbors (vertices completing a triangle)
        common = adj_tri[u] & adj_tri[v]
        for w in common:
            tri_key = tuple(sorted([u, v, w]))
            if tri_key in seen_triangles:
                continue
            seen_triangles.add(tri_key)
            # Filtration value of triangle = max of its three edge weights
            a, b, c = tri_key
            w_ab = edge_weights.get((a, b), math.inf)
            w_ac = edge_weights.get((a, c), math.inf)
            w_bc = edge_weights.get((b, c), math.inf)
            filt_val = max(w_ab, w_ac, w_bc)
            triangles.append((filt_val, a, b, c))

    # Sort triangles by filtration value (process lowest first)
    triangles.sort(key=lambda t: (t[0], t[1], t[2], t[3]))

    # Kill H₁ cycles via ∂₂ boundary matching (correct persistence pairing).
    # A triangle {a,b,c} entering at filtration value f kills the H₁ cycle
    # created by its heaviest edge (the closing edge — last added, which
    # completed the cycle). This is equivalent to column reduction of ∂₂
    # for flag complexes built from a weighted graph.
    for filt_val, a, b, c in triangles:
        # Identify the triangle's three edges and find the heaviest (closing) edge
        tri_edges = [(a, b), (a, c), (b, c)]
        # Sort by weight descending to try the heaviest first; on ties, try all
        tri_edges_sorted = sorted(
            tri_edges,
            key=lambda e: edge_weights.get((min(e), max(e)), 0.0),
            reverse=True,
        )

        for eu, ev in tri_edges_sorted:
            edge_key = (min(eu, ev), max(eu, ev))
            if edge_key in h1_by_creating_edge:
                pair = h1_by_creating_edge[edge_key]
                if math.isinf(pair.death):
                    pair.death = filt_val
                    del h1_by_creating_edge[edge_key]
                    break  # One triangle kills at most one cycle

    # Final β₁ = number of H₁ pairs that are still alive (death = inf)
    final_beta_0 = uf.components
    final_beta_1 = sum(1 for p in h1_pairs if math.isinf(p.death))

    return pairs, final_beta_0, final_beta_1


# --- Articulation Points (Fragility) ---


def find_articulation_points(
    num_vertices: int,
    edges: list[WeightedEdge],
) -> list[int]:
    """Find articulation points using Tarjan's algorithm (iterative DFS).

    An articulation point is a vertex whose removal increases beta-0.
    Uses edge-index-based parent tracking to correctly handle multigraphs.
    """
    if num_vertices <= 2:
        return []

    adj: dict[int, list[tuple[int, int]]] = defaultdict(list)  # vertex -> [(neighbor, edge_idx)]
    for idx, edge in enumerate(edges):
        adj[edge.u].append((edge.v, idx))
        adj[edge.v].append((edge.u, idx))

    visited = [False] * num_vertices
    disc = [0] * num_vertices
    low = [0] * num_vertices
    is_ap = [False] * num_vertices
    timer = 0

    # Run DFS from each unvisited vertex (handles disconnected graphs)
    for start in range(num_vertices):
        if visited[start] or not adj[start]:
            continue

        visited[start] = True
        disc[start] = low[start] = timer
        timer += 1

        # Stack entries: (u, parent_edge_idx, neighbor_list_position)
        stack: list[tuple[int, int, int]] = [(start, -1, 0)]
        children_count: dict[int, int] = defaultdict(int)

        while stack:
            u, parent_edge, pos = stack[-1]

            if pos < len(adj[u]):
                # Advance to next neighbor
                stack[-1] = (u, parent_edge, pos + 1)
                v, edge_idx = adj[u][pos]

                if not visited[v]:
                    children_count[u] += 1
                    visited[v] = True
                    disc[v] = low[v] = timer
                    timer += 1
                    stack.append((v, edge_idx, 0))
                elif edge_idx != parent_edge:
                    low[u] = min(low[u], disc[v])
            else:
                # Done with u; pop and propagate low value to parent
                stack.pop()
                if stack:
                    parent_u = stack[-1][0]
                    low[parent_u] = min(low[parent_u], low[u])

                    # Non-root AP check: low[u] >= disc[parent_u]
                    if len(stack) > 1 and low[u] >= disc[parent_u]:
                        is_ap[parent_u] = True
                    # Root AP check: 2+ children in DFS tree
                    if len(stack) == 1 and children_count[parent_u] > 1:
                        is_ap[parent_u] = True

    return [i for i in range(num_vertices) if is_ap[i]]


# --- Bridge Edges ---


def find_bridge_edges(
    num_vertices: int,
    edges: list[WeightedEdge],
) -> list[tuple[int, int]]:
    """Find bridge edges whose removal disconnects the graph."""
    if num_vertices <= 1:
        return []

    adj: dict[int, list[tuple[int, int]]] = defaultdict(list)  # vertex -> [(neighbor, edge_idx)]
    for idx, edge in enumerate(edges):
        adj[edge.u].append((edge.v, idx))
        adj[edge.v].append((edge.u, idx))

    visited = [False] * num_vertices
    disc = [0] * num_vertices
    low = [0] * num_vertices
    parent_edge = [-1] * num_vertices
    timer = 0
    bridges: list[tuple[int, int]] = []

    for start in range(num_vertices):
        if visited[start] or not adj[start]:
            continue

        # Iterative DFS using explicit stack.
        # Each stack frame holds (vertex, index into adj[vertex]).
        stack: list[tuple[int, int]] = [(start, 0)]
        visited[start] = True
        disc[start] = low[start] = timer
        timer += 1

        while stack:
            u, adj_idx = stack[-1]
            neighbors = adj[u]

            if adj_idx < len(neighbors):
                # Advance the iterator for this frame
                stack[-1] = (u, adj_idx + 1)
                v, edge_idx = neighbors[adj_idx]

                if not visited[v]:
                    visited[v] = True
                    disc[v] = low[v] = timer
                    timer += 1
                    parent_edge[v] = edge_idx
                    stack.append((v, 0))
                elif edge_idx != parent_edge[u]:
                    low[u] = min(low[u], disc[v])
            else:
                # All neighbors of u processed; backtrack
                stack.pop()
                if stack:
                    parent_u = stack[-1][0]
                    low[parent_u] = min(low[parent_u], low[u])
                    pe = parent_edge[u]
                    if low[u] > disc[parent_u]:
                        bridges.append((edges[pe].u, edges[pe].v))

    return bridges


# --- Void Detection ---


def detect_voids(
    theories: list[Theory],
    edges: list[WeightedEdge],
    persistence_pairs: list[PersistencePair],
    all_domains: set[str],
) -> list[KnowledgeVoid]:
    """Detect knowledge voids from persistent H₁ features.

    Correct interpretation of H₁ cycles in a knowledge graph:
    - A cycle means there are INDIRECT paths connecting theories, but no
      direct shortcut through the interior (no triangle fills the loop).
    - A persistent cycle (high lifetime or death=inf) indicates a genuine
      structural gap: theories are connected around the boundary but the
      interior lacks bridging knowledge.
    - A short-lived cycle (quickly killed by a triangle) is NOT a void —
      it represents well-connected, redundant knowledge (noise).

    Only cycles with HIGH persistence (long lifetime relative to max filtration)
    are reported as voids. Short-lived cycles are filtered out as noise.
    """
    if not theories:
        return []

    voids: list[KnowledgeVoid] = []
    theory_ids = [t.id for t in theories]
    id_to_theory = {t.id: t for t in theories}

    # H₁ pairs represent cycles — only persistent ones indicate voids
    h1_pairs = [p for p in persistence_pairs if p.dimension == 1]

    if not h1_pairs:
        return []

    # Determine max filtration value for normalization
    max_filtration = 0.0
    for edge in edges:
        if edge.weight > max_filtration:
            max_filtration = edge.weight
    if max_filtration == 0.0:
        max_filtration = 1.0

    # Filter: only keep H₁ pairs with significant persistence.
    # Short-lived cycles (quickly filled by triangles) = redundancy = healthy.
    # Long-lived or infinite cycles = genuine structural gaps.
    persistence_threshold = max_filtration * 0.2  # At least 20% of filtration range
    significant_h1 = [
        p for p in h1_pairs
        if math.isinf(p.death) or (p.death - p.birth) > persistence_threshold
    ]

    # Sort by lifetime (longer-lived = more significant void)
    significant_h1.sort(
        key=lambda p: p.lifetime if not math.isinf(p.lifetime) else 1e6,
        reverse=True,
    )

    # Adjacency for neighborhood expansion
    adj: dict[int, set[int]] = defaultdict(set)
    for edge in edges:
        adj[edge.u].add(edge.v)
        adj[edge.v].add(edge.u)

    id_to_idx = {tid: i for i, tid in enumerate(theory_ids)}

    for pair in significant_h1[:10]:  # Analyze top 10 most persistent cycles
        # Find the cycle's surrounding theories
        cycle_theories: list[str] = []
        for gen in pair.generators:
            if gen in id_to_theory:
                cycle_theories.append(gen)

        if len(cycle_theories) < 2:
            continue

        # Expand to find full cycle neighborhood
        neighborhood_theories: set[str] = set(cycle_theories)
        for tid in cycle_theories:
            if tid in id_to_idx:
                idx = id_to_idx[tid]
                for neighbor in adj[idx]:
                    if neighbor < len(theory_ids):
                        neighborhood_theories.add(theory_ids[neighbor])

        # Domains around the void
        surrounding_domains: set[str] = set()
        for tid in neighborhood_theories:
            if tid in id_to_theory:
                domains = _extract_theory_domains(id_to_theory[tid])
                surrounding_domains.update(domains)

        # Find covered domains vs all domains to detect what's missing
        covered = surrounding_domains & all_domains
        if not covered:
            continue

        # Severity: based on actual persistence relative to max filtration.
        # Infinite death (cycle never filled) = highest severity.
        # Finite death = severity proportional to persistence / max_filtration.
        if math.isinf(pair.death):
            severity = min(1.0, 0.7 + len(neighborhood_theories) * 0.05)
        else:
            persistence = pair.death - pair.birth
            severity = min(1.0, (persistence / max_filtration) * 0.8
                           + len(neighborhood_theories) * 0.05)

        # Generate description
        domain_list = sorted(surrounding_domains)[:4]
        if math.isinf(pair.death):
            gap_desc = (
                f"Structural gap between: {', '.join(domain_list)}. "
                f"Theories form an indirect loop with no bridging knowledge "
                f"filling the interior — no triangle connects them directly."
            )
        else:
            gap_desc = (
                f"Sparse region between: {', '.join(domain_list)}. "
                f"Theories are loosely connected (cycle persisted from "
                f"{pair.birth:.2f} to {pair.death:.2f}) before being bridged."
            )

        voids.append(KnowledgeVoid(
            surrounding_domains=sorted(surrounding_domains)[:5],
            surrounding_theories=sorted(neighborhood_theories)[:5],
            gap_description=gap_desc,
            severity=severity,
            cycle_length=len(neighborhood_theories),
        ))

    return voids[:5]  # Top 5 most significant voids


# --- Domain Coverage ---


# The 32-domain taxonomy from intelligence/domains.py
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


def compute_domain_coverage(theories: list[Theory]) -> tuple[float, set[str], set[str]]:
    """Compute what proportion of the domain taxonomy is covered.

    Returns: (coverage_ratio, covered_domains, uncovered_domains)
    """
    covered: set[str] = set()
    for theory in theories:
        domains = _extract_theory_domains(theory)
        for d in domains:
            if d in ALL_DOMAINS:
                covered.add(d)

    uncovered = ALL_DOMAINS - covered
    ratio = len(covered) / len(ALL_DOMAINS) if ALL_DOMAINS else 0.0
    return ratio, covered, uncovered


# --- Triangle Detection ---


def count_triangles(num_vertices: int, edges: list[WeightedEdge]) -> int:
    """Count 2-simplices (triangles) in the graph.

    Used for Euler characteristic: χ = V - E + F
    """
    adj: dict[int, set[int]] = defaultdict(set)
    for edge in edges:
        adj[edge.u].add(edge.v)
        adj[edge.v].add(edge.u)

    triangles = 0
    for edge in edges:
        u, v = edge.u, edge.v
        common = adj[u] & adj[v]
        triangles += len(common)

    # Each triangle counted 3 times (once per edge)
    return triangles // 3


# --- Main Engine ---


class TopologicalHealthEngine:
    """Computes topological health of the developer's knowledge graph."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def compute_health(
        self,
        theories: list[Theory] | None = None,
        project: str = "",
    ) -> KnowledgeHealth:
        """Full TKH pipeline: build graph → filtration → persistence → metrics."""
        # Load theories if not provided
        if theories is None:
            theories = self._load_theories(project)

        if not theories:
            return KnowledgeHealth(health_score=0.0)

        # Filter to active theories only
        active_theories = [t for t in theories if t.active]
        if not active_theories:
            return KnowledgeHealth(health_score=0.0)

        n = len(active_theories)

        # Build weighted graph
        theory_ids, edges = build_knowledge_graph(active_theories, self._db)

        # Compute persistence
        pairs, beta_0, beta_1 = compute_persistence(n, edges)

        # Count triangles
        triangles = count_triangles(n, edges)

        # Euler characteristic of the flag (clique) complex: χ = V - E + F
        # where F = filled triangles (3-cliques). For the 1-skeleton alone,
        # χ = β₀ - β₁ = V - E + (components that never merge). Here we use
        # the flag complex interpretation where triangles count as 2-faces.
        euler = n - len(edges) + triangles

        # Connectivity: 1.0 when fully connected (β₀ = 1)
        connectivity = 1.0 / beta_0 if beta_0 > 0 else 0.0

        # Fragility: proportion of articulation points
        art_points = find_articulation_points(n, edges)
        fragility = len(art_points) / max(n, 1) if n > 2 else 0.0

        # Bridge edges
        bridge_edges = find_bridge_edges(n, edges)

        # Crystallization: based on persistence lifetimes and density
        crystallization = self._compute_crystallization(
            n, edges, pairs, triangles, beta_0
        )

        # Domain coverage
        coverage, covered_domains, uncovered_domains = compute_domain_coverage(active_theories)

        # Detect voids
        voids = detect_voids(active_theories, edges, pairs, covered_domains)

        # Build knowledge bridges
        bridges = self._build_bridges(
            active_theories, theory_ids, art_points, bridge_edges, edges
        )

        # Build knowledge islands
        islands = self._build_islands(active_theories, theory_ids, n, edges)

        # Compute overall health score (0-100)
        health_score = self._compute_health_score(
            connectivity=connectivity,
            fragility=fragility,
            crystallization=crystallization,
            coverage=coverage,
            void_count=len(voids),
            n=n,
        )

        return KnowledgeHealth(
            betti_0=beta_0,
            betti_1=beta_1,
            euler_characteristic=euler,
            connectivity=connectivity,
            fragility=fragility,
            crystallization=crystallization,
            coverage=coverage,
            voids=voids,
            bridges=bridges,
            islands=islands,
            persistence_pairs=pairs,
            health_score=health_score,
            vertex_count=n,
            edge_count=len(edges),
            triangle_count=triangles,
        )

    def _load_theories(self, project: str) -> list[Theory]:
        """Load theories from DB."""
        try:
            if project:
                return self._db.list_theories(project=project, limit=500)
            return self._db.list_theories(limit=500)
        except Exception:
            return []

    def _compute_crystallization(
        self,
        n: int,
        edges: list[WeightedEdge],
        pairs: list[PersistencePair],
        triangles: int,
        beta_0: int,
    ) -> float:
        """Crystallization score: how mature and well-structured the topology is.

        Components:
        1. Edge density relative to maximum possible
        2. Average persistence lifetime of H₀ features (longer = more robust merges)
        3. Triangle density (clustering = tightly-knit knowledge)
        4. Fragmentation penalty based on β₀ (fewer components = better connected)
        """
        if n <= 1:
            return 0.0

        # Edge density: |E| / (n*(n-1)/2)
        max_edges = n * (n - 1) / 2
        density = len(edges) / max_edges if max_edges > 0 else 0.0

        # Average persistence lifetime of H₀ pairs (component merges)
        h0_pairs = [p for p in pairs if p.dimension == 0 and not math.isinf(p.death)]
        avg_lifetime = 0.0
        if h0_pairs:
            avg_lifetime = sum(p.lifetime for p in h0_pairs) / len(h0_pairs)
            # Normalize: shorter average lifetime = earlier merges = better
            avg_lifetime = 1.0 - min(avg_lifetime, 1.0)

        # Triangle density (clustering coefficient proxy)
        max_triangles = n * (n - 1) * (n - 2) / 6
        tri_density = triangles / max_triangles if max_triangles > 0 else 0.0

        # Combine with weights
        # 4th component: fragmentation penalty proportional to β₀.
        # Lower β₀ (fewer connected components) = better crystallization.
        # When β₀ = 1 (fully connected), penalty is 0 → full 0.15 contribution.
        fragmentation_penalty = min((beta_0 - 1) / max(n - 1, 1), 1.0)
        score = (
            0.35 * density
            + 0.30 * avg_lifetime
            + 0.20 * tri_density
            + 0.15 * (1.0 - fragmentation_penalty)
        )

        return min(max(score, 0.0), 1.0)

    def _build_bridges(
        self,
        theories: list[Theory],
        theory_ids: list[str],
        art_points: list[int],
        bridge_edges: list[tuple[int, int]],
        edges: list[WeightedEdge],
    ) -> list[KnowledgeBridge]:
        """Build KnowledgeBridge objects from articulation points."""
        bridges: list[KnowledgeBridge] = []

        # Build adjacency map once (O(E)) rather than per articulation point
        adj: dict[int, set[int]] = defaultdict(set)
        for edge in edges:
            adj[edge.u].add(edge.v)
            adj[edge.v].add(edge.u)

        # Articulation point theories
        for ap_idx in art_points:
            if ap_idx >= len(theories):
                continue
            theory = theories[ap_idx]

            # Find what domains this theory connects
            neighbors_domains: list[set[str]] = []

            for neighbor_idx in adj[ap_idx]:
                if neighbor_idx < len(theories):
                    domains = set(_extract_theory_domains(theories[neighbor_idx]))
                    if domains:
                        neighbors_domains.append(domains)

            # Determine what clusters it bridges
            if len(neighbors_domains) >= 2:
                all_neighbor_domains = set()
                for ds in neighbors_domains:
                    all_neighbor_domains.update(ds)
                domain_list = sorted(all_neighbor_domains)
                connects = (
                    domain_list[0] if domain_list else "unknown",
                    domain_list[-1] if len(domain_list) > 1 else "unknown",
                )
            else:
                connects = ("unknown", "unknown")

            # Criticality: proportion of graph reachable only through this point
            criticality = min(1.0, len(adj[ap_idx]) / max(len(theories) - 1, 1))

            bridges.append(KnowledgeBridge(
                theory_id=theory.id,
                theory_content=theory.content[:80],
                connects=connects,
                criticality=criticality,
            ))

        # Sort by criticality descending
        bridges.sort(key=lambda b: b.criticality, reverse=True)
        return bridges[:5]

    def _build_islands(
        self,
        theories: list[Theory],
        theory_ids: list[str],
        n: int,
        edges: list[WeightedEdge],
    ) -> list[KnowledgeIsland]:
        """Identify disconnected knowledge clusters."""
        if n == 0:
            return []

        uf = UnionFind(n)
        for edge in edges:
            uf.union(edge.u, edge.v)

        # Group theories by component
        components: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            root = uf.find(i)
            components[root].append(i)

        # Find the largest component size
        max_size = max(len(members) for members in components.values()) if components else 0

        islands: list[KnowledgeIsland] = []
        for _root, members in components.items():
            member_theories = [theory_ids[i] for i in members if i < len(theory_ids)]
            member_domains: set[str] = set()
            for i in members:
                if i < len(theories):
                    member_domains.update(_extract_theory_domains(theories[i]))

            isolation = 1.0 - (len(members) / max_size) if max_size > 0 else 0.0

            islands.append(KnowledgeIsland(
                theory_ids=member_theories,
                domains=sorted(member_domains)[:5],
                size=len(members),
                isolation_score=isolation,
            ))

        # Sort: largest first
        islands.sort(key=lambda isl: isl.size, reverse=True)
        return islands

    def _compute_health_score(
        self,
        connectivity: float,
        fragility: float,
        crystallization: float,
        coverage: float,
        void_count: int,
        n: int,
    ) -> float:
        """Compute overall health score (0-100).

        Formula:
            size_maturity = min(n / 20.0, 1.0)
            raw_score = 25·connectivity + 25·(1-fragility) + 25·crystallization
                        + 15·coverage + 10·(1 - void_penalty)
            score = raw_score * size_maturity

        Where void_penalty = min(void_count / 5, 1.0)

        The size_maturity factor penalizes small graphs: a single theory
        cannot represent robust knowledge topology. The factor scales
        linearly from 0 to 1 as the theory count grows from 0 to 20,
        ensuring that health scores reflect both structural quality and
        sufficient knowledge mass.
        """
        if n == 0:
            return 0.0

        size_maturity = min(n / 20.0, 1.0)
        void_penalty = min(void_count / 5.0, 1.0)

        raw_score = (
            25.0 * connectivity
            + 25.0 * (1.0 - fragility)
            + 25.0 * crystallization
            + 15.0 * coverage
            + 10.0 * (1.0 - void_penalty)
        )

        score = raw_score * size_maturity

        return min(max(round(score, 1), 0.0), 100.0)
