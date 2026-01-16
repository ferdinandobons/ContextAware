import json
import os
from typing import List, Optional
from ..models.context_item import ContextItem

class JSONContextStore:
    def __init__(self, storage_dir: str = ".context_aware"):
        self.storage_dir = storage_dir
        self.items_file = os.path.join(storage_dir, "context_items.json")
        self._ensure_storage()

    def _ensure_storage(self):
        os.makedirs(self.storage_dir, exist_ok=True)
        if not os.path.exists(self.items_file):
            with open(self.items_file, 'w') as f:
                json.dump([], f)

    def save(self, items: List[ContextItem]):
        existing = self.load()
        merged_map = {item.id: item for item in existing}
        
        for item in items:
            merged_map[item.id] = item
            
        final_list = list(merged_map.values())
        
        with open(self.items_file, 'w') as f:
            # model_dump is pydantic v2, dict is v1. Assuming v2 given 'BaseModel' usage pattern usually implies modern usage, 
            # but let's be safe. If user environment is old, this might fail. 
            # Reverting to typical .dict() for broad compatibility or assuming pydantic is installed. 
            # Using .model_dump() assuming Pydantic V2 is available (standard now).
            json.dump([item.model_dump() for item in final_list], f, indent=2)

    def load(self) -> List[ContextItem]:
        if not os.path.exists(self.items_file):
            return []
        with open(self.items_file, 'r') as f:
            try:
                data = json.load(f)
                return [ContextItem(**item) for item in data]
            except json.JSONDecodeError:
                return []
            
    def query(self, query_text: str) -> List[ContextItem]:
         items = self.load()
         results = []
         for item in items:
             # Basic fuzzy match
             match_content = query_text.lower() in item.content.lower()
             match_meta = query_text.lower() in str(item.metadata).lower()
             if match_content or match_meta:
                 results.append(item)
         return results
