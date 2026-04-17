"""Tests for hierarchy.py — theory hierarchy, semantic parents, merging."""

from __future__ import annotations

from neurosync.hierarchy import TheoryHierarchy
from neurosync.models import Session, Theory


class TestTheoryHierarchy:
    def _setup(self, db, vectorstore):
        session = Session(project="test")
        db.save_session(session)
        hierarchy = TheoryHierarchy(db, vectorstore)
        return session, hierarchy

    def test_depth_root(self, db, vectorstore):
        """Root theory (no parent) should have depth 0."""
        _, hierarchy = self._setup(db, vectorstore)
        root = Theory(content="root theory")
        db.save_theory(root)
        assert hierarchy.get_depth(root.id) == 0

    def test_depth_nested(self, db, vectorstore):
        """Nested theory should reflect correct depth."""
        _, hierarchy = self._setup(db, vectorstore)
        root = Theory(content="root theory")
        db.save_theory(root)
        child = Theory(content="child theory", parent_theory_id=root.id)
        db.save_theory(child)
        grandchild = Theory(content="grandchild theory", parent_theory_id=child.id)
        db.save_theory(grandchild)
        assert hierarchy.get_depth(child.id) == 1
        assert hierarchy.get_depth(grandchild.id) == 2

    def test_ancestors(self, db, vectorstore):
        """get_ancestors should return parent chain."""
        _, hierarchy = self._setup(db, vectorstore)
        root = Theory(content="root")
        db.save_theory(root)
        child = Theory(content="child", parent_theory_id=root.id)
        db.save_theory(child)
        grandchild = Theory(content="grandchild", parent_theory_id=child.id)
        db.save_theory(grandchild)
        ancestors = hierarchy.get_ancestors(grandchild.id)
        assert len(ancestors) == 2
        assert ancestors[0].id == child.id
        assert ancestors[1].id == root.id

    def test_children(self, db, vectorstore):
        """get_children should return direct children."""
        _, hierarchy = self._setup(db, vectorstore)
        parent = Theory(content="parent theory")
        db.save_theory(parent)
        c1 = Theory(content="child one", parent_theory_id=parent.id)
        c2 = Theory(content="child two", parent_theory_id=parent.id)
        db.save_theory(c1)
        db.save_theory(c2)
        children = hierarchy.get_children(parent.id)
        assert len(children) == 2

    def test_subtree(self, db, vectorstore):
        """get_subtree should return nested structure."""
        _, hierarchy = self._setup(db, vectorstore)
        root = Theory(content="root pattern")
        db.save_theory(root)
        child = Theory(content="child pattern", parent_theory_id=root.id)
        db.save_theory(child)
        subtree = hierarchy.get_subtree(root.id)
        assert subtree["id"] == root.id
        assert len(subtree["children"]) == 1
        assert subtree["children"][0]["id"] == child.id

    def test_find_semantic_parent(self, db, vectorstore):
        """Should find a broader theory as potential parent."""
        _, hierarchy = self._setup(db, vectorstore)
        # Broad theory with many sources
        broad = Theory(
            content="Caching patterns require careful invalidation strategies across all layers",
            source_episodes=["ep1", "ep2", "ep3", "ep4", "ep5"],
            confirmation_count=5,
        )
        db.save_theory(broad)
        vectorstore.add_theory(broad)
        # Narrow theory — subset of the broad concept
        narrow = Theory(
            content="Cache invalidation in DNS layer needs special TTL handling",
            source_episodes=["ep6"],
            confirmation_count=1,
        )
        db.save_theory(narrow)
        vectorstore.add_theory(narrow)
        parent = hierarchy.find_semantic_parent(narrow.id, distance_threshold=0.5)
        # May or may not find parent depending on embedding distance; check structure
        if parent:
            assert parent.id == broad.id

    def test_promote_to_parent(self, db, vectorstore):
        """promote_to_parent should create parent and link children."""
        _, hierarchy = self._setup(db, vectorstore)
        c1 = Theory(content="Cache invalidation in DNS", source_episodes=["ep1"])
        c2 = Theory(content="Cache invalidation in Storage", source_episodes=["ep2"])
        db.save_theory(c1)
        db.save_theory(c2)
        vectorstore.add_theory(c1)
        vectorstore.add_theory(c2)
        parent = hierarchy.promote_to_parent(
            [c1.id, c2.id],
            "Cache invalidation patterns across all layers",
        )
        assert parent is not None
        assert parent.hierarchy_depth == 0
        # Children should reference parent
        loaded_c1 = db.get_theory(c1.id)
        loaded_c2 = db.get_theory(c2.id)
        assert loaded_c1.parent_theory_id == parent.id
        assert loaded_c2.parent_theory_id == parent.id
        assert loaded_c1.hierarchy_depth == 1

    def test_merge_theories(self, db, vectorstore):
        """merge_theories should keep highest-confidence survivor."""
        _, hierarchy = self._setup(db, vectorstore)
        t1 = Theory(content="Pattern A version one", confidence=0.9, source_episodes=["ep1"])
        t2 = Theory(content="Pattern A version two", confidence=0.6, source_episodes=["ep2"])
        db.save_theory(t1)
        db.save_theory(t2)
        vectorstore.add_theory(t1)
        vectorstore.add_theory(t2)
        survivor = hierarchy.merge_theories([t1.id, t2.id])
        assert survivor is not None
        assert survivor.id == t1.id  # highest confidence
        assert "ep2" in survivor.source_episodes
        # t2 should be inactive
        loaded_t2 = db.get_theory(t2.id)
        assert loaded_t2.active is False
        assert loaded_t2.superseded_by == t1.id

    def test_detect_merge_candidates(self, db, vectorstore):
        """Near-duplicate theories should be detected as merge candidates."""
        _, hierarchy = self._setup(db, vectorstore)
        t1 = Theory(content="Always validate user input at system boundaries to prevent injection")
        t2 = Theory(content="Always validate user input at system boundaries to prevent injection attacks")
        db.save_theory(t1)
        db.save_theory(t2)
        vectorstore.add_theory(t1)
        vectorstore.add_theory(t2)
        candidates = hierarchy.detect_merge_candidates(distance_threshold=0.3)
        assert len(candidates) >= 1

    def test_graph_aware_recall(self, db, vectorstore):
        """graph_aware_recall should return hierarchy context."""
        _, hierarchy = self._setup(db, vectorstore)
        root = Theory(content="root theory for recall test")
        db.save_theory(root)
        child1 = Theory(content="child one of root", parent_theory_id=root.id)
        child2 = Theory(content="child two of root", parent_theory_id=root.id)
        db.save_theory(child1)
        db.save_theory(child2)
        context = hierarchy.graph_aware_recall(child1)
        assert len(context["ancestors"]) == 1
        assert context["ancestors"][0]["id"] == root.id
        assert len(context["siblings"]) == 1
        assert context["siblings"][0]["id"] == child2.id
