import asyncio
import os
from typing import Any, List
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from .store.sqlite_store import SQLiteContextStore
from .router.graph_router import GraphRouter
from .compiler.simple_compiler import SimpleCompiler
from .analyzer.ts_analyzer import TreeSitterAnalyzer

# Initialize server
server = Server("context-aware")

# Global store reference (initialized in start_mcp_server)
store: SQLiteContextStore = None

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search",
            description="Search the codebase for relevant context using keywords. Returns a high-level skeleton of matches.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query keywords"},
                    "type": {"type": "string", "enum": ["class", "function", "file"], "description": "Filter by item type"}
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="read",
            description="Read the full source code of a specific item found via search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The Item ID (e.g., class:file.py:MyClass)"}
                },
                "required": ["id"]
            }
        ),
        types.Tool(
            name="impacts",
            description="Analyze dependencies to see what items depend on the target item (Reverse Lookup).",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The Item ID to analyze"}
                },
                "required": ["id"]
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: Any) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if not store:
        return [types.TextContent(type="text", text="Error: Store not initialized")]

    if name == "search":
        query = arguments.get("query")
        type_filter = arguments.get("type")
        
        router = GraphRouter(store)
        compiler = SimpleCompiler()
        
        items = router.route(query, type_filter=type_filter)
        if items:
            text = compiler.compile_search_results(items)
        else:
            text = "No results found."
            
        return [types.TextContent(type="text", text=text)]

    elif name == "read":
        item_id = arguments.get("id")
        item = store.get_by_id(item_id)
        
        if item:
            # On-demand fetch (similar to CLI read command)
            symbol_name = item.metadata.get("name")
            fresh_content = item.content
            
            if os.path.exists(item.source_file):
                # We need a way to determine analyzer based on file type
                # For now, simplistic fallback or just read file
                # TODO: Integrate the generic TreeSitter analyzer here for robust extraction
                # Use generic TreeSitterAnalyzer
                from .analyzer.ts_analyzer import TreeSitterAnalyzer
                
                analyzer = None
                if item.source_file.endswith(".py"):
                    analyzer = TreeSitterAnalyzer("python")
                elif item.source_file.endswith(".js"):
                    analyzer = TreeSitterAnalyzer("javascript")
                elif item.source_file.endswith((".ts", ".tsx")):
                    analyzer = TreeSitterAnalyzer("typescript")
                elif item.source_file.endswith(".go"):
                    analyzer = TreeSitterAnalyzer("go")

                if analyzer:
                    code = analyzer.extract_code_by_symbol(item.source_file, symbol_name)
                    if code:
                        fresh_content = code
            
            return [types.TextContent(type="text", text=fresh_content)]
        else:
            return [types.TextContent(type="text", text=f"Item not found: {item_id}")]

    elif name == "impacts":
        item_id = arguments.get("id")
        dependents = store.get_inbound_edges(item_id)
        
        if dependents:
            lines = [f"Found {len(dependents)} items that depend on {item_id}:"]
            for item in dependents:
                lines.append(f"- [{item.metadata.get('type', 'unknown')}] {item.id}")
            text = "\n".join(lines)
        else:
            text = "No dependents found."
            
        return [types.TextContent(type="text", text=text)]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

async def run_mcp_server(root_dir: str):
    global store
    store = SQLiteContextStore(root_dir=root_dir)
    pass 
    # stdio_server handles the look loop
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

def start_mcp(root_dir: str):
    asyncio.run(run_mcp_server(root_dir))
