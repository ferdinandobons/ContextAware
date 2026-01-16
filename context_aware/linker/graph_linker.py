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
        # Common standard library modules to ignore/classify as external
        self.PYTHON_STDLIB = {
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

    def is_external(self, target_key: str) -> bool:
        """
        Checks if a target key is likely an external library or standard library.
        """
        if not target_key:
            return False
            
        # Top-level check (e.g. "json", "os")
        root_module = target_key.split('.')[0]
        
        # Python Stdlib Check
        if root_module in self.PYTHON_STDLIB:
            return True
            
        # JS/TS Check: if it doesn't start with ./ or ../ and contains no / or starts with @
        # Heuristic: standard imports are "react", "fs", "@angular/core"
        # Local paths are "./utils", "../components/Header"
        if '/' not in root_module and not target_key.startswith('.'):
             return True
             
        return False

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
        external_count = 0
        truly_unresolved_count = 0
        
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
            if not target_key:
                truly_unresolved_count += 1
                continue

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
            else:
                # Check if External
                if self.is_external(target_key):
                    external_count += 1
                else:
                    truly_unresolved_count += 1
        
        # 4. Batch Update target_ids
        if updates:
            cursor.executemany("UPDATE edges SET target_id = ? WHERE rowid = ?", updates)
            conn.commit()
            
        # Detailed Reporting
        print("\nGraph Linking Report:")
        print(f"  - Internal Linked:   {resolved_count}")
        print(f"  - External/StdLib:   {external_count}")
        print(f"  - Unresolved:        {truly_unresolved_count}")
        print(f"  (Total Processed: {len(unresolved)})\n")
        
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
