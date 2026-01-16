from typing import List
from ..store.json_store import JSONContextStore
from ..models.context_item import ContextItem

class BasicRouter:
    def __init__(self, store: JSONContextStore):
        self.store = store

    def route(self, query: str) -> List[ContextItem]:
        items = self.load() # Was self.store.query(query) but that filtered inside store. We need all items to score them.
        # Ideally store should support this, but for MVP we fetch all and filter in memory
        
        results = []
        query_tokens = query.lower().split()
        if not query_tokens:
            return []
            
        for item in items:
            score = 0
            content_lower = item.content.lower()
            meta_str = str(item.metadata).lower()
            
            # Exact match bonus
            if query.lower() in content_lower:
                score += 10
            
            # Token match
            matches = 0
            for token in query_tokens:
                if token in content_lower or token in meta_str:
                    matches += 1
            
            if matches > 0:
                score += matches
                
            if score > 0:
                results.append((score, item))
        
        # Sort by score desc
        results.sort(key=lambda x: x[0], reverse=True)
        
        # Return top 20 items to avoid flooding
        return [item for score, item in results[:20]]

    def load(self) -> List[ContextItem]:
        return self.store.load()
