"""
Core data models for ContextAware.

This module defines the fundamental data structures used throughout the system:
  - ContextLayer: Categorizes items by their abstraction level
  - ContextItem: Represents an indexed code element (file, class, function)

These models are used by:
  - Analyzer: Creates ContextItems from parsed source files
  - Store: Persists and retrieves ContextItems from SQLite
  - Router: Searches and traverses ContextItems via the dependency graph
  - Compiler: Formats ContextItems as XML for LLM consumption
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ContextLayer(str, Enum):
    """
    Categorizes indexed items by their abstraction level.

    Layers help organize search results and can be used for filtering:
      - PROJECT: File-level items (the file itself, with imports as dependencies)
      - SEMANTIC: Code-level items (classes, functions, interfaces)

    The layer affects how items are displayed and ranked in search results.
    """
    PROJECT = "project"
    SEMANTIC = "semantic"


class ContextItem(BaseModel):
    """
    Represents an indexed code element in the ContextAware system.

    A ContextItem can be:
      - A file (type="file"): Represents the file with its imports as dependencies
      - A class (type="class"): A class/interface/struct definition
      - A function (type="function"): A function/method definition

    Attributes:
        id: Unique identifier in format "type:filename:name"
            Examples: "file:user.py", "class:user.py:User", "function:utils.py:calculate"

        layer: Abstraction level (PROJECT for files, SEMANTIC for code elements)

        content: Human-readable summary or signature
            - For search results: First line (e.g., "class User:")
            - For read operations: Full source code

        metadata: Flexible key-value store containing:
            - type: "file", "class", or "function"
            - name: Symbol name (e.g., "User", "calculate")
            - dependencies: List of imported modules or referenced symbols
            - file: Full path to source file (for class/function items)
            - lineno: Line number in source file (for class/function items)

        source_file: Absolute path to the source file (used to fetch live code)

        line_number: Starting line number in the source file (1-indexed)

        embedding: Optional 384-dim vector for semantic search (all-MiniLM-L6-v2)
            Only populated when indexing with --semantic flag
    """
    id: str
    layer: ContextLayer
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    source_file: Optional[str] = None
    line_number: Optional[int] = None
    embedding: Optional[List[float]] = None
