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

    # query command
    query_parser = subparsers.add_parser("query", help="Query the context")
    query_parser.add_argument("text", help="Query text")
    query_parser.add_argument("--mode", choices=["full", "skeleton"], default="full", help="Output mode")
    query_parser.add_argument("--type", choices=["class", "function", "file"], help="Filter by item type")
    
    # retrieve command
    retrieve_parser = subparsers.add_parser("retrieve", help="Retrieve specific item by ID")
    retrieve_parser.add_argument("id", help="Exact ID of the context item")
    
    args = parser.parse_args()
    
    # Store at root of current execution 
    store = SQLiteContextStore(root_dir=args.root)
    
    if args.command == "init":
        print(f"Initialized ContextAware store at {store.db_path}")
        
    elif args.command == "index":
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
        
    elif args.command == "query":
        router = GraphRouter(store)
        compiler = SimpleCompiler()
        
        print(f"Querying for: '{args.text}' (Mode: {args.mode}, Type: {args.type})")
        items = router.route(args.text, type_filter=args.type)
        print(f"Found {len(items)} items.")
        
        if items:
            prompt = compiler.compile(items, mode=args.mode)
            print("\n--- Compiled Context ---\n")
            print(prompt)
            print("\n------------------------\n")
            
    elif args.command == "retrieve":
        # Direct DB lookup to get file path and symbol name
        item = store.get_by_id(args.id)
        
        if item:
            print(f"Retrieved item: {item.id}")
            
            # Hybrid AST Lookup: Fetch fresh code from disk
            # We need to construct the absolute path if it's relative
            # item.source_file comes from the machine that indexed it. 
            # If we are running on the same machine/mount, it works.
            
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
            prompt = compiler.compile([fresh_item], mode="full")
            print("\n--- Context Item ---\n")
            print(prompt)
            print("\n--------------------\n")
        else:
            print(f"Item not found: {args.id}")
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
