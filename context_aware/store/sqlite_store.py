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
                line_number INTEGER,
                score REAL DEFAULT 0,
                embedding BLOB
            )
        ''')
        
        # Migration: Check if embedding column exists
        cursor.execute("PRAGMA table_info(items)")
        columns = [info[1] for info in cursor.fetchall()]
        if "embedding" not in columns:
            cursor.execute("ALTER TABLE items ADD COLUMN embedding BLOB")
        
        # Edges table for relational graph
        # target_key: the raw string import (e.g. "products.inventory.InventoryService")
        # target_id: the resolved Item ID (e.g. "class:inventory.py:InventoryService") - populated by Linker
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS edges (
                source_id TEXT,
                target_key TEXT,
                target_id TEXT,
                relation_type TEXT,
                PRIMARY KEY (source_id, target_key, relation_type),
                FOREIGN KEY(source_id) REFERENCES items(id)
            )
        ''')
        
        # Index for reverse lookup and joins
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_key)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_edges_target_id ON edges(target_id)')

        # Tracked files for incremental indexing
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tracked_files (
                path TEXT PRIMARY KEY,
                last_modified REAL
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
        
        import numpy as np
        
        for item in items:
            meta_json = json.dumps(item.metadata)
            
            # Serialize embedding if present
            embedding_blob = None
            if item.embedding:
                # Convert list[float] to numpy array then to bytes
                # We assume float32 for space efficiency
                arr = np.array(item.embedding, dtype=np.float32)
                embedding_blob = arr.tobytes()
            
            # Upsert into main table
            cursor.execute('''
                INSERT OR REPLACE INTO items (id, layer, content, metadata, source_file, line_number, score, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (item.id, item.layer.value, item.content, meta_json, item.source_file, item.line_number, 0.0, embedding_blob))
            
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
                        INSERT OR IGNORE INTO edges (source_id, target_key, target_id, relation_type)
                        VALUES (?, ?, ?, ?)
                    ''', (item.id, dep, None, "import"))
            
        conn.commit()
        conn.close()

    def load(self) -> List[ContextItem]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM items')
        rows = cursor.fetchall()
        conn.close()
        return [self._row_to_item(row) for row in rows]

    def search_hybrid(self, query_text: str, query_embedding: Optional[List[float]] = None, limit: int = 50, alpha: float = 0.5) -> List[ContextItem]:
        """
        Performs a hybrid search combining FTS BM25 scores with Cosine Similarity.
        alpha: Weight for Vector Score (0.0 - 1.0). 1.0 = Pure Vector, 0.0 = Pure Keyword.
        """
        import numpy as np
        
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. FTS Search to get candidate set and BM25 scores
        clean_query = query_text.replace('"', '""')
        
        # We use a custom query to get rank
        # fts5 returns rank (lower is better usually? No, fts5 bm25 is negative log prob? 
        # Actually fts5 'bm25' func returns a score where smaller is better (more negative).
        # But 'rank' column usually needs configuring. 
        # Let's use standard MATCH and assume reliable ordering.
        # But wait, we need normalized scores to combine.
        
        # Simplified: Get top N keyword results
        fts_candidates = {}
        try:
             cursor.execute('''
                SELECT id, rank FROM items_fts WHERE items_fts MATCH ? ORDER BY rank LIMIT 100
             ''', (clean_query,))
             for row in cursor.fetchall():
                 # FTS rank is usually smaller = better. Invert it roughly for mixing.
                 # Let's just store the rank and normalize later
                 fts_candidates[row[0]] = row[1] 
        except sqlite3.OperationalError:
             pass # FTS failed
        
        # 2. Vector Search (Brute force over all items with embeddings)
        # In a real system, we'd filter by layer or use an index.
        # For small codebases (<10k items), numpy brute force is fine (<50ms).
        
        vector_scores = {}
        if query_embedding:
            cursor.execute('SELECT id, embedding FROM items WHERE embedding IS NOT NULL')
            rows = cursor.fetchall()
            
            if rows:
                ids = []
                vectors = []
                for r_id, r_blob in rows:
                    ids.append(r_id)
                    vectors.append(np.frombuffer(r_blob, dtype=np.float32))
                
                if vectors:
                    matrix = np.vstack(vectors) # (N, D)
                    q_vec = np.array(query_embedding, dtype=np.float32) # (D,)
                    
                    # Cosine Similarity: (A . B) / (|A| |B|)
                    # Assume vectors are normalized? If not, normalize.
                    norm_matrix = np.linalg.norm(matrix, axis=1)
                    norm_q = np.linalg.norm(q_vec)
                    
                    if norm_q > 0:
                         # dot product
                         scores = np.dot(matrix, q_vec) / (norm_matrix * norm_q)
                         # Map to Dictionary
                         for i, score in enumerate(scores):
                             vector_scores[ids[i]] = float(score)

        # 3. Combine Scores
        # We need the union of keys
        all_ids = set(fts_candidates.keys()) | set(vector_scores.keys())
        final_scores = []
        
        for item_id in all_ids:
            # Normalize FTS rank
            # FTS rank: closer to 0 is better (usually negative or small positive).
            # Let's treat FTS presence as a strong signal.
            # Very heuristic: 
            fts_score = 0.0
            if item_id in fts_candidates:
                raw_rank = fts_candidates[item_id]
                # Invert rank: 1 / (1 + rank) ? Rank can be negative.
                # Let's just assign a fixed high score for being in top 100 FTS results 
                # scaled by position?
                # Simpler: If in FTS, score 1.0. If not, 0.0. 
                # This equals "Boost Semantic results that also match Keywords"
                fts_score = 1.0 
            
            vec_score = vector_scores.get(item_id, 0.0)
            
            # Simple weighted average
            # If we don't have embeddings, alpha should be effectively 0
            effective_alpha = alpha if query_embedding else 0.0
            
            # Hybrid Score
            # If effective_alpha is 0.5: 50% keyword presence, 50% semantic similarity
            score = ((1 - effective_alpha) * fts_score) + (effective_alpha * vec_score)
            
            final_scores.append((item_id, score))
            
        final_scores.sort(key=lambda x: x[1], reverse=True)
        top_ids = [x[0] for x in final_scores[:limit]]
        
        # 4. Fetch full items
        results = []
        if top_ids:
            placeholders = ','.join(['?'] * len(top_ids))
            # Preserve order? Python list is ordered, SQL IN is not.
            cursor.execute(f'SELECT * FROM items WHERE id IN ({placeholders})', top_ids)
            rows = cursor.fetchall()
            row_map = {row[0]: row for row in rows}
            
            for item_id in top_ids:
                if item_id in row_map:
                    results.append(self._row_to_item(row_map[item_id]))
                    
        if use_own_conn:
            conn.close()
            
        return results

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
                    SELECT id FROM items_fts WHERE items_fts MATCH ?
                )
                ORDER BY score DESC
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
        """Returns list of (source_id, target_key, target_id) for given source_ids."""
        if not source_ids:
            return []
            
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        placeholders = ','.join(['?'] * len(source_ids))
        cursor.execute(f'SELECT source_id, target_key, target_id FROM edges WHERE source_id IN ({placeholders})', source_ids)
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

    def get_inbound_edges(self, target_id: str) -> List[ContextItem]:
        """
        Reverse lookup: Find all items that depend on (import/call) the target_id.
        This uses the 'target_id' column populated by the Linker.
        """
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Join edges with items to get the full source item
        cursor.execute('''
            SELECT i.* 
            FROM edges e
            JOIN items i ON e.source_id = i.id
            WHERE e.target_id = ?
        ''', (target_id,))
        
        rows = cursor.fetchall()
        
        if use_own_conn:
            conn.close()
            
        return [self._row_to_item(row) for row in rows]

    def should_reindex(self, file_path: str, current_mtime: float) -> bool:
        """Returns True if file needs to be re-indexed (new or modified)."""
        # Normalize path
        abs_path = os.path.abspath(file_path)
        
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('SELECT last_modified FROM tracked_files WHERE path = ?', (abs_path,))
            result = cursor.fetchone()
            
            if result is None:
                return True # New file
                
            stored_mtime = result[0]
            # Check if modified (using a small epsilon for float comparison safety, though simple inequality usually works)
            return abs(current_mtime - stored_mtime) > 0.001
            
        finally:
            if use_own_conn:
                conn.close()

    def update_file_status(self, file_path: str, current_mtime: float):
        """Updates the tracked modified time for a file."""
        abs_path = os.path.abspath(file_path)
        
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO tracked_files (path, last_modified)
                VALUES (?, ?)
            ''', (abs_path, current_mtime))
            conn.commit()
        finally:
            if use_own_conn:
                conn.close()

    def cleanup_deleted_files(self, current_files: List[str]):
        """Removes items and tracking info for files that no longer exist."""
        # Normalize all current files
        current_files_set = set(os.path.abspath(f) for f in current_files)
        
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get all tracked files
            cursor.execute('SELECT path FROM tracked_files')
            row_paths = cursor.fetchall()
            tracked_paths = [r[0] for r in row_paths]
            
            # Find missing files
            missing_files = [p for p in tracked_paths if p not in current_files_set]
            
            if missing_files:
                for missing in missing_files:
                    # 1. Remove from tracked_files
                    cursor.execute('DELETE FROM tracked_files WHERE path = ?', (missing,))
                    
                    # 2. Remove items derived from this file
                    # We stored 'source_file' in items table. 
                    # Note: source_file might be absolute or relative depending on how it was saved.
                    # Ideally we should strictly use absolute paths everywhere.
                    # For now, let's try to match both just in case, or rely on what we saved.
                    cursor.execute('DELETE FROM items WHERE source_file = ?', (missing,))
                    
                    # Also delete items that MIGHT be relative path if that's what we stored?
                    # The analyzer seems to store absolute path in 'source_file' if passed absolute path.
                    
                    # Cleanup edges where source was deleted (cascade from items? no proper cascade set on items delete?)
                    # We set FOREIGN KEY but did we enable foreign keys? simpler to delete edges explicitly or rely on next save cleanup.
                    # But if we delete items, we should delete edges.
                    # We'll rely on a separate query or join delete for edges.
                    
                    # Let's clean orphan edges just in case
                    # (This is expensive to do one by one, better to do by subquery)
                    
                # Batch cleanup edges for missing file items
                # "DELETE FROM edges WHERE source_id NOT IN (SELECT id FROM items)"
                cursor.execute('DELETE FROM edges WHERE source_id NOT IN (SELECT id FROM items)')
                
                # Also clean FTS
                cursor.execute('DELETE FROM items_fts WHERE id NOT IN (SELECT id FROM items)')

                conn.commit()
                print(f"Cleaned up {len(missing_files)} deleted files.")
                
        finally:
            if use_own_conn:
                conn.close()

    def get_all_edges(self) -> List[tuple]:
        """Returns all edges in the graph as (source_id, target_key, target_id, relation_type)."""
        use_own_conn = self._conn is None
        conn = self._conn if self._conn else sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT source_id, target_key, target_id, relation_type FROM edges')
        rows = cursor.fetchall()
        
        if use_own_conn:
            conn.close()
            
        return rows
