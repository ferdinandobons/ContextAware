import argparse
import os
import sys
from ..store.sqlite_store import SQLiteContextStore
from ..analyzer.python_analyzer import PythonAnalyzer
from ..router.graph_router import GraphRouter
from ..compiler.simple_compiler import SimpleCompiler

def main():
    parser = argparse.ArgumentParser(description="ContextAware MVP CLI")
    parser.add_argument("--root", default=".", help="Root directory of the project (containing .context_aware)")
    subparsers = parser.add_subparsers(dest="command")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize the context store")
    # path arg here is redundant if we have --root, but keeping for compatibility if usage was 'init <path>'
    init_parser.add_argument("path", nargs="?", default=".", help="Project path to initialize")

    # index command
    index_parser = subparsers.add_parser("index", help="Index the current project or a file")
    index_parser.add_argument("path", help="Path to file or directory to index")
    index_parser.add_argument("--re-index", action="store_true", help="Force re-indexing if index already exists")

    # search command (formerly query)
    search_parser = subparsers.add_parser("search", help="Search the context (Skeleton Mode)")
    search_parser.add_argument("text", help="Search text")
    search_parser.add_argument("--type", choices=["class", "function", "file"], help="Filter by item type")
    search_parser.add_argument("--output", help="Output file path (optional)")
    
    # read command (formerly retrieve)
    read_parser = subparsers.add_parser("read", help="Read specific item content (Full Mode)")
    read_parser.add_argument("id", help="Exact ID of the context item")
    
    args = parser.parse_args()
    
    # Store at root of current execution 
    store = SQLiteContextStore(root_dir=args.root)
    
    if args.command == "init":
        print(f"Initialized ContextAware store at {store.db_path}")
        
    elif args.command == "index":
        if store.has_index() and not args.re_index:
            print(f"Index already exists at {store.db_path}.")
            print("Use --re-index to overwrite.")
            sys.exit(0)
            
        analyzer = PythonAnalyzer()
        target_path = os.path.abspath(args.path)
        print(f"Indexing {target_path}...")
        
        items = []
        if os.path.isfile(target_path):
            items = analyzer.analyze_file(target_path)
        elif os.path.isdir(target_path):
            for root, dirs, files in os.walk(target_path):
                # skip .context_aware and hidden dirs
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for file in files:
                    if file.endswith(".py"):
                        full_path = os.path.join(root, file)
                        items.extend(analyzer.analyze_file(full_path))
        
        if items:
            store.save(items)
            print(f"Indexed {len(items)} items.")
        else:
            print("No items found to index.")
        
    elif args.command == "search":
        router = GraphRouter(store)
        compiler = SimpleCompiler()
        
        print(f"Searching for: '{args.text}' (Type: {args.type})")
        # Enforce Skeleton Mode for Search
        items = router.route(args.text, type_filter=args.type)
        print(f"Found {len(items)} items.")
        
        if items:
            prompt = compiler.compile(items, mode="skeleton")
            
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
            analyzer = PythonAnalyzer()
            symbol_name = item.metadata.get("name")
            
            # Verify file exists
            if not os.path.exists(item.source_file):
                print(f"Warning: Source file not found at {item.source_file}. Returning basic metadata.")
                fresh_content = item.content
            else:
                fresh_code = analyzer.extract_code_by_symbol(item.source_file, symbol_name)
                if fresh_code:
                    fresh_content = fresh_code  # Update content with fresh code
                else:
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
            prompt = compiler.compile([fresh_item], mode="full")
            print("\n--- Item Content (Full) ---\n")
            print(prompt)
            print("\n---------------------------\n")
        else:
            print(f"Item not found: {args.id}")
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
