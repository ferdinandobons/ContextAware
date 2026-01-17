"""
SQLite-based storage for the ContextAware index.

This module provides persistent storage for:
  - Context items (files, classes, functions) with metadata
  - Dependency graph edges (who imports/calls what)
  - File tracking for incremental indexing
  - FTS5 full-text search index
  - Vector embeddings for semantic search

Database location: .context_aware/context.db (relative to project root)

Schema overview:
  - items: Main table storing indexed symbols
  - edges: Dependency relationships between items
  - tracked_files: Modification times for incremental indexing
  - items_fts: FTS5 virtual table for full-text search
"""
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterable, List, Optional, Tuple, TYPE_CHECKING

from ..models.context_item import ContextItem, ContextLayer

if TYPE_CHECKING:
    import numpy as np

# Lazy import for numpy (only needed for semantic search)
_np = None

def _get_numpy():
    """Lazy load numpy only when needed for vector operations."""
    global _np
    if _np is None:
        try:
            import numpy
            _np = numpy
        except ImportError:
            raise ImportError(
                "numpy is required for semantic search. "
                "Install it with: pip install numpy"
            )
    return _np

logger = logging.getLogger(__name__)


class SQLiteContextStore:
    """
    Persistent storage layer using SQLite.

    Supports two usage patterns:
      1. Context manager: `with store:` - keeps connection open for batched ops
      2. Method calls: Each method opens/closes its own connection

    The context manager pattern is preferred for operations that make
    multiple queries, as it avoids connection overhead.
    """

    def __init__(self, root_dir: str = "."):
        self.storage_dir = os.path.join(root_dir, ".context_aware")
        self.db_path = os.path.join(self.storage_dir, "context.db")
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_storage()

    def __enter__(self) -> "SQLiteContextStore":
        """Open a persistent connection for batched operations."""
        self._conn = sqlite3.connect(self.db_path)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close the persistent connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @contextmanager
    def _get_connection(self):
        """
        Get a database connection, creating one if needed.

        If we're inside a `with store:` block, reuses the existing connection.
        Otherwise, creates a temporary connection that's closed after use.
        """
        if self._conn is not None:
            yield self._conn
        else:
            conn = sqlite3.connect(self.db_path)
            try:
                yield conn
            finally:
                conn.close()

    def _ensure_storage(self) -> None:
        """
        Initialize the database schema if it doesn't exist.

        Creates tables, indexes, and runs any necessary migrations.
        This is called on every store instantiation but is idempotent.
        """
        os.makedirs(self.storage_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Main items table - stores all indexed symbols
            # id format: "type:filename:symbolname" (e.g., "class:user.py:User")
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

            # Schema migration: add embedding column if missing (for upgrades)
            cursor.execute("PRAGMA table_info(items)")
            columns = [info[1] for info in cursor.fetchall()]
            if "embedding" not in columns:
                cursor.execute("ALTER TABLE items ADD COLUMN embedding BLOB")

            # Edges table: stores the dependency graph
            # target_key: symbolic reference (e.g., "UserService")
            # target_id: resolved item ID (filled by GraphLinker)
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

            # Indexes optimized for common access patterns
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_key)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_edges_target_id ON edges(target_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_edges_source_target ON edges(source_id, target_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_items_source_file ON items(source_file)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_items_layer ON items(layer)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_items_score ON items(score DESC)')

            # File tracking for incremental indexing (skip unchanged files)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tracked_files (
                    path TEXT PRIMARY KEY,
                    last_modified REAL
                )
            ''')

            # FTS5 for fast full-text search (falls back to LIKE if unavailable)
            try:
                cursor.execute('''
                    CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(id, content, metadata)
                ''')
            except sqlite3.OperationalError:
                logger.warning("FTS5 not available. Fallback to LIKE query.")

            conn.commit()
        finally:
            conn.close()

    def has_index(self) -> bool:
        """Check if the database has any indexed items (used by CLI for prompts)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('SELECT 1 FROM items LIMIT 1')
                result = cursor.fetchone()
                return result is not None
            except sqlite3.OperationalError:
                return False

    def _sanitize_fts_query(self, query_text: str) -> str:
        """
        Sanitize user input for safe FTS5 MATCH queries.

        FTS5 has special syntax characters that could cause errors or
        unexpected behavior. We strip them and wrap in quotes for phrase matching.
        """
        for char in ['"', '*', '+', '-', '^', ':', '(', ')']:
            query_text = query_text.replace(char, ' ')
        query_text = ' '.join(query_text.split())
        return f'"{query_text}"'

    def _sanitize_like_query(self, query_text: str) -> str:
        """Escape LIKE wildcards to prevent pattern injection."""
        query_text = query_text.replace('\\', '\\\\')
        query_text = query_text.replace('%', '\\%')
        query_text = query_text.replace('_', '\\_')
        return query_text

    def save(self, items: List[ContextItem]) -> None:
        """
        Persist a batch of ContextItems to the database.

        For each item:
          1. Upsert into items table (with optional embedding)
          2. Update FTS index for search
          3. Create edges for declared dependencies
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            for item in items:
                meta_json = json.dumps(item.metadata)

                # Convert embedding list to binary blob for storage
                embedding_blob = None
                if item.embedding:
                    np = _get_numpy()
                    arr = np.array(item.embedding, dtype=np.float32)
                    embedding_blob = arr.tobytes()

                cursor.execute('''
                    INSERT OR REPLACE INTO items (id, layer, content, metadata, source_file, line_number, score, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (item.id, item.layer.value, item.content, meta_json, item.source_file, item.line_number, 0.0, embedding_blob))

                # Keep FTS in sync (delete + insert for upsert semantics)
                cursor.execute('DELETE FROM items_fts WHERE id = ?', (item.id,))
                cursor.execute('''
                    INSERT INTO items_fts (id, content, metadata)
                    VALUES (?, ?, ?)
                ''', (item.id, item.content, meta_json))

                # Create edge records for dependencies (target_id filled later by linker)
                cursor.execute('DELETE FROM edges WHERE source_id = ?', (item.id,))

                deps = item.metadata.get("dependencies", [])
                for dep in deps:
                    if dep:
                        cursor.execute('''
                            INSERT OR IGNORE INTO edges (source_id, target_key, target_id, relation_type)
                            VALUES (?, ?, ?, ?)
                        ''', (item.id, dep, None, "import"))

            conn.commit()

    def load(self) -> List[ContextItem]:
        """Load all items from the database (used for graph export)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM items')
            rows = cursor.fetchall()
            return [self._row_to_item(row) for row in rows]

    def search_hybrid(
        self,
        query_text: str,
        query_embedding: Optional[List[float]] = None,
        limit: int = 50,
        alpha: float = 0.5,
        type_filter: Optional[str] = None
    ) -> List[ContextItem]:
        """
        Hybrid search combining keyword (FTS) and semantic (vector) signals.

        Algorithm:
          1. FTS5 search for keyword matches (fast, precise)
          2. Vector similarity search across all embeddings (slower, semantic)
          3. Combine scores: score = (1-alpha)*FTS + alpha*vector
          4. Return top results sorted by combined score

        Args:
            query_text: User's search query
            query_embedding: Pre-computed embedding of query (None = FTS only)
            limit: Maximum results to return
            alpha: Balance between FTS (0) and vector (1). Default 0.5 = equal weight
            type_filter: Optional filter for "class", "function", or "file"
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Phase 1: FTS candidate retrieval
            clean_query = self._sanitize_fts_query(query_text)

            fts_candidates = {}
            try:
                cursor.execute('''
                    SELECT id, rank FROM items_fts WHERE items_fts MATCH ? ORDER BY rank LIMIT 100
                ''', (clean_query,))
                for row in cursor.fetchall():
                    fts_candidates[row[0]] = row[1]
            except sqlite3.OperationalError:
                pass

            # Phase 2: Vector similarity (brute force - fine for small codebases)
            vector_scores = {}
            if query_embedding:
                np = _get_numpy()
                if type_filter:
                    cursor.execute(
                        "SELECT id, embedding FROM items WHERE embedding IS NOT NULL AND metadata LIKE ?",
                        (f'%"type": "{type_filter}"%',)
                    )
                else:
                    cursor.execute('SELECT id, embedding FROM items WHERE embedding IS NOT NULL')
                rows = cursor.fetchall()

                if rows:
                    ids = []
                    vectors = []
                    for r_id, r_blob in rows:
                        ids.append(r_id)
                        vectors.append(np.frombuffer(r_blob, dtype=np.float32))

                    if vectors:
                        matrix = np.vstack(vectors)
                        q_vec = np.array(query_embedding, dtype=np.float32)

                        # Compute cosine similarity: dot(A, B) / (||A|| * ||B||)
                        norm_matrix = np.linalg.norm(matrix, axis=1)
                        norm_q = np.linalg.norm(q_vec)

                        if norm_q > 1e-10 and np.any(norm_matrix > 1e-10):
                            safe_norm_matrix = np.where(norm_matrix < 1e-10, 1.0, norm_matrix)
                            scores = np.dot(matrix, q_vec) / (safe_norm_matrix * norm_q)
                            scores = np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)
                            for i, score in enumerate(scores):
                                vector_scores[ids[i]] = float(score)

            # Phase 3: Score fusion
            all_ids = set(fts_candidates.keys()) | set(vector_scores.keys())
            final_scores = []

            for item_id in all_ids:
                fts_score = 1.0 if item_id in fts_candidates else 0.0
                vec_score = vector_scores.get(item_id, 0.0)

                effective_alpha = alpha if query_embedding else 0.0
                score = ((1 - effective_alpha) * fts_score) + (effective_alpha * vec_score)
                final_scores.append((item_id, score))

            final_scores.sort(key=lambda x: x[1], reverse=True)
            top_ids = [x[0] for x in final_scores[:limit]]

            # Phase 4: Fetch full items (preserving ranked order)
            results = []
            if top_ids:
                placeholders = ','.join(['?'] * len(top_ids))
                cursor.execute(f'SELECT * FROM items WHERE id IN ({placeholders})', top_ids)
                rows = cursor.fetchall()
                row_map = {row[0]: row for row in rows}

                for item_id in top_ids:
                    if item_id in row_map:
                        results.append(self._row_to_item(row_map[item_id]))

            return results

    def query(self, query_text: str, type_filter: Optional[str] = None) -> List[ContextItem]:
        """
        Execute a full-text search query using FTS5 (with LIKE fallback).

        Args:
            query_text: Search keywords
            type_filter: Optional filter for "class", "function", or "file"

        Returns:
            Matching ContextItems, ordered by importance score
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            clean_query = self._sanitize_fts_query(query_text)

            try:
                # Apply type_filter at SQL level for efficiency
                if type_filter:
                    cursor.execute('''
                        SELECT * FROM items
                        WHERE id IN (
                            SELECT id FROM items_fts WHERE items_fts MATCH ?
                        ) AND metadata LIKE ?
                        ORDER BY score DESC
                    ''', (clean_query, f'%"type": "{type_filter}"%'))
                else:
                    cursor.execute('''
                        SELECT * FROM items
                        WHERE id IN (
                            SELECT id FROM items_fts WHERE items_fts MATCH ?
                        )
                        ORDER BY score DESC
                    ''', (clean_query,))
            except sqlite3.OperationalError:
                # Fallback to LIKE
                like_query = self._sanitize_like_query(query_text)
                base_query = "SELECT * FROM items WHERE (content LIKE ? ESCAPE '\\' OR metadata LIKE ? ESCAPE '\\')"
                params = [f"%{like_query}%", f"%{like_query}%"]

                if type_filter:
                    base_query += " AND metadata LIKE ? ESCAPE '\\'"
                    params.append(f'%"type": "{type_filter}"%')

                cursor.execute(base_query, params)

            rows = cursor.fetchall()
            return [self._row_to_item(row) for row in rows]

    def get_by_id(self, item_id: str) -> Optional[ContextItem]:
        """Fetch a single item by its exact ID, or None if not found."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM items WHERE id = ?', (item_id,))
            row = cursor.fetchone()
            return self._row_to_item(row) if row else None

    def get_items_by_ids(self, item_ids: Iterable[str]) -> List[ContextItem]:
        """Batch fetch items by IDs - optimized to avoid N+1 queries.
        Accepts any iterable (list, set, tuple) to avoid unnecessary conversions.
        """
        # Convert to tuple for SQL params (works with any iterable)
        ids_tuple = tuple(item_ids)
        if not ids_tuple:
            return []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Use parameterized query with IN clause
            placeholders = ','.join(['?'] * len(ids_tuple))
            cursor.execute(f'SELECT * FROM items WHERE id IN ({placeholders})', ids_tuple)
            rows = cursor.fetchall()
            return [self._row_to_item(row) for row in rows]

    def _row_to_item(self, row: Tuple) -> ContextItem:
        """
        Convert a database row tuple to a ContextItem object.

        Row format: (id, layer, content, metadata_json, source_file, line_number, score, embedding)
        """
        try:
            metadata = json.loads(row[3])
        except json.JSONDecodeError:
            metadata = {}
        return ContextItem(
            id=row[0],
            layer=ContextLayer(row[1]),
            content=row[2],
            metadata=metadata,
            source_file=row[4],
            line_number=row[5]
        )

    def get_outbound_edges(self, source_ids: List[str]) -> List[Tuple[str, str, Optional[str]]]:
        """
        Get all outgoing dependency edges from the given items.

        Used by GraphRouter to expand search results along dependency paths.
        Returns: [(source_id, target_key, target_id), ...]
        """
        if not source_ids:
            return []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ','.join(['?'] * len(source_ids))
            cursor.execute(
                f'SELECT source_id, target_key, target_id FROM edges WHERE source_id IN ({placeholders})',
                source_ids
            )
            return cursor.fetchall()

    def get_items_by_name(self, names: Iterable[str]) -> List[ContextItem]:
        """
        Lookup items by symbol name (fallback for unresolved edges).

        This is slower than ID lookup because it scans metadata with LIKE.
        Used when GraphLinker hasn't resolved an edge yet.
        """
        names_list = list(names)
        if not names_list:
            return []

        with self._get_connection() as conn:
            cursor = conn.cursor()

            conditions = []
            params = []
            for name in names_list:
                escaped_name = self._sanitize_like_query(name)
                conditions.append("metadata LIKE ? ESCAPE '\\'")
                params.append(f'%"name": "{escaped_name}"%')

            if not conditions:
                return []

            query = f"SELECT * FROM items WHERE {' OR '.join(conditions)}"
            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Deduplicate (a symbol name might match multiple items)
            seen_ids = set()
            results = []
            for row in rows:
                if row[0] not in seen_ids:
                    seen_ids.add(row[0])
                    results.append(self._row_to_item(row))

            return results

    def get_inbound_edges(self, target_id: str) -> List[ContextItem]:
        """
        Reverse lookup: find all items that depend on the given target.

        Used by the "impacts" command to answer "what would break if I change X?"
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT i.*
                FROM edges e
                JOIN items i ON e.source_id = i.id
                WHERE e.target_id = ?
            ''', (target_id,))
            rows = cursor.fetchall()
            return [self._row_to_item(row) for row in rows]

    def get_cascade_dependents(
        self,
        target_id: str,
        max_depth: int = 3
    ) -> Tuple[List[ContextItem], List[ContextItem]]:
        """
        Get both direct and cascade dependents using BFS traversal.

        Returns:
            Tuple of (direct_dependents, cascade_dependents)
            where cascade_dependents are items indirectly affected.
        """
        direct = self.get_inbound_edges(target_id)
        direct_ids = {item.id for item in direct}

        # BFS for cascade
        visited = {target_id} | direct_ids
        current_layer = direct_ids
        cascade = []

        for depth in range(max_depth - 1):
            if not current_layer:
                break

            next_layer = set()
            for item_id in current_layer:
                dependents = self.get_inbound_edges(item_id)
                for dep in dependents:
                    if dep.id not in visited:
                        visited.add(dep.id)
                        next_layer.add(dep.id)
                        cascade.append(dep)

            current_layer = next_layer

        return direct, cascade

    def should_reindex(self, file_path: str, current_mtime: float) -> bool:
        """
        Check if a file needs re-indexing based on modification time.

        Enables incremental indexing: only re-parse files that changed.
        """
        abs_path = os.path.abspath(file_path)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT last_modified FROM tracked_files WHERE path = ?', (abs_path,))
            result = cursor.fetchone()

            if result is None:
                return True

            return current_mtime != result[0]

    def update_file_status(self, file_path: str, current_mtime: float) -> None:
        """Record that a file was indexed at the given modification time."""
        abs_path = os.path.abspath(file_path)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO tracked_files (path, last_modified)
                VALUES (?, ?)
            ''', (abs_path, current_mtime))
            conn.commit()

    def cleanup_deleted_files(self, current_files: List[str]) -> None:
        """
        Remove index entries for files that were deleted from disk.

        Called during directory indexing to keep the database in sync.
        Also cleans up orphaned edges and FTS entries.
        """
        current_files_set = set(os.path.abspath(f) for f in current_files)

        with self._get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT path FROM tracked_files')
            tracked_paths = [r[0] for r in cursor.fetchall()]

            missing_files = [p for p in tracked_paths if p not in current_files_set]

            if missing_files:
                for missing in missing_files:
                    cursor.execute('DELETE FROM tracked_files WHERE path = ?', (missing,))
                    cursor.execute('DELETE FROM items WHERE source_file = ?', (missing,))

                cursor.execute('DELETE FROM edges WHERE source_id NOT IN (SELECT id FROM items)')
                cursor.execute('DELETE FROM items_fts WHERE id NOT IN (SELECT id FROM items)')

                conn.commit()
                logger.info(f"Cleaned up {len(missing_files)} deleted files.")

    def get_all_edges(self) -> List[Tuple[str, str, Optional[str], str]]:
        """Return all edges for graph export (Mermaid, visualization)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT source_id, target_key, target_id, relation_type FROM edges')
            return cursor.fetchall()

    def get_all_items_metadata(self) -> List[Tuple[str, str, str]]:
        """Return lightweight item data for the linker's name resolution."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, metadata, source_file FROM items")
            return cursor.fetchall()

    def get_unresolved_edges(self) -> List[Tuple[int, str]]:
        """Return edges that haven't been linked to concrete IDs yet."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT rowid, target_key FROM edges WHERE target_id IS NULL")
            return cursor.fetchall()

    def batch_update_edge_targets(self, updates: List[Tuple[str, int]]) -> None:
        """Bulk update resolved target_ids (called by GraphLinker)."""
        if not updates:
            return

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("UPDATE edges SET target_id = ? WHERE rowid = ?", updates)
            conn.commit()

    def batch_update_scores(self, scores: List[Tuple[float, str]]) -> None:
        """Bulk update importance scores (called by GraphLinker)."""
        if not scores:
            return

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("UPDATE items SET score = ? WHERE id = ?", scores)
            conn.commit()

    def get_indegree_counts(self) -> List[Tuple[str, int]]:
        """
        Count incoming edges per item for importance scoring.

        Items with more dependents are considered more important.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT target_id, COUNT(*) as degree
                FROM edges
                WHERE target_id IS NOT NULL
                GROUP BY target_id
            ''')
            return cursor.fetchall()

    def get_graph_nodes(self, limit: Optional[int] = None, offset: int = 0) -> List[dict]:
        """
        Return node data for vis.js graph visualization.

        Returns lightweight dicts with just the fields needed for rendering,
        ordered by importance score. Supports pagination for large graphs.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if limit:
                cursor.execute(
                    'SELECT id, metadata FROM items ORDER BY score DESC LIMIT ? OFFSET ?',
                    (limit, offset)
                )
            else:
                cursor.execute('SELECT id, metadata FROM items ORDER BY score DESC')

            nodes = []
            for row in cursor.fetchall():
                item_id = row[0]
                try:
                    meta = json.loads(row[1])
                except json.JSONDecodeError:
                    meta = {}
                nodes.append({
                    "id": item_id,
                    "label": meta.get("name", item_id.split(":")[-1]),
                    "group": meta.get("type", "unknown"),
                    "title": item_id
                })
            return nodes

    def get_item_count(self) -> int:
        """Return total items in the index (for pagination info)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM items')
            result = cursor.fetchone()
            return result[0] if result else 0
