import ast
import os
from typing import List, Optional
from ..models.context_item import ContextItem, ContextLayer

class PythonAnalyzer:
    def analyze_file(self, file_path: str) -> List[ContextItem]:
        if not os.path.exists(file_path):
            return []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            tree = ast.parse(content)
        except (SyntaxError, UnicodeDecodeError):
            return [] # Skip invalid files
            
        items = []
        rel_path = os.path.basename(file_path) # Simplified for now, ideally relative to project root
        
        # Whole file context
        imports = self._extract_imports(tree)
        # source_lines removed to keep DB light
        
        items.append(ContextItem(
            id=f"file:{rel_path}",
            layer=ContextLayer.PROJECT,
            content=f"File: {rel_path}\nLength: {len(content)} chars\nImports: {', '.join(imports)}",
            metadata={"type": "file", "path": file_path, "dependencies": imports},
            source_file=file_path
        ))
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                items.append(self._create_item(node, file_path, "function", imports))
            elif isinstance(node, ast.ClassDef):
                items.append(self._create_item(node, file_path, "class", imports))
                
        return items

    def _create_item(self, node, file_path, type_str, dependencies=None):
        doc = ast.get_docstring(node) or ""
        rel_path = os.path.basename(file_path)
        
        # Store only signature/definition + docstring to save space
        content = f"{type_str} {node.name}"
        if doc:
            content += f"\nDocstring: {doc}"
            
        return ContextItem(
            id=f"{type_str}:{rel_path}:{node.name}",
            layer=ContextLayer.SEMANTIC,
            content=content,
            metadata={
                "type": type_str, 
                "name": node.name, 
                "file": file_path,
                "lineno": node.lineno,
                "dependencies": dependencies or []
            },
            source_file=file_path,
            line_number=node.lineno
        )

    def _extract_imports(self, tree) -> List[str]:
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}")
        return imports

    def extract_code_by_symbol(self, file_path: str, symbol_name: str) -> Optional[str]:
        """
        Parses the file on-demand to find the symbol and return its full source code.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            tree = ast.parse(content)
            source_lines = content.splitlines()
            
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if node.name == symbol_name:
                         if hasattr(node, 'lineno') and hasattr(node, 'end_lineno'):
                            return "\n".join(source_lines[node.lineno-1 : node.end_lineno])
            return None
        except Exception as e:
            return f"Error reading file {file_path}: {str(e)}"
