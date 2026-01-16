from typing import List
from ..models.context_item import ContextItem

class SimpleCompiler:
    def compile(self, items: List[ContextItem]) -> str:
        output = []
        output.append("<context_aware_context>")
        
        if not items:
            output.append("  <!-- No context found -->")
        else:
            for item in items:
                output.append(f"  <item id='{item.id}' layer='{item.layer.value}'>")
                # Indent content slightly
                content_lines = item.content.split('\n')
                for line in content_lines:
                    output.append(f"    {line}")
                output.append("  </item>")
            
        output.append("</context_aware_context>")
        return "\n".join(output)
