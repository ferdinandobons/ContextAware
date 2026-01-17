"""
Abstract base class for language-specific source code analyzers.

Analyzers are responsible for parsing source files and extracting semantic
information (classes, functions, imports, dependencies). Each supported
language has its own analyzer implementation.

The analyzer interface defines two core operations:
  1. analyze_file: Parse a file and extract all indexable symbols
  2. extract_code_by_symbol: Retrieve the source code for a specific symbol

Currently, TreeSitterAnalyzer (ts_analyzer.py) implements this interface
for Python, JavaScript, TypeScript, and Go using Tree-sitter grammars.

To add support for a new language:
  1. Create a new analyzer class inheriting from BaseAnalyzer
  2. Implement analyze_file() to parse the language's syntax
  3. Implement extract_code_by_symbol() for on-demand code retrieval
  4. Register the file extension in ts_analyzer.SUPPORTED_EXTENSIONS
"""
from abc import ABC, abstractmethod
from typing import List, Optional

from ..models.context_item import ContextItem


class BaseAnalyzer(ABC):
    """
    Abstract interface for language-specific source code analyzers.

    Implementations must provide two capabilities:
      1. Full-file analysis: Extract all symbols (classes, functions) as ContextItems
      2. Symbol extraction: Retrieve the source code for a specific named symbol

    This abstraction allows ContextAware to support multiple languages through
    a unified interface, with each language using its own parsing strategy.
    """

    @abstractmethod
    def analyze_file(self, file_path: str) -> List[ContextItem]:
        """
        Parse a source file and extract all indexable symbols.

        Args:
            file_path: Absolute path to the source file

        Returns:
            List of ContextItems containing:
              - One file-level item (type="file") with imports as dependencies
              - One item per class/function defined in the file

        Note:
            Returns an empty list if the file cannot be read or parsed.
            Each ContextItem includes metadata for dependency tracking.
        """
        pass

    @abstractmethod
    def extract_code_by_symbol(self, file_path: str, symbol_name: str) -> Optional[str]:
        """
        Extract the complete source code for a specific symbol.

        Used by the "read" command to fetch live code from the filesystem,
        ensuring users always see the current version even if the index is stale.

        Args:
            file_path: Absolute path to the source file
            symbol_name: Name of the symbol to extract (e.g., "UserService")

        Returns:
            The full source code of the symbol (including body), or None if
            the symbol is not found (may have been renamed or deleted).
        """
        pass
