"""
Graph Linker: Resolves symbolic dependencies to concrete database IDs.

After indexing, the edges table contains "fuzzy" references like:
  source_id="class:user.py:User", target_key="UserService", target_id=NULL

The linker's job is to resolve target_key -> target_id by matching against
known items in the database. After linking:
  source_id="class:user.py:User", target_key="UserService", target_id="class:service.py:UserService"

This enables efficient graph traversal for the router and impacts analysis.

The linker also calculates importance scores based on in-degree centrality
(how many other items depend on each item).
"""
import json
import logging
import math
from typing import Dict, List, Set, Tuple

from ..store.sqlite_store import SQLiteContextStore

logger = logging.getLogger(__name__)

# Python standard library modules - these are never resolved to local items
# Used to avoid false positives when "json" or "os" appears as a dependency
PYTHON_STDLIB: Set[str] = {
    'abc', 'argparse', 'ast', 'asyncio', 'base64', 'collections',
    'contextlib', 'copy', 'csv', 'datetime', 'decimal', 'enum',
    'functools', 'hashlib', 'hmac', 'importlib', 'inspect', 'io',
    'itertools', 'json', 'logging', 'math', 'multiprocessing', 'os',
    'pathlib', 'pickle', 'platform', 'pprint', 'random', 're',
    'shutil', 'signal', 'socket', 'sqlite3', 'ssl', 'stat', 'string',
    'subprocess', 'sys', 'tempfile', 'threading', 'time', 'traceback',
    'typing', 'unittest', 'urllib', 'uuid', 'warnings', 'weakref',
    'zipfile', 'zlib'
}


class GraphLinker:
    """
    Resolves symbolic dependency references to concrete item IDs.

    The linking process:
      1. Load all unresolved edges (target_id IS NULL)
      2. Build a name->item_id map from all indexed items
      3. Match each target_key to a known item by name
      4. Handle ambiguity using path-based heuristics
      5. Update the edges table with resolved target_ids
      6. Calculate importance scores for ranking search results
    """

    def __init__(self, store: SQLiteContextStore):
        self.store = store

    def is_external(self, target_key: str) -> bool:
        """
        Check if a dependency points to an external library (not project code).

        External dependencies include:
          - Python stdlib (os, json, datetime, etc.)
          - npm packages (react, lodash, @angular/core)
          - Go stdlib (fmt, net/http)

        These are intentionally not resolved to avoid polluting the graph.
        """
        if not target_key:
            return False

        root_module = target_key.split('.')[0]

        if root_module in PYTHON_STDLIB:
            return True

        # JS/TS heuristic: relative imports start with ./ or ../
        # Package imports are bare names like "react" or scoped like "@angular/core"
        if '/' not in root_module and not target_key.startswith('.'):
            return True

        return False

    def link(self) -> None:
        """
        Main linking algorithm: resolve all unresolved edges to concrete item IDs.

        Resolution strategy:
          1. Extract the short name from target_key (e.g., "User" from "models.User")
          2. Look up all items with that name
          3. If multiple matches, use path heuristics to pick the best one
          4. Mark external dependencies (stdlib, npm packages) as such

        After linking, runs score calculation for search ranking.
        """
        logger.info("Linking graph nodes...")

        unresolved = self.store.get_unresolved_edges()

        if not unresolved:
            logger.info("Graph is fully linked.")
            return

        resolved_count = 0
        external_count = 0
        truly_unresolved_count = 0

        # Build lookup table: symbol name -> list of (item_id, source_file)
        # This allows O(1) name lookup during resolution
        items_metadata = self.store.get_all_items_metadata()
        name_map: Dict[str, List[Tuple[str, str]]] = {}

        for item_id, metadata_json, source_file in items_metadata:
            source_file = source_file or ""
            try:
                meta = json.loads(metadata_json)
                name = meta.get("name")
                if name:
                    if name not in name_map:
                        name_map[name] = []
                    name_map[name].append((item_id, source_file))
            except json.JSONDecodeError as e:
                logger.warning(f"Could not parse metadata for item {item_id}: {e}")

        updates: List[Tuple[str, int]] = []

        for rowid, target_key in unresolved:
            if not target_key:
                logger.warning("Empty target_key encountered in graph linking")
                truly_unresolved_count += 1
                continue

            # Extract short name: "inventory.InventoryService" -> "InventoryService"
            key_parts = target_key.rsplit('.', 2)
            short_name = key_parts[-1]

            candidates = name_map.get(short_name)
            if candidates:
                target_id = None

                # Disambiguation: if target_key looks like a path (inventory.InventoryService),
                # prefer the candidate whose file path contains "inventory"
                if len(candidates) > 1 and len(key_parts) > 1:
                    path_fragment = key_parts[-2].lower()
                    for cid, cpath in candidates:
                        if path_fragment in cpath.lower():
                            target_id = cid
                            break

                # Default: use first match
                if not target_id:
                    target_id = candidates[0][0]

                updates.append((target_id, rowid))
                resolved_count += 1
            else:
                if self.is_external(target_key):
                    external_count += 1
                else:
                    truly_unresolved_count += 1

        if updates:
            self.store.batch_update_edge_targets(updates)

        logger.info("Graph Linking Report:")
        logger.info(f"  - Internal Linked:   {resolved_count}")
        logger.info(f"  - External/StdLib:   {external_count}")
        logger.info(f"  - Unresolved:        {truly_unresolved_count}")
        logger.info(f"  (Total Processed: {len(unresolved)})")

        self._calculate_scores()

    def _calculate_scores(self) -> None:
        """
        Calculate importance scores using in-degree centrality.

        Items with more incoming edges (more things depend on them) get higher scores.
        Uses log scale to prevent hub nodes from dominating search results.

        Score formula: score = log(1 + in_degree)
        """
        logger.info("Calculating importance scores...")

        indegree_counts = self.store.get_indegree_counts()

        scores: List[Tuple[float, str]] = []
        for target_id, degree in indegree_counts:
            score = math.log(1 + degree)
            scores.append((score, target_id))

        if scores:
            self.store.batch_update_scores(scores)

        logger.info("Scoring complete.")
