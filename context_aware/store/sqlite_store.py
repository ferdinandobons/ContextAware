import sqlite3
import json
import os
from typing import List, Optional
from ..models.context_item import ContextItem, ContextLayer

class SQLiteContextStore:
    def __init__(self, root_dir: str = "."):
        self.storage_dir = os.path.join(root_dir, ".context_aware")
        self.db_path = os.path.join(self.storage_dir, "context.db")
        self._conn = None
        self._ensure_storage()

    def __enter__(self):
        self._conn = sqlite3.connect(self.db_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_storage(self):
        os.makedirs(self.storage_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Main table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                layer TEXT,
                content TEXT,
                metadata TEXT,
                source_file TEXT,
                line_number INTEGER
            )
        ''')
        
        # Edges table for relational graph
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS edges (
                source_id TEXT,
                target_key TEXT,
                relation_type TEXT,
                PRIMARY KEY (source_id, target_key, relation_type),
                FOREIGN KEY(source_id) REFERENCES items(id)
            )
        ''')
        
        # Index for reverse lookup and joins
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_key)')

        # FTS5 virtual table for search
        # We need to check if FTS5 is available, usually yes in standard python sqlite3
        try:
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(id, content, metadata)
            ''')
        except sqlite3.OperationalError:
            print("Warning: FTS5 not available. Fallback to LIKE query.")
            
        conn.commit()
        conn.close()

    def has_index(self) -> bool:
        """Checks if the index already contains items."""
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT 1 FROM items LIMIT 1')
            result = cursor.fetchone()
        except sqlite3.OperationalError:
            result = None
            
        if use_own_conn:
            conn.close()
            
        return result is not None

    def save(self, items: List[ContextItem]):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for item in items:
            meta_json = json.dumps(item.metadata)
            
            # Upsert into main table
            cursor.execute('''
                INSERT OR REPLACE INTO items (id, layer, content, metadata, source_file, line_number)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (item.id, item.layer.value, item.content, meta_json, item.source_file, item.line_number))
            
            # Update FTS index (delete old if exists, then insert)
            cursor.execute('DELETE FROM items_fts WHERE id = ?', (item.id,))
            cursor.execute('''
                INSERT INTO items_fts (id, content, metadata)
                VALUES (?, ?, ?)
            ''', (item.id, item.content, meta_json))
            
            # --- Populate Edges Graph ---
            # Clear existing edges for this source to avoid stale links
            cursor.execute('DELETE FROM edges WHERE source_id = ?', (item.id,))
            
            deps = item.metadata.get("dependencies", [])
            for dep in deps:
                # For v1 graph, target_key is the import string (e.g. "products.inventory.InventoryService")
                # We normalize it slightly to help matching.
                if dep:
                    cursor.execute('''
                        INSERT OR IGNORE INTO edges (source_id, target_key, relation_type)
                        VALUES (?, ?, ?)
                    ''', (item.id, dep, "import"))
            
        conn.commit()
        conn.close()

    def load(self) -> List[ContextItem]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM items')
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_item(row) for row in rows]

    def query(self, query_text: str, type_filter: Optional[str] = None) -> List[ContextItem]:
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Clean query for FTS (basic sanitation)
        clean_query = query_text.replace('"', '""')
        
        try:
            # FTS Search
            cursor.execute('''
                SELECT * FROM items 
                WHERE id IN (
                    SELECT id FROM items_fts WHERE items_fts MATCH ? ORDER BY rank
                )
            ''', (clean_query,))
        except sqlite3.OperationalError:
             # Fallback if FTS syntax is weird or not supported
             cursor.execute('''
                SELECT * FROM items WHERE content LIKE ? OR metadata LIKE ?
             ''', (f"%{clean_query}%", f"%{clean_query}%"))
             
        rows = cursor.fetchall()
        
        if use_own_conn:
            conn.close()
        
        results = [self._row_to_item(row) for row in rows]
        
        if type_filter:
            results = [item for item in results if item.metadata.get("type") == type_filter]
            
        return results

    def get_by_id(self, item_id: str) -> Optional[ContextItem]:
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM items WHERE id = ?', (item_id,))
        row = cursor.fetchone()
        
        if use_own_conn:
            conn.close()
        return self._row_to_item(row) if row else None

    def _row_to_item(self, row) -> ContextItem:
        return ContextItem(
            id=row[0],
            layer=ContextLayer(row[1]),
            content=row[2],
            metadata=json.loads(row[3]),
            source_file=row[4],
            line_number=row[5]
        )

    def get_outbound_edges(self, source_ids: List[str]) -> List[tuple]:
        """Returns list of (source_id, target_key) for given source_ids."""
        if not source_ids:
            return []
            
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        placeholders = ','.join(['?'] * len(source_ids))
        cursor.execute(f'SELECT source_id, target_key FROM edges WHERE source_id IN ({placeholders})', source_ids)
        rows = cursor.fetchall()
        
        if use_own_conn:
            conn.close()
        return rows

    def get_items_by_name(self, names: List[str]) -> List[ContextItem]:
        """Bulk lookup items by simple name (parallelized FTS for speed)."""
        if not names:
            return []
        
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        results = []
        # Optimization: Try to match exact "name" in metadata via FTS or LIKE
        # Since FTS5 with metadata column is active, we can use it.
        # But for robustness against tokenizer, let's use a big OR query on metadata with LIKE
        # OR just iterate. Iterating is safer for correctness, batching 20-30.
        
        # Super simple strategy: fetch where metadata like %"name": "TargetName"% 
        # Only feasible if list is small. 
        
        for name in names:
             cursor.execute("SELECT * FROM items WHERE metadata LIKE ?", (f'%"name": "{name}"%',))
             rows = cursor.fetchall()
             results.extend([self._row_to_item(row) for row in rows])
             
        if use_own_conn:
             conn.close()
             
        return results
