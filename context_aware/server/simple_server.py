import http.server
import socketserver
import json
import os
import urllib.parse
from ..store.sqlite_store import SQLiteContextStore

class ContextGraphHandler(http.server.SimpleHTTPRequestHandler):
    store = None # Class variable to hold store reference

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        
        if parsed_path.path == "/":
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            
            # Serve graph.html
            ui_path = os.path.join(os.path.dirname(__file__), '../ui/graph.html')
            if os.path.exists(ui_path):
                with open(ui_path, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b"Error: graph.html not found.")
                
        elif parsed_path.path == "/api/graph":
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            # Nodes
            items = self.store.load()
            nodes = []
            for item in items:
                nodes.append({
                    "id": item.id,
                    "label": item.metadata.get("name", item.id.split(":")[-1]),
                    "group": item.metadata.get("type", "unknown"),
                    "title": item.id # Tooltip
                })
                
            # Edges
            raw_edges = self.store.get_all_edges()
            edges = []
            for src, key, target, rel in raw_edges:
                if target: # Only linked edges or maybe all? Vis.js needs 'to'
                    edges.append({
                        "from": src,
                        "to": target,
                        "arrows": "to",
                        "label": rel
                    })
                # We could visualize unresolved edges too if we want, but 'to' is missing.
                # Skip for now.
                
            data = {"nodes": nodes, "edges": edges}
            self.wfile.write(json.dumps(data).encode('utf-8'))
            
        elif parsed_path.path == "/api/item":
             query = urllib.parse.parse_qs(parsed_path.query)
             item_id = query.get('id', [None])[0]
             
             if item_id:
                 item = self.store.get_by_id(item_id)
                 if item:
                     self.send_response(200)
                     self.send_header('Content-type', 'application/json')
                     self.end_headers()
                     
                     # Serialize context item
                     data = {
                         "id": item.id,
                         "content": item.content,
                         "metadata": item.metadata,
                         "source_file": item.source_file,
                         "line_number": item.line_number
                     }
                     self.wfile.write(json.dumps(data).encode('utf-8'))
                     return

             self.send_response(404)
             self.end_headers()
             
        else:
            # Fallback to default file serving (optional, or just 404)
            self.send_response(404)
            self.end_headers()

def start_server(store: SQLiteContextStore, port: int = 8000):
    ContextGraphHandler.store = store
    try:
        with socketserver.TCPServer(("", port), ContextGraphHandler) as httpd:
            print(f"Serving Context Graph at http://localhost:{port}")
            print("Press Ctrl+C to stop.")
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
