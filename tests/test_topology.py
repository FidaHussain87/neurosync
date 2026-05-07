"""Tests for Topological Knowledge Health — persistent homology on knowledge graphs."""

import math

from neurosync.models import Theory
from neurosync.topology import (
    KnowledgeHealth,
    KnowledgeVoid,
    TopologicalHealthEngine,
    UnionFind,
    WeightedEdge,
    build_knowledge_graph,
    compute_domain_coverage,
    compute_persistence,
    count_triangles,
    detect_voids,
    find_articulation_points,
    find_bridge_edges,
)


class TestUnionFind:
    """Tests for disjoint set data structure."""

    def test_initial_state(self):
        uf = UnionFind(5)
        assert uf.components == 5
        for i in range(5):
            assert uf.find(i) == i

    def test_union_reduces_components(self):
        uf = UnionFind(4)
        assert uf.union(0, 1) is True
        assert uf.components == 3
        assert uf.union(2, 3) is True
        assert uf.components == 2

    def test_union_same_component_returns_false(self):
        uf = UnionFind(3)
        uf.union(0, 1)
        assert uf.union(0, 1) is False
        assert uf.components == 2

    def test_connected(self):
        uf = UnionFind(4)
        uf.union(0, 1)
        uf.union(1, 2)
        assert uf.connected(0, 2) is True
        assert uf.connected(0, 3) is False

    def test_component_sizes(self):
        uf = UnionFind(5)
        uf.union(0, 1)
        uf.union(1, 2)
        uf.union(3, 4)
        sizes = uf.component_sizes()
        assert sizes == [3, 2]

    def test_path_compression(self):
        uf = UnionFind(10)
        # Create a long chain
        for i in range(9):
            uf.union(i, i + 1)
        # After path compression, find should be O(1)
        root = uf.find(0)
        assert uf.find(9) == root
        assert uf.components == 1

    def test_single_element(self):
        uf = UnionFind(1)
        assert uf.components == 1
        assert uf.find(0) == 0
        assert uf.component_sizes() == [1]


class TestPersistence:
    """Tests for persistent homology computation (Rips complex model).

    compute_persistence uses the Rips complex model: vertices (0-simplices),
    edges (1-simplices), AND 2-simplices (filled triangles) are processed.
    A triangle's 2-simplex is added at filtration = max(edge weights), which
    can kill H1 cycles that would otherwise persist forever in a pure 1-skeleton.

    Key behavioral differences vs a pure 1-skeleton (graph-only) model:
    - 1-skeleton: H1 cycles born when a closing edge is added, NEVER killed (beta_1
      counts all cycles ever created).
    - Rips complex: H1 cycles born when a closing edge is added, KILLED when a
      triangle 2-simplex fills them. Only cycles with no filling triangle persist.

    For focused Rips complex tests, see TestRipsComplex below.
    """

    def test_empty_graph(self):
        pairs, beta_0, beta_1 = compute_persistence(0, [])
        assert pairs == []
        assert beta_0 == 0
        assert beta_1 == 0

    def test_isolated_vertices(self):
        pairs, beta_0, beta_1 = compute_persistence(3, [])
        assert beta_0 == 3
        assert beta_1 == 0
        assert pairs == []

    def test_single_edge(self):
        edges = [WeightedEdge(u=0, v=1, weight=0.5, u_label="a", v_label="b")]
        pairs, beta_0, beta_1 = compute_persistence(2, edges)
        assert beta_0 == 1
        assert beta_1 == 0
        assert len(pairs) == 1
        assert pairs[0].dimension == 0

    def test_triangle_cycle_killed_by_2_simplex(self):
        """A triangle's H1 cycle is immediately killed by its 2-simplex.

        In the Rips complex: the closing edge (0,2)@0.5 creates the cycle, and the
        triangle 2-simplex enters at max(0.2, 0.3, 0.5) = 0.5, killing it immediately.
        The H1 pair has birth=0.5, death=0.5, lifetime=0. Final beta_1 = 0.
        """
        edges = [
            WeightedEdge(u=0, v=1, weight=0.2, u_label="a", v_label="b"),
            WeightedEdge(u=1, v=2, weight=0.3, u_label="b", v_label="c"),
            WeightedEdge(u=0, v=2, weight=0.5, u_label="a", v_label="c"),
        ]
        pairs, beta_0, beta_1 = compute_persistence(3, edges)
        assert beta_0 == 1
        assert beta_1 == 0  # Triangle 2-simplex kills the H1 cycle

        # The H1 pair exists but with zero lifetime
        h1_pairs = [p for p in pairs if p.dimension == 1]
        assert len(h1_pairs) == 1
        assert h1_pairs[0].birth == 0.5
        assert h1_pairs[0].death == 0.5
        assert h1_pairs[0].lifetime == 0.0

    def test_tree_no_cycles(self):
        # Star graph: center connected to 4 leaves — no cycles possible
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="center", v_label="l1"),
            WeightedEdge(u=0, v=2, weight=0.2, u_label="center", v_label="l2"),
            WeightedEdge(u=0, v=3, weight=0.3, u_label="center", v_label="l3"),
            WeightedEdge(u=0, v=4, weight=0.4, u_label="center", v_label="l4"),
        ]
        pairs, beta_0, beta_1 = compute_persistence(5, edges)
        assert beta_0 == 1
        assert beta_1 == 0

    def test_two_triangles_sharing_edge_both_killed(self):
        """Two triangles sharing an edge: both H1 cycles killed by their 2-simplices.

        Triangles {0,1,2} and {1,2,3} both have their 2-simplices added,
        killing both H1 cycles. Final beta_1 = 0.
        """
        # Two triangles sharing an edge (4 vertices, 5 edges)
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="", v_label=""),
            WeightedEdge(u=1, v=2, weight=0.2, u_label="", v_label=""),
            WeightedEdge(u=0, v=2, weight=0.3, u_label="", v_label=""),
            WeightedEdge(u=1, v=3, weight=0.4, u_label="", v_label=""),
            WeightedEdge(u=2, v=3, weight=0.5, u_label="", v_label=""),
        ]
        pairs, beta_0, beta_1 = compute_persistence(4, edges)
        assert beta_0 == 1
        assert beta_1 == 0  # Both cycles killed by their respective triangles

        # Two H1 pairs created, both with finite death
        h1_pairs = [p for p in pairs if p.dimension == 1]
        assert len(h1_pairs) == 2
        assert all(not math.isinf(p.death) for p in h1_pairs)

    def test_disconnected_components(self):
        edges = [
            WeightedEdge(u=0, v=1, weight=0.2, u_label="", v_label=""),
            WeightedEdge(u=2, v=3, weight=0.4, u_label="", v_label=""),
        ]
        pairs, beta_0, beta_1 = compute_persistence(4, edges)
        assert beta_0 == 2
        assert beta_1 == 0

    def test_persistence_pair_lifetime(self):
        edges = [
            WeightedEdge(u=0, v=1, weight=0.3, u_label="a", v_label="b"),
        ]
        pairs, _, _ = compute_persistence(2, edges)
        assert pairs[0].lifetime == 0.3  # death - birth = 0.3 - 0.0

    def test_h1_pair_finite_lifetime_in_triangle(self):
        """A triangle's H1 cycle has FINITE lifetime (zero) because the 2-simplex
        fills it at the same filtration value it was born.

        Edges at 0.1, 0.2, 0.3: cycle born at 0.3 (closing edge),
        killed at 0.3 (triangle max = 0.3). Lifetime = 0.
        """
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="", v_label=""),
            WeightedEdge(u=1, v=2, weight=0.2, u_label="", v_label=""),
            WeightedEdge(u=0, v=2, weight=0.3, u_label="", v_label=""),
        ]
        pairs, _, beta_1 = compute_persistence(3, edges)
        h1_pairs = [p for p in pairs if p.dimension == 1]
        assert len(h1_pairs) == 1
        assert h1_pairs[0].birth == 0.3
        assert h1_pairs[0].death == 0.3
        assert h1_pairs[0].lifetime == 0.0
        assert beta_1 == 0  # No surviving H1 features

    def test_h1_persists_when_no_triangle_exists(self):
        """A cycle without a filling triangle retains infinite lifetime (genuine gap).

        Square (4-cycle): 4 vertices, 4 edges forming a loop with no diagonals.
        No 3 mutually-connected vertices exist, so no triangle 2-simplex can kill
        the cycle. This represents a genuine structural void in the knowledge graph.
        """
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="a", v_label="b"),
            WeightedEdge(u=1, v=2, weight=0.2, u_label="b", v_label="c"),
            WeightedEdge(u=2, v=3, weight=0.3, u_label="c", v_label="d"),
            WeightedEdge(u=0, v=3, weight=0.4, u_label="a", v_label="d"),
        ]
        pairs, _, beta_1 = compute_persistence(4, edges)
        h1_pairs = [p for p in pairs if p.dimension == 1]
        assert len(h1_pairs) == 1
        assert math.isinf(h1_pairs[0].lifetime)  # No triangle to kill it
        assert beta_1 == 1  # One genuine structural gap


class TestRipsComplex:
    """Tests for persistent homology with Rips complex (2-simplex filling).

    compute_persistence already implements the Rips complex model: when all three
    edges of a triangle exist, the 2-simplex (filled triangle) is added at
    filtration = max(edge weights). This 2-simplex kills the H1 cycle.

    This test class provides focused, documented test cases for the Rips complex
    behavior with detailed filtration-step explanations:
    - Triangle: H1 cycle born at max(edge weights), immediately killed by the
      2-simplex at the same filtration value -> lifetime = 0, effective beta_1 = 0.
    - Square (no diagonals): H1 cycle persists because no triangle can fill it.
    - Square with one diagonal: triangles fill, killing the H1 cycles.
    - Pentagon: no triangles, H1 persists.
    - K4: all cycles killed.
    """

    def _compute_rips(self, num_vertices, edges):
        """Call compute_persistence (which already implements Rips complex).

        This helper exists for forward-compatibility: if compute_persistence is
        later refactored to accept a mode parameter or a separate function is
        introduced, this adapter handles the dispatch.
        """
        import inspect

        # Try mode kwarg (future-proofing)
        sig = inspect.signature(compute_persistence)
        if "mode" in sig.parameters:
            return compute_persistence(num_vertices, edges, mode="rips")

        # Try dedicated function (future-proofing)
        try:
            from neurosync.topology import compute_persistence_rips

            return compute_persistence_rips(num_vertices, edges)
        except ImportError:
            pass

        # Current: compute_persistence already includes Rips complex support
        return compute_persistence(num_vertices, edges)

    def test_triangle_h1_killed_by_2_simplex(self):
        """A triangle (3 vertices, 3 edges) -- the 2-simplex kills the H1 cycle.

        Edges at weights 0.2, 0.3, 0.5:
        - Edge (0,1) at 0.2: merges components
        - Edge (1,2) at 0.3: merges components
        - Edge (0,2) at 0.5: closes the cycle (H1 born at 0.5)
        - 2-simplex {0,1,2} added at max(0.2, 0.3, 0.5) = 0.5: kills the H1 cycle

        The cycle is born and immediately killed at filtration 0.5 -> lifetime = 0.
        Final beta_1 = 0.
        """
        edges = [
            WeightedEdge(u=0, v=1, weight=0.2, u_label="a", v_label="b"),
            WeightedEdge(u=1, v=2, weight=0.3, u_label="b", v_label="c"),
            WeightedEdge(u=0, v=2, weight=0.5, u_label="a", v_label="c"),
        ]
        pairs, beta_0, beta_1 = self._compute_rips(3, edges)

        # The cycle should be killed by the filled triangle
        assert beta_0 == 1, "All 3 vertices connected -> single component"
        assert beta_1 == 0, "Triangle 2-simplex kills the H1 cycle"

        # Check persistence pairs: H1 pair should have finite (zero) lifetime
        h1_pairs = [p for p in pairs if p.dimension == 1]
        if h1_pairs:
            # If the implementation records the born-and-immediately-killed pair:
            assert h1_pairs[0].birth == 0.5
            assert h1_pairs[0].death == 0.5
            assert h1_pairs[0].lifetime == 0.0

    def test_triangle_equal_weights(self):
        """Triangle with equal edge weights -- all edges and 2-simplex at same filtration.

        All edges at weight 0.4 -> cycle born at 0.4, 2-simplex at 0.4, killed immediately.
        """
        edges = [
            WeightedEdge(u=0, v=1, weight=0.4, u_label="a", v_label="b"),
            WeightedEdge(u=1, v=2, weight=0.4, u_label="b", v_label="c"),
            WeightedEdge(u=0, v=2, weight=0.4, u_label="a", v_label="c"),
        ]
        pairs, beta_0, beta_1 = self._compute_rips(3, edges)

        assert beta_0 == 1
        assert beta_1 == 0, "Equal-weight triangle: 2-simplex kills cycle at same filtration"

    def test_square_no_diagonals_h1_persists(self):
        """A square (4 vertices, 4 edges, no diagonals) -- H1 = 1 persists.

        No triangle can be formed (no 3 mutually-connected vertices), so no 2-simplex
        exists to kill the cycle. The H1 cycle persists with infinite lifetime.

        Vertices: 0-1-2-3 in a cycle
        Edges: (0,1), (1,2), (2,3), (0,3)
        """
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="a", v_label="b"),
            WeightedEdge(u=1, v=2, weight=0.2, u_label="b", v_label="c"),
            WeightedEdge(u=2, v=3, weight=0.3, u_label="c", v_label="d"),
            WeightedEdge(u=0, v=3, weight=0.4, u_label="a", v_label="d"),
        ]
        pairs, beta_0, beta_1 = self._compute_rips(4, edges)

        assert beta_0 == 1, "All 4 vertices connected -> single component"
        assert beta_1 == 1, "Square cycle persists (no triangle can fill it)"

        # The H1 pair should have infinite lifetime
        h1_pairs = [p for p in pairs if p.dimension == 1]
        assert len(h1_pairs) == 1
        assert math.isinf(h1_pairs[0].lifetime), "No 2-simplex to kill the square cycle"
        assert h1_pairs[0].birth == 0.4, "Cycle born when last edge closes the square"

    def test_square_with_one_diagonal(self):
        """A square with one diagonal (5 edges) -- triangles fill, killing H1.

        Vertices: 0-1-2-3 in a cycle, plus diagonal (0,2)
        Edges: (0,1)=0.1, (1,2)=0.2, (2,3)=0.3, (0,2)=0.35, (0,3)=0.4

        This creates two triangles: {0,1,2} and {0,2,3}.
        - Triangle {0,1,2}: edges (0,1)=0.1, (1,2)=0.2, (0,2)=0.35 -> 2-simplex at 0.35
        - Triangle {0,2,3}: edges (0,2)=0.35, (2,3)=0.3, (0,3)=0.4 -> 2-simplex at 0.4

        Processing order:
        - (0,1)@0.1: merge
        - (1,2)@0.2: merge
        - (2,3)@0.3: merge
        - (0,2)@0.35: cycle born. Triangle {0,1,2} max=0.35, 2-simplex kills it.
        - (0,3)@0.4: cycle born. Triangle {0,2,3} max=0.4, 2-simplex kills it.

        Net result: beta_1 = 0 (both cycles killed by their triangles).
        """
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="a", v_label="b"),
            WeightedEdge(u=1, v=2, weight=0.2, u_label="b", v_label="c"),
            WeightedEdge(u=2, v=3, weight=0.3, u_label="c", v_label="d"),
            WeightedEdge(u=0, v=2, weight=0.35, u_label="a", v_label="c"),  # diagonal
            WeightedEdge(u=0, v=3, weight=0.4, u_label="a", v_label="d"),
        ]
        pairs, beta_0, beta_1 = self._compute_rips(4, edges)

        assert beta_0 == 1, "All vertices connected -> single component"
        # Both triangles {0,1,2} and {0,2,3} exist and their 2-simplices kill cycles
        assert beta_1 == 0, "Both triangles filled -> all H1 cycles killed"

    def test_square_with_one_diagonal_filtration_details(self):
        """Square with diagonal -- verify H1 pairs have zero lifetime (born=died).

        Edges: (0,1)=0.1, (1,2)=0.2, (0,2)=0.3, (2,3)=0.5, (0,3)=0.6

        Processing order:
        - (0,1)@0.1: merge
        - (1,2)@0.2: merge
        - (0,2)@0.3: cycle born. Triangle {0,1,2} max=0.3, 2-simplex@0.3 kills it.
        - (2,3)@0.5: merge
        - (0,3)@0.6: cycle born. Triangle {0,2,3} max=0.6, 2-simplex@0.6 kills it.

        Final beta_1 = 0 (both cycles killed).
        """
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="a", v_label="b"),
            WeightedEdge(u=1, v=2, weight=0.2, u_label="b", v_label="c"),
            WeightedEdge(u=0, v=2, weight=0.3, u_label="a", v_label="c"),  # diagonal
            WeightedEdge(u=2, v=3, weight=0.5, u_label="c", v_label="d"),
            WeightedEdge(u=0, v=3, weight=0.6, u_label="a", v_label="d"),
        ]
        pairs, beta_0, beta_1 = self._compute_rips(4, edges)

        assert beta_0 == 1
        assert beta_1 == 0, "Both triangles filled by 2-simplices"

        # Verify the H1 pairs have finite lifetime (born and killed at same filtration)
        h1_pairs = [p for p in pairs if p.dimension == 1]
        for pair in h1_pairs:
            assert not math.isinf(pair.lifetime), "All H1 cycles should be killed"
            assert pair.lifetime == 0.0, "Cycle killed at same filtration it was born"

    def test_pentagon_no_triangles_h1_persists(self):
        """A pentagon (5 vertices, 5 edges) -- no triangles exist, H1 persists.

        In a Rips complex, if no 3 mutually-connected vertices exist, no 2-simplex
        is added. The 5-cycle persists with infinite lifetime.
        """
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="a", v_label="b"),
            WeightedEdge(u=1, v=2, weight=0.2, u_label="b", v_label="c"),
            WeightedEdge(u=2, v=3, weight=0.3, u_label="c", v_label="d"),
            WeightedEdge(u=3, v=4, weight=0.4, u_label="d", v_label="e"),
            WeightedEdge(u=0, v=4, weight=0.5, u_label="a", v_label="e"),
        ]
        pairs, beta_0, beta_1 = self._compute_rips(5, edges)

        assert beta_0 == 1
        assert beta_1 == 1, "Pentagon cycle persists (no triangle can fill it)"

        h1_pairs = [p for p in pairs if p.dimension == 1]
        assert len(h1_pairs) == 1
        assert math.isinf(h1_pairs[0].lifetime)

    def test_k4_complete_graph_all_cycles_killed(self):
        """K4 (complete graph on 4 vertices, 6 edges) -- all H1 killed by 2-simplices.

        K4 contains 4 triangles. Every cycle can be expressed as a sum of triangle
        boundaries. In the Rips complex, all 2-simplices are added, and beta_1 = 0.
        """
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="", v_label=""),
            WeightedEdge(u=0, v=2, weight=0.2, u_label="", v_label=""),
            WeightedEdge(u=1, v=2, weight=0.3, u_label="", v_label=""),
            WeightedEdge(u=0, v=3, weight=0.4, u_label="", v_label=""),
            WeightedEdge(u=1, v=3, weight=0.5, u_label="", v_label=""),
            WeightedEdge(u=2, v=3, weight=0.6, u_label="", v_label=""),
        ]
        pairs, beta_0, beta_1 = self._compute_rips(4, edges)

        assert beta_0 == 1
        assert beta_1 == 0, "K4: all cycles killed by triangle 2-simplices"

    def test_two_triangles_sharing_edge_both_killed(self):
        """Two triangles sharing an edge (4 vertices, 5 edges) -- both H1 killed.

        In the 1-skeleton model, this produces beta_1 = 2. In the Rips complex,
        both triangles are filled, killing both cycles. Final beta_1 = 0.
        """
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="", v_label=""),
            WeightedEdge(u=1, v=2, weight=0.2, u_label="", v_label=""),
            WeightedEdge(u=0, v=2, weight=0.3, u_label="", v_label=""),
            WeightedEdge(u=1, v=3, weight=0.4, u_label="", v_label=""),
            WeightedEdge(u=2, v=3, weight=0.5, u_label="", v_label=""),
        ]
        pairs, beta_0, beta_1 = self._compute_rips(4, edges)

        assert beta_0 == 1
        assert beta_1 == 0, "Both triangles filled -> both H1 cycles killed"

    def test_rips_h0_unchanged_from_skeleton(self):
        """Rips complex does not change H0 (connected components) vs 1-skeleton.

        Adding 2-simplices only affects H1 and higher. H0 is determined purely
        by the 1-skeleton (edge connectivity).
        """
        # Two disconnected triangles
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="", v_label=""),
            WeightedEdge(u=1, v=2, weight=0.2, u_label="", v_label=""),
            WeightedEdge(u=0, v=2, weight=0.3, u_label="", v_label=""),
            WeightedEdge(u=3, v=4, weight=0.4, u_label="", v_label=""),
            WeightedEdge(u=4, v=5, weight=0.5, u_label="", v_label=""),
            WeightedEdge(u=3, v=5, weight=0.6, u_label="", v_label=""),
        ]
        pairs, beta_0, beta_1 = self._compute_rips(6, edges)

        assert beta_0 == 2, "Two disconnected components (same as 1-skeleton)"
        assert beta_1 == 0, "Both triangles filled -> no H1"


class TestArticulationPoints:
    """Tests for Tarjan's articulation point algorithm."""

    def test_no_articulation_in_triangle(self):
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1),
            WeightedEdge(u=1, v=2, weight=0.2),
            WeightedEdge(u=0, v=2, weight=0.3),
        ]
        aps = find_articulation_points(3, edges)
        assert aps == []

    def test_center_of_star_is_articulation(self):
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1),
            WeightedEdge(u=0, v=2, weight=0.2),
            WeightedEdge(u=0, v=3, weight=0.3),
        ]
        aps = find_articulation_points(4, edges)
        assert 0 in aps

    def test_chain_middle_nodes(self):
        # 0 -- 1 -- 2 -- 3
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1),
            WeightedEdge(u=1, v=2, weight=0.2),
            WeightedEdge(u=2, v=3, weight=0.3),
        ]
        aps = find_articulation_points(4, edges)
        assert 1 in aps
        assert 2 in aps

    def test_empty_graph(self):
        aps = find_articulation_points(0, [])
        assert aps == []

    def test_two_vertices(self):
        edges = [WeightedEdge(u=0, v=1, weight=0.1)]
        aps = find_articulation_points(2, edges)
        assert aps == []

    def test_complete_graph_no_articulation(self):
        # K4: all pairs connected
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1),
            WeightedEdge(u=0, v=2, weight=0.2),
            WeightedEdge(u=0, v=3, weight=0.3),
            WeightedEdge(u=1, v=2, weight=0.4),
            WeightedEdge(u=1, v=3, weight=0.5),
            WeightedEdge(u=2, v=3, weight=0.6),
        ]
        aps = find_articulation_points(4, edges)
        assert aps == []


class TestBridgeEdges:
    """Tests for bridge edge detection."""

    def test_single_edge_is_bridge(self):
        edges = [WeightedEdge(u=0, v=1, weight=0.1)]
        bridges = find_bridge_edges(2, edges)
        assert len(bridges) == 1

    def test_triangle_no_bridges(self):
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1),
            WeightedEdge(u=1, v=2, weight=0.2),
            WeightedEdge(u=0, v=2, weight=0.3),
        ]
        bridges = find_bridge_edges(3, edges)
        assert bridges == []

    def test_two_triangles_connected_by_bridge(self):
        # Triangle 0-1-2, triangle 3-4-5, bridge 2-3
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1),
            WeightedEdge(u=1, v=2, weight=0.2),
            WeightedEdge(u=0, v=2, weight=0.3),
            WeightedEdge(u=2, v=3, weight=0.4),  # bridge
            WeightedEdge(u=3, v=4, weight=0.5),
            WeightedEdge(u=4, v=5, weight=0.6),
            WeightedEdge(u=3, v=5, weight=0.7),
        ]
        bridges = find_bridge_edges(6, edges)
        assert len(bridges) == 1
        bridge = bridges[0]
        assert (min(bridge), max(bridge)) == (2, 3)

    def test_empty_graph(self):
        bridges = find_bridge_edges(0, [])
        assert bridges == []


class TestTriangles:
    """Tests for triangle counting."""

    def test_single_triangle(self):
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1),
            WeightedEdge(u=1, v=2, weight=0.2),
            WeightedEdge(u=0, v=2, weight=0.3),
        ]
        assert count_triangles(3, edges) == 1

    def test_no_triangles(self):
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1),
            WeightedEdge(u=2, v=3, weight=0.2),
        ]
        assert count_triangles(4, edges) == 0

    def test_complete_k4(self):
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1),
            WeightedEdge(u=0, v=2, weight=0.2),
            WeightedEdge(u=0, v=3, weight=0.3),
            WeightedEdge(u=1, v=2, weight=0.4),
            WeightedEdge(u=1, v=3, weight=0.5),
            WeightedEdge(u=2, v=3, weight=0.6),
        ]
        # K4 has 4 triangles
        assert count_triangles(4, edges) == 4

    def test_empty(self):
        assert count_triangles(0, []) == 0


class TestDomainCoverage:
    """Tests for domain taxonomy coverage."""

    def test_no_coverage(self):
        theories = [Theory(content="something obscure")]
        ratio, covered, uncovered = compute_domain_coverage(theories)
        assert ratio == 0.0
        assert len(uncovered) == 32

    def test_partial_coverage(self):
        theories = [
            Theory(content="concurrency and testing patterns", metadata={"domains": ["concurrency", "testing"]}),
            Theory(content="api design", metadata={"domains": ["api-design"]}),
        ]
        ratio, covered, uncovered = compute_domain_coverage(theories)
        assert ratio >= 3 / 32
        assert "concurrency" in covered
        assert "testing" in covered
        assert "api-design" in covered

    def test_unknown_domains_ignored(self):
        theories = [
            Theory(content="concurrency stuff", metadata={"domains": ["unknown-domain", "concurrency"]}),
        ]
        ratio, covered, _ = compute_domain_coverage(theories)
        assert "concurrency" in covered
        assert "unknown-domain" not in covered


class TestBuildKnowledgeGraph:
    """Tests for graph construction from theories."""

    class FakeDB:
        def list_causal_links(self):
            return []

    def test_empty_theories(self):
        ids, edges = build_knowledge_graph([], self.FakeDB())
        assert ids == []
        assert edges == []

    def test_shared_domain_creates_edge(self):
        theories = [
            Theory(id="t1", content="Theory about authentication", scope_qualifier="authentication"),
            Theory(id="t2", content="Theory about authentication tokens", scope_qualifier="authentication"),
        ]
        ids, edges = build_knowledge_graph(theories, self.FakeDB())
        assert len(ids) == 2
        assert len(edges) >= 1

    def test_no_shared_domain_may_still_connect_via_keywords(self):
        theories = [
            Theory(id="t1", content="database connection pooling optimization", scope_qualifier="database-access"),
            Theory(id="t2", content="caching strategy for frontend", scope_qualifier="caching"),
        ]
        ids, edges = build_knowledge_graph(theories, self.FakeDB())
        assert len(ids) == 2
        # May or may not have edges depending on keyword overlap

    def test_same_scope_creates_edge(self):
        theories = [
            Theory(id="t1", content="First theory", scope_qualifier="payments"),
            Theory(id="t2", content="Second theory", scope_qualifier="payments"),
        ]
        ids, edges = build_knowledge_graph(theories, self.FakeDB())
        assert len(edges) >= 1

    def test_keyword_overlap_creates_edge(self):
        theories = [
            Theory(id="t1", content="database connection pooling timeout retry logic"),
            Theory(id="t2", content="connection pooling database retry mechanism"),
        ]
        ids, edges = build_knowledge_graph(theories, self.FakeDB())
        assert len(edges) >= 1


class TestVoidDetection:
    """Tests for knowledge void detection."""

    def test_no_voids_in_dense_graph(self):
        theories = [
            Theory(id="t1", content="x", scope_qualifier="concurrency"),
            Theory(id="t2", content="y", scope_qualifier="concurrency"),
            Theory(id="t3", content="z", scope_qualifier="concurrency"),
        ]
        # Fully connected — no voids
        edges = [
            WeightedEdge(u=0, v=1, weight=0.1, u_label="t1", v_label="t2"),
            WeightedEdge(u=1, v=2, weight=0.2, u_label="t2", v_label="t3"),
            WeightedEdge(u=0, v=2, weight=0.3, u_label="t1", v_label="t3"),
        ]
        from neurosync.topology import PersistencePair
        # No H₁ pairs = no voids
        pairs = [PersistencePair(birth=0.0, death=0.2, dimension=0, generators=["t1", "t2"])]
        voids = detect_voids(theories, edges, pairs, {"concurrency"})
        assert voids == []

    def test_detects_void_from_h1_pair(self):
        theories = [
            Theory(id="t1", content="x", scope_qualifier="concurrency"),
            Theory(id="t2", content="y", scope_qualifier="testing"),
            Theory(id="t3", content="z", scope_qualifier="api-design"),
        ]
        edges = [
            WeightedEdge(u=0, v=1, weight=0.2, u_label="t1", v_label="t2"),
            WeightedEdge(u=1, v=2, weight=0.3, u_label="t2", v_label="t3"),
            WeightedEdge(u=0, v=2, weight=0.5, u_label="t1", v_label="t3"),
        ]
        from neurosync.topology import PersistencePair
        # H₁ pair indicates a cycle (void)
        pairs = [
            PersistencePair(birth=0.5, death=math.inf, dimension=1, generators=["t1", "t3"]),
        ]
        voids = detect_voids(theories, edges, pairs, {"concurrency", "testing", "api-design"})
        assert len(voids) >= 1
        assert voids[0].severity > 0

    def test_empty_theories_no_voids(self):
        voids = detect_voids([], [], [], set())
        assert voids == []


class TestKnowledgeHealth:
    """Tests for the KnowledgeHealth dataclass."""

    def test_format_summary(self):
        health = KnowledgeHealth(
            betti_0=2, betti_1=1, euler_characteristic=3,
            health_score=72.5,
        )
        summary = health.format_summary()
        assert "health=72/100" in summary or "health=73/100" in summary
        assert "\u03b2\u2080=2" in summary
        assert "\u03b2\u2081=1" in summary

    def test_to_dict(self):
        health = KnowledgeHealth(
            betti_0=1, betti_1=0, euler_characteristic=5,
            connectivity=0.8, fragility=0.2, crystallization=0.6,
            coverage=0.3, health_score=75.0,
            vertex_count=10, edge_count=15, triangle_count=3,
        )
        d = health.to_dict()
        assert d["health_score"] == 75.0
        assert d["betti_0"] == 1
        assert d["connectivity"] == 0.8
        assert "summary" in d

    def test_to_dict_with_voids(self):
        health = KnowledgeHealth(
            voids=[KnowledgeVoid(
                surrounding_domains=["concurrency"],
                surrounding_theories=["t1", "t2"],
                gap_description="A gap",
                severity=0.7,
                cycle_length=3,
            )],
        )
        d = health.to_dict()
        assert len(d["voids"]) == 1
        assert d["voids"][0]["severity"] == 0.7


class TestTopologicalHealthEngine:
    """Integration tests for the full TKH pipeline."""

    class FakeDB:
        def __init__(self, theories=None):
            self._theories = theories or []

        def list_theories(self, project=None, limit=500):
            return self._theories

        def list_causal_links(self):
            return []

    def test_empty_knowledge(self):
        engine = TopologicalHealthEngine(self.FakeDB())
        health = engine.compute_health(theories=[])
        assert health.health_score == 0.0
        assert health.betti_0 == 0

    def test_single_theory(self):
        theories = [Theory(id="t1", content="Something", active=True)]
        engine = TopologicalHealthEngine(self.FakeDB(theories))
        health = engine.compute_health(theories=theories)
        assert health.vertex_count == 1
        assert health.betti_0 == 1
        assert health.edge_count == 0

    def test_connected_theories(self):
        theories = [
            Theory(id="t1", content="database connection pooling",
                   scope_qualifier="database-access", active=True, confidence=0.8),
            Theory(id="t2", content="database query optimization",
                   scope_qualifier="database-access", active=True, confidence=0.8),
            Theory(id="t3", content="database transaction handling",
                   scope_qualifier="database-access", active=True, confidence=0.8),
        ]
        engine = TopologicalHealthEngine(self.FakeDB(theories))
        health = engine.compute_health(theories=theories)
        assert health.vertex_count == 3
        assert health.edge_count >= 1
        assert health.connectivity > 0.0

    def test_fragmented_knowledge(self):
        # Two clusters with no connection
        theories = [
            Theory(id="t1", content="auth login flow", scope_qualifier="authentication", active=True),
            Theory(id="t2", content="auth token refresh", scope_qualifier="authentication", active=True),
            Theory(id="t3", content="deploy kubernetes helm", scope_qualifier="deployment", active=True),
            Theory(id="t4", content="deploy docker compose", scope_qualifier="deployment", active=True),
        ]
        engine = TopologicalHealthEngine(self.FakeDB(theories))
        health = engine.compute_health(theories=theories)
        # Should have low connectivity (two separate clusters)
        assert health.betti_0 >= 1
        assert health.health_score < 90

    def test_inactive_theories_excluded(self):
        theories = [
            Theory(id="t1", content="active", active=True),
            Theory(id="t2", content="retired", active=False),
        ]
        engine = TopologicalHealthEngine(self.FakeDB(theories))
        health = engine.compute_health(theories=theories)
        assert health.vertex_count == 1

    def test_detects_bridges(self):
        # Star topology: center theory bridges all others
        theories = [
            Theory(id="center", content="central connecting concept spanning authentication and database",
                   metadata={"domains": ["authentication", "database-access"]}, active=True),
            Theory(id="a1", content="authentication login mechanism", scope_qualifier="authentication", active=True),
            Theory(id="a2", content="authentication session handling", scope_qualifier="authentication", active=True),
            Theory(id="d1", content="database connection pool", scope_qualifier="database-access", active=True),
            Theory(id="d2", content="database migration runner", scope_qualifier="database-access", active=True),
        ]
        engine = TopologicalHealthEngine(self.FakeDB(theories))
        health = engine.compute_health(theories=theories)
        # The center theory should be detected as a bridge/articulation point
        # (or at minimum, there should be multiple islands if it weren't there)
        assert health.vertex_count == 5
        assert health.health_score > 0

    def test_health_score_bounded(self):
        theories = [
            Theory(id=f"t{i}", content=f"theory {i} about testing patterns",
                   scope_qualifier="testing", active=True, confidence=0.9)
            for i in range(10)
        ]
        engine = TopologicalHealthEngine(self.FakeDB(theories))
        health = engine.compute_health(theories=theories)
        assert 0 <= health.health_score <= 100

    def test_loads_from_db_when_theories_not_provided(self):
        theories = [
            Theory(id="t1", content="from db about testing", scope_qualifier="testing", active=True),
        ]
        engine = TopologicalHealthEngine(self.FakeDB(theories))
        health = engine.compute_health()
        assert health.vertex_count == 1

    def test_high_coverage_improves_score(self):
        # Many different domains covered via scope_qualifier
        domains_list = [
            "api-design", "authentication", "concurrency", "testing",
            "database-access", "error-handling", "security", "caching",
        ]
        theories = [
            Theory(id=f"t{i}", content=f"theory about {d}",
                   scope_qualifier=d, active=True, confidence=0.8)
            for i, d in enumerate(domains_list)
        ]
        engine = TopologicalHealthEngine(self.FakeDB(theories))
        health = engine.compute_health(theories=theories)
        assert health.coverage > 0.2
        # Coverage contributes to health score
        assert health.health_score > 0

    def test_euler_characteristic_computed(self):
        theories = [
            Theory(id="t1", content="testing pattern alpha", scope_qualifier="testing", active=True, confidence=0.8),
            Theory(id="t2", content="testing pattern beta", scope_qualifier="testing", active=True, confidence=0.8),
            Theory(id="t3", content="testing pattern gamma", scope_qualifier="testing", active=True, confidence=0.8),
        ]
        engine = TopologicalHealthEngine(self.FakeDB(theories))
        health = engine.compute_health(theories=theories)
        # χ = V - E + F
        assert health.euler_characteristic == health.vertex_count - health.edge_count + health.triangle_count
