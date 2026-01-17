# Context Aware Navigation

Use this skill when you need to understand project structure, find code to modify, or analyze the impact of changes. ContextAware indexes your codebase and tracks dependencies between components.

> **Tip**: Run `context_aware --help` or `context_aware <command> --help` for detailed usage information.

---

## Available Commands

### 1. Get Project Overview

```bash
context_aware structure
```

Shows a high-level map of the project including modules, entry points, and key components. Use this at the **start of any task** to understand how the codebase is organized.

**Options:**
- `--compact` - Minimal output, useful for quick reference
- `--inject` - Output without headers (used by pre-prompt hooks)

**Example:**
```bash
context_aware structure --compact
```

---

### 2. Search for Components

```bash
context_aware search "query"
```

Finds classes, functions, or files matching your query. Returns a skeleton view with metadata, dependencies, and file locations.

**Options:**
- `--type {class,function,file}` - Filter results by item type
- `--semantic` - Enable hybrid semantic search (slower but finds conceptually related items)
- `--output FILE` - Save results to a file

**Examples:**
```bash
# Find all authentication-related code
context_aware search "authentication"

# Find only classes related to user management
context_aware search "user" --type class

# Semantic search for error handling patterns
context_aware search "exception handling" --semantic
```

---

### 3. Read Full Source Code

```bash
context_aware read "item_id"
```

Retrieves the complete source code for a specific indexed item. The item ID follows the format `type:path/file.ext:Name`.

**ID Format:**
- `class:path/file.py:ClassName` - A class definition
- `function:path/file.py:function_name` - A function definition
- `file:path/file.py` - An entire file

**Examples:**
```bash
# Read a specific class
context_aware read "class:auth/service.py:AuthService"

# Read a specific function
context_aware read "function:utils/helpers.py:validate_email"

# Read an entire file
context_aware read "file:config/settings.py"
```

> **Note**: Item IDs are returned by the `search` command. Copy them directly from search results.

---

### 4. Analyze Impact Before Modifying

```bash
context_aware impacts "item_id"
```

Shows what depends on the specified item. This is **critical** before making changes to understand the cascade effect.

**Output includes:**
- **Direct dependents**: Items that directly use this component
- **Cascade impact**: Items indirectly affected through the dependency chain

**Examples:**
```bash
# See what uses the User class
context_aware impacts "class:models/user.py:User"

# Check impact before modifying a utility function
context_aware impacts "function:utils/db.py:get_connection"
```

---

## Typical Workflow

1. **Understand the project**
   ```bash
   context_aware structure
   ```
   Get the overall layout and identify relevant modules.

2. **Search for what you need**
   ```bash
   context_aware search "feature keyword"
   ```
   Find components related to your task.

3. **Inspect the code**
   ```bash
   context_aware read "class:path/file.py:ClassName"
   ```
   Get full source code with dependencies.

4. **Analyze impact BEFORE modifying**
   ```bash
   context_aware impacts "class:path/file.py:ClassName"
   ```
   Understand what will break if you change this.

5. **Make informed changes**
   Modify with full awareness of dependencies and affected code.

---

## Quick Reference

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `structure` | Project overview | Start of any task |
| `search "query"` | Find components | Looking for specific code |
| `read "id"` | Full source code | Need implementation details |
| `impacts "id"` | Dependency analysis | Before modifying anything |

---

## Getting Help

```bash
# General help
context_aware --help

# Command-specific help
context_aware search --help
context_aware read --help
context_aware impacts --help
context_aware structure --help
```
