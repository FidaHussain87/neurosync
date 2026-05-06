"""CLI: serve, consolidate, status, import-starter-pack, install-hook, reset."""

from __future__ import annotations

import argparse
import json
import sys

from neurosync.logging import configure_logging
from neurosync.version import __version__


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the MCP server on stdio."""
    from neurosync.mcp_server import serve

    serve()


def cmd_status(args: argparse.Namespace) -> None:
    """Show NeuroSync status with component-level health."""
    from neurosync.config import NeuroSyncConfig

    config = NeuroSyncConfig.load()
    status: dict = {"version": __version__}

    try:
        from neurosync.db import Database

        db = Database(config)
        status["database"] = db.stats()
        status["database"]["healthy"] = True
        db.close()
    except Exception as e:
        status["database"] = {"healthy": False, "error": str(e)}

    try:
        from neurosync.vectorstore import VectorStore

        vs = VectorStore(config)
        status["vectorstore"] = vs.stats()
        status["vectorstore"]["healthy"] = True
    except Exception as e:
        status["vectorstore"] = {"healthy": False, "error": str(e)}

    try:
        from neurosync.graph import GraphStore

        gs = GraphStore(config)
        status["graph"] = gs.stats()
        status["graph"]["healthy"] = True
        gs.close()
    except ImportError:
        status["graph"] = {"healthy": False, "error": "neo4j package not installed"}
    except Exception as e:
        status["graph"] = {"healthy": False, "error": str(e)}

    print(json.dumps(status, indent=2))


def cmd_consolidate(args: argparse.Namespace) -> None:
    """Run the consolidation engine."""
    from neurosync.config import NeuroSyncConfig
    from neurosync.consolidation import ConsolidationEngine
    from neurosync.db import Database
    from neurosync.episodic import EpisodicMemory
    from neurosync.semantic import SemanticMemory
    from neurosync.vectorstore import VectorStore

    config = NeuroSyncConfig.load()
    db = Database(config)
    vs = VectorStore(config)
    episodic = EpisodicMemory(db, vs)
    semantic = SemanticMemory(db, vs)
    engine = ConsolidationEngine(db, vs, episodic, semantic)
    result = engine.run(project=args.project, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


def cmd_import_starter_pack(args: argparse.Namespace) -> None:
    """Import a starter pack of theories."""
    from neurosync.config import NeuroSyncConfig
    from neurosync.db import Database
    from neurosync.semantic import SemanticMemory
    from neurosync.starter_pack_loader import load_starter_pack
    from neurosync.vectorstore import VectorStore

    config = NeuroSyncConfig.load()
    db = Database(config)
    vs = VectorStore(config)
    semantic = SemanticMemory(db, vs)
    result = load_starter_pack(args.pack_name, semantic)
    print(json.dumps(result, indent=2))


def cmd_reindex(args: argparse.Namespace) -> None:
    """Re-populate ChromaDB from the SQLite source of truth."""
    from neurosync.config import NeuroSyncConfig
    from neurosync.db import Database
    from neurosync.vectorstore import VectorStore

    config = NeuroSyncConfig.load()
    db = Database(config)
    try:
        vs = VectorStore(config)
        if args.reset:
            vs.reset()
            print("ChromaDB collections reset before reindex.")
            # Re-initialize after reset to get fresh collections
            vs = VectorStore(config)
        result = vs.reindex_from_db(db, project=args.project or "")
        print(json.dumps({"reindexed": result}, indent=2))
    finally:
        db.close()


def cmd_downgrade(args: argparse.Namespace) -> None:
    """Downgrade the database schema to a target version."""
    from neurosync.config import NeuroSyncConfig

    config = NeuroSyncConfig.load()
    target = args.version

    # Determine backend
    backend = getattr(config, "db_backend", "sqlite")

    if backend == "postgresql":
        from neurosync.pg_db import CURRENT_SCHEMA_VERSION, PostgresDatabase

        if not args.confirm:
            print(
                f"Would downgrade PostgreSQL schema from"
                f" {CURRENT_SCHEMA_VERSION} to {target}.\n"
                f"This will DROP tables/indexes added in migrations"
                f" above version {target}.\n"
                f"Use --confirm to proceed.",
                file=sys.stderr,
            )
            sys.exit(1)

        db = PostgresDatabase(config)
        try:
            db.downgrade(target)
            print(f"PostgreSQL schema downgraded to version {target}.")
        finally:
            db.close()
    else:
        from neurosync.db import CURRENT_SCHEMA_VERSION, Database

        if not args.confirm:
            print(
                f"Would downgrade SQLite schema from"
                f" {CURRENT_SCHEMA_VERSION} to {target}.\n"
                f"This will DROP tables/indexes added in migrations"
                f" above version {target}.\n"
                f"Use --confirm to proceed.",
                file=sys.stderr,
            )
            sys.exit(1)

        db = Database(config)
        try:
            db.downgrade(target)
            print(f"SQLite schema downgraded to version {target}.")
        finally:
            db.close()


def cmd_reset(args: argparse.Namespace) -> None:
    """Reset all NeuroSync data."""
    if not args.confirm:
        print("This will delete ALL NeuroSync data. Use --confirm to proceed.", file=sys.stderr)
        sys.exit(1)

    import os

    from neurosync.config import NeuroSyncConfig

    config = NeuroSyncConfig.load()
    sqlite_path = config.sqlite_path
    if os.path.exists(sqlite_path):
        os.remove(sqlite_path)
        print("SQLite database deleted.")
        for suffix in ("-wal", "-shm"):
            p = sqlite_path + suffix
            if os.path.exists(p):
                os.remove(p)

    try:
        from neurosync.vectorstore import VectorStore

        vs = VectorStore(config)
        vs.reset()
        print("ChromaDB collections reset.")
    except Exception as e:
        print(
            f"Warning: ChromaDB reset failed ({e}), you may need to "
            f"delete {config.chroma_path} manually.",
            file=sys.stderr,
        )

    print("NeuroSync data reset.")


def cmd_graph_sync(args: argparse.Namespace) -> None:
    """Sync SQLite data to Neo4j knowledge graph."""
    from neurosync.config import NeuroSyncConfig
    from neurosync.db import Database

    config = NeuroSyncConfig.load()
    db = Database(config)
    try:
        from neurosync.graph import GraphStore

        gs = GraphStore(config)
        try:
            result = gs.sync(db, project=args.project)
            print(json.dumps(result, indent=2))
        finally:
            gs.close()
    except ImportError:
        print(
            json.dumps({"error": "Neo4j driver not installed. Run: pip install neurosync[neo4j]"})
        )
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": f"Cannot connect to Neo4j: {e}"}))
        sys.exit(1)
    finally:
        db.close()


def cmd_graph_status(args: argparse.Namespace) -> None:
    """Show Neo4j graph health and statistics."""
    from neurosync.config import NeuroSyncConfig

    config = NeuroSyncConfig.load()
    try:
        from neurosync.graph import GraphStore

        gs = GraphStore(config)
        stats = gs.stats()
        stats["healthy"] = True
        print(json.dumps(stats, indent=2))
        gs.close()
    except ImportError:
        print(json.dumps({"healthy": False, "error": "neo4j package not installed"}))
    except Exception as e:
        print(json.dumps({"healthy": False, "error": str(e)}))


def cmd_export(args: argparse.Namespace) -> None:
    """Export all NeuroSync data to a JSON file."""
    from neurosync.config import NeuroSyncConfig
    from neurosync.db import Database

    config = NeuroSyncConfig.load()
    db = Database(config)
    try:
        sessions = db.list_sessions(limit=100_000)
        episodes = db.list_episodes(limit=100_000)
        theories = db.list_theories(active_only=False, limit=100_000)

        data = {
            "version": "1",
            "sessions": [
                {
                    "id": s.id,
                    "project": s.project,
                    "branch": s.branch,
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "summary": s.summary,
                }
                for s in sessions
            ],
            "episodes": [
                {
                    "id": e.id,
                    "session_id": e.session_id,
                    "event_type": e.event_type,
                    "content": e.content,
                    "timestamp": e.timestamp,
                    "signal_weight": e.signal_weight,
                    "consolidated": e.consolidated,
                    "cause": e.cause,
                    "effect": e.effect,
                    "reasoning": e.reasoning,
                    "files_touched": e.files_touched,
                    "layers_touched": e.layers_touched,
                }
                for e in episodes
            ],
            "theories": [
                {
                    "id": t.id,
                    "content": t.content,
                    "scope": t.scope,
                    "scope_qualifier": t.scope_qualifier,
                    "confidence": t.confidence,
                    "active": t.active,
                    "source_episodes": t.source_episodes,
                }
                for t in theories
            ],
        }
        with open(args.output, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Exported to {args.output}")
    finally:
        db.close()


def cmd_import(args: argparse.Namespace) -> None:
    """Import NeuroSync data from a JSON file."""
    from neurosync.config import NeuroSyncConfig
    from neurosync.db import Database
    from neurosync.models import Episode, Session, Theory

    config = NeuroSyncConfig.load()
    db = Database(config)
    try:
        with open(args.input) as f:
            data = json.load(f)

        imported = {"sessions": 0, "episodes": 0, "theories": 0}
        for s in data.get("sessions", []):
            session = Session(
                id=s["id"],
                project=s.get("project", ""),
                branch=s.get("branch", ""),
                started_at=s.get("started_at", ""),
                ended_at=s.get("ended_at"),
                summary=s.get("summary", ""),
            )
            db.save_session(session)
            imported["sessions"] += 1

        for e in data.get("episodes", []):
            episode = Episode(
                id=e["id"],
                session_id=e.get("session_id", ""),
                event_type=e.get("event_type", "decision"),
                content=e.get("content", ""),
                timestamp=e.get("timestamp", ""),
                signal_weight=e.get("signal_weight", 1.0),
                consolidated=e.get("consolidated", 0),
                cause=e.get("cause", ""),
                effect=e.get("effect", ""),
                reasoning=e.get("reasoning", ""),
                files_touched=e.get("files_touched", []),
                layers_touched=e.get("layers_touched", []),
            )
            db.save_episode(episode)
            imported["episodes"] += 1

        for t in data.get("theories", []):
            theory = Theory(
                id=t["id"],
                content=t.get("content", ""),
                scope=t.get("scope", "craft"),
                scope_qualifier=t.get("scope_qualifier", ""),
                confidence=t.get("confidence", 0.5),
                active=t.get("active", True),
                source_episodes=t.get("source_episodes", []),
            )
            db.save_theory(theory)
            imported["theories"] += 1

        print(json.dumps({"imported": imported}, indent=2))
    finally:
        db.close()


def cmd_generate_protocol(args: argparse.Namespace) -> None:
    """Output the minimal NeuroSync protocol section."""
    from neurosync.protocol import generate_claude_md, generate_protocol_section

    if args.project:
        print(generate_claude_md(project_name=args.project))
    else:
        print(generate_protocol_section())


def cmd_install_hook(args: argparse.Namespace) -> None:
    """Install the auto-recall hook for Claude Code."""
    import os

    from neurosync.hooks import (
        format_hook_instructions,
        generate_settings_hook,
        get_hook_install_path,
    )

    project_dir = args.project_dir or os.getcwd()
    hook_path = get_hook_install_path(project_dir)

    if args.dry_run:
        print(format_hook_instructions())
        print(f"Would install to: {hook_path}")
        print(json.dumps(generate_settings_hook(), indent=2))
        return

    os.makedirs(os.path.dirname(hook_path), exist_ok=True)
    existing: dict = {}
    if os.path.exists(hook_path):
        with open(hook_path) as f:
            existing = json.load(f)
    hook_config = generate_settings_hook()
    existing.setdefault("hooks", {})
    existing["hooks"]["SessionStart"] = hook_config["hooks"]["SessionStart"]
    with open(hook_path, "w") as f:
        json.dump(existing, f, indent=2)
    print(f"Hook installed to {hook_path}")


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="neurosync",
        description="NeuroSync — Developer-focused memory for AI coding agents",
    )
    parser.add_argument("--version", action="version", version=f"neurosync {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    # serve
    subparsers.add_parser("serve", help="Start MCP server on stdio")

    # status
    subparsers.add_parser("status", help="Show NeuroSync status")

    # consolidate
    p_consolidate = subparsers.add_parser("consolidate", help="Run consolidation engine")
    p_consolidate.add_argument("--project", default=None, help="Limit to project")
    p_consolidate.add_argument("--dry-run", action="store_true", help="Preview only")

    # import-starter-pack
    p_import = subparsers.add_parser("import-starter-pack", help="Import a starter pack")
    p_import.add_argument("pack_name", help="Pack name (e.g., python_developer)")

    # export
    p_export = subparsers.add_parser("export", help="Export all data to JSON file")
    p_export.add_argument("--output", required=True, help="Output file path")

    # import
    p_import = subparsers.add_parser("import", help="Import data from JSON file")
    p_import.add_argument("--input", required=True, help="Input file path")

    # generate-protocol
    p_protocol = subparsers.add_parser(
        "generate-protocol",
        help="Output minimal NeuroSync protocol for CLAUDE.md",
    )
    p_protocol.add_argument("--project", default=None, help="Project name for full CLAUDE.md")

    # install-hook
    p_hook = subparsers.add_parser("install-hook", help="Install auto-recall hook for Claude Code")
    p_hook.add_argument("--project-dir", default=None, help="Project directory (default: cwd)")
    p_hook.add_argument("--dry-run", action="store_true", help="Preview only")

    # graph-sync
    p_graph_sync = subparsers.add_parser("graph-sync", help="Sync SQLite data to Neo4j")
    p_graph_sync.add_argument("--project", default=None, help="Limit sync to project")

    # graph-status
    subparsers.add_parser("graph-status", help="Show Neo4j graph health")

    # reindex
    p_reindex = subparsers.add_parser(
        "reindex", help="Re-populate ChromaDB from SQLite source of truth"
    )
    p_reindex.add_argument("--project", default=None, help="Project name for episode metadata")
    p_reindex.add_argument(
        "--reset", action="store_true", help="Reset ChromaDB collections before reindexing"
    )

    # downgrade
    p_downgrade = subparsers.add_parser("downgrade", help="Downgrade database schema")
    p_downgrade.add_argument(
        "--version", type=int, required=True, help="Target schema version"
    )
    p_downgrade.add_argument(
        "--confirm", action="store_true", help="Confirm downgrade"
    )

    # reset
    p_reset = subparsers.add_parser("reset", help="Reset all NeuroSync data")
    p_reset.add_argument("--confirm", action="store_true", help="Confirm reset")

    args = parser.parse_args()

    commands = {
        "serve": cmd_serve,
        "status": cmd_status,
        "consolidate": cmd_consolidate,
        "import-starter-pack": cmd_import_starter_pack,
        "export": cmd_export,
        "import": cmd_import,
        "generate-protocol": cmd_generate_protocol,
        "install-hook": cmd_install_hook,
        "graph-sync": cmd_graph_sync,
        "graph-status": cmd_graph_status,
        "reindex": cmd_reindex,
        "downgrade": cmd_downgrade,
        "reset": cmd_reset,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
