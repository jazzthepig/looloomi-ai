#!/usr/bin/env python3
"""
CometCloud Compliance Hook — PreToolUse
Phase B of HARNESS_UPGRADE.md

Scans edits, writes, and bash commands for forbidden transactional language
before they reach the filesystem. Currently in DRY-RUN mode (warns but does
not block). To enable blocking: set COMPLIANCE_BLOCK=1 in environment.

How this works:
  Claude Code fires PreToolUse hooks before executing Edit / Write / Bash.
  This script reads the tool input from stdin (JSON), checks for forbidden
  signals, and exits 0 (allow) or 2 (block) depending on mode.

Usage (Claude Code hooks config):
  {
    "hooks": {
      "PreToolUse": [
        {
          "matcher": "Edit|Write|Bash",
          "hooks": [{"type": "command", "command": "python3 .claude/hooks/compliance_check.py"}]
        }
      ]
    }
  }
"""

import sys
import json
import re
import os

# ─── Configuration ─────────────────────────────────────────────────────────────

# Set COMPLIANCE_BLOCK=1 to block violations. Default: warn only (dry run).
BLOCK_MODE = os.environ.get("COMPLIANCE_BLOCK", "0") == "1"

# Files and paths that are always exempt from compliance checks
EXEMPT_PATHS = [
    ".claude/skills/",          # Skills document the rules (must reference forbidden terms)
    "CIS_METHODOLOGY.md",       # May reference old terms in "DO NOT USE" context
    "CLAUDE.md",                # Documents the rules
    "HARNESS_UPGRADE.md",       # References rules in documentation
    "tests/",                   # Test fixtures may contain violation examples
    "Shadow/",                  # Read-only reference; never rendered to users
    ".claude/hooks/",           # This file itself
]

# Forbidden transactional signal patterns (case-insensitive, word boundary)
FORBIDDEN_PATTERNS = [
    # Signal labels
    (r'\bSTRONG\s+BUY\b',         "signal label 'STRONG BUY' → use 'STRONG OUTPERFORM'"),
    (r'(?<![A-Z_])\bBUY\b(?!\s*(?:side|back|in\s+at))', "signal label 'BUY' → use 'OUTPERFORM'"),
    (r'\bSTRONG\s+SELL\b',        "signal label 'STRONG SELL' → use 'UNDERWEIGHT'"),
    (r'(?<![A-Z_])\bSELL\b(?!\s+(?:side|off))', "signal label 'SELL' → use 'UNDERPERFORM'"),
    (r'\bACCUMULATE\b',           "signal label 'ACCUMULATE' → use 'OUTPERFORM'"),
    (r'\bAVOID\b(?!\s+(?:using|the\s+word|this\s+file|this\s+function))',
                                  "signal label 'AVOID' → use 'UNDERWEIGHT'"),
    (r'\bREDUCE\s+(?:position|exposure|holding)s?\b',
                                  "'REDUCE [exposure]' → use 'risk reduction positioning'"),
    # Imperative trade actions aimed at reader
    (r'\bGO\s+LONG\b',            "'go long' → use 'STRONG OUTPERFORM positioning'"),
    (r'\bGO\s+SHORT\b',           "'go short' → describe as 'UNDERWEIGHT positioning'"),
    (r'\bLOAD\s+UP\b',            "'load up' → use 'STRONG OUTPERFORM'"),
    (r'\bSTOP\s+OUT\b',           "'stop out' → describe as position exit in past tense"),
    (r'\bLIQUIDATE\b',            "'liquidate' → describe as 'position closed'"),
    (r'\bDUMP\b',                 "'dump' → describe as 'positioned UNDERWEIGHT'"),
    # Price target language (Type 4 advisory territory)
    (r'\bTARGET\s+PRICE\b',       "price target language requires Type 4 license"),
    (r'\bPRICE\s+TARGET\b',       "price target language requires Type 4 license"),
    # Chinese forbidden terms
    (r'买入|賣出|卖出|建仓|建倉|清仓|清倉|减仓|減倉|加仓|加倉|做多|做空',
                                  "Chinese transactional language → use 定位/看好/看淡"),
]

# Paths that are user-facing (always check these regardless of file extension)
USER_FACING_GLOBS = [
    "src/api/routers/",
    "dashboard/src/",
    "dashboard/public/",
    "src/data/",
    "src/mcp/",
]


def is_exempt(path: str) -> bool:
    """Return True if this path should be skipped."""
    if not path:
        return False
    for exempt in EXEMPT_PATHS:
        if exempt in path:
            return True
    return False


def is_user_facing(path: str) -> bool:
    """Return True if this path produces user-facing output."""
    if not path:
        return False
    for prefix in USER_FACING_GLOBS:
        if prefix in path:
            return True
    # Check by extension
    if path.endswith((".jsx", ".tsx", ".html", ".md")):
        return True
    return False


def scan_content(content: str, path: str = "") -> list[dict]:
    """Scan text content for compliance violations. Returns list of findings."""
    findings = []
    lines = content.splitlines()

    for pattern_str, description in FORBIDDEN_PATTERNS:
        pattern = re.compile(pattern_str, re.IGNORECASE)
        for lineno, line in enumerate(lines, 1):
            # Skip lines that are clearly rule documentation (contain "→ use", "NEVER", "DO NOT")
            if any(marker in line for marker in ["→ use", "NEVER use", "DO NOT use",
                                                  "not:", "forbidden", "prohibited"]):
                continue
            match = pattern.search(line)
            if match:
                findings.append({
                    "line": lineno,
                    "col": match.start(),
                    "match": match.group(0),
                    "description": description,
                    "context": line.strip()[:100],
                })

    return findings


def check_edit(tool_input: dict) -> list[dict]:
    """Check Edit tool — scans new_string."""
    path = tool_input.get("file_path", "")
    if is_exempt(path):
        return []
    new_string = tool_input.get("new_string", "")
    return scan_content(new_string, path)


def check_write(tool_input: dict) -> list[dict]:
    """Check Write tool — scans content."""
    path = tool_input.get("file_path", "")
    if is_exempt(path):
        return []
    content = tool_input.get("content", "")
    return scan_content(content, path)


def check_bash(tool_input: dict) -> list[dict]:
    """Check Bash tool — scans command for inline content writes."""
    command = tool_input.get("command", "")
    # Only scan heredoc content (cat <<'EOF') — avoid flagging comments or path names
    if "EOF" in command or "echo" in command:
        return scan_content(command, "bash_command")
    return []


def format_findings(findings: list[dict], tool_name: str, path: str) -> str:
    """Format findings into a human-readable compliance report."""
    lines = [
        f"⚠️  COMPLIANCE: {len(findings)} violation(s) detected in {tool_name} → {path or 'command'}",
        "",
    ]
    for f in findings[:5]:  # Show max 5 to avoid overwhelming
        lines.append(f"  Line {f['line']}: [{f['match']}] — {f['description']}")
        lines.append(f"  Context: {f['context']}")
        lines.append("")

    if len(findings) > 5:
        lines.append(f"  ... and {len(findings) - 5} more. Run audit checklist for full scan.")

    lines.append("  Reference: .claude/skills/compliance-language/SKILL.md")
    lines.append("  Substitutions: .claude/skills/compliance-language/references/substitution_table.md")

    if not BLOCK_MODE:
        lines.append("")
        lines.append("  ℹ️  DRY-RUN mode (COMPLIANCE_BLOCK not set). Edit was allowed through.")
        lines.append("  Set COMPLIANCE_BLOCK=1 to enable blocking.")

    return "\n".join(lines)


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)

        data = json.loads(raw)
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})

    except (json.JSONDecodeError, KeyError):
        # If we can't parse the input, allow through (fail open — don't block agent)
        sys.exit(0)

    # Route to the right checker
    findings = []
    path = tool_input.get("file_path", tool_input.get("path", ""))

    if tool_name == "Edit":
        findings = check_edit(tool_input)
    elif tool_name == "Write":
        findings = check_write(tool_input)
    elif tool_name == "Bash":
        findings = check_bash(tool_input)
    else:
        sys.exit(0)

    if not findings:
        sys.exit(0)

    # Only surface findings for user-facing paths OR always-on violations
    if not is_user_facing(path) and not BLOCK_MODE:
        # Internal file, dry-run mode — silently allow
        sys.exit(0)

    report = format_findings(findings, tool_name, path)

    if BLOCK_MODE:
        # Exit 2 = block the tool call and return the message as the result
        print(json.dumps({
            "decision": "block",
            "reason": report
        }))
        sys.exit(2)
    else:
        # Exit 0 = allow, but print warning to stderr for visibility
        print(report, file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
