import re
import os
from typing import List, Optional
from ..models.context_item import ContextItem, ContextLayer
from .base_analyzer import BaseAnalyzer

class JavascriptAnalyzer(BaseAnalyzer):
    """
    A simple Regex-based analyzer for JavaScript/TypeScript files.
    """
    def analyze_file(self, file_path: str) -> List[ContextItem]:
        items = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except:
            return []

        # 1. File Item
        relative_path = os.path.basename(file_path)
        
        # Regex for import dependencies
        # import X from '...' or import { X } from '...'
        import_pattern = re.compile(r'import\s+.*?from\s+[\'"](.*?)[\'"]')
        deps = import_pattern.findall(content)
        
        items.append(ContextItem(
            id=f"file:{relative_path}",
            layer=ContextLayer.PROJECT,
            content=f"File: {relative_path}",
            metadata={"type": "file", "dependencies": deps, "name": relative_path},
            source_file=file_path,
            line_number=1
        ))
        
        # 2. Classes (simple ES6 regex)
        # class ClassName ... {
        class_pattern = re.compile(r'class\s+(\w+)')
        for match in class_pattern.finditer(content):
            class_name = match.group(1)
            # Naive line number detection
            line_num = content[:match.start()].count('\n') + 1
            
            items.append(ContextItem(
                id=f"class:{relative_path}:{class_name}",
                layer=ContextLayer.SEMANTIC,
                content=f"class {class_name}",
                metadata={"type": "class", "name": class_name, "dependencies": []},
                source_file=file_path,
                line_number=line_num
            ))

        # 3. Functions (function foo() or const foo = () =>)
        # Matches: function foo(...) OR const|let|var foo = ... =>
        func_pattern = re.compile(r'(?:function\s+(\w+))|(?:(const|let|var)\s+(\w+)\s*=\s*.*=>)')
        for match in func_pattern.finditer(content):
            # group(1) for 'function foo', group(3) for 'const foo ='
            func_name = match.group(1) or match.group(3)
            
            if func_name:
                line_num = content[:match.start()].count('\n') + 1
                items.append(ContextItem(
                    id=f"function:{relative_path}:{func_name}",
                    layer=ContextLayer.SEMANTIC,
                    content=f"function {func_name}",
                    metadata={"type": "function", "name": func_name, "dependencies": []},
                    source_file=file_path,
                    line_number=line_num
                ))
            
        return items

    def extract_code_by_symbol(self, file_path: str, symbol_name: str) -> Optional[str]:
        """
        Extracts the code block for a given symbol using basic brace counting.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            start_line = -1
            # Simple heuristic to find the start declaration
            for i, line in enumerate(lines):
                 # Matches "class Name" or "function Name" or "const Name ="
                if re.search(r'\b(class|function)\s+' + re.escape(symbol_name) + r'\b', line) or \
                   re.search(r'\b(const|let|var)\s+' + re.escape(symbol_name) + r'\s*=\s*', line):
                    start_line = i
                    break
            
            if start_line == -1:
                return None
                
            # Brace counting to find end of block
            cnt = 0
            found_start_brace = False
            extracted_lines = []
            
            for i in range(start_line, len(lines)):
                line = lines[i]
                extracted_lines.append(line)
                
                open_braces = line.count('{')
                close_braces = line.count('}')
                
                if open_braces > 0:
                    found_start_brace = True
                
                cnt += (open_braces - close_braces)
                
                if found_start_brace and cnt <= 0:
                    # End of block reached
                    break
            
            return "".join(extracted_lines)
                
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return None
