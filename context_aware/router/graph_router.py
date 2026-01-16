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
            
            # 2. Graph Traversal (Bulk Optimized)
            current_layer_ids = [item.id for item in initial_hits]
            
            for _ in range(depth):
                if not current_layer_ids:
                    break
                    
                # A. Bulk fetch edges from DB
                edges = self.store.get_outbound_edges(current_layer_ids)
                if not edges:
                    break
                    
                next_layer_ids = []
                ids_to_fetch = set()
                names_to_resolve = set()

                for _, target_key, target_id in edges:
                    if target_id:
                        ids_to_fetch.add(target_id)
                    elif target_key:
                        # Fallback to name resolution if Linker hasn't run or failed
                        name = target_key.split('.')[-1]
                        names_to_resolve.add(name)
                
                # Resolving concrete IDs directly
                if ids_to_fetch:
                    for tid in ids_to_fetch:
                         if tid not in final_items:
                             item = self.store.get_by_id(tid)
                             if item:
                                 final_items[item.id] = item
                                 next_layer_ids.append(item.id)

                # Resolving by Name (Fallback)
                if names_to_resolve:
                    resolved_items = self.store.get_items_by_name(list(names_to_resolve))
                    for item in resolved_items:
                        if item.id not in final_items:
                            final_items[item.id] = item
                            next_layer_ids.append(item.id)
                
                current_layer_ids = next_layer_ids
            
            return list(final_items.values())
