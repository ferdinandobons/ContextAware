import argparse
import os
import sys
from ..store.sqlite_store import SQLiteContextStore
from ..analyzer.ts_analyzer import TreeSitterAnalyzer
from ..router.graph_router import GraphRouter
from ..compiler.simple_compiler import SimpleCompiler
from ..linker.graph_linker import GraphLinker
from ..exporters.mermaid_exporter import MermaidExporter
from ..server.simple_server import start_server
from ..mcp_server import start_mcp
from ..services.embedding_service import EmbeddingService
from tqdm import tqdm

def main():
    parser = argparse.ArgumentParser(description="ContextAware CLI")
    parser.add_argument("--root", default=".", help="Root directory of the project (containing .context_aware)")
    subparsers = parser.add_subparsers(dest="command")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize the context store")

    # index command
    index_parser = subparsers.add_parser("index", help="Index the current project or a file")
    index_parser.add_argument("path", help="Path to file or directory to index")
    index_parser.add_argument("--re-index", action="store_true", help="Force re-indexing if index already exists")
    index_parser.add_argument("--semantic", action="store_true", help="Generate embeddings for semantic search (slower)")

    # search command
    search_parser = subparsers.add_parser("search", help="Search the context")
    search_parser.add_argument("text", help="Search text")
    search_parser.add_argument("--type", choices=["class", "function", "file"], help="Filter by item type")
    search_parser.add_argument("--output", help="Output file path (optional)")
    search_parser.add_argument("--semantic", action="store_true", help="Use hybrid semantic search")
    
    # read command
    read_parser = subparsers.add_parser("read", help="Read specific item content (Full Mode)")
    read_parser.add_argument("id", help="Exact ID of the context item")
    
    # impacts command (Reverse Lookup)
    impacts_parser = subparsers.add_parser("impacts", help="Analyze what depends on a specific item")
    impacts_parser.add_argument("id", help="Target Item ID (e.g. class:user.py:User)")

    # graph command (Visualization)
    graph_parser = subparsers.add_parser("graph", help="Export dependency graph to Mermaid format")
    graph_parser.add_argument("--output", help="Output file path (default: stdout)")

    # ui command (formerly serve)
    ui_parser = subparsers.add_parser("ui", help="Start interactive context visualization (HTTP)")
    ui_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")

    # serve command (MCP)
    serve_parser = subparsers.add_parser("serve", help="Start MCP (Model Context Protocol) Server")
    # MCP usually runs over stdio, but we can add args if needed.
    # We could also keep 'mcp' as an alias.
    mcp_parser = subparsers.add_parser("mcp", help="Alias for serve")

    
    args = parser.parse_args()
    
    # Store at root of current execution 
    store = SQLiteContextStore(root_dir=args.root)
    
    if args.command == "init":
        print(f"Initialized ContextAware store at {store.db_path}")
        
    elif args.command == "index":
        # Note: we removed the "Index already exists" check to allow incremental updates.
            
        # Using TreeSitter for all languages
        analyzer_py = TreeSitterAnalyzer("python")
        analyzer_js = TreeSitterAnalyzer("javascript")
        analyzer_ts = TreeSitterAnalyzer("typescript")
        analyzer_go = TreeSitterAnalyzer("go")
        target_path = os.path.abspath(args.path)
        print(f"Indexing {target_path}...")
        
        files_to_process = []
        all_scanned_files = [] # Keep track of all files to detect deletions
        
        if os.path.isfile(target_path):
            if target_path.endswith((".py", ".js", ".ts", ".go")):
                all_scanned_files.append(target_path)
                mtime = os.path.getmtime(target_path)
                if args.re_index or store.should_reindex(target_path, mtime):
                    files_to_process.append(target_path)
                
        elif os.path.isdir(target_path):
            print("Scanning files...")
            for root, dirs, files in os.walk(target_path):
                # skip .context_aware and hidden dirs
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for file in files:
                    if file.endswith((".py", ".js", ".ts", ".go")):
                        full_path = os.path.join(root, file)
                        all_scanned_files.append(full_path)
                        
                        mtime = os.path.getmtime(full_path)
                        if args.re_index or store.should_reindex(full_path, mtime):
                           files_to_process.append(full_path)

        # 1. Cleanup Deleted Files
        # Only cleanup if we scanned a directory (meaning we expect to see everything there)
        # If user points to a single file, we shouldn't delete other stuff.
        # However, for simplicity, incremental index is usually run on root.
        # Let's run cleanup only if target is dir.
        if os.path.isdir(target_path):
             store.cleanup_deleted_files(all_scanned_files)

        print(f"Found {len(files_to_process)} changed files to index (out of {len(all_scanned_files)} total).")
        
        items = []
        for full_path in tqdm(files_to_process, desc="Indexing", unit="file"):
            current_items = []
            if full_path.endswith(".py"):
                current_items = analyzer_py.analyze_file(full_path)
            elif full_path.endswith(".js"):
                current_items = analyzer_js.analyze_file(full_path)
            elif full_path.endswith(".ts") or full_path.endswith(".tsx"):
                current_items = analyzer_ts.analyze_file(full_path)
            elif full_path.endswith(".go"):
                current_items = analyzer_go.analyze_file(full_path)
            
            if current_items:
                items.extend(current_items)
                # Update tracking status immediately after successful analysis
                store.update_file_status(full_path, os.path.getmtime(full_path))
        
        if items:
            # Semantic Indexing
            if args.semantic:
                print("Generating embeddings for semantic search...")
                embedding_service = EmbeddingService.get_instance()
                
                # Prepare text for embedding: Name + Docstring + snippet?
                # For now just use item.content which contains signature + docstring usually.
                # Or construct a representation.
                batch_texts = []
                for item in items:
                     # Content usually has "Function foo... Docstring..."
                     batch_texts.append(item.content)
                
                # Generate in one batch (or chunk if huge)
                # Showing progress for embeddings since it's slow
                embeddings = embedding_service.generate_embeddings(batch_texts)
                for i, item in enumerate(items):
                    if i < len(embeddings):
                        item.embedding = embeddings[i]

            store.save(items)
            print(f"Indexed {len(items)} new/modified items.")
            
            # --- Phase 1: Linking ---
            # We must re-link EVERYTHING because a change in one file (e.g. new class)
            # might resolve a dangling edge in another unchanged file.
            # Efficiency note: Linker could be optimized to only check unresolved edges, 
            # but for now re-linking the graph is safer and fast enough (metadata only).
            print("Updating graph links...")
            linker = GraphLinker(store)
            linker.link()
        else:
            print("No new items found to index.")
        
    elif args.command == "search":
        router = GraphRouter(store)
        compiler = SimpleCompiler()
        
        print(f"Searching for: '{args.text}' (Type: {args.type})")
        
        query_embedding = None
        if args.semantic:
             print("Computing query embedding...")
             service = EmbeddingService.get_instance()
             query_embedding = service.generate_embedding(args.text)
        
        # Enforce Skeleton Mode for Search
        items = router.route(args.text, type_filter=args.type, query_embedding=query_embedding)
        print(f"Found {len(items)} items.")
        
        if items:
            prompt = compiler.compile_search_results(items)
            
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(prompt)
                print(f"\nContext saved to {args.output}")
            else:
                print("\n--- Compiled Context (Skeleton) ---\n")
                print(prompt)
                print("\n-----------------------------------\n")
            
    elif args.command == "read":
        # Direct DB lookup to get file path and symbol name
        item = store.get_by_id(args.id)
        
        if item:
            print(f"Reading item: {item.id}")
            
            # Hybrid AST Lookup: Fetch fresh code from disk
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
                symbol_name = item.metadata.get("name")
            else:
                # Fallback for unknown types or file types
                symbol_name = None
            
            # Verify file exists
            if not os.path.exists(item.source_file):
                print(f"Warning: Source file not found at {item.source_file}. Returning basic metadata.")
                fresh_content = item.content
            else:
                fresh_code = None
                if analyzer and symbol_name:
                    fresh_code = analyzer.extract_code_by_symbol(item.source_file, symbol_name)
                
                if fresh_code:
                    fresh_content = fresh_code  # Update content with fresh code
                else:
                    if analyzer:
                        print(f"Warning: Symbol '{symbol_name}' not found in file. Has it been renamed?")
                    fresh_content = item.content
            
            # Create a temporary item with fresh content for compilation
            from ..models.context_item import ContextItem
            fresh_item = ContextItem(
                id=item.id,
                layer=item.layer,
                content=fresh_content,
                metadata=item.metadata,
                source_file=item.source_file,
                line_number=item.line_number
            )
            
            compiler = SimpleCompiler()
            # Enforce Full Mode for Read
            prompt = compiler.compile_read_result(fresh_item)
            print("\n--- Item Content (Full) ---\n")
            print(prompt)
            print("\n---------------------------\n")
        else:
            print(f"Item not found: {args.id}")
            
    elif args.command == "impacts":
        print(f"Analyzing impacts for: {args.id}...")
        dependents = store.get_inbound_edges(args.id)
        
        if dependents:
            print(f"Found {len(dependents)} items that depend on this:\n")
            for item in dependents:
                # Pretty print: [Type] ID
                print(f" - [{item.metadata.get('type', 'unknown')}] {item.id}")
        else:
            print("No dependents found (Safe to delete/modify?).")

    elif args.command == "graph":
        exporter = MermaidExporter(store)
        chart = exporter.export()
        
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write("```mermaid\n")
                f.write(chart)
                f.write("\n```")
            print(f"Graph exported to {args.output}")
        else:
            print(chart)
        
    elif args.command == "ui":
        start_server(store, port=args.port)
        
    elif args.command == "serve" or args.command == "mcp":
        start_mcp(root_dir=args.root)

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
