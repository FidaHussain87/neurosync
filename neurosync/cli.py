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

    # reset
    p_reset = subparsers.add_parser("reset", help="Reset all NeuroSync data")
    p_reset.add_argument("--confirm", action="store_true", help="Confirm reset")

    args = parser.parse_args()

    commands = {
        "serve": cmd_serve,
        "status": cmd_status,
        "consolidate": cmd_consolidate,
        "import-starter-pack": cmd_import_starter_pack,
        "generate-protocol": cmd_generate_protocol,
        "install-hook": cmd_install_hook,
        "graph-sync": cmd_graph_sync,
        "graph-status": cmd_graph_status,
        "reset": cmd_reset,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
