from typing import List, Optional
import os

class EmbeddingService:
    _instance = None
    _model = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        
    def _load_model(self):
        if self._model is None:
            # Lazy import to avoid slow startup for CLI commands that don't need it
            try:
                from sentence_transformers import SentenceTransformer
                print(f"Loading embedding model: {self.model_name}...")
                self._model = SentenceTransformer(self.model_name)
            except ImportError:
                print("Warning: sentence-transformers not installed. Semantic search disabled.")
                self._model = None
                
    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        self._load_model()
        if not self._model:
            return []
            
        if not texts:
            return []
            
        # Returns numpy array, convert to list
        embeddings = self._model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()
        
    def generate_embedding(self, text: str) -> Optional[List[float]]:
        results = self.generate_embeddings([text])
        if results:
            return results[0]
        return None
