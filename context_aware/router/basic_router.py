from typing import List
from ..store.json_store import JSONContextStore
from ..models.context_item import ContextItem

class BasicRouter:
    def __init__(self, store: JSONContextStore):
        self.store = store

    def route(self, query: str) -> List[ContextItem]:
        # MVP: Direct query to store
        return self.store.query(query)
