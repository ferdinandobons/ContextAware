# Context Aware Navigation

Use this skill when you need to understand project structure,
find code to modify, or analyze impact of changes.

## Available Commands

### Get project overview
```bash
context_aware structure
```
Use at the start of a task to understand the codebase layout.

### Search for components
```bash
context_aware search "query"
```
Find classes, functions, or files matching your query.

### Read component with dependencies
```bash
context_aware read "class:path/file.py:ClassName"
```
Get full source code for a specific indexed item.

### Analyze impact before modifying
```bash
context_aware impacts "function:path/file.py:func_name"
```
See what would break if you modify this component.

## Workflow

1. **Understand**: Start with `structure` to get the project map
2. **Search**: Use `search` to find relevant components
3. **Inspect**: Use `read` to see full code with dependencies
4. **Analyze**: Use `impacts` BEFORE modifying to understand consequences
5. **Modify**: Make changes with full awareness of the impact
