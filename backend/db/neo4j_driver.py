"""
OmniProf v3.0 — Neo4j Database Manager (Deprecated)
This module is deprecated. Use graph_manager.py with RustWorkX instead.
Kept for backward compatibility.
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
