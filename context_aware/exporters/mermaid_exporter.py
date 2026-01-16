from typing import List
import sqlite3
import json
from ..store.sqlite_store import SQLiteContextStore

class MermaidExporter:
    """
    Exports the dependency graph to Mermaid.js format.
    """
    def __init__(self, store: SQLiteContextStore):
        self.store = store

    def export(self) -> str:
        lines = ["graph TD"]
        
        # Styles
        # Styles
        lines.append("classDef file fill:#e1f5fe,stroke:#01579b,stroke-width:2px")
        lines.append("")
        lines.append("classDef class fill:#fff9c4,stroke:#fbc02d,stroke-width:2px")
        lines.append("")
        lines.append("classDef function fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px")
        lines.append("")
        
        conn = sqlite3.connect(self.store.db_path)
        cursor = conn.cursor()
        
        # 1. Fetch all items (Nodes)
        cursor.execute("SELECT id, metadata FROM items ORDER BY score DESC")
        items = cursor.fetchall()
        
        # Helper to sanitize IDs for Mermaid (remove : and .)
        def safe_id(raw_id):
            return raw_id.replace(":", "_").replace(".", "_").replace("-", "_")
            
        for raw_id, meta_json in items:
            meta = json.loads(meta_json)
            name = meta.get("name", raw_id)
            type_ = meta.get("type", "unknown")
            
            # Label: "Name"
            # Node ID: safe_id
            sid = safe_id(raw_id)
            label = f"{name}"
            
            # Assign class based on type
            style_class = "file"
            if type_ == "class": style_class = "class"
            if type_ == "function": style_class = "function"
            
            lines.append(f'  {sid}["{label}"]:::{style_class}')
            
        # 2. Fetch all edges (Relationships)
        cursor.execute("SELECT source_id, target_id FROM edges WHERE target_id IS NOT NULL")
        edges = cursor.fetchall()
        
        for source, target in edges:
            s_sid = safe_id(source)
            t_sid = safe_id(target)
            lines.append(f"  {s_sid} --> {t_sid}")
            
        conn.close()
        
        return "\n".join(lines)
