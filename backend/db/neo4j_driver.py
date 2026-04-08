"""
OmniProf v3.0 — Graph manager compatibility shim.
Routes legacy imports to the RustWorkX-based graph manager.
Prefer importing from backend.db.graph_manager directly.
"""

import logging

logger = logging.getLogger(__name__)

# Import from new graph_manager for backward compatibility
try:
    from backend.db.graph_manager import GraphManager, Neo4jGraphManager
    __all__ = ['GraphManager', 'Neo4jGraphManager']
except ImportError as e:
    logger.error(f"Failed to import from graph_manager: {e}")
    logger.error("Make sure rustworkx is installed: pip install rustworkx")
    raise
