from typing import List, Set
from ..store.sqlite_store import SQLiteContextStore
from ..models.context_item import ContextItem

class GraphRouter:
    def __init__(self, store: SQLiteContextStore):
        self.store = store

    def route(self, query: str, type_filter: str = None, depth: int = 1) -> List[ContextItem]:
        with self.store:
            # 1. Initial Search (using SQLite FTS)
            initial_hits = self.store.query(query, type_filter=type_filter)
            
            # If FTS returns nothing, fallback to token scoring? 
            # Actually our SQLite FTS is robust for keywords.
            # But for "stock check" matching "check_stock", FTS5 prefix matching might be needed or token usage.
            # Our SQLite tokenization should handle basic stuff.
            
            if not initial_hits:
                return []
                
            final_items = {item.id: item for item in initial_hits}
            processed_ids = set(final_items.keys())
            
            # 2. Graph Traversal
            current_layer = list(initial_hits)
            
            for _ in range(depth):
                next_layer = []
                for item in current_layer:
                    deps = item.metadata.get("dependencies", [])
                    for dep_str in deps:
                        # Resolve dependency.
                        # dep_str could be "products.inventory.InventoryService" or "datetime"
                        # We look for items with name matching the last part.
                        
                        target_name = dep_str.split('.')[-1]
                        
                        # We can't query by ID directly as we don't know the file path.
                        # We query content/metadata for the name.
                        # For performance, we'd want a specific lookup, but querying FTS for the name works for now.
                        
                        # Optimization: Use a specialized query or load all and filter (bad for scale).
                        # Better: SQLite query by metadata field if we extracted it, but it's JSON.
                        # We can use the FTS index which includes metadata.
                        
                        candidates = self.store.query(target_name)
                        
                        for cand in candidates:
                             # Strict check: make sure the candidate's name actually matches target_name
                             # to avoid "Service" matching "AuthService" fuzzy.
                             if cand.metadata.get("name") == target_name:
                                 if cand.id not in processed_ids:
                                     processed_ids.add(cand.id)
                                     final_items[cand.id] = cand
                                     next_layer.append(cand)
                
                current_layer = next_layer
            
            return list(final_items.values())
