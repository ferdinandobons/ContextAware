"""
MCP (Model Context Protocol) Server for ContextAware.

Exposes the indexed codebase to AI assistants (Claude, etc.) via the MCP protocol.
This allows LLMs to search code, read implementations, and analyze dependencies
as part of their reasoning process.

Available MCP Tools:
  - search: Query the index with keywords or semantic search
  - read: Fetch full source code for a specific item
  - impacts: Analyze reverse dependencies (with cascade analysis)
  - structure: Get project structure overview

The server runs over stdio, making it compatible with Claude Desktop, VS Code
extensions, and other MCP clients. All output is formatted as Markdown for
optimal LLM consumption.
"""
import asyncio
import logging
import os
from typing import Any, List, Optional, Union

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from .store.sqlite_store import SQLiteContextStore
from .router.graph_router import GraphRouter
from .compiler.simple_compiler import SimpleCompiler
from .analyzer.ts_analyzer import TreeSitterAnalyzer, get_language_for_file
from .services.embedding_service import EmbeddingService
from .tools.structure import StructureGenerator
from .models.context_item import ContextItem

logger = logging.getLogger(__name__)

# Type alias for MCP tool responses (text, image, or embedded resource)
ToolResult = List[Union[types.TextContent, types.ImageContent, types.EmbeddedResource]]


class MCPServerState:
    """
    Holds server-wide state in a structured way.

    Using a class instead of global variables makes testing easier and
    prevents accidental state leakage between test runs.
    """

    def __init__(self):
        self.store: Optional[SQLiteContextStore] = None
        self.initialization_lock: Optional[asyncio.Lock] = None
        self.store_ready: Optional[asyncio.Event] = None


server = Server("context-aware")
_state = MCPServerState()


def _error_response(message: str) -> ToolResult:
    """Wrap an error message in MCP TextContent format."""
    return [types.TextContent(type="text", text=f"Error: {message}")]


def _text_response(text: str) -> ToolResult:
    """Wrap a success message in MCP TextContent format."""
    return [types.TextContent(type="text", text=text)]


def _validate_string_param(
    arguments: Any,
    param_name: str,
    required: bool = True
) -> tuple[Optional[str], Optional[ToolResult]]:
    """
    Validate and extract a string parameter from MCP tool arguments.

    Returns:
      (value, None) on success - the validated string
      (None, error_response) on failure - ready-to-return error

    This pattern allows callers to early-return errors cleanly:
        query, error = _validate_string_param(arguments, "query")
        if error:
            return error
    """
    value = arguments.get(param_name)

    if value is None:
        if required:
            return None, _error_response(f"Missing '{param_name}' parameter")
        return None, None

    if not isinstance(value, str):
        return None, _error_response(f"Invalid '{param_name}' parameter: must be a string")

    value = value.strip()
    if required and not value:
        return None, _error_response(f"'{param_name}' cannot be empty")

    return value, None


@server.list_tools()
async def list_tools() -> List[types.Tool]:
    """
    Advertise available MCP tools to the client (Claude, etc.).

    Each tool has a JSON Schema defining its parameters, which helps
    LLMs understand how to call them correctly.
    """
    return [
        types.Tool(
            name="search",
            description="Search the codebase for relevant context using keywords. Returns a high-level skeleton of matches.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query keywords"},
                    "type": {"type": "string", "enum": ["class", "function", "file"], "description": "Filter by item type"},
                    "semantic": {"type": "boolean", "description": "Enable semantic hybrid search (slower but finds concepts)"}
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
            description="Analyze dependencies to see what items depend on the target item (Reverse Lookup). Shows both direct and cascade impacts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The Item ID to analyze"}
                },
                "required": ["id"]
            }
        ),
        types.Tool(
            name="structure",
            description="Get a high-level overview of the project structure. Shows modules, entry points, and key components.",
            inputSchema={
                "type": "object",
                "properties": {
                    "compact": {"type": "boolean", "description": "Return minimal output for context injection"}
                },
                "required": []
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: Any) -> ToolResult:
    """
    MCP tool dispatcher - routes tool calls to the appropriate handler.

    Waits for store initialization on first call (async-safe).
    """
    if _state.store_ready:
        try:
            await asyncio.wait_for(_state.store_ready.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            return _error_response("Store initialization timeout")

    if not _state.store:
        return _error_response("Store not initialized")

    store = _state.store

    if name == "search":
        return _handle_search(store, arguments)
    elif name == "read":
        return _handle_read(store, arguments)
    elif name == "impacts":
        return _handle_impacts(store, arguments)
    elif name == "structure":
        return _handle_structure(store, arguments)

    return _error_response(f"Unknown tool: {name}")


def _handle_search(store: SQLiteContextStore, arguments: Any) -> ToolResult:
    """
    Execute a search query and return skeleton results.

    Supports both FTS (fast) and hybrid semantic search (slower, concept-aware).
    Returns Markdown-formatted results suitable for LLM consumption.
    """
    query, error = _validate_string_param(arguments, "query")
    if error:
        return error

    type_filter = arguments.get("type")

    if type_filter is not None and type_filter not in ("class", "function", "file"):
        return _error_response(f"Invalid type filter: {type_filter}")

    router = GraphRouter(store)
    compiler = SimpleCompiler()

    query_embedding = None
    if arguments.get("semantic"):
        try:
            service = EmbeddingService.get_instance()
            query_embedding = service.generate_embedding(query)
        except Exception as e:
            logger.warning(f"Failed to generate embedding: {e}")
            # Graceful degradation: continue with FTS-only search

    items = router.route(query, type_filter=type_filter, query_embedding=query_embedding)
    text = compiler.compile_search_results(items, query=query)

    return _text_response(text)


def _handle_read(store: SQLiteContextStore, arguments: Any) -> ToolResult:
    """
    Fetch and return full source code for a specific item.

    Reads live from the filesystem for freshness. Falls back to stored
    content if the source file was deleted or symbol was renamed.
    Returns Markdown-formatted output with code blocks.
    """
    item_id, error = _validate_string_param(arguments, "id")
    if error:
        return error

    item = store.get_by_id(item_id)

    if not item:
        return _error_response(f"Item not found: {item_id}")

    symbol_name = item.metadata.get("name")
    fresh_content = item.content

    if item.source_file and os.path.exists(item.source_file):
        lang = get_language_for_file(item.source_file)

        if lang and symbol_name:
            analyzer = TreeSitterAnalyzer(lang)
            code = analyzer.extract_code_by_symbol(item.source_file, symbol_name)
            if code:
                fresh_content = code

    # Create a fresh item with updated content
    fresh_item = ContextItem(
        id=item.id,
        layer=item.layer,
        content=fresh_content,
        metadata=item.metadata,
        source_file=item.source_file,
        line_number=item.line_number
    )

    compiler = SimpleCompiler()
    text = compiler.compile_read_result(fresh_item)
    return _text_response(text)


def _handle_impacts(store: SQLiteContextStore, arguments: Any) -> ToolResult:
    """
    Return all items that depend on the specified item.

    Uses cascade analysis to show both direct dependents and indirectly
    affected items through the dependency chain.
    """
    item_id, error = _validate_string_param(arguments, "id")
    if error:
        return error

    direct, cascade = store.get_cascade_dependents(item_id)

    compiler = SimpleCompiler()
    text = compiler.compile_impacts_result(item_id, direct, cascade)

    return _text_response(text)


def _handle_structure(store: SQLiteContextStore, arguments: Any) -> ToolResult:
    """
    Generate and return project structure overview.

    Provides a high-level map of the project for AI agents to understand
    the codebase organization, modules, and key components.
    """
    compact = arguments.get("compact", False)

    generator = StructureGenerator(store)
    text = generator.generate(compact=compact)

    return _text_response(text)


async def run_mcp_server(root_dir: str) -> None:
    """
    Async entry point for the MCP server.

    Initializes the store (with locking to prevent races) and starts
    the stdio-based MCP protocol handler.
    """
    if _state.initialization_lock is None:
        _state.initialization_lock = asyncio.Lock()

    async with _state.initialization_lock:
        if _state.store is None:
            _state.store_ready = asyncio.Event()
            _state.store = SQLiteContextStore(root_dir=root_dir)
            _state.store_ready.set()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


def start_mcp(root_dir: str) -> None:
    """Blocking entry point - runs the MCP server until interrupted."""
    asyncio.run(run_mcp_server(root_dir))
