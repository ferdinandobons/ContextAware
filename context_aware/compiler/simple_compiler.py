from typing import List
from ..models.context_item import ContextItem

class SimpleCompiler:
    def compile(self, items: List[ContextItem], mode: str = "full") -> str:
        output = []
        output.append("<context_aware_context>")
        
        if not items:
            output.append("  <!-- No context found -->")
        else:
            for item in items:
                output.append(f"  <item id='{item.id}' layer='{item.layer.value}'>")
                
                if mode == "skeleton":
                    # Render only docstring and dependencies
                    content_lines = item.content.split('\n')
                    # Heuristic: First line is signature/definition
                    if content_lines:
                        output.append(f"    {content_lines[0]}")
                    
                    # Extract dependencies
                    deps = item.metadata.get("dependencies", [])
                    if deps:
                        output.append("    <dependencies>")
                        for dep in deps:
                             # Should link to ID but we only have name here
                             output.append(f"      <dep>{dep}</dep>")
                        output.append("    </dependencies>")
                    
                    # Search for docstring in content (naive but simple)
                    for line in content_lines:
                        if "Docstring:" in line:
                             output.append(f"    {line}")
                
                else: 
                    # Full mode
                    content_lines = item.content.split('\n')
                    for line in content_lines:
                        output.append(f"    {line}")
                        
                output.append("  </item>")
            
        output.append("</context_aware_context>")
        return "\n".join(output)
