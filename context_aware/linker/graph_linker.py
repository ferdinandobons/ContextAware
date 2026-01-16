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
        # Strategy: Fetch all (name, id, source_file) from items.
        cursor.execute("SELECT id, metadata, source_file FROM items")
        
        import json
        name_map = {} # "InventoryService" -> [("id1", "path/to/file1"), ("id2", "path/to/file2")]
        
        for row in cursor.fetchall():
            item_id = row[0]
            source_file = row[2] or ""
            try:
                meta = json.loads(row[1])
                name = meta.get("name")
                if name:
                    if name not in name_map:
                        name_map[name] = []
                    name_map[name].append((item_id, source_file))
            except:
                pass
                
        # 3. Resolve
        updates = []
        for rowid, target_key in unresolved:
            # target_key might be "products.inventory.InventoryService" or just "InventoryService"
            short_name = target_key.split('.')[-1]
            
            candidates = name_map.get(short_name)
            if candidates:
                target_id = None
                
                # Heuristic: If target_key acts like a path (e.g. inventory.InventoryService), 
                # prefer candidate whose file path contains "inventory"
                if len(candidates) > 1 and '.' in target_key:
                    path_fragment = target_key.split('.')[-2].lower() # "inventory"
                    for cid, cpath in candidates:
                         if path_fragment in cpath.lower():
                             target_id = cid
                             break
                
                # Fallback: Pick first
                if not target_id:
                    target_id = candidates[0][0]
                    
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
