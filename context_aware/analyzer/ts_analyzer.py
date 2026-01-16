import os
from typing import List, Optional, Dict, Any
from tree_sitter import Language, Parser, Node
import tree_sitter_languages
from ..models.context_item import ContextItem, ContextLayer
from .base_analyzer import BaseAnalyzer

class TreeSitterAnalyzer(BaseAnalyzer):
    def __init__(self, language_name: str):
        self.language_name = language_name
        self.language = tree_sitter_languages.get_language(language_name)
        self.parser = Parser()
        self.parser.set_language(self.language)
        
        # Query configurations for different languages
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
                (import_statementSource: (string) @import_source) @import
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

    def analyze_file(self, file_path: str) -> List[ContextItem]:
        if not os.path.exists(file_path):
            return []
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return []

        tree = self.parser.parse(bytes(content, "utf8"))
        
        # Base file item
        relative_path = os.path.basename(file_path)
        items = [ContextItem(
            id=f"file:{relative_path}",
            layer=ContextLayer.PROJECT,
            content=f"File: {relative_path}\nLength: {len(content)} chars",
            metadata={"type": "file", "path": file_path, "dependencies": []}, # Deps populated later if needed
            source_file=file_path,
            line_number=1
        )]

        # Run query
        query_scm = self.queries.get(self.language_name)
        if not query_scm:
            return items

        query = self.language.query(query_scm)
        captures = query.captures(tree.root_node)

        # deduplicate captures based on node id
        processed_nodes = set()
        
        for node, capture_name in captures:
            if node.id in processed_nodes:
                continue
                
            if capture_name in ["class", "function"]:
                processed_nodes.add(node.id)
                
                # Find the @name capture associated with this node
                # Queries often capture the whole node as @class AND the name identifier as @name
                # We need to find the name child or reuse the capture if the structure allows.
                # In the queries above, I mapped (identifier) @name. 
                # Yet `captures` returns a flat list of (node, name). 
                # We need to iterate and match.
                
                # Simpler approach: Iterate captures, if it's @name, look at parent to decide type
                pass

        # Better loop for captures
        # Group captures by definition node?
        
        # Let's simplify: Just iterate and handle based on capture name
        # The queries above explicitly capture definition nodes as @class/@function 
        # AND name nodes as @name.
        # This makes it tricky to pair them in a flat list.
        
        # Alternative: Use specific traversals or simpler queries.
        # But `query.captures` returns them in order.
        
        # Let's refine the logic:
        # We will iterate and find @name captures. Then check their parent/grandparent to determine type.
        
        for node, capture_name in captures:
            if capture_name == "name":
                parent = node.parent
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
                     # const foo = () => ...
                     type_str = "function"
                elif parent.type == "interface_declaration":
                     type_str = "class" # Treat interface as class-like

                # Go
                elif parent.type == "type_spec": # type MyStruct struct
                    type_str = "class"
                elif parent.type == "function_declaration":
                     type_str = "function"
                elif parent.type == "method_declaration":
                     type_str = "function"

                if type_str:
                    # decoding using utf8 to match bytes parsing
                    name_text = node.text.decode('utf8')
                    # definition node is the parent (usually)
                    def_node = parent
                    if type_str == "class" and self.language_name == "go":
                         # In Go, parent is type_spec, grandparent is type_declaration
                         def_node = grandparent
                    elif parent.type == "variable_declarator":
                         # JS variable decl
                         def_node = parent.parent # variable_declaration
                    
                    # Use definition node for line number
                    start_line = def_node.start_point[0] + 1
                    
                    items.append(ContextItem(
                        id=f"{type_str}:{relative_path}:{name_text}",
                        layer=ContextLayer.SEMANTIC,
                        content=f"{type_str} {name_text}",
                        metadata={
                            "type": type_str,
                            "name": name_text,
                            "file": file_path,
                            "lineno": start_line
                        },
                        source_file=file_path,
                        line_number=start_line
                    ))
                    
        return items

    def extract_code_by_symbol(self, file_path: str, symbol_name: str) -> Optional[str]:
        if not os.path.exists(file_path):
            return None
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            return None
            
        tree = self.parser.parse(bytes(content, "utf8"))
        query_scm = """
            (class_definition name: (identifier) @name) @def
            (function_definition name: (identifier) @name) @def
            (class_declaration name: (identifier) @name) @def
            (function_declaration name: (identifier) @name) @def
            (variable_declarator name: (identifier) @name) @def
            (type_spec name: (type_identifier) @name) @def
            (method_declaration name: (field_identifier) @name) @def
        """
        # Note: This generic query mixes languages, but Tree-sitter is lenient or we can use the specific one.
        # Better use the self.queries but adapt to capture @def
        
        # Simplified on-demand search using a custom traversal or re-using queries
        # For robustness, let's just use the language specific query and look for the name matches.
        
        # Using the same queries as analyze_file but modified to capture @def nodes is cleaner.
        # But for now, let's just re-run the same query logic and simpler extraction.
        
        query_scm = self.queries.get(self.language_name)
        if not query_scm: return None
        
        query = self.language.query(query_scm)
        captures = query.captures(tree.root_node)
        
        target_node = None
        
        for node, capture_name in captures:
             if capture_name == "name":
                 if node.text.decode('utf8') == symbol_name:
                     # Found the name, now find the definition node
                     parent = node.parent
                     gramdparent = parent.parent if parent else None
                     
                     if parent.type in ["class_definition", "function_definition", "class_declaration", "function_declaration", "method_declaration", "interface_declaration"]:
                         target_node = parent
                     elif parent.type == "variable_declarator":
                         target_node = parent.parent
                     elif parent.type == "type_spec":
                         target_node = gramdparent # type declaration
                     
                     if target_node:
                         break
                         
        if target_node:
            start_byte = target_node.start_byte
            end_byte = target_node.end_byte
            return content.encode('utf-8')[start_byte:end_byte].decode('utf-8')
            
        return None
