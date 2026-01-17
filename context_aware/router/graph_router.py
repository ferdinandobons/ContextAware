"""
Graph Router: Executes queries and traverses the dependency graph.

The router is the bridge between user search queries and the stored graph.
It handles both the initial search and the dependency expansion that makes
ContextAware more useful than plain grep.

Search Flow:
  1. Execute initial search (FTS or hybrid semantic)
  2. For each result, follow outbound edges to find dependencies
  3. Recursively expand up to `depth` levels
  4. Return all relevant items (deduped)

This "graph-aware" search means that if you search for "UserController",
you also get the UserService it depends on, which provides better context.
"""
from typing import Dict, List, Optional, Set

from ..store.sqlite_store import SQLiteContextStore
from ..models.context_item import ContextItem


class GraphRouter:
    """
    Executes queries and expands results through the dependency graph.

    Unlike a plain text search, the router follows the dependency graph to
    include related items, giving LLMs a more complete picture of the code.
    """

    def __init__(self, store: SQLiteContextStore):
        self.store = store

    def route(
        self,
        query: str,
        type_filter: Optional[str] = None,
        depth: int = 1,
        query_embedding: Optional[List[float]] = None
    ) -> List[ContextItem]:
        """
        Execute a search query and expand results through the dependency graph.

        Args:
            query: Search text (keywords or natural language for semantic)
            type_filter: Limit results to "class", "function", or "file"
            depth: How many levels of dependencies to traverse (default 1)
            query_embedding: Pre-computed embedding vector for semantic search

        Returns:
            List of matching items plus their dependencies (deduped)
        """
        with self.store:
            # Step 1: Initial search - find direct matches
            if query_embedding:
                initial_hits = self.store.search_hybrid(
                    query,
                    query_embedding=query_embedding,
                    type_filter=type_filter
                )
            else:
                initial_hits = self.store.query(query, type_filter=type_filter)

            if not initial_hits:
                return []

            # Use dict for O(1) deduplication while preserving items
            final_items: Dict[str, ContextItem] = {item.id: item for item in initial_hits}

            # Step 2: Graph expansion - follow dependencies to related items
            current_layer_ids: List[str] = [item.id for item in initial_hits]

            for _ in range(depth):
                if not current_layer_ids:
                    break

                edges = self.store.get_outbound_edges(current_layer_ids)
                if not edges:
                    break

                next_layer_ids: List[str] = []
                ids_to_fetch: Set[str] = set()
                names_to_resolve: Set[str] = set()

                for _, target_key, target_id in edges:
                    if target_id:
                        # Resolved edge: we know the exact target item
                        if target_id not in final_items:
                            ids_to_fetch.add(target_id)
                    elif target_key:
                        # Unresolved edge: try name-based lookup as fallback
                        name = target_key.split('.')[-1]
                        names_to_resolve.add(name)

                # Batch fetch by ID (fast - direct lookup)
                if ids_to_fetch:
                    fetched_items = self.store.get_items_by_ids(ids_to_fetch)
                    for item in fetched_items:
                        if item.id not in final_items:
                            final_items[item.id] = item
                            next_layer_ids.append(item.id)

                # Batch fetch by name (slower - metadata scan)
                if names_to_resolve:
                    resolved_items = self.store.get_items_by_name(names_to_resolve)
                    for item in resolved_items:
                        if item.id not in final_items:
                            final_items[item.id] = item
                            next_layer_ids.append(item.id)

                current_layer_ids = next_layer_ids

            return list(final_items.values())
