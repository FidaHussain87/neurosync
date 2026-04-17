"""CLI: serve, consolidate, status, import-starter-pack, reset."""

from __future__ import annotations

import argparse
import json
import sys

from neurosync.version import __version__


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the MCP server on stdio."""
    from neurosync.mcp_server import serve
    serve()


def cmd_status(args: argparse.Namespace) -> None:
    """Show NeuroSync status."""
    from neurosync.config import NeuroSyncConfig
    from neurosync.db import Database
    from neurosync.vectorstore import VectorStore

    config = NeuroSyncConfig.load()
    try:
        db = Database(config)
        vs = VectorStore(config)
        db_stats = db.stats()
        vs_stats = vs.stats()
        print(json.dumps({"database": db_stats, "vectorstore": vs_stats}, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


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
        # Also remove WAL/SHM files
        for suffix in ("-wal", "-shm"):
            p = sqlite_path + suffix
            if os.path.exists(p):
                os.remove(p)
    from neurosync.vectorstore import VectorStore
    try:
        vs = VectorStore(config)
        vs.reset()
    except Exception:
        pass
    print("NeuroSync data reset.")


def main() -> None:
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

    # reset
    p_reset = subparsers.add_parser("reset", help="Reset all NeuroSync data")
    p_reset.add_argument("--confirm", action="store_true", help="Confirm reset")

    args = parser.parse_args()

    commands = {
        "serve": cmd_serve,
        "status": cmd_status,
        "consolidate": cmd_consolidate,
        "import-starter-pack": cmd_import_starter_pack,
        "reset": cmd_reset,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
