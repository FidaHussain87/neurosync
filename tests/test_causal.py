"""Tests for causal.py — causal graph construction and querying."""

from __future__ import annotations

from neurosync.causal import CausalGraph
from neurosync.models import CausalLink, Episode, Session, Theory


class TestCausalGraph:
    def _setup(self, db, vectorstore):
        session = Session(project="test")
        db.save_session(session)
        graph = CausalGraph(db, vectorstore)
        return session, graph

    def test_extract_from_episode_direct(self, db, vectorstore):
        """Should extract a causal link from episode with cause/effect."""
        session, graph = self._setup(db, vectorstore)
        ep = Episode(
            session_id=session.id,
            event_type="causal",
            content="Missing index caused slow queries",
            cause="missing database index",
            effect="slow query performance",
            reasoning="Full table scan instead of index lookup",
        )
        db.save_episode(ep)
        link = graph.extract_link_from_episode(ep.id)
        assert link is not None
        assert link.cause_text == "missing database index"
        assert link.effect_text == "slow query performance"

    def test_mechanism_detection(self, db, vectorstore):
        """Should classify mechanism from reasoning text."""
        session, graph = self._setup(db, vectorstore)
        ep = Episode(
            session_id=session.id,
            content="Firewall rule prevents access",
            cause="firewall rule",
            effect="blocked access",
            reasoning="The rule prevents unauthorized connections",
        )
        db.save_episode(ep)
        link = graph.extract_link_from_episode(ep.id)
        assert link is not None
        assert link.mechanism == "preventing"

    def test_extract_from_theory(self, db, vectorstore):
        """Should extract links from 'When X, then Y because Z' theories."""
        session, graph = self._setup(db, vectorstore)
        theory = Theory(
            content="When cache TTL expires, then stale data is served because invalidation is async",
        )
        db.save_theory(theory)
        links = graph.extract_links_from_theory(theory.id)
        assert len(links) == 1
        assert links[0].cause_text == "cache TTL expires"
        assert "stale data" in links[0].effect_text

    def test_save_retrieve_link(self, db, vectorstore):
        """Should save and retrieve a causal link."""
        _, graph = self._setup(db, vectorstore)
        link = CausalLink(
            cause_text="high traffic",
            effect_text="increased latency",
            mechanism="direct",
            strength=0.8,
        )
        saved = graph.save_link(link)
        assert saved.id is not None
        loaded = db.get_causal_link(saved.id)
        assert loaded.cause_text == "high traffic"
        assert loaded.strength == 0.8

    def test_strengthen_link(self, db, vectorstore):
        """strengthen_link should increment observation count."""
        _, graph = self._setup(db, vectorstore)
        link = CausalLink(cause_text="X", effect_text="Y")
        saved = db.save_causal_link(link)
        graph.strengthen_link(saved.id, "ep-new")
        loaded = db.get_causal_link(saved.id)
        assert loaded.observation_count == 2
        assert "ep-new" in loaded.source_episode_ids

    def test_effects_depth_1(self, db, vectorstore):
        """get_effects_of should return direct effects."""
        _, graph = self._setup(db, vectorstore)
        db.save_causal_link(CausalLink(cause_text="A", effect_text="B"))
        db.save_causal_link(CausalLink(cause_text="B", effect_text="C"))
        effects = graph.get_effects_of("A", max_depth=1)
        assert len(effects) == 1
        assert effects[0].effect_text == "B"

    def test_effects_depth_2(self, db, vectorstore):
        """get_effects_of with depth 2 should return transitive effects."""
        _, graph = self._setup(db, vectorstore)
        db.save_causal_link(CausalLink(cause_text="A", effect_text="B"))
        db.save_causal_link(CausalLink(cause_text="B", effect_text="C"))
        effects = graph.get_effects_of("A", max_depth=2)
        effect_texts = {l.effect_text for l in effects}
        assert "B" in effect_texts
        assert "C" in effect_texts

    def test_causes_of(self, db, vectorstore):
        """get_causes_of should return upstream causes."""
        _, graph = self._setup(db, vectorstore)
        db.save_causal_link(CausalLink(cause_text="A", effect_text="B"))
        db.save_causal_link(CausalLink(cause_text="B", effect_text="C"))
        causes = graph.get_causes_of("C", max_depth=2)
        cause_texts = {l.cause_text for l in causes}
        assert "B" in cause_texts

    def test_causal_chain(self, db, vectorstore):
        """get_causal_chain should find path from A to C."""
        _, graph = self._setup(db, vectorstore)
        db.save_causal_link(CausalLink(cause_text="A", effect_text="B"))
        db.save_causal_link(CausalLink(cause_text="B", effect_text="C"))
        chain = graph.get_causal_chain("A", "C")
        assert chain is not None
        assert len(chain) == 2
        assert chain[0].cause_text == "A"
        assert chain[1].effect_text == "C"

    def test_common_causes(self, db, vectorstore):
        """find_common_causes should identify shared root causes."""
        _, graph = self._setup(db, vectorstore)
        db.save_causal_link(CausalLink(cause_text="bad config", effect_text="slow queries"))
        db.save_causal_link(CausalLink(cause_text="bad config", effect_text="timeout errors"))
        db.save_causal_link(CausalLink(cause_text="network issue", effect_text="timeout errors"))
        common = graph.find_common_causes(["slow queries", "timeout errors"])
        assert len(common) == 1
        assert common[0].cause_text == "bad config"

    def test_neighborhood(self, db, vectorstore):
        """get_causal_neighborhood should return upstream + downstream."""
        _, graph = self._setup(db, vectorstore)
        db.save_causal_link(CausalLink(cause_text="A", effect_text="B"))
        db.save_causal_link(CausalLink(cause_text="B", effect_text="C"))
        hood = graph.get_causal_neighborhood("B", radius=1)
        assert hood["concept"] == "B"
        assert len(hood["upstream"]) >= 1
        assert len(hood["downstream"]) >= 1

    def test_build_from_episodes(self, db, vectorstore):
        """build_from_episodes should process episodes with cause/effect."""
        session, graph = self._setup(db, vectorstore)
        ep1 = Episode(
            session_id=session.id, content="t1",
            cause="X", effect="Y", reasoning="because",
        )
        ep2 = Episode(
            session_id=session.id, content="t2",
            cause="", effect="",  # no causal data
        )
        db.save_episode(ep1)
        db.save_episode(ep2)
        result = graph.build_from_episodes()
        assert result["links_created"] == 1
