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
                    
                # B. Extract potential target names
                # edge is (source_id, target_key)
                # target_key might be "products.inventory.InventoryService"
                target_names = set()
                for _, target_key in edges:
                    if target_key:
                        name = target_key.split('.')[-1]
                        target_names.add(name)
                
                if not target_names:
                    break
                    
                # C. Bulk resolve items by name
                resolved_items = self.store.get_items_by_name(list(target_names))
                
                next_layer_ids = []
                for item in resolved_items:
                    # Strict validation: Only accept if the name matches the target_key tail
                    # (Simple heuristic for now, robust enough for v0.2)
                    if item.id not in processed_ids:
                        processed_ids.add(item.id)
                        final_items[item.id] = item
                        next_layer_ids.append(item.id)
                
                current_layer_ids = next_layer_ids
            
            return list(final_items.values())
            
            return list(final_items.values())
