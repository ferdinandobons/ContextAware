import re
import os
from typing import List, Optional
from ..models.context_item import ContextItem, ContextLayer
from .base_analyzer import BaseAnalyzer

class GoAnalyzer(BaseAnalyzer):
    def analyze_file(self, file_path: str) -> List[ContextItem]:
        if not os.path.exists(file_path):
            return []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            lines = content.splitlines()
        except (UnicodeDecodeError, IOError):
            return [] # Skip invalid files
            
        items = []
        rel_path = os.path.basename(file_path)
        imports = self._extract_imports(content)
        
        # Add file level item
        items.append(ContextItem(
            id=f"file:{rel_path}",
            layer=ContextLayer.PROJECT,
            content=f"File: {rel_path}\nLength: {len(content)} chars\nImports: {', '.join(imports)}",
            metadata={"type": "file", "path": file_path, "dependencies": imports},
            source_file=file_path,
            line_number=1
        ))
        
        # Regex patterns for Go
        # 1. Functions: func Name(args) ...
        #    func (r *Receiver) Name(args) ... (Methods)
        func_pattern = re.compile(r'^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(', re.MULTILINE)
        
        # 2. Types: type Name struct/interface
        type_pattern = re.compile(r'^type\s+(\w+)\s+(struct|interface)', re.MULTILINE)

        # Scan for functions/methods
        # Note: This is a simple regex scanner, it won't be perfect with nested functions or closures,
        # but good enough for top-level skeleton.
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if line_stripped.startswith("func"):
                match = func_pattern.match(line)
                if match:
                    func_name = match.group(1)
                    # Try to capture receiver if present (very rough)
                    # func (t *Type) Name
                    full_sig = line.strip()
                    if full_sig.endswith("{"):
                        full_sig = full_sig[:-1].strip()
                        
                    items.append(ContextItem(
                        id=f"func:{rel_path}:{func_name}",
                        layer=ContextLayer.SEMANTIC,
                        content=f"Function: {full_sig}",
                        metadata={
                            "type": "function",
                            "name": func_name,
                            "dependencies": imports
                        },
                        source_file=file_path,
                        line_number=i+1
                    ))
            
            elif line_stripped.startswith("type"):
                match = type_pattern.match(line)
                if match:
                    type_name = match.group(1)
                    type_kind = match.group(2)
                    
                    items.append(ContextItem(
                        id=f"type:{rel_path}:{type_name}",
                        layer=ContextLayer.SEMANTIC,
                        content=f"Type: {type_name} ({type_kind})",
                        metadata={
                            "type": "class", # Map to class for consistency
                            "name": type_name,
                            "dependencies": imports
                        },
                        source_file=file_path,
                        line_number=i+1
                    ))

        return items

    def _extract_imports(self, content: str) -> List[str]:
        imports = []
        # Single line import: import "fmt"
        # Multi line: import ( ... )
        
        # Check for multi-line block
        block_pattern = re.compile(r'import\s*\((.*?)\)', re.DOTALL)
        match = block_pattern.search(content)
        if match:
            block_content = match.group(1)
            # extract "path/to/lib"
            paths = re.findall(r'"([^"]+)"', block_content)
            imports.extend(paths)
            
        # Check for single lines outside (technically go fmt merges them, but valid go allows it)
        single_pattern = re.findall(r'^import\s+"([^"]+)"', content, re.MULTILINE)
        imports.extend(single_pattern)
        
        return list(set(imports))

    def extract_code_by_symbol(self, file_path: str, symbol_name: str) -> Optional[str]:
        """
        Simple brace counting extractor for Go symbols.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            lines = content.splitlines()
        except:
            return None

        # Naive search for definition line
        start_line = -1
        
        # matches func Name( or func (r) Name( or type Name
        # We need to construct regex based on symbol_name
        
        for i, line in enumerate(lines):
            # Check func
            func_match = re.search(r'func\s+(?:\([^)]+\)\s+)?' + re.escape(symbol_name) + r'\s*\(', line)
            if func_match:
                start_line = i
                break
            
            # Check type
            type_match = re.search(r'type\s+' + re.escape(symbol_name) + r'\s+', line)
            if type_match:
                start_line = i
                break
                
        if start_line == -1:
            return None
            
        # Brace counting from start_line
        # Note: This is fragile (comments, strings with braces) but works for 90%
        # A proper Go parser is needed for 100% correctness.
        
        extracted_lines = []
        brace_balance = 0
        started = False
        
        for i in range(start_line, len(lines)):
            line = lines[i]
            extracted_lines.append(line)
            
            # Very primitive brace counting, ignoring strings/comments for speed/simplicity
            # In a real impl we'd filter out strings/comments before counting.
            brace_balance += line.count('{')
            brace_balance -= line.count('}')
            
            if brace_balance > 0:
                started = True
            
            # If we started and balance hits 0 (or less), we are done.
            # OR if we never found an opening brace in the first line (e.g. interface one liner?), 
            # usually go fmt puts { on same line.
            if started and brace_balance <= 0:
                break
                
            # Sanity check: if we went 500 lines deep, maybe abort?
            if len(extracted_lines) > 2000: 
                break
                
        return "\n".join(extracted_lines)
