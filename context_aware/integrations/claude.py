"""
Claude Code integration for ContextAware.

Sets up hooks and skills for seamless Claude Code integration:
- Pre-prompt hook: Injects project structure automatically
- Custom skill: Provides guidance on using ContextAware commands
"""
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Template files are located relative to this module
TEMPLATES_DIR = Path(__file__).parent / "templates"


def setup_claude_integration(project_root: str) -> bool:
    """
    Set up Claude Code integration files.

    Creates:
    - .claude/hooks/UserPromptSubmit.toml - Pre-prompt structure injection
    - .claude/skills/context-aware.md - Usage guidance for Claude

    Args:
        project_root: Root directory of the project

    Returns:
        True if setup was successful, False otherwise
    """
    root = Path(project_root)

    try:
        # Create .claude directories
        hooks_dir = root / ".claude" / "hooks"
        skills_dir = root / ".claude" / "skills"

        hooks_dir.mkdir(parents=True, exist_ok=True)
        skills_dir.mkdir(parents=True, exist_ok=True)

        # Copy hook template
        hook_src = TEMPLATES_DIR / "claude_hook.toml"
        hook_dst = hooks_dir / "UserPromptSubmit.toml"

        if hook_src.exists():
            shutil.copy(hook_src, hook_dst)
            logger.info(f"Created hook: {hook_dst}")
        else:
            # Fallback: write inline if template not found
            _write_hook_inline(hook_dst)
            logger.info(f"Created hook (inline): {hook_dst}")

        # Copy skill template
        skill_src = TEMPLATES_DIR / "claude_skill.md"
        skill_dst = skills_dir / "context-aware.md"

        if skill_src.exists():
            shutil.copy(skill_src, skill_dst)
            logger.info(f"Created skill: {skill_dst}")
        else:
            # Fallback: write inline if template not found
            _write_skill_inline(skill_dst)
            logger.info(f"Created skill (inline): {skill_dst}")

        return True

    except Exception as e:
        logger.error(f"Failed to set up Claude integration: {e}")
        return False


def _write_hook_inline(path: Path) -> None:
    """Write hook content inline when template is not available."""
    content = '''# ContextAware pre-prompt hook for Claude Code
# Injects project structure before each user prompt

[[hooks]]
event = "UserPromptSubmit"

[hooks.run]
command = "context_aware"
args = ["structure", "--compact", "--inject"]
timeout = 5000
'''
    path.write_text(content)


def _write_skill_inline(path: Path) -> None:
    """Write skill content inline when template is not available."""
    content = '''# Context Aware Navigation

Use this skill when you need to understand project structure, find code to modify, or analyze the impact of changes.

> **Tip**: Run `context_aware --help` or `context_aware <command> --help` for detailed usage.

## Commands

| Command | Purpose |
|---------|---------|
| `context_aware structure` | Project overview (start here) |
| `context_aware search "query"` | Find components |
| `context_aware read "id"` | Full source code |
| `context_aware impacts "id"` | Dependency analysis |

## Workflow

1. `context_aware structure` - Understand the project layout
2. `context_aware search "keyword"` - Find relevant components
3. `context_aware read "class:path/file.py:Name"` - Get full code
4. `context_aware impacts "class:path/file.py:Name"` - Check before modifying
5. Make changes with full awareness of dependencies
'''
    path.write_text(content)


def check_claude_integration(project_root: str) -> dict:
    """
    Check if Claude integration is set up.

    Returns:
        Dict with status of each integration component
    """
    root = Path(project_root)

    return {
        "hook_exists": (root / ".claude" / "hooks" / "UserPromptSubmit.toml").exists(),
        "skill_exists": (root / ".claude" / "skills" / "context-aware.md").exists(),
    }
