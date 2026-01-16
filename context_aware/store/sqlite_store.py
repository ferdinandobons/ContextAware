import sqlite3
import json
import os
from typing import List, Optional
from ..models.context_item import ContextItem, ContextLayer

class SQLiteContextStore:
    def __init__(self, root_dir: str = "."):
        self.storage_dir = os.path.join(root_dir, ".context_aware")
        self.db_path = os.path.join(self.storage_dir, "context.db")
        self._ensure_storage()

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
            
        conn.commit()
        conn.close()

    def load(self) -> List[ContextItem]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM items')
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_item(row) for row in rows]

    def query(self, query_text: str) -> List[ContextItem]:
        conn = sqlite3.connect(self.db_path)
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
        conn.close()
        return [self._row_to_item(row) for row in rows]

    def get_by_id(self, item_id: str) -> Optional[ContextItem]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM items WHERE id = ?', (item_id,))
        row = cursor.fetchone()
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
