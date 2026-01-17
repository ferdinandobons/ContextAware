"""
Embedding Service: Generates vector embeddings for semantic search.

Uses sentence-transformers to convert text into dense vectors that capture
semantic meaning. These embeddings enable "concept search" - finding code
that's semantically related even without exact keyword matches.

Model: all-MiniLM-L6-v2 (default)
  - 384-dimensional vectors
  - Fast inference, good quality for code
  - ~80MB model size

The service is a thread-safe singleton with LRU caching to avoid
recomputing embeddings for frequently-searched queries.
"""
import logging
import threading
from collections import OrderedDict
from typing import List, Optional

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Thread-safe singleton for generating text embeddings.

    Why singleton? The embedding model is large (~80MB) and slow to load.
    Sharing one instance across the application avoids repeated loading
    and reduces memory usage.

    Why LRU cache? Query embeddings are often repeated (e.g., user refines
    search). Caching avoids redundant computation.
    """

    _instance: Optional["EmbeddingService"] = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls, model_name: str = "all-MiniLM-L6-v2"):
        if cls._instance is not None and cls._initialized:
            raise RuntimeError(
                "EmbeddingService is a singleton. Use get_instance() instead."
            )
        return super().__new__(cls)

    @classmethod
    def get_instance(cls, model_name: str = "all-MiniLM-L6-v2") -> "EmbeddingService":
        """
        Get or create the singleton instance.

        Thread-safe: uses a lock to prevent race conditions during
        first initialization in multi-threaded contexts.
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(model_name)
                cls._instance._load_model()
                cls._initialized = True
        return cls._instance

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        if hasattr(self, '_model_name'):
            return
        self._model_name = model_name
        self._model = None
        self._model_loaded = False
        # OrderedDict maintains insertion order for LRU eviction
        self._embedding_cache: OrderedDict = OrderedDict()
        self._cache_max_size = 1024

    def _load_model(self):
        """
        Load the sentence-transformers model.

        Fails gracefully if the library isn't installed - semantic search
        will be disabled but the rest of the application works.
        """
        if self._model_loaded:
            return
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {self._model_name}...")
            self._model = SentenceTransformer(self._model_name)
        except ImportError:
            logger.warning("sentence-transformers not installed. Semantic search disabled.")
            self._model = None
        self._model_loaded = True

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in batch.

        Batching is more efficient than single-text calls because it
        allows the model to parallelize computation on GPU/CPU.
        """
        if not self._model:
            return []

        if not texts:
            return []

        embeddings = self._model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding for a single text with LRU caching.

        Cache hit: O(1) lookup, moves entry to end (most recently used)
        Cache miss: Generate embedding, evict oldest if at capacity
        """
        if not self._model:
            return None

        if text in self._embedding_cache:
            self._embedding_cache.move_to_end(text)
            return self._embedding_cache[text]

        results = self.generate_embeddings([text])
        if results:
            embedding = results[0]
            if len(self._embedding_cache) >= self._cache_max_size:
                self._embedding_cache.popitem(last=False)
            self._embedding_cache[text] = embedding
            return embedding
        return None

    def clear_cache(self) -> None:
        """Clear all cached embeddings (useful for testing or memory pressure)."""
        self._embedding_cache.clear()

    def get_cache_stats(self) -> dict:
        """Return cache statistics for monitoring/debugging."""
        return {
            "size": len(self._embedding_cache),
            "max_size": self._cache_max_size
        }
