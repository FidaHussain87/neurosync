"""FastAPI REST server wrapping all 11 NeuroSync MCP handlers."""

from __future__ import annotations

import hashlib
import os
import secrets
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone

from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from neurosync import mcp_server as _mcp
from neurosync.version import __version__

_API_KEYS_TABLE = "api_keys"

# Paths exempt from authentication
_EXEMPT_PATHS = {"/", "/health", "/docs", "/redoc", "/openapi.json"}

# Cached flag: once keys exist, skip the per-request COUNT query.
# Reset to None when a key is created so the next request re-checks once.
_keys_exist_cache: bool | None = None


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _ensure_api_keys_table(db) -> None:
    conn = db._get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            key_hash TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)
    conn.commit()


def _any_active_keys(db) -> bool:
    """Return True if at least one active key exists (cached after first check)."""
    global _keys_exist_cache
    if _keys_exist_cache is not None:
        return _keys_exist_cache
    row = db._get_conn().execute(
        f"SELECT 1 FROM {_API_KEYS_TABLE} WHERE active=1 LIMIT 1"
    ).fetchone()
    _keys_exist_cache = row is not None
    return _keys_exist_cache


def _validate_key(db, key: str) -> bool:
    h = _hash_key(key)
    row = db._get_conn().execute(
        f"SELECT id FROM {_API_KEYS_TABLE} WHERE key_hash=? AND active=1", (h,)
    ).fetchone()
    return row is not None


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _keys_exist_cache
    _keys_exist_cache = None
    _mcp._init()
    _ensure_api_keys_table(_mcp._db)
    yield
    # Reset DB so _init() can run fresh on next startup (e.g. --reload, tests)
    db = _mcp._db
    _mcp._db = None
    if db is not None:
        with suppress(Exception):
            db.close()


def create_app() -> FastAPI:
    allowed_origins = os.environ.get("NEUROSYNC_CORS_ORIGINS", "*").split(",")

    app = FastAPI(
        title="neurosync-api",
        version=__version__,
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)
        db = _mcp._db
        if db is None or not _any_active_keys(db):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"error": "Missing or invalid Authorization header"},
                status_code=401,
            )
        key = auth[len("Bearer "):]
        if not _validate_key(db, key):
            return JSONResponse({"error": "Invalid API key"}, status_code=401)
        return await call_next(request)

    def _run(handler, params: dict) -> JSONResponse:
        try:
            result = handler(params)
            if isinstance(result, dict) and "error" in result:
                return JSONResponse(result, status_code=400)
            return JSONResponse(result)
        except _mcp.InputTooLargeError as e:
            return JSONResponse(
                {"error": str(e), "error_code": "INPUT_TOO_LARGE"}, status_code=413
            )
        except Exception:
            # Do not leak internal error details in production
            return JSONResponse(
                {"error": "Internal server error", "error_code": "INTERNAL_ERROR"},
                status_code=500,
            )

    @app.get("/")
    async def root():
        return {"name": "neurosync-api", "version": __version__, "docs": "/docs"}

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": __version__}

    # FastAPI intentionally uses Body() in default args for request body declaration.
    # ruff B008 does not apply here — this is the documented FastAPI pattern.

    @app.post("/v1/recall")
    async def recall(body: dict = Body(default={})):  # noqa: B008
        return _run(_mcp.handle_recall, body)

    @app.post("/v1/record")
    async def record(body: dict = Body(default={})):  # noqa: B008
        return _run(_mcp.handle_record, body)

    @app.post("/v1/remember")
    async def remember(body: dict = Body(default={})):  # noqa: B008
        return _run(_mcp.handle_remember, body)

    @app.post("/v1/query")
    async def query(body: dict = Body(default={})):  # noqa: B008
        return _run(_mcp.handle_query, body)

    @app.post("/v1/correct")
    async def correct(body: dict = Body(default={})):  # noqa: B008
        return _run(_mcp.handle_correct, body)

    @app.post("/v1/status")
    @app.get("/v1/status")
    async def status(body: dict = Body(default={})):  # noqa: B008
        return _run(_mcp.handle_status, body)

    @app.post("/v1/theories")
    async def theories(body: dict = Body(default={})):  # noqa: B008
        return _run(_mcp.handle_theories, body)

    @app.post("/v1/consolidate")
    async def consolidate(body: dict = Body(default={})):  # noqa: B008
        return _run(_mcp.handle_consolidate, body)

    @app.post("/v1/handoff")
    async def handoff(body: dict = Body(default={})):  # noqa: B008
        return _run(_mcp.handle_handoff, body)

    @app.post("/v1/poll")
    async def poll(body: dict = Body(default={})):  # noqa: B008
        return _run(_mcp.handle_poll, body)

    @app.post("/v1/graph")
    async def graph(body: dict = Body(default={})):  # noqa: B008
        return _run(_mcp.handle_graph, body)

    @app.get("/v1/api-keys")
    async def list_api_keys():
        db = _mcp._db
        conn = db._get_conn()
        rows = conn.execute(
            f"SELECT id, name, created_at FROM {_API_KEYS_TABLE} WHERE active=1 ORDER BY created_at"
        ).fetchall()
        return {"keys": [{"id": r[0], "name": r[1], "created_at": r[2]} for r in rows]}

    @app.post("/v1/api-keys")
    async def create_api_key(body: dict = Body(default={})):  # noqa: B008
        global _keys_exist_cache
        db = _mcp._db
        conn = db._get_conn()
        name = body.get("name", "")
        key = "ns_" + secrets.token_hex(24)
        key_id = secrets.token_hex(8)
        key_hash = _hash_key(key)
        created_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            f"INSERT INTO {_API_KEYS_TABLE} (id, key_hash, name, created_at, active) VALUES (?,?,?,?,1)",
            (key_id, key_hash, name, created_at),
        )
        conn.commit()
        # Invalidate cache so next request re-checks
        _keys_exist_cache = None
        return {"id": key_id, "key": key, "name": name, "created_at": created_at}

    return app
