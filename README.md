# ContextAware

**ContextAware** is a lightweight, agent-centric context management framework. It acts as a "Map Provider" for LLMs, allowing them to navigate large codebases efficiently without consuming massive amounts of tokens.

## 🚀 Why ContextAware?

Standard RAG (Retrieval-Augmented Generation) is often too imprecise for coding tasks (missing dependencies, hallucinating imports). Reading the entire codebase is too expensive and slow.

**ContextAware solves this by treating your code as a Navigable Graph.**
*   **Token Efficiency**: Reduces exploration costs by 90% via "Skeleton Mode".
*   **Contextual Understanding**: LLMs often need to read dozens of files just to understand the project structure and locate relevant code. ContextAware replaces this with a structured map.
*   **Smart Ranking**: Uses PageRank-like scoring to prioritize core architectural components over utility scripts.
*   **Impact Analysis**: Explicitly answers "What breaks if I change this file?" via reverse graph lookup.
*   **Scalable**: Built on SQLite + Relational Graph, works on projects of any size.
*   **Agent-Ready**: Returns structured XML optimized for LLM consumption.

## 🌍 Supported Languages

*   **Python**: Full support via **Tree-sitter** (Classes, Functions, Imports).
*   **JavaScript/TypeScript**: Full support via **Tree-sitter** (Classes, Functions, Variables).
*   **Go**: Full support via **Tree-sitter** (Structs, Interfaces, Functions).
*   **Other Languages**: Easily extensible thanks to the new generic Tree-sitter analyzer.


---

## 🤖 Agent Protocol (How to use this tool)

If you are an AI Agent (e.g., Devin, Cline, Gemini Code Assist), follow this explicit protocol to solve tasks with maximum efficiency.

### Workflow: "Skeleton-First" Navigation

Do not read file contents blindly. Use the tool to find what matters.

#### Phase 1: Discovery (Low Cost)
Ask "Where is the code related to X?" getting only the high-level structure.
*   **Command**: `context_aware search "your search terms"`
*   **Goal**: Identify relevant classes/functions and their relationships.
*   **Output**: You will see signatures and `<dependencies>` tags.

#### Phase 2: Traversal (Optional)
If a class depends on another service (e.g., `OrderProcessor` uses `InventoryService`), follow the link.
*   **Command**: `context_aware search "InventoryService"`
*   **Goal**: Understand the API of the dependency without reading its implementation.

#### Phase 3: Extraction (High Cost, High Value)
Once you pinpoint the exact function/class to modify or debug, fetch its full source code.
*   **Command**: `context_aware read "function:file.py:target_function"`
*   **Goal**: Get the actual code to work on.

---

## 📦 Installation & Setup

1.  **Install via pip**:
    ```bash
    pip install context-aware
    ```

2.  **Initialize a Project**:
    Navigate to your target project root and run:
    ```bash
    context_aware init
    ```
    *Or for an external project:*
    ```bash
    context_aware --root /path/to/project init
    ```

3.  **Index the Codebase**:
    Parse and store the project structure (runs locally, no data leaves your machine).
    ```bash
    context_aware index .
    # Or
    context_aware --root /path/to/project index /path/to/project
    ```

---

## 📖 CLI Reference

### `init`
Creates the local SQLite store (`.context_aware/context.db`).
```bash
context_aware init
```

### `index <path>`
Parses Python files, extracts AST nodes (classes, functions, imports), and updates the graph.
```bash
context_aware index ./src
# Optional: Generate embeddings for semantic search (slower)
context_aware index ./src --semantic
```

### `search <query>`
Search for relevant code context. Returns signatures, docstrings, and dependencies.
```bash
context_aware search "order processing"
```
Options:
- `--type <class|function|file>`: Filter results.
- `--output <file>`: Save results to a file.
- `--semantic`: Enable Hybrid Semantic Search (combines keywords + embeddings). Requires `sentence-transformers`.

### `read <id>`
Read the full source code of a specific item found during search.
```bash
context_aware read "class:orders/processor.py:OrderProcessor"
```

### `impacts <id>`
Analyze what depends on a specific item (Reverse Lookup).
```bash
context_aware impacts "class:user.py:User"
```

### `graph`
Export the dependency graph to Mermaid format.
```bash
context_aware graph --output architecture.mmd
```

### `serve` (or `mcp`)
Starts the **Model Context Protocol (MCP)** server. This allows AI Agents (like Claude Desktop) to mount the repository as a resource, enabling direct tool usage (`search`, `read`, `impacts`) over stdio.
```bash
context_aware serve
# or
context_aware mcp
```

### `ui`
Starts the interactive visualization server (Browser UI).
```bash
context_aware ui --port 8000
```


### Global Options
*   `--root <path>`: Specify the root directory of the project (where `.context_aware` lives). Essential when working on projects outside the current working directory.

---

## ⚡️ Example Scenario

**Task**: "Fix a bug in the discount calculation logic."

1.  **Agent asks**: Where are discounts handled?
    ```bash
    context_aware search "discount calculation"
    ```
    *Output*: Found `class:PricingService` in `pricing.py`. It uses `UserTierService`.

2.  **Agent analyzes**: I see `PricingService.calculate_discount`. I need to see the code.
    ```bash
    context_aware read "class:pricing.py:PricingService"
    ```
    *Output*: Full Python code of the class.

3.  **Agent plans refactor**: I want to change the User class. context_aware, what depends on it?
    ```bash
    context_aware impacts "class:user.py:User"
    ```
    *Output*: List of dependents: `AccountService`, `TransactionManager`. "Okay, I need to check those files too."

3.  **Agent executes**: The bug is identified. The agent creates a patch.

---

## 🏗 Architecture

*   **Analyzer**: `TreeSitterAnalyzer` provides robust, error-tolerant parsing for Python, JS, TS, and Go. Extracts symbols and dependencies while **storing only metadata** in the DB.
*   **Store**: `SQLiteContextStore` with FTS5 for fast fuzzy search of docstrings and names.
*   **Router**: `GraphRouter` performs graph traversal on the metadata.
*   **Retriever**: **On-Demand AST Parsing**. When you request code (`read`), the system reads the file from disk *at that moment* and extracts the function body. This ensures **zero stale data**—you always get the current code.
*   **Compiler**: Converts nodes into XML prompts (`<item>`, `<dependencies>`) for the LLM.