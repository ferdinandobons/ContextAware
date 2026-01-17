"""
Structure tool: generates a compact project structure overview.

This tool aggregates indexed data to produce a high-level map of the project,
designed to help AI agents quickly understand the codebase organization.

Output includes:
- Entry points (files with main blocks)
- Module breakdown by directory
- Key classes and functions per module
- Simplified dependency graph between modules
"""
import json
import os
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from ..store.sqlite_store import SQLiteContextStore


class StructureGenerator:
    """
    Generates a Markdown overview of project structure from indexed data.

    The output is optimized for LLM consumption:
    - Hierarchical organization by directory
    - Symbol counts and key components per module
    - Cross-module dependency visualization
    """

    def __init__(self, store: SQLiteContextStore):
        self.store = store

    def generate(self, compact: bool = False, inject_mode: bool = False) -> str:
        """
        Generate the project structure overview.

        Args:
            compact: If True, produces a minimal output for context injection
            inject_mode: If True, omits headers for hook integration
        """
        items = self.store.load()

        if not items:
            if inject_mode:
                return "No indexed items. Run `context_aware index .` first."
            return "## Project Structure\n\nNo indexed items found. Run `context_aware index .` to build the index."

        # Analyze the indexed items
        modules = self._group_by_module(items)
        entry_points = self._find_entry_points(items)
        module_deps = self._compute_module_dependencies(items)

        # Build output
        lines: List[str] = []

        if not inject_mode:
            project_name = self._detect_project_name()
            lines.append(f"## Project Structure: {project_name}")
            lines.append("")

        # Entry points section
        if entry_points and not compact:
            lines.append("### Entry Points")
            lines.append("")
            for ep in entry_points[:5]:
                desc = ep.get("description", "")
                lines.append(f"- `{ep['file']}` {desc}")
            lines.append("")

        # Modules section
        lines.append("### Modules")
        lines.append("")

        sorted_modules = sorted(modules.items(), key=lambda x: (-x[1]['total'], x[0]))

        for module_path, data in sorted_modules[:15]:  # Limit modules shown
            classes = data.get('classes', [])
            functions = data.get('functions', [])
            files = data.get('files', set())

            # Module header
            file_count = len(files)
            class_count = len(classes)
            func_count = len(functions)

            if compact:
                # Ultra-compact: just module name and counts
                lines.append(f"- **{module_path}/** ({file_count}f, {class_count}c, {func_count}fn)")
            else:
                lines.append(f"- **{module_path}/** ({file_count} files, {class_count} classes, {func_count} functions)")

                # Show key symbols
                key_symbols = classes[:3] + functions[:2]
                if key_symbols:
                    lines.append(f"  - Key: {', '.join(key_symbols)}")

        if len(sorted_modules) > 15:
            lines.append(f"- ... and {len(sorted_modules) - 15} more modules")

        lines.append("")

        # Dependency graph (simplified)
        if module_deps and not compact:
            lines.append("### Module Dependencies")
            lines.append("")
            lines.append("```")
            for source, targets in list(module_deps.items())[:10]:
                if targets:
                    target_list = ", ".join(list(targets)[:3])
                    if len(targets) > 3:
                        target_list += f" (+{len(targets)-3})"
                    lines.append(f"{source} → {target_list}")
            lines.append("```")
            lines.append("")

        # Statistics
        if not compact and not inject_mode:
            total_items = len(items)
            total_classes = sum(1 for i in items if i.metadata.get('type') == 'class')
            total_functions = sum(1 for i in items if i.metadata.get('type') == 'function')
            total_files = len(set(i.source_file for i in items if i.source_file))

            lines.append("### Statistics")
            lines.append("")
            lines.append(f"- **Files indexed**: {total_files}")
            lines.append(f"- **Classes**: {total_classes}")
            lines.append(f"- **Functions**: {total_functions}")
            lines.append(f"- **Total symbols**: {total_items}")

        return "\n".join(lines)

    def _group_by_module(self, items) -> Dict[str, dict]:
        """Group items by their parent directory (module)."""
        modules: Dict[str, dict] = defaultdict(lambda: {
            'classes': [],
            'functions': [],
            'files': set(),
            'total': 0
        })

        for item in items:
            if not item.source_file:
                continue

            # Get directory path relative to common root
            dir_path = os.path.dirname(item.source_file)
            module_name = self._normalize_module_path(dir_path)

            if not module_name:
                module_name = "."

            item_type = item.metadata.get('type', 'unknown')
            item_name = item.metadata.get('name', '')

            modules[module_name]['files'].add(item.source_file)
            modules[module_name]['total'] += 1

            if item_type == 'class' and item_name:
                modules[module_name]['classes'].append(item_name)
            elif item_type == 'function' and item_name:
                modules[module_name]['functions'].append(item_name)

        return dict(modules)

    def _normalize_module_path(self, dir_path: str) -> str:
        """Convert absolute path to relative module path."""
        # Try to find a common project structure
        parts = dir_path.split(os.sep)

        # Look for common project root indicators
        for i, part in enumerate(parts):
            if part in ('src', 'lib', 'app', 'context_aware', 'tests'):
                return os.sep.join(parts[i:])

        # Fallback: use last 2-3 directory components
        if len(parts) > 2:
            return os.sep.join(parts[-2:])

        return dir_path

    def _find_entry_points(self, items) -> List[dict]:
        """Identify likely entry points (main files, CLI, servers)."""
        entry_points = []

        for item in items:
            if not item.source_file:
                continue

            content = item.content.lower()
            file_name = os.path.basename(item.source_file)

            # Heuristics for entry points
            is_main = 'if __name__' in content or '__main__' in content
            is_cli = 'argparse' in content or 'click' in content or 'typer' in content
            is_server = 'app.run' in content or 'uvicorn' in content or 'fastapi' in content
            is_main_file = file_name in ('main.py', 'cli.py', 'app.py', 'server.py', 'index.js', 'index.ts')

            if is_main or is_cli or is_server or is_main_file:
                desc = ""
                if is_cli:
                    desc = "→ CLI"
                elif is_server:
                    desc = "→ Server"
                elif is_main:
                    desc = "→ Main"

                entry_points.append({
                    'file': self._normalize_module_path(item.source_file),
                    'description': desc
                })

        # Deduplicate by file
        seen = set()
        unique = []
        for ep in entry_points:
            if ep['file'] not in seen:
                seen.add(ep['file'])
                unique.append(ep)

        return unique

    def _compute_module_dependencies(self, items) -> Dict[str, Set[str]]:
        """Build a simplified module-to-module dependency graph."""
        edges = self.store.get_all_edges()

        # Map item IDs to their modules
        id_to_module: Dict[str, str] = {}
        for item in items:
            if item.source_file:
                module = self._normalize_module_path(os.path.dirname(item.source_file))
                id_to_module[item.id] = module if module else "."

        # Aggregate edges at module level
        module_deps: Dict[str, Set[str]] = defaultdict(set)

        for source_id, target_key, target_id, relation_type in edges:
            source_module = id_to_module.get(source_id)
            target_module = id_to_module.get(target_id) if target_id else None

            if source_module and target_module and source_module != target_module:
                module_deps[source_module].add(target_module)

        return dict(module_deps)

    def _detect_project_name(self) -> str:
        """Try to detect the project name from common sources."""
        # Check for pyproject.toml, package.json, etc.
        root = self.store.storage_dir.replace('/.context_aware', '')

        candidates = [
            os.path.join(root, 'pyproject.toml'),
            os.path.join(root, 'package.json'),
            os.path.join(root, 'setup.py'),
            os.path.join(root, 'go.mod'),
        ]

        for path in candidates:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        content = f.read()

                    if path.endswith('.toml'):
                        # Simple regex for name in pyproject.toml
                        import re
                        match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
                        if match:
                            return match.group(1)
                    elif path.endswith('.json'):
                        data = json.loads(content)
                        if 'name' in data:
                            return data['name']
                except Exception:
                    pass

        # Fallback: directory name
        return os.path.basename(root)
