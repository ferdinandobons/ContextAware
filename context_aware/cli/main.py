import argparse
import os
import sys
from ..store.json_store import JSONContextStore
from ..analyzer.python_analyzer import PythonAnalyzer
from ..router.basic_router import BasicRouter
from ..compiler.simple_compiler import SimpleCompiler

def main():
    parser = argparse.ArgumentParser(description="ContextAware MVP CLI")
    subparsers = parser.add_subparsers(dest="command")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize the context store")
    init_parser.add_argument("path", nargs="?", default=".", help="Project path to initialize")

    # index command
    index_parser = subparsers.add_parser("index", help="Index the current project or a file")
    index_parser.add_argument("path", help="Path to file or directory to index")

    # query command
    query_parser = subparsers.add_parser("query", help="Query the context")
    query_parser.add_argument("text", help="Query text")
    
    args = parser.parse_args()
    
    # Store at root of current execution 
    store = JSONContextStore()
    
    if args.command == "init":
        print(f"Initialized ContextAware store at {store.items_file}")
        
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
        router = BasicRouter(store)
        compiler = SimpleCompiler()
        
        print(f"Querying for: '{args.text}'")
        items = router.route(args.text)
        print(f"Found {len(items)} items.")
        
        if items:
            prompt = compiler.compile(items)
            print("\n--- Compiled Context ---\n")
            print(prompt)
            print("\n------------------------\n")
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
