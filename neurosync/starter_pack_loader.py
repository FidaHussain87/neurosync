"""Load and install YAML starter packs as pre-built theories."""

from __future__ import annotations

import os
from typing import Any

import yaml

from neurosync.semantic import SemanticMemory

_PACK_DIR = os.path.join(os.path.dirname(__file__), "starter_packs")

AVAILABLE_PACKS = [
    "perl_developer",
    "python_developer",
    "cloud_infra",
    "web_fullstack",
]


def list_packs() -> list[str]:
    """List available starter pack names."""
    return AVAILABLE_PACKS


def load_starter_pack(pack_name: str, semantic: SemanticMemory) -> dict[str, Any]:
    """Load a YAML starter pack and create theories from it."""
    if pack_name not in AVAILABLE_PACKS:
        return {"error": f"Unknown pack: {pack_name}. Available: {AVAILABLE_PACKS}"}

    yaml_path = os.path.join(_PACK_DIR, f"{pack_name}.yaml")
    if not os.path.exists(yaml_path):
        return {"error": f"Pack file not found: {yaml_path}"}

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    if not data or "theories" not in data:
        return {"error": "Invalid pack format: missing 'theories' key"}

    created = 0
    skipped = 0
    for entry in data["theories"]:
        content = entry.get("content", "")
        if not content.strip():
            skipped += 1
            continue
        # Check for duplicates via semantic search
        existing = semantic.search(content, n_results=1, active_only=True)
        if existing and existing[0].get("distance", 1.0) < 0.3:
            skipped += 1
            continue
        semantic.create_theory(
            content=content,
            scope=entry.get("scope", "craft"),
            scope_qualifier=entry.get("scope_qualifier", ""),
            confidence=entry.get("confidence", 0.6),
            metadata={"source": f"starter_pack:{pack_name}"},
        )
        created += 1

    return {
        "pack": pack_name,
        "theories_created": created,
        "theories_skipped": skipped,
    }
