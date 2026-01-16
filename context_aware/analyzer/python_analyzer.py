import ast
import os
from typing import List
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
        rel_path = os.path.basename(file_path) # Simplified for MVP, ideally relative to project root
        
        # Whole file context
        items.append(ContextItem(
            id=f"file:{rel_path}",
            layer=ContextLayer.PROJECT,
            content=f"File: {rel_path}\nLength: {len(content)} chars",
            metadata={"type": "file", "path": file_path},
            source_file=file_path
        ))
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                items.append(self._create_item(node, file_path, "function"))
            elif isinstance(node, ast.ClassDef):
                items.append(self._create_item(node, file_path, "class"))
                
        return items

    def _create_item(self, node, file_path, type_str):
        doc = ast.get_docstring(node) or ""
        rel_path = os.path.basename(file_path)
        
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
                "lineno": node.lineno
            },
            source_file=file_path,
            line_number=node.lineno
        )
