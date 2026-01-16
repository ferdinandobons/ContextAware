from abc import ABC, abstractmethod
from typing import List, Optional
from ..models.context_item import ContextItem

class BaseAnalyzer(ABC):
    """
    Abstract Base Class for language-specific analyzers.
    """
    
    @abstractmethod
    def analyze_file(self, file_path: str) -> List[ContextItem]:
        """
        Parses a file and returns a list of context items (file, classes, functions).
        """
        pass

    @abstractmethod
    def extract_code_by_symbol(self, file_path: str, symbol_name: str) -> Optional[str]:
        """
        Extracts the raw source code for a specific symbol (e.g. function/class body).
        """
        pass
