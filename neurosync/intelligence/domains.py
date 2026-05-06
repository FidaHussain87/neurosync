"""Domain Classifier — assigns conceptual domains to episodes at record-time.

Zero LLM. Pure keyword fingerprinting + file-path heuristics + event-type weighting.
Domains represent problem families that transfer across languages and projects:
"concurrency" is concurrency whether you're in Perl, Python, Java, or Go.

The taxonomy has 7 families → 32 domains, each with a keyword fingerprint.
Classification uses TF-IDF-inspired scoring: keyword hits weighted by
specificity (rare keywords score higher than common ones).
"""

from __future__ import annotations

import re
import threading as _threading
from dataclasses import dataclass
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# TAXONOMY: 7 families → 32 domains
# ─────────────────────────────────────────────────────────────────────────────

DOMAIN_FAMILIES = {
    "data_state": [
        "state-management",
        "data-transformation",
        "data-modeling",
        "serialization",
        "caching",
    ],
    "control_flow": [
        "iteration",
        "concurrency",
        "scheduling",
        "error-handling",
        "conditional-logic",
    ],
    "communication": [
        "api-design",
        "messaging",
        "networking",
        "database-access",
        "file-io",
    ],
    "security": [
        "authentication",
        "authorization",
        "cryptography",
        "input-validation",
    ],
    "quality": [
        "testing",
        "logging",
        "monitoring",
        "debugging",
        "performance",
    ],
    "architecture": [
        "dependency-management",
        "modularity",
        "patterns",
        "configuration",
        "deployment",
    ],
    "user_facing": [
        "rendering",
        "interaction",
        "accessibility",
    ],
}

ALL_DOMAINS = frozenset(d for domains in DOMAIN_FAMILIES.values() for d in domains)

# ─────────────────────────────────────────────────────────────────────────────
# KEYWORD FINGERPRINTS
# Each domain has:
#   - primary: high-specificity keywords (score ×3 when matched)
#   - secondary: supporting keywords (score ×1)
# Keywords are lowercase stems/fragments matched via word-boundary regex.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DomainFingerprint:
    primary: frozenset[str]
    secondary: frozenset[str]


FINGERPRINTS: dict[str, DomainFingerprint] = {
    # ── DATA & STATE ──
    "state-management": DomainFingerprint(
        primary=frozenset([
            "state machine", "shared state", "mutable state", "global state",
            "state transition", "reactive", "observable", "redux", "zustand",
            "atom", "signal", "store", "stateful", "stateless",
        ]),
        secondary=frozenset([
            "state", "mutation", "immutable", "snapshot", "undo", "redo",
            "subscribe", "notify", "propagat", "side effect", "scope",
        ]),
    ),
    "data-transformation": DomainFingerprint(
        primary=frozenset([
            "map/filter", "map/reduce", "filter", "reduce", "transform",
            "pipeline", "etl", "reshape", "aggregate", "flatten", "zip",
            "groupby", "pivot", "normalize", "denormalize",
        ]),
        secondary=frozenset([
            "convert", "parse", "extract", "collect", "accumulate",
            "stream", "batch", "chunk", "iterate", "projection",
        ]),
    ),
    "data-modeling": DomainFingerprint(
        primary=frozenset([
            "schema", "entity", "relation", "foreign key", "primary key",
            "migration", "model", "orm", "table", "column", "index",
            "normalization", "one-to-many", "many-to-many", "inheritance",
        ]),
        secondary=frozenset([
            "field", "attribute", "constraint", "nullable", "unique",
            "cascade", "join", "association", "embed", "reference",
        ]),
    ),
    "serialization": DomainFingerprint(
        primary=frozenset([
            "serializ", "deserializ", "marshal", "unmarshal", "json",
            "protobuf", "msgpack", "pickle", "yaml", "xml", "encode",
            "decode", "codec", "wire format", "binary format",
        ]),
        secondary=frozenset([
            "payload", "format", "parse", "stringify", "schema",
            "versioned", "backward compatible", "field number",
        ]),
    ),
    "caching": DomainFingerprint(
        primary=frozenset([
            "cache", "invalidat", "ttl", "expire", "memoiz", "lru",
            "evict", "cache-aside", "write-through", "write-behind",
            "redis", "memcache", "cdn", "stale-while-revalidate",
        ]),
        secondary=frozenset([
            "hit", "miss", "warm", "cold", "preload", "refresh",
            "lookup", "store", "purge", "bust",
        ]),
    ),

    # ── CONTROL FLOW & EXECUTION ──
    "iteration": DomainFingerprint(
        primary=frozenset([
            "loop", "for loop", "while loop", "recursion", "recursive",
            "generator", "yield", "iterator", "paginate", "cursor",
            "batch", "pagination", "infinite loop", "traversal",
        ]),
        secondary=frozenset([
            "iterate", "next", "each", "repeat", "cycle", "enumerate",
            "range", "step", "break", "continue", "accumulate",
        ]),
    ),
    "concurrency": DomainFingerprint(
        primary=frozenset([
            "thread", "lock", "mutex", "semaphore", "deadlock",
            "race condition", "atomic", "concurrent", "parallel",
            "async", "await", "future", "promise", "goroutine",
            "channel", "actor", "coroutine", "spawn", "join",
        ]),
        secondary=frozenset([
            "synchron", "barrier", "queue", "worker", "pool",
            "shared", "volatile", "cas", "compare-and-swap",
            "non-blocking", "blocking", "contention",
        ]),
    ),
    "scheduling": DomainFingerprint(
        primary=frozenset([
            "cron", "scheduler", "timer", "interval", "rate limit",
            "throttle", "debounce", "backpressure", "delay", "timeout",
            "periodic", "job queue", "task queue", "celery", "sidekiq",
        ]),
        secondary=frozenset([
            "schedule", "trigger", "poll", "tick", "heartbeat",
            "retry delay", "exponential backoff", "jitter", "deadline",
        ]),
    ),
    "error-handling": DomainFingerprint(
        primary=frozenset([
            "exception", "try", "catch", "rescue", "recover", "panic",
            "retry", "fallback", "circuit breaker", "graceful degradation",
            "error boundary", "unhandled", "throw", "raise",
        ]),
        secondary=frozenset([
            "error", "fail", "fault", "toleran", "resilien", "recover",
            "rollback", "compensat", "idempoten", "at-least-once",
        ]),
    ),
    "conditional-logic": DomainFingerprint(
        primary=frozenset([
            "strategy pattern", "polymorphism", "dispatch", "switch",
            "match", "pattern matching", "visitor", "rule engine",
            "decision table", "predicate", "guard clause",
        ]),
        secondary=frozenset([
            "condition", "branch", "if-else", "case", "when",
            "toggle", "flag", "variant", "discriminat",
        ]),
    ),

    # ── COMMUNICATION & INTEGRATION ──
    "api-design": DomainFingerprint(
        primary=frozenset([
            "endpoint", "rest", "graphql", "grpc", "openapi", "swagger",
            "api version", "breaking change", "backward compat",
            "pagination", "idempoten", "rate limit", "contract",
        ]),
        secondary=frozenset([
            "api", "request", "response", "status code", "header",
            "query param", "path param", "body", "resource", "crud",
        ]),
    ),
    "messaging": DomainFingerprint(
        primary=frozenset([
            "pub-sub", "publish", "subscribe", "event-driven",
            "message queue", "kafka", "rabbitmq", "nats", "sns", "sqs",
            "dead letter", "eventual consistency", "event bus", "topic",
        ]),
        secondary=frozenset([
            "message", "event", "emit", "listener", "consumer",
            "producer", "broker", "partition", "offset", "ack",
        ]),
    ),
    "networking": DomainFingerprint(
        primary=frozenset([
            "http", "websocket", "tcp", "udp", "dns", "ssl", "tls",
            "connection pool", "keep-alive", "proxy", "load balanc",
            "latency", "bandwidth", "socket", "handshake",
        ]),
        secondary=frozenset([
            "request", "timeout", "retry", "connect", "disconnect",
            "port", "host", "protocol", "packet", "header",
        ]),
    ),
    "database-access": DomainFingerprint(
        primary=frozenset([
            "query", "sql", "transaction", "commit", "rollback",
            "n+1", "connection pool", "prepared statement", "cursor",
            "index", "explain plan", "deadlock", "isolation level",
        ]),
        secondary=frozenset([
            "database", "db", "select", "insert", "update", "delete",
            "join", "where", "orm", "repository", "dao", "migration",
        ]),
    ),
    "file-io": DomainFingerprint(
        primary=frozenset([
            "file read", "file write", "stream", "buffer", "atomic write",
            "rename", "fsync", "inode", "file lock", "mmap",
            "stdin", "stdout", "pipe", "temp file", "file descriptor",
        ]),
        secondary=frozenset([
            "file", "path", "directory", "permission", "chmod",
            "open", "close", "flush", "seek", "truncate", "append",
        ]),
    ),

    # ── SECURITY & TRUST ──
    "authentication": DomainFingerprint(
        primary=frozenset([
            "login", "logout", "session", "token", "jwt", "oauth",
            "refresh token", "password", "credential", "identity",
            "sso", "saml", "openid", "two-factor", "mfa", "2fa",
        ]),
        secondary=frozenset([
            "auth", "authenticate", "verify", "sign in", "sign out",
            "user", "account", "register", "forgot password",
        ]),
    ),
    "authorization": DomainFingerprint(
        primary=frozenset([
            "permission", "role", "rbac", "abac", "policy", "acl",
            "access control", "privilege", "scope", "grant", "deny",
            "resource-level", "tenant", "multi-tenant",
        ]),
        secondary=frozenset([
            "authoriz", "allow", "forbid", "restrict", "admin",
            "owner", "member", "public", "private", "protected",
        ]),
    ),
    "cryptography": DomainFingerprint(
        primary=frozenset([
            "encrypt", "decrypt", "hmac", "hashing", "signing",
            "aes", "rsa", "sha256", "sha512", "bcrypt", "argon", "salt", "nonce",
            "key rotation", "public key", "private key", "certificate",
        ]),
        secondary=frozenset([
            "crypto", "secret", "secure", "digest", "cipher",
            "plaintext", "ciphertext", "iv", "padding",
        ]),
    ),
    "input-validation": DomainFingerprint(
        primary=frozenset([
            "sanitiz", "validat", "injection", "xss", "sqli",
            "whitelist", "blacklist", "allowlist", "denylist",
            "escape", "parameteriz", "bound", "constrain",
        ]),
        secondary=frozenset([
            "input", "user input", "form", "check", "assert",
            "type coercion", "cast", "clamp", "regex", "pattern",
        ]),
    ),

    # ── QUALITY & OBSERVABILITY ──
    "testing": DomainFingerprint(
        primary=frozenset([
            "unit test", "integration test", "mock", "stub", "spy",
            "fixture", "assertion", "test case", "coverage", "tdd",
            "bdd", "arrange-act-assert", "given-when-then", "parametriz",
        ]),
        secondary=frozenset([
            "test", "expect", "assert", "verify", "setup", "teardown",
            "before", "after", "describe", "it", "spec", "suite",
        ]),
    ),
    "logging": DomainFingerprint(
        primary=frozenset([
            "log level", "structured log", "correlation id", "trace id",
            "audit trail", "log aggregat", "elk", "splunk", "fluentd",
            "syslog", "log rotation", "json log",
        ]),
        secondary=frozenset([
            "log", "logger", "debug", "info", "warn", "error",
            "print", "trace", "verbose", "quiet", "silent",
        ]),
    ),
    "monitoring": DomainFingerprint(
        primary=frozenset([
            "metric", "gauge", "counter", "histogram", "prometheus",
            "grafana", "health check", "uptime", "slo", "sla", "sli",
            "alert", "threshold", "anomaly", "dashboard", "observab",
        ]),
        secondary=frozenset([
            "monitor", "watch", "track", "measure", "report",
            "baseline", "spike", "degradation", "incident",
        ]),
    ),
    "debugging": DomainFingerprint(
        primary=frozenset([
            "breakpoint", "stack trace", "root cause", "bisect",
            "reproduce", "minimal repro", "debugger", "core dump",
            "memory leak", "segfault", "null pointer", "undefined",
        ]),
        secondary=frozenset([
            "debug", "trace", "inspect", "dump", "step through",
            "watch", "evaluate", "symptom", "diagnos",
        ]),
    ),
    "performance": DomainFingerprint(
        primary=frozenset([
            "profil", "bottleneck", "latency", "throughput", "p99",
            "p95", "benchmark", "flame graph", "hot path", "gc",
            "garbage collect", "memory leak", "cpu bound", "io bound",
        ]),
        secondary=frozenset([
            "slow", "fast", "optimiz", "efficient", "overhead",
            "allocat", "pool", "batch", "lazy", "eager", "precompute",
        ]),
    ),

    # ── ARCHITECTURE & DESIGN ──
    "dependency-management": DomainFingerprint(
        primary=frozenset([
            "dependency inject", "inversion of control", "ioc",
            "container", "provider", "circular dependency", "import cycle",
            "loose coupling", "tight coupling", "composition root",
        ]),
        secondary=frozenset([
            "depend", "inject", "wire", "bind", "resolve",
            "register", "singleton", "scoped", "transient",
        ]),
    ),
    "modularity": DomainFingerprint(
        primary=frozenset([
            "module", "package", "boundary", "interface", "contract",
            "encapsulat", "cohesion", "coupling", "separation of concerns",
            "layered", "hexagonal", "clean architecture", "port", "adapter",
        ]),
        secondary=frozenset([
            "internal", "external", "public api", "private", "export",
            "import", "namespace", "isolat", "abstraction",
        ]),
    ),
    "patterns": DomainFingerprint(
        primary=frozenset([
            "factory", "observer", "decorator", "middleware", "pipeline",
            "builder", "singleton", "proxy", "facade", "adapter",
            "command pattern", "event sourcing", "cqrs", "saga",
        ]),
        secondary=frozenset([
            "pattern", "design pattern", "anti-pattern", "refactor",
            "composition", "delegation", "template method", "hook",
        ]),
    ),
    "configuration": DomainFingerprint(
        primary=frozenset([
            "env var", "environment variable", "config file", "dotenv",
            "feature flag", "toggle", "secret", "vault", "ssm",
            "twelve-factor", "config map", "settings",
        ]),
        secondary=frozenset([
            "config", "option", "default", "override", "fallback",
            "profile", "dev", "staging", "production", "local",
        ]),
    ),
    "deployment": DomainFingerprint(
        primary=frozenset([
            "ci/cd", "pipeline", "docker", "container", "kubernetes",
            "helm", "terraform", "deploy", "rollback", "blue-green",
            "canary", "rolling update", "artifact", "registry",
        ]),
        secondary=frozenset([
            "build", "release", "ship", "promote", "infrastructure",
            "provision", "scale", "replica", "health check",
        ]),
    ),

    # ── USER-FACING ──
    "rendering": DomainFingerprint(
        primary=frozenset([
            "component", "render", "virtual dom", "reconcil",
            "hydrat", "ssr", "csr", "layout", "reflow", "repaint",
            "canvas", "webgl", "three.js", "animation", "frame",
        ]),
        secondary=frozenset([
            "view", "template", "jsx", "tsx", "html", "css",
            "style", "theme", "responsive", "viewport",
        ]),
    ),
    "interaction": DomainFingerprint(
        primary=frozenset([
            "event handler", "click", "drag", "drop", "gesture",
            "keyboard", "focus", "blur", "form", "input",
            "debounce", "throttle", "touch", "scroll", "hover",
        ]),
        secondary=frozenset([
            "ui", "ux", "user", "interact", "button", "modal",
            "dialog", "navigation", "route", "redirect",
        ]),
    ),
    "accessibility": DomainFingerprint(
        primary=frozenset([
            "aria", "screen reader", "wcag", "a11y", "tab order",
            "focus trap", "alt text", "semantic html", "landmark",
            "role", "label", "announce", "contrast ratio",
        ]),
        secondary=frozenset([
            "accessible", "keyboard nav", "skip link", "caption",
            "subtitle", "high contrast", "reduced motion",
        ]),
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# FILE PATH PATTERNS → domain hints
# ─────────────────────────────────────────────────────────────────────────────

_PATH_DOMAIN_HINTS: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"(^|/)auth", re.I), "authentication", 0.6),
    (re.compile(r"(^|/)(permission|rbac|acl|policy)", re.I), "authorization", 0.6),
    (re.compile(r"(^|/)cach(e|ing)", re.I), "caching", 0.6),
    (re.compile(r"(^|/)(test|spec|__test)", re.I), "testing", 0.5),
    (re.compile(r"(^|/)migrat", re.I), "data-modeling", 0.5),
    (re.compile(r"(^|/)(model|entity|schema)", re.I), "data-modeling", 0.4),
    (re.compile(r"(^|/)middleware", re.I), "patterns", 0.4),
    (re.compile(r"(^|/)(api|endpoint|route|controller|handler)", re.I), "api-design", 0.5),
    (re.compile(r"(^|/)(deploy|ci|cd|docker|k8s|terraform|helm)", re.I), "deployment", 0.6),
    (re.compile(r"(^|/)(config|settings|env)", re.I), "configuration", 0.4),
    (re.compile(r"(^|/)log(s|ger|ging)?(/|$)", re.I), "logging", 0.4),
    (re.compile(r"(^|/)(metric|monitor|health)", re.I), "monitoring", 0.5),
    (re.compile(r"(^|/)(queue|worker|job|task)", re.I), "scheduling", 0.4),
    (re.compile(r"(^|/)(component|view|page|screen|ui)", re.I), "rendering", 0.4),
    (re.compile(r"(^|/)(db|database|repository|dao)", re.I), "database-access", 0.5),
    (re.compile(r"(^|/)(crypto|encrypt)", re.I), "cryptography", 0.5),
    (re.compile(r"(^|/)(serial|codec|proto|format)", re.I), "serialization", 0.4),
    (re.compile(r"(^|/)(hook|plugin|adapter|port)", re.I), "modularity", 0.3),
]

# ─────────────────────────────────────────────────────────────────────────────
# EVENT TYPE → domain boost
# Certain event types naturally correlate with domains
# ─────────────────────────────────────────────────────────────────────────────

_EVENT_TYPE_DOMAIN_BOOST: dict[str, list[tuple[str, float]]] = {
    "debugging": [("debugging", 0.4)],
    "correction": [("error-handling", 0.2)],
    "frustration": [("debugging", 0.2)],
    "architecture": [("modularity", 0.3), ("patterns", 0.2)],
}


# ─────────────────────────────────────────────────────────────────────────────
# CLASSIFIER ENGINE
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DomainScore:
    """A scored domain assignment."""

    domain: str
    score: float
    family: str


_DOMAIN_TO_FAMILY: dict[str, str] = {}
for _fam, _doms in DOMAIN_FAMILIES.items():
    for _d in _doms:
        _DOMAIN_TO_FAMILY[_d] = _fam


def _get_family(domain: str) -> str:
    return _DOMAIN_TO_FAMILY.get(domain, "unknown")


# Pre-compile keyword patterns for performance
_COMPILED_FINGERPRINTS: dict[str, tuple[list[re.Pattern[str]], list[re.Pattern[str]]]] = {}


def _compile_fingerprints() -> None:
    """Pre-compile all keyword patterns. Called once at module load."""
    for domain, fp in FINGERPRINTS.items():
        primary_patterns = []
        for kw in fp.primary:
            if " " in kw or "/" in kw:
                # Multi-word: match as substring (case-insensitive)
                primary_patterns.append(re.compile(re.escape(kw), re.I))
            else:
                # Single word: word boundary match
                primary_patterns.append(re.compile(r"(?<![a-zA-Z])" + re.escape(kw), re.I))
        secondary_patterns = []
        for kw in fp.secondary:
            if " " in kw or "/" in kw:
                secondary_patterns.append(re.compile(re.escape(kw), re.I))
            else:
                secondary_patterns.append(re.compile(r"(?<![a-zA-Z])" + re.escape(kw), re.I))
        _COMPILED_FINGERPRINTS[domain] = (primary_patterns, secondary_patterns)


_compile_fingerprints()


class DomainClassifier:
    """Assigns conceptual domains to episodes based on content, files, and event type.

    Classification is O(n_domains × n_keywords) where n_keywords ~ 10-20 per domain.
    With 32 domains × ~15 avg keywords = ~480 regex checks per episode.
    Empirically < 1ms per classification on modern hardware.
    """

    def __init__(
        self,
        min_score: float = 1.5,
        max_domains: int = 3,
        family_diversity: bool = True,
    ) -> None:
        self._min_score = min_score
        self._max_domains = max_domains
        self._family_diversity = family_diversity

    def classify(
        self,
        content: str,
        context: str = "",
        files_touched: Optional[list[str]] = None,
        event_type: str = "",
        cause: str = "",
        effect: str = "",
        reasoning: str = "",
    ) -> list[str]:
        """Classify an episode into 0-3 conceptual domains.

        Returns a list of domain strings, ordered by confidence (highest first).
        Returns empty list if no domain scores above threshold.
        """
        # Build the full text signal (concatenate all meaningful text)
        parts = [content]
        if context:
            parts.append(context)
        if cause:
            parts.append(cause)
        if effect:
            parts.append(effect)
        if reasoning:
            parts.append(reasoning)
        full_text = " ".join(parts)

        if not full_text.strip():
            return []

        # Score each domain
        scores: dict[str, float] = {}

        for domain, (primary_patterns, secondary_patterns) in _COMPILED_FINGERPRINTS.items():
            score = 0.0

            # Primary keywords: ×3 weight
            for pattern in primary_patterns:
                if pattern.search(full_text):
                    score += 3.0

            # Secondary keywords: ×1 weight
            for pattern in secondary_patterns:
                if pattern.search(full_text):
                    score += 1.0

            if score > 0:
                scores[domain] = score

        # File path heuristics
        if files_touched:
            for fpath in files_touched:
                for pattern, domain, weight in _PATH_DOMAIN_HINTS:
                    if pattern.search(fpath):
                        scores[domain] = scores.get(domain, 0) + weight * 3.0

        # Event type boost
        if event_type in _EVENT_TYPE_DOMAIN_BOOST:
            for domain, boost in _EVENT_TYPE_DOMAIN_BOOST[event_type]:
                scores[domain] = scores.get(domain, 0) + boost * 3.0

        # Filter by minimum threshold
        viable = [
            DomainScore(domain=d, score=s, family=_get_family(d))
            for d, s in scores.items()
            if s >= self._min_score
        ]

        if not viable:
            return []

        # Sort by score descending
        viable.sort(key=lambda x: -x.score)

        # Select top domains with optional family diversity
        selected: list[str] = []
        families_used: set[str] = set()

        for ds in viable:
            if len(selected) >= self._max_domains:
                break
            if self._family_diversity and ds.family in families_used and ds.score < self._min_score * 2:
                continue
            selected.append(ds.domain)
            families_used.add(ds.family)

        return selected

    def classify_episode(
        self,
        content: str,
        context: str = "",
        files_touched: Optional[list[str]] = None,
        event_type: str = "",
        cause: str = "",
        effect: str = "",
        reasoning: str = "",
    ) -> list[str]:
        """Convenience alias for classify()."""
        return self.classify(
            content=content,
            context=context,
            files_touched=files_touched,
            event_type=event_type,
            cause=cause,
            effect=effect,
            reasoning=reasoning,
        )

    def get_domain_family(self, domain: str) -> str:
        """Get the family for a domain."""
        return _get_family(domain)

    def get_all_domains(self) -> list[str]:
        """Return all valid domain names."""
        return sorted(ALL_DOMAINS)

    def get_taxonomy(self) -> dict[str, list[str]]:
        """Return the full taxonomy tree."""
        return dict(DOMAIN_FAMILIES)


# Module-level singleton for convenience
_default_classifier: Optional[DomainClassifier] = None
_classifier_lock = _threading.Lock()


def get_classifier() -> DomainClassifier:
    """Get or create the module-level DomainClassifier singleton (thread-safe)."""
    global _default_classifier
    if _default_classifier is None:
        with _classifier_lock:
            if _default_classifier is None:
                _default_classifier = DomainClassifier()
    return _default_classifier


def classify_episode(
    content: str,
    context: str = "",
    files_touched: Optional[list[str]] = None,
    event_type: str = "",
    cause: str = "",
    effect: str = "",
    reasoning: str = "",
) -> list[str]:
    """Module-level convenience function for domain classification."""
    return get_classifier().classify(
        content=content,
        context=context,
        files_touched=files_touched,
        event_type=event_type,
        cause=cause,
        effect=effect,
        reasoning=reasoning,
    )
