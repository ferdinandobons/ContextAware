"""
ContextAware CLI - Main entry point for the command-line interface.

Commands:
    init      - Initialize the .context_aware directory and SQLite database
    index     - Parse source files and build the context index
    search    - Query the index using keywords or semantic search
    read      - Fetch full source code for a specific symbol
    impacts   - Show reverse dependencies (what depends on X?)
    structure - Show project structure overview
    serve     - Start MCP server for IDE/editor integration

The CLI orchestrates all major components: analyzer, store, router, compiler, linker.
"""
import argparse
import logging
import os
from typing import Dict

from tqdm import tqdm

from ..store.sqlite_store import SQLiteContextStore
from ..analyzer.ts_analyzer import (
    TreeSitterAnalyzer,
    ALL_SUPPORTED_EXTENSIONS,
    get_language_for_file,
)
from ..router.graph_router import GraphRouter
from ..compiler.simple_compiler import SimpleCompiler
from ..linker.graph_linker import GraphLinker
from ..mcp_server import start_mcp
from ..services.embedding_service import EmbeddingService
from ..models.context_item import ContextItem
from ..tools.structure import StructureGenerator
from ..integrations.claude import setup_claude_integration

logger = logging.getLogger(__name__)


def main():
    """
    CLI entry point. Parses arguments and dispatches to the appropriate handler.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )

    parser = argparse.ArgumentParser(description="ContextAware CLI")
    parser.add_argument("--root", default=".", help="Root directory of the project (containing .context_aware)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    subparsers = parser.add_subparsers(dest="command")

    # Command: init - Creates .context_aware/ and initializes the SQLite database
    init_parser = subparsers.add_parser("init", help="Initialize the context store")
    init_parser.add_argument("--claude", action="store_true", help="Set up Claude Code integration (hooks, skills)")

    # Command: index - Parses source files and populates the database
    index_parser = subparsers.add_parser("index", help="Index the current project or a file")
    index_parser.add_argument("path", help="Path to file or directory to index")
    index_parser.add_argument("--re-index", action="store_true", help="Force re-indexing if index already exists")
    index_parser.add_argument("--semantic", action="store_true", help="Generate embeddings for semantic search (slower)")

    # Command: search - Query the index with FTS or hybrid semantic search
    search_parser = subparsers.add_parser("search", help="Search the context")
    search_parser.add_argument("text", help="Search text")
    search_parser.add_argument("--type", choices=["class", "function", "file"], help="Filter by item type")
    search_parser.add_argument("--output", help="Output file path (optional)")
    search_parser.add_argument("--semantic", action="store_true", help="Use hybrid semantic search")

    # Command: read - Fetch full source code for a specific indexed item
    read_parser = subparsers.add_parser("read", help="Read specific item content (Full Mode)")
    read_parser.add_argument("id", help="Exact ID of the context item")

    # Command: impacts - Reverse dependency lookup (who calls/uses this item?)
    impacts_parser = subparsers.add_parser("impacts", help="Analyze what depends on a specific item")
    impacts_parser.add_argument("id", help="Target Item ID (e.g. class:user.py:User)")

    # Command: structure - Show project structure overview
    structure_parser = subparsers.add_parser("structure", help="Show project structure overview")
    structure_parser.add_argument("--compact", action="store_true", help="Minimal output for context injection")
    structure_parser.add_argument("--inject", action="store_true", help="Output without headers (for hooks)")

    # Command: serve/mcp - Start MCP server for AI assistant integration
    subparsers.add_parser("serve", help="Start MCP (Model Context Protocol) Server")
    subparsers.add_parser("mcp", help="Alias for serve")

    args = parser.parse_args()

    if hasattr(args, 'verbose') and args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize store at project root (creates .context_aware/ if needed)
    store = SQLiteContextStore(root_dir=args.root)

    if args.command == "init":
        logger.info(f"Initialized ContextAware store at {store.db_path}")
        if hasattr(args, 'claude') and args.claude:
            if setup_claude_integration(args.root):
                logger.info("Claude Code integration set up successfully.")
                logger.info("Created: .claude/hooks/UserPromptSubmit.toml")
                logger.info("Created: .claude/skills/context-aware.md")
            else:
                logger.error("Failed to set up Claude Code integration.")

    elif args.command == "index":
        _handle_index(args, store)

    elif args.command == "search":
        _handle_search(args, store)

    elif args.command == "read":
        _handle_read(args, store)

    elif args.command == "impacts":
        _handle_impacts(args, store)

    elif args.command == "structure":
        _handle_structure(args, store)

    elif args.command in ("serve", "mcp"):
        start_mcp(root_dir=args.root)

    else:
        parser.print_help()


def _handle_index(args, store: SQLiteContextStore) -> None:
    """
    Index source files: parse, extract symbols, build dependency graph.

    Indexing pipeline:
      1. Scan for supported files (.py, .js, .ts, .tsx, .go)
      2. Check modification times to skip unchanged files (incremental indexing)
      3. Parse each changed file with TreeSitterAnalyzer
      4. Optionally generate embeddings for semantic search (--semantic flag)
      5. Save ContextItems to SQLite with FTS indexing
      6. Run GraphLinker to resolve fuzzy dependencies to concrete IDs
    """
    target_path = os.path.abspath(args.path)
    logger.info(f"Indexing {target_path}...")

    files_to_process = []
    all_scanned_files = []

    if os.path.isfile(target_path):
        if target_path.endswith(ALL_SUPPORTED_EXTENSIONS):
            all_scanned_files.append(target_path)
            mtime = os.path.getmtime(target_path)
            if args.re_index or store.should_reindex(target_path, mtime):
                files_to_process.append(target_path)

    elif os.path.isdir(target_path):
        logger.info("Scanning files...")
        for root, dirs, files in os.walk(target_path):
            # Skip hidden directories (e.g., .git, .venv)
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for file in files:
                if file.endswith(ALL_SUPPORTED_EXTENSIONS):
                    full_path = os.path.join(root, file)
                    all_scanned_files.append(full_path)

                    mtime = os.path.getmtime(full_path)
                    if args.re_index or store.should_reindex(full_path, mtime):
                        files_to_process.append(full_path)

    # Remove orphaned entries for deleted files
    if os.path.isdir(target_path):
        store.cleanup_deleted_files(all_scanned_files)

    logger.info(f"Found {len(files_to_process)} changed files to index (out of {len(all_scanned_files)} total).")

    # Lazy-load analyzers per language to avoid loading unused grammars
    analyzers: Dict[str, TreeSitterAnalyzer] = {}

    def get_analyzer(lang: str) -> TreeSitterAnalyzer:
        if lang not in analyzers:
            analyzers[lang] = TreeSitterAnalyzer(lang)
        return analyzers[lang]

    items = []
    for full_path in tqdm(files_to_process, desc="Indexing", unit="file"):
        lang = get_language_for_file(full_path)
        if lang:
            current_items = get_analyzer(lang).analyze_file(full_path)
            if current_items:
                items.extend(current_items)
                store.update_file_status(full_path, os.path.getmtime(full_path))

    if items:
        # Generate vector embeddings for hybrid search (optional, slower)
        if args.semantic:
            logger.info("Generating embeddings for semantic search...")
            embedding_service = EmbeddingService.get_instance()

            batch_texts = [item.content for item in items]
            embeddings = embedding_service.generate_embeddings(batch_texts)

            if len(embeddings) != len(items):
                logger.warning(f"Generated {len(embeddings)} embeddings for {len(items)} items")

            for i, item in enumerate(items):
                if i < len(embeddings):
                    item.embedding = embeddings[i]

        store.save(items)
        logger.info(f"Indexed {len(items)} new/modified items.")

        # Resolve symbolic dependencies (e.g., "UserService") to concrete item IDs
        logger.info("Updating graph links...")
        linker = GraphLinker(store)
        linker.link()
    else:
        logger.info("No new items found to index.")


def _handle_search(args, store: SQLiteContextStore) -> None:
    """
    Search the index using keywords or hybrid semantic search.

    Two modes:
      - FTS (default): Fast full-text search using SQLite FTS5
      - Hybrid (--semantic): Combines FTS with vector similarity for concept matching

    Output is a "skeleton view" showing signatures and dependencies, not full code.
    Use the `read` command to fetch complete source code.
    """
    router = GraphRouter(store)
    compiler = SimpleCompiler()

    logger.info(f"Searching for: '{args.text}' (Type: {args.type})")

    query_embedding = None
    if args.semantic:
        logger.info("Computing query embedding...")
        service = EmbeddingService.get_instance()
        query_embedding = service.generate_embedding(args.text)

    items = router.route(args.text, type_filter=args.type, query_embedding=query_embedding)
    logger.info(f"Found {len(items)} items.")

    prompt = compiler.compile_search_results(items, query=args.text)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(prompt)
        logger.info(f"Context saved to {args.output}")
    else:
        print(prompt)


def _handle_read(args, store: SQLiteContextStore) -> None:
    """
    Fetch and display full source code for a specific indexed item.

    Always reads live from the filesystem to ensure freshness, falling back
    to stored content if the file was deleted or the symbol was renamed.
    """
    item = store.get_by_id(args.id)

    if not item:
        logger.error(f"Item not found: {args.id}")
        return

    logger.info(f"Reading item: {item.id}")

    if not item.source_file:
        logger.warning("Item has no source file. Returning stored content.")
        fresh_content = item.content
    elif not os.path.exists(item.source_file):
        logger.warning(f"Source file not found at {item.source_file}. Returning stored content.")
        fresh_content = item.content
    else:
        # Extract live code from the actual file
        lang = get_language_for_file(item.source_file)
        symbol_name = item.metadata.get("name")
        fresh_content = item.content

        if lang and symbol_name:
            analyzer = TreeSitterAnalyzer(lang)
            fresh_code = analyzer.extract_code_by_symbol(item.source_file, symbol_name)

            if fresh_code:
                fresh_content = fresh_code
            else:
                logger.warning(f"Symbol '{symbol_name}' not found in file. Has it been renamed?")

    fresh_item = ContextItem(
        id=item.id,
        layer=item.layer,
        content=fresh_content,
        metadata=item.metadata,
        source_file=item.source_file,
        line_number=item.line_number
    )

    compiler = SimpleCompiler()
    prompt = compiler.compile_read_result(fresh_item)
    print(prompt)


def _handle_impacts(args, store: SQLiteContextStore) -> None:
    """
    Reverse dependency analysis: find all items that depend on a given item.

    Useful for impact analysis before refactoring - answers "if I change X,
    what else might break?"
    """
    logger.info(f"Analyzing impacts for: {args.id}...")
    direct, cascade = store.get_cascade_dependents(args.id)

    compiler = SimpleCompiler()
    prompt = compiler.compile_impacts_result(args.id, direct, cascade)
    print(prompt)


def _handle_structure(args, store: SQLiteContextStore) -> None:
    """
    Generate and display project structure overview.

    Outputs a compact map of the project for AI agents to understand
    the codebase organization, modules, and key components.
    """
    generator = StructureGenerator(store)
    output = generator.generate(
        compact=args.compact,
        inject_mode=args.inject
    )
    print(output)


if __name__ == "__main__":
    main()
