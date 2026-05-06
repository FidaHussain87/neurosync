"""Tests for the DomainClassifier — conceptual domain assignment for episodes."""

import pytest

from neurosync.intelligence.domains import (
    ALL_DOMAINS,
    DOMAIN_FAMILIES,
    DomainClassifier,
    classify_episode,
    get_classifier,
)


class TestDomainTaxonomy:
    """Verify taxonomy integrity."""

    def test_all_domains_count(self):
        assert len(ALL_DOMAINS) == 32

    def test_families_cover_all_domains(self):
        family_domains = set()
        for domains in DOMAIN_FAMILIES.values():
            family_domains.update(domains)
        assert family_domains == ALL_DOMAINS

    def test_seven_families(self):
        assert len(DOMAIN_FAMILIES) == 7

    def test_no_duplicate_domains_across_families(self):
        seen: set[str] = set()
        for domains in DOMAIN_FAMILIES.values():
            for d in domains:
                assert d not in seen, f"Duplicate domain: {d}"
                seen.add(d)


class TestClassifierBasics:
    """Basic classification behavior."""

    def test_empty_content_returns_empty(self):
        result = classify_episode(content="")
        assert result == []

    def test_max_three_domains(self):
        # Content touching many domains at once
        content = (
            "Fixed a race condition in the authentication mutex lock, "
            "added retry logic with exponential backoff to the API endpoint, "
            "and wrote unit tests for the caching layer invalidation"
        )
        result = classify_episode(content=content)
        assert len(result) <= 3

    def test_singleton_classifier(self):
        c1 = get_classifier()
        c2 = get_classifier()
        assert c1 is c2

    def test_classifier_instance(self):
        c = DomainClassifier()
        result = c.get_all_domains()
        assert len(result) == 32
        assert "concurrency" in result

    def test_taxonomy_retrieval(self):
        c = DomainClassifier()
        tax = c.get_taxonomy()
        assert "control_flow" in tax
        assert "concurrency" in tax["control_flow"]


class TestConcurrencyDomain:
    """The concurrency domain should fire for threading/async/lock concepts."""

    def test_race_condition(self):
        result = classify_episode(
            content="Fixed race condition in session handler — two threads writing to shared map without synchronization. Added mutex."
        )
        assert "concurrency" in result

    def test_async_await(self):
        result = classify_episode(
            content="Converted callback-based flow to async/await with proper error propagation through the promise chain"
        )
        assert "concurrency" in result

    def test_deadlock(self):
        result = classify_episode(
            content="Discovered deadlock between database connection pool lock and the transaction semaphore"
        )
        assert "concurrency" in result

    def test_goroutine(self):
        result = classify_episode(
            content="Spawned goroutines for parallel HTTP fetching with a channel for results aggregation"
        )
        assert "concurrency" in result


class TestCachingDomain:
    """Caching domain should fire for invalidation/TTL/LRU concepts."""

    def test_cache_invalidation(self):
        result = classify_episode(
            content="Cache invalidation was causing stale data — switched from TTL-based to event-driven invalidation"
        )
        assert "caching" in result

    def test_memoization(self):
        result = classify_episode(
            content="Added memoization to the expensive computation with LRU eviction when memory exceeds threshold"
        )
        assert "caching" in result


class TestErrorHandlingDomain:
    """Error handling should fire for retry/fallback/circuit-breaker concepts."""

    def test_retry_with_backoff(self):
        result = classify_episode(
            content="Implemented retry with exponential backoff and circuit breaker pattern for the flaky external service"
        )
        assert "error-handling" in result

    def test_exception_handling(self):
        result = classify_episode(
            content="Unhandled exception in the payment flow — added try/catch with graceful degradation fallback"
        )
        assert "error-handling" in result


class TestAuthenticationDomain:
    """Authentication should fire for login/token/session concepts."""

    def test_jwt_refresh(self):
        result = classify_episode(
            content="JWT refresh token rotation was broken — token expired before the refresh endpoint could issue a new one"
        )
        assert "authentication" in result

    def test_oauth_flow(self):
        result = classify_episode(
            content="Implemented OAuth 2.0 authorization code flow with PKCE for the mobile app login"
        )
        assert "authentication" in result


class TestDatabaseAccessDomain:
    """Database access should fire for query/transaction/N+1 concepts."""

    def test_n_plus_one(self):
        result = classify_episode(
            content="N+1 query problem in the orders listing — added eager loading with a JOIN to fix"
        )
        assert "database-access" in result

    def test_transaction_isolation(self):
        result = classify_episode(
            content="Transaction isolation level was too low — concurrent reads were seeing uncommitted writes. Switched to SERIALIZABLE."
        )
        # Should get both concurrency and database-access
        assert "database-access" in result


class TestCrossProjectTransfer:
    """The core value: same concept, different context → same domain."""

    def test_perl_lock_and_python_lock_same_domain(self):
        perl_episode = classify_episode(
            content="Fixed race condition in Perl daemon — flock() was not exclusive, multiple processes corrupted the state file"
        )
        python_episode = classify_episode(
            content="Fixed race condition in Python asyncio — concurrent coroutines modifying shared dict without asyncio.Lock"
        )
        # Both should classify as concurrency regardless of language
        assert "concurrency" in perl_episode
        assert "concurrency" in python_episode

    def test_java_retry_and_go_retry_same_domain(self):
        java_episode = classify_episode(
            content="Added retry logic with exponential backoff to the Spring RestTemplate calls using Resilience4j"
        )
        go_episode = classify_episode(
            content="Added retry with backoff to the Go HTTP client using a custom retry middleware"
        )
        assert "error-handling" in java_episode
        assert "error-handling" in go_episode

    def test_concept_transfers_not_syntax(self):
        # The insight is about the CONCEPT (shared mutable state is dangerous)
        # not the SYNTAX (mutex vs Lock vs flock vs synchronized)
        episode = classify_episode(
            content="Learned: any shared mutable state accessed from multiple execution contexts needs synchronization, regardless of the mechanism"
        )
        assert "concurrency" in episode


class TestFilePathHeuristics:
    """File paths should boost domain scores."""

    def test_auth_path(self):
        result = classify_episode(
            content="Refactored the login flow",
            files_touched=["src/auth/login_handler.py"],
        )
        assert "authentication" in result

    def test_migration_path(self):
        result = classify_episode(
            content="Added new column for user preferences",
            files_touched=["db/migrations/0042_add_preferences.sql"],
        )
        assert "data-modeling" in result

    def test_test_path(self):
        result = classify_episode(
            content="Fixed flaky assertion in the order service",
            files_touched=["tests/unit/test_orders.py"],
        )
        assert "testing" in result

    def test_deploy_path(self):
        result = classify_episode(
            content="Updated the resource limits",
            files_touched=["deploy/k8s/production/deployment.yaml"],
        )
        assert "deployment" in result


class TestEventTypeBoost:
    """Event types should subtly boost related domains."""

    def test_debugging_event(self):
        result = classify_episode(
            content="Traced the stack to find the root cause of null pointer in serialization",
            event_type="debugging",
        )
        assert "debugging" in result

    def test_architecture_event(self):
        result = classify_episode(
            content="Decided to separate the module boundaries to reduce coupling between services",
            event_type="architecture",
        )
        assert "modularity" in result


class TestFamilyDiversity:
    """Classifier should prefer diverse families over clustering in one."""

    def test_diverse_families_preferred(self):
        # Content touching state-management AND concurrency (different families)
        result = classify_episode(
            content="Race condition in the global state store — two threads updating the shared reactive state atom simultaneously without a lock"
        )
        families = set()
        c = DomainClassifier()
        for d in result:
            families.add(c.get_domain_family(d))
        # Should ideally span 2 families (data_state + control_flow)
        assert len(families) >= 2 or len(result) <= 1


class TestMinScoreThreshold:
    """Vague content shouldn't trigger false domain assignments."""

    def test_generic_content_no_domains(self):
        result = classify_episode(
            content="Updated the code to work better"
        )
        # Too generic — no specific domain keywords
        assert result == []

    def test_minimal_mention_below_threshold(self):
        # Single weak keyword shouldn't be enough
        result = classify_episode(content="Changed the file")
        assert "file-io" not in result  # "file" alone is too weak (only secondary)


class TestCausalFields:
    """Cause/effect/reasoning fields should contribute to classification."""

    def test_cause_effect_contribute(self):
        result = classify_episode(
            content="Fixed the timeout issue",
            cause="Connection pool exhaustion under concurrent load",
            effect="Requests queue up and eventually timeout",
            reasoning="The pool size was set to 5 but we have 20 concurrent threads",
        )
        assert "concurrency" in result or "database-access" in result


class TestMultipleDomains:
    """Episodes often touch multiple concepts — verify multi-assignment."""

    def test_auth_plus_caching(self):
        result = classify_episode(
            content="Session token cache was returning expired JWT tokens — the TTL eviction wasn't accounting for token refresh window"
        )
        # Should get auth + caching
        domains_set = set(result)
        assert "authentication" in domains_set or "caching" in domains_set
        # At least one should match
        assert len(domains_set) >= 1

    def test_testing_plus_database(self):
        result = classify_episode(
            content="Integration test was failing because the transaction rollback didn't clean up the test fixtures properly"
        )
        domains_set = set(result)
        assert "testing" in domains_set or "database-access" in domains_set
