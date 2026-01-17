"""
Multi-language source code analyzer using Tree-sitter for AST parsing.

This module is the core of ContextAware's indexing pipeline. It extracts semantic
information (classes, functions, imports, dependencies) from source files by parsing
them into Abstract Syntax Trees using Tree-sitter grammars.

Supported languages: Python, JavaScript, TypeScript, Go.

Architecture:
    1. TreeSitterAnalyzer parses a file into an AST
    2. Tree-sitter queries extract named symbols (classes, functions)
    3. Import statements are parsed to build a dependency graph
    4. Each symbol becomes a ContextItem stored in SQLite for later search

Usage:
    analyzer = TreeSitterAnalyzer("python")
    items = analyzer.analyze_file("/path/to/file.py")
"""
import logging
import os
import re
from typing import List, Optional, Set, Dict, Pattern

from tree_sitter import Parser
import tree_sitter_languages

from ..models.context_item import ContextItem, ContextLayer
from .base_analyzer import BaseAnalyzer

logger = logging.getLogger(__name__)

# Pre-compiled regex for JS/TS imports: matches `from 'module'` or `import 'module'`
# Group 1: ES6 import source, Group 2: side-effect import
_JS_IMPORT_PATTERN: Pattern = re.compile(r"from\s+['\"]([^'\"]+)['\"]|^import\s+['\"]([^'\"]+)['\"]", re.MULTILINE)

# Pre-compiled regex for Go imports: matches quoted strings in import declarations
_GO_IMPORT_PATTERN: Pattern = re.compile(r'"([^"]+)"')

# Maps language names to their file extensions (used for file discovery during indexing)
SUPPORTED_EXTENSIONS: Dict[str, tuple] = {
    "python": (".py",),
    "javascript": (".js",),
    "typescript": (".ts", ".tsx"),
    "go": (".go",),
}

# Flattened tuple of all supported extensions for quick membership checks
ALL_SUPPORTED_EXTENSIONS: tuple = tuple(
    ext for exts in SUPPORTED_EXTENSIONS.values() for ext in exts
)


def get_language_for_file(file_path: str) -> Optional[str]:
    """
    Determine the programming language based on file extension.

    Used by the CLI and MCP server to select the correct analyzer for a file.
    Returns None for unsupported file types (which should be skipped during indexing).
    """
    for lang, exts in SUPPORTED_EXTENSIONS.items():
        if file_path.endswith(exts):
            return lang
    return None


class TreeSitterAnalyzer(BaseAnalyzer):
    """
    AST-based source code analyzer supporting Python, JavaScript, TypeScript, and Go.

    Uses Tree-sitter for parsing, which provides:
    - Fast incremental parsing (not used yet, but possible for IDE integration)
    - Language-agnostic query syntax for extracting symbols
    - Robust error recovery (can parse partially broken files)

    Class-level caches ensure compiled queries and regex patterns are reused
    across multiple file analyses, significantly improving indexing performance.
    """

    # Shared cache: compiled Tree-sitter queries (expensive to compile)
    _compiled_queries: Dict[str, object] = {}

    # Shared cache: regex patterns for symbol name matching in function bodies
    _symbol_patterns: Dict[str, Pattern] = {}

    def __init__(self, language_name: str):
        self.language_name = language_name
        self.language = tree_sitter_languages.get_language(language_name)
        self.parser = Parser()
        self.parser.set_language(self.language)

        # Tree-sitter S-expression queries for each language.
        # These queries capture:
        #   @name  - The identifier node (used to get the symbol name)
        #   @class/@function/@import - The full definition node (used for context)
        #
        # Note: TypeScript interfaces are treated as "class" for simplicity.
        # Note: Arrow functions assigned to variables are captured as functions.
        self.queries = {
            "python": """
                (class_definition name: (identifier) @name) @class
                (function_definition name: (identifier) @name) @function
                (import_statement) @import
                (import_from_statement) @import
            """,
            "javascript": """
                (class_declaration name: (identifier) @name) @class
                (function_declaration name: (identifier) @name) @function
                (variable_declarator
                    name: (identifier) @name
                    value: [(arrow_function) (function_expression)]
                ) @function
                (import_statement source: (string) @import_source) @import
            """,
            "typescript": """
                (class_declaration name: (identifier) @name) @class
                (interface_declaration name: (type_identifier) @name) @class
                (function_declaration name: (identifier) @name) @function
                (variable_declarator
                    name: (identifier) @name
                    value: [(arrow_function) (function_expression)]
                ) @function
                (import_statement source: (string) @import_source) @import
            """,
            "go": """
                (type_declaration spec: (type_spec name: (type_identifier) @name)) @class
                (function_declaration name: (identifier) @name) @function
                (method_declaration name: (field_identifier) @name) @function
                (import_declaration) @import
            """
        }

        self._ensure_compiled_query()

    def _ensure_compiled_query(self) -> None:
        """Lazily compile and cache the Tree-sitter query for this language."""
        cache_key = self.language_name
        if cache_key not in TreeSitterAnalyzer._compiled_queries:
            query_scm = self.queries.get(self.language_name)
            if query_scm:
                TreeSitterAnalyzer._compiled_queries[cache_key] = self.language.query(query_scm)

    def _get_compiled_query(self):
        """Retrieve the cached compiled query, or None if language is unsupported."""
        return TreeSitterAnalyzer._compiled_queries.get(self.language_name)

    def _get_symbol_pattern(self, name: str) -> Pattern:
        """
        Get or create a cached regex pattern for whole-word symbol matching.

        Used to detect if a known symbol (class/function name) appears in a
        function body, indicating a local dependency within the same file.
        """
        if name not in TreeSitterAnalyzer._symbol_patterns:
            TreeSitterAnalyzer._symbol_patterns[name] = re.compile(rf'\b{re.escape(name)}\b')
        return TreeSitterAnalyzer._symbol_patterns[name]

    def _extract_imports(self, tree, content_bytes: bytes) -> List[str]:
        """
        Extract module/package import paths from the AST.

        Returns a list of import targets (e.g., "os", "react", "../utils").
        These are stored as file-level dependencies and inherited by all
        symbols defined in the file.
        """
        imports: Set[str] = set()

        query = self._get_compiled_query()
        if not query:
            return []

        captures = query.captures(tree.root_node)

        for node, capture_name in captures:
            if capture_name == "import":
                import_text = node.text.decode('utf8')

                if self.language_name == "python":
                    # Handle: import foo, from foo import bar
                    imports.update(self._parse_python_import(import_text))
                elif self.language_name in ("javascript", "typescript"):
                    # Handle: import { x } from 'module'
                    imports.update(self._parse_js_import(import_text))
                elif self.language_name == "go":
                    # Handle: import "fmt" or import ( "fmt" "os" )
                    imports.update(self._parse_go_import(import_text))

        return list(imports)

    def _parse_python_import(self, import_text: str) -> Set[str]:
        """
        Parse Python import statements into module names.

        Handles both forms:
          - `import foo, bar.baz` -> {"foo", "bar.baz"}
          - `from foo.bar import baz` -> {"foo.bar"}

        The `as` alias is stripped since we care about the source module.
        """
        deps: Set[str] = set()
        lines = import_text.strip().split('\n')

        for line in lines:
            line = line.strip()
            if line.startswith('from '):
                parts = line.split(' import ')[0].replace('from ', '').strip()
                if parts:
                    deps.add(parts)
            elif line.startswith('import '):
                modules = line.replace('import ', '').split(',')
                for mod in modules:
                    mod = mod.strip().split(' as ')[0].strip()
                    if mod:
                        deps.add(mod)
        return deps

    def _parse_js_import(self, import_text: str) -> Set[str]:
        """
        Parse JavaScript/TypeScript import statements.

        Handles:
          - `import { x } from 'module'` -> {"module"}
          - `import 'side-effect-module'` -> {"side-effect-module"}

        Uses pre-compiled regex for efficiency during bulk indexing.
        """
        deps: Set[str] = set()
        for match in _JS_IMPORT_PATTERN.finditer(import_text):
            module = match.group(1) or match.group(2)
            if module:
                deps.add(module)
        return deps

    def _parse_go_import(self, import_text: str) -> Set[str]:
        """
        Parse Go import declarations.

        Handles both single and grouped imports:
          - `import "fmt"` -> {"fmt"}
          - `import ( "fmt" "os" )` -> {"fmt", "os"}
        """
        deps: Set[str] = set()
        for match in _GO_IMPORT_PATTERN.finditer(import_text):
            pkg = match.group(1)
            if pkg:
                deps.add(pkg)
        return deps

    def _find_dependencies_in_body(self, def_node, all_names: Set[str], content_bytes: bytes) -> List[str]:
        """
        Detect intra-file dependencies by scanning a function/class body for references.

        This is a heuristic: if a known symbol name appears as a whole word in the
        body text, we assume it's a dependency. This catches cases like:
          - `result = HelperClass.process(data)`
          - `return calculate_total(items)`

        Two-phase check: fast substring scan, then regex confirmation for whole-word match.
        """
        deps: Set[str] = set()
        body_text = def_node.text.decode('utf8')

        for name in all_names:
            if name in body_text:
                pattern = self._get_symbol_pattern(name)
                if pattern.search(body_text):
                    deps.add(name)
        return list(deps)

    def analyze_file(self, file_path: str) -> List[ContextItem]:
        """
        Parse a source file and extract all indexable symbols as ContextItems.

        Returns a list containing:
          1. A file-level item (type="file") with all imports as dependencies
          2. One item per class/function with its own dependencies

        The dependency graph is built in two layers:
          - File imports: All symbols in the file inherit these
          - Local references: Detected by scanning function bodies for known symbols
        """
        if not os.path.exists(file_path):
            return []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (UnicodeDecodeError, FileNotFoundError, IOError, OSError) as e:
            logger.warning(f"Could not read {file_path}: {e}")
            return []

        content_bytes = bytes(content, "utf8")
        tree = self.parser.parse(content_bytes)

        file_imports = self._extract_imports(tree, content_bytes)

        # Create the file-level item first (always included even if no symbols found)
        relative_path = os.path.basename(file_path)
        items = [ContextItem(
            id=f"file:{relative_path}",
            layer=ContextLayer.PROJECT,
            content=f"File: {relative_path}\nLength: {len(content)} chars",
            metadata={
                "type": "file",
                "name": relative_path,
                "path": file_path,
                "dependencies": file_imports
            },
            source_file=file_path,
            line_number=1
        )]

        query = self._get_compiled_query()
        if not query:
            return items

        captures = query.captures(tree.root_node)

        # Two-pass algorithm:
        # Pass 1: Collect all symbol names (needed for intra-file dependency detection)
        # Pass 2: Create ContextItems with computed dependencies
        all_symbol_names: Set[str] = set()
        symbol_nodes: List[tuple] = []

        for node, capture_name in captures:
            if capture_name == "name":
                parent = node.parent
                if not parent:
                    continue
                grandparent = parent.parent if parent else None

                type_str = None

                # Python
                if parent.type == "class_definition":
                    type_str = "class"
                elif parent.type == "function_definition":
                    type_str = "function"

                # JS/TS
                elif parent.type == "class_declaration":
                    type_str = "class"
                elif parent.type == "function_declaration":
                    type_str = "function"
                elif parent.type == "variable_declarator":
                    type_str = "function"
                elif parent.type == "interface_declaration":
                    type_str = "class"

                # Go
                elif parent.type == "type_spec":
                    type_str = "class"
                elif parent.type == "method_declaration":
                    type_str = "function"

                if type_str:
                    name_text = node.text.decode('utf8')
                    all_symbol_names.add(name_text)

                    # Determine definition node
                    def_node = parent
                    if type_str == "class" and self.language_name == "go":
                        if grandparent is not None:
                            def_node = grandparent
                    elif parent.type == "variable_declarator":
                        if parent.parent is not None:
                            def_node = parent.parent

                    start_line = def_node.start_point[0] + 1
                    symbol_nodes.append((name_text, type_str, def_node, start_line))

        file_imports_set = set(file_imports)

        # Pass 2: Create ContextItems for each symbol with merged dependencies
        for name_text, type_str, def_node, start_line in symbol_nodes:
            # Find symbols referenced in this definition's body (excluding self-reference)
            local_refs = self._find_dependencies_in_body(
                def_node,
                all_symbol_names - {name_text},
                content_bytes
            )

            # Dependencies = file-level imports + local symbol references
            dependencies = list(file_imports_set | set(local_refs))

            items.append(ContextItem(
                id=f"{type_str}:{relative_path}:{name_text}",
                layer=ContextLayer.SEMANTIC,
                content=f"{type_str} {name_text}",
                metadata={
                    "type": type_str,
                    "name": name_text,
                    "file": file_path,
                    "lineno": start_line,
                    "dependencies": dependencies
                },
                source_file=file_path,
                line_number=start_line
            ))

        return items

    def extract_code_by_symbol(self, file_path: str, symbol_name: str) -> Optional[str]:
        """
        Extract the full source code of a specific symbol (class/function) from a file.

        Used by the "read" command to fetch live code on-demand, ensuring the user
        always sees the current version even if the index is stale.

        Returns None if the symbol is not found (may have been renamed or deleted).
        """
        if not os.path.exists(file_path):
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (UnicodeDecodeError, IOError, OSError):
            return None

        tree = self.parser.parse(bytes(content, "utf8"))

        query = self._get_compiled_query()
        if not query:
            return None

        captures = query.captures(tree.root_node)
        target_node = None

        # Search for a matching symbol name in the captures
        for node, capture_name in captures:
            if capture_name == "name":
                if node.text.decode('utf8') == symbol_name:
                    parent = node.parent
                    if not parent:
                        continue
                    grandparent = parent.parent if parent else None

                    # Determine the full definition node based on AST structure
                    if parent.type in [
                        "class_definition", "function_definition",
                        "class_declaration", "function_declaration",
                        "method_declaration", "interface_declaration"
                    ]:
                        target_node = parent
                    elif parent.type == "variable_declarator":
                        target_node = parent.parent if parent.parent else parent
                    elif parent.type == "type_spec":
                        target_node = grandparent if grandparent else parent

                    if target_node:
                        break

        if target_node:
            start_byte = target_node.start_byte
            end_byte = target_node.end_byte
            return content.encode('utf-8')[start_byte:end_byte].decode('utf-8')

        return None
