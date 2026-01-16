from typing import List
import sqlite3
from ..store.sqlite_store import SQLiteContextStore

class GraphLinker:
    """
    Resolves 'fuzzy' dependencies in the edges table to concrete Item IDs.
    This transforms the graph from String-based to ID-based.
    """
    def __init__(self, store: SQLiteContextStore):
        self.store = store

    def link(self):
        """
        Scans all edges with NULL target_id and tries to resolve them.
        """
        conn = sqlite3.connect(self.store.db_path)
        cursor = conn.cursor()
        
        print("Linking graph nodes...")
        
        # 1. Fetch all unresolved edges
        cursor.execute("SELECT rowid, target_key FROM edges WHERE target_id IS NULL")
        unresolved = cursor.fetchall()
        
        if not unresolved:
            print("Graph is fully linked.")
            conn.close()
            return

        resolved_count = 0
        
        # 2. For each edge, try to find a matching item
        # Optimization: We can load all item names into memory for O(1) lookup if items < 100k
        # For now, let's stick to SQL lookups for safety, but optimize with LIKE
        
        # Improved Strategy:
        # Instead of 1 query per edge, let's fetch all (name, id) from items first.
        cursor.execute("SELECT id, metadata FROM items")
        # We need to parse metadata to get the name. 
        # Or... we can rely on the fact that ID often contains the name (e.g. class:file:Name)
        # But let's trust metadata['name']
        
        import json
        name_map = {} # "InventoryService" -> ["id1", "id2"]
        
        for row in cursor.fetchall():
            item_id = row[0]
            try:
                meta = json.loads(row[1])
                name = meta.get("name")
                if name:
                    if name not in name_map:
                        name_map[name] = []
                    name_map[name].append(item_id)
            except:
                pass
                
        # 3. Resolve
        updates = []
        for rowid, target_key in unresolved:
            # target_key might be "products.inventory.InventoryService"
            short_name = target_key.split('.')[-1]
            
            candidates = name_map.get(short_name)
            if candidates:
                # If multiple, take the first one (ambiguity handling is a v0.4 feature)
                # Or better, prefer one that matches the path?
                # For v0.3, simple name match.
                target_id = candidates[0]
                updates.append((target_id, rowid))
                resolved_count += 1
        
        # 4. Batch Update target_ids
        if updates:
            cursor.executemany("UPDATE edges SET target_id = ? WHERE rowid = ?", updates)
            conn.commit()
            
        print(f"Linked {resolved_count}/{len(unresolved)} edges.")
        
        # --- Phase 3: Smart Ranking (Centrality Scoring) ---
        print("Calculating importance scores...")
        
        # Calculate In-Degree
        cursor.execute('''
            SELECT target_id, COUNT(*) as degree 
            FROM edges 
            WHERE target_id IS NOT NULL 
            GROUP BY target_id
        ''')
        
        scores = []
        import math
        for target_id, degree in cursor.fetchall():
            # Simple log scale to dampen effect of massive hubs
            score = math.log(1 + degree)
            scores.append((score, target_id))
            
        if scores:
            cursor.executemany("UPDATE items SET score = ? WHERE id = ?", scores)
            conn.commit()
            
        print("Scoring complete.")
        
        conn.close()
