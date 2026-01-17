"""
Compiler module: transforms ContextItems into Markdown output for LLM consumption.

The compiler formats search results and item details as structured Markdown that's
easy for language models to parse and understand. Two output formats:

1. Skeleton Mode (search results): Shows signatures, location, and dependencies
   - Used for browsing/discovery without overwhelming the context window
   - Includes bidirectional relationships (deps + dependents)

2. Full Mode (read command): Includes complete source code
   - Used when the user needs to see implementation details
   - Code is wrapped in language-specific fenced blocks
"""
from typing import List, Optional

from ..models.context_item import ContextItem


class SimpleCompiler:
    """
    Formats ContextItems as Markdown for consumption by LLMs or other tools.

    Output optimized for AI agents:
    - Structured headers for easy parsing
    - Location format (path:line) for IDE integration
    - Bidirectional dependencies when available
    - Code blocks with language hints
    """

    def compile_search_results(
        self,
        items: List[ContextItem],
        query: Optional[str] = None,
        include_dependents: bool = False,
        dependents_map: Optional[dict] = None
    ) -> str:
        """
        Compile search results into skeleton format.

        Args:
            items: List of matching ContextItems
            query: Original search query (for header)
            include_dependents: Whether to include reverse dependencies
            dependents_map: Dict mapping item_id -> list of dependent items
        """
        lines: List[str] = []

        # Header
        if query:
            lines.append(f"## Search Results: \"{query}\"")
        else:
            lines.append("## Search Results")
        lines.append("")

        if not items:
            lines.append("No matches found.")
            return "\n".join(lines)

        lines.append(f"### Found {len(items)} matches")
        lines.append("")

        for i, item in enumerate(items, 1):
            item_type = item.metadata.get("type", "unknown")
            name = item.metadata.get("name", item.id.split(":")[-1])

            # Item header with reference
            lines.append(f"#### {i}. `{item.id}`")
            lines.append("")

            # Metadata table
            lines.append(f"- **Type**: {item_type}")

            # Location for IDE navigation
            if item.source_file and item.line_number:
                lines.append(f"- **Location**: `{item.source_file}:{item.line_number}`")
            elif item.source_file:
                lines.append(f"- **Location**: `{item.source_file}`")

            # Signature (first line of content)
            content_lines = item.content.split('\n')
            if content_lines:
                signature = content_lines[0].strip()
                if signature:
                    lines.append(f"- **Signature**: `{signature}`")

            # Dependencies (what this item uses)
            deps = item.metadata.get("dependencies", [])
            if deps:
                lines.append("- **Dependencies**:")
                for dep in deps:
                    lines.append(f"  - `{dep}`")

            # Dependents (what uses this item) - if available
            if include_dependents and dependents_map and item.id in dependents_map:
                dependents = dependents_map[item.id]
                if dependents:
                    lines.append("- **Used by**:")
                    for dep in dependents:
                        dep_id = dep.id if hasattr(dep, 'id') else str(dep)
                        lines.append(f"  - `{dep_id}`")

            # Docstring hint if present
            docstring = item.metadata.get("docstring")
            if docstring:
                # Truncate long docstrings
                if len(docstring) > 150:
                    docstring = docstring[:150] + "..."
                lines.append(f"- **Description**: {docstring}")

            lines.append("")

        return "\n".join(lines)

    def compile_read_result(
        self,
        item: ContextItem,
        include_deps: bool = True,
        deps_items: Optional[List[ContextItem]] = None
    ) -> str:
        """
        Compile a single item with full source code.

        Args:
            item: The ContextItem to display
            include_deps: Whether to list dependencies
            deps_items: Resolved dependency items (for inline context)
        """
        lines: List[str] = []

        item_type = item.metadata.get("type", "unknown")
        name = item.metadata.get("name", item.id.split(":")[-1])

        # Header
        lines.append(f"## {item_type.title()}: `{name}`")
        lines.append("")

        # Metadata
        lines.append(f"**ID**: `{item.id}`")

        if item.source_file and item.line_number:
            lines.append(f"**Location**: `{item.source_file}:{item.line_number}`")
        elif item.source_file:
            lines.append(f"**Location**: `{item.source_file}`")

        lines.append("")

        # Dependencies summary
        if include_deps:
            deps = item.metadata.get("dependencies", [])
            if deps:
                lines.append("### Dependencies")
                lines.append("")
                for dep in deps:
                    lines.append(f"- `{dep}`")
                lines.append("")

        # Full source code
        lines.append("### Source Code")
        lines.append("")

        # Detect language for syntax highlighting
        lang = self._detect_language(item.source_file)
        lines.append(f"```{lang}")
        lines.append(item.content)
        lines.append("```")

        return "\n".join(lines)

    def compile_impacts_result(
        self,
        target_id: str,
        direct_dependents: List[ContextItem],
        cascade_dependents: Optional[List[ContextItem]] = None
    ) -> str:
        """
        Compile impact analysis results.

        Args:
            target_id: The item being analyzed
            direct_dependents: Items that directly depend on target
            cascade_dependents: Items that indirectly depend on target
        """
        lines: List[str] = []

        lines.append(f"## Impact Analysis: `{target_id}`")
        lines.append("")

        if not direct_dependents and not cascade_dependents:
            lines.append("No dependents found. This item appears to be safe to modify.")
            return "\n".join(lines)

        # Direct dependents
        if direct_dependents:
            lines.append(f"### Direct Dependents ({len(direct_dependents)})")
            lines.append("")
            for i, dep in enumerate(direct_dependents, 1):
                dep_type = dep.metadata.get("type", "unknown")
                location = ""
                if dep.source_file and dep.line_number:
                    location = f" → `{dep.source_file}:{dep.line_number}`"
                lines.append(f"{i}. `{dep.id}` ({dep_type}){location}")
            lines.append("")

        # Cascade dependents
        if cascade_dependents:
            lines.append(f"### Cascade Impact ({len(cascade_dependents)} additional)")
            lines.append("")
            lines.append("These items are indirectly affected through the dependency chain:")
            lines.append("")
            for dep in cascade_dependents[:20]:  # Limit cascade display
                dep_type = dep.metadata.get("type", "unknown")
                lines.append(f"- `{dep.id}` ({dep_type})")
            if len(cascade_dependents) > 20:
                lines.append(f"- ... and {len(cascade_dependents) - 20} more")
            lines.append("")

        # Summary
        total = len(direct_dependents) + (len(cascade_dependents) if cascade_dependents else 0)
        lines.append("### Summary")
        lines.append("")
        lines.append(f"**Total affected items**: {total}")
        if total > 5:
            lines.append("")
            lines.append("⚠️ Consider reviewing tests and documentation before modifying.")

        return "\n".join(lines)

    def _detect_language(self, source_file: Optional[str]) -> str:
        """Detect language for syntax highlighting based on file extension."""
        if not source_file:
            return ""

        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".rb": "ruby",
            ".php": "php",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".sh": "bash",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".md": "markdown",
            ".sql": "sql",
        }

        for ext, lang in ext_map.items():
            if source_file.endswith(ext):
                return lang

        return ""
