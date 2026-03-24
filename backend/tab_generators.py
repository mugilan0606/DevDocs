"""
tab_generators.py — Generates Mermaid and Markdown content for report tabs.
Works with both GPT and Ollama by accepting a query_fn callable.
"""

import os
import ast
import re


def _read_files(repo_dir: str, extensions: tuple, max_files: int = 8, max_chars: int = 1500) -> str:
    snippets = []
    for root, _, files in os.walk(repo_dir):
        for f in files:
            if f.endswith(extensions) and len(snippets) < max_files:
                path = os.path.join(root, f)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        content = fh.read(max_chars)
                    rel = os.path.relpath(path, repo_dir)
                    snippets.append(f"### {rel}\n{content}")
                except Exception:
                    pass
    return "\n\n".join(snippets)


def _clean_mermaid(raw: str) -> str:
    """
    Strip markdown fences, fix common LLM syntax errors, and sanitize
    Mermaid diagram code so it renders correctly in Mermaid v10.
    """
    import re as _r

    # 1. Strip markdown fences
    raw = raw.strip()
    raw = _r.sub(r"^```(?:mermaid)?\s*", "", raw, flags=_r.IGNORECASE | _r.MULTILINE)
    raw = _r.sub(r"```\s*$", "", raw, flags=_r.MULTILINE)
    raw = raw.strip()

    # 2. Find where the diagram actually starts (skip any LLM prose before it)
    diagram_types = [
        "graph ", "flowchart ", "sequenceDiagram", "classDiagram",
        "stateDiagram", "erDiagram", "gantt", "pie ", "mindmap", "gitGraph",
    ]
    lines = raw.splitlines()
    start_idx = 0
    for i, line in enumerate(lines):
        if any(line.strip().startswith(dt) for dt in diagram_types):
            start_idx = i
            break
    lines = lines[start_idx:]

    # 3. Deduplicate body lines (keep first occurrence of each line)
    if lines:
        header = lines[0]
        seen   = []
        unique = []
        for line in lines[1:]:
            key = line.strip()
            if key not in seen:
                seen.append(key)
                unique.append(line)
        lines = [header] + unique

    # 4. Process arrow lines
    # Match: Actor-->>Actor: label  where actor names may contain letters/digits/_
    # Use a non-greedy actor pattern that stops before the arrow
    arrow_re = _r.compile(
        r'^(\s*)([\w]+)'          # source actor (word chars only, no hyphen)
        r'(-->>|-->|->>|->)'      # arrow (must come before dst)
        r'([\w]*)'                # dest actor
        r'(\s*:\s*)'              # colon
        r'(.*)'                   # label
    )

    result_lines = []
    for line in lines:
        stripped = line.strip()

        # Pass through header, blank lines, keywords, comments unchanged
        if (not stripped
                or stripped.startswith("%%")
                or any(stripped.startswith(k) for k in [
                    "sequenceDiagram", "participant", "actor", "note",
                    "loop", "alt", "else", "opt", "par", "rect", "end",
                    "subgraph", "classDef", "class ", "state ", "direction",
                ])):
            result_lines.append(line)
            continue

        m = arrow_re.match(stripped)
        if m:
            src, arrow, dst, colon, label = m.group(2), m.group(3), m.group(4), m.group(5), m.group(6)

            # Fix bare -> to ->>
            if arrow == "->":
                arrow = "->>"

            # Only strip chars that genuinely break Mermaid v10 parser:
            # semicolons, backticks, single/double quotes, backslash, pipe, ampersand
            # angle brackets, curly braces — but KEEP: () / . _ - = + ! ? # % @
            label = _r.sub(r'[;`\'"\\|&<>{}]', '', label)
            label = _r.sub(r'  +', ' ', label).strip()
            if len(label) > 60:
                label = label[:57] + "..."

            result_lines.append(f"{src}{arrow}{dst}{colon}{label}")
        else:
            # Not an arrow line — keep if it looks like diagram syntax, drop if prose
            is_prose = (
                len(stripped) > 80
                and not any(c in stripped for c in ["->>", "-->", "---", ":::", "[", "("])
            )
            if not is_prose:
                result_lines.append(line)

    return "\n".join(result_lines).strip()



# ─── 1. API Docs ──────────────────────────────────────────────────────────────

def generate_api_docs(repo_dir: str, dir_string: str, query_fn) -> str:
    code = _read_files(repo_dir, (".py", ".js", ".ts", ".go", ".java"), max_files=10)
    prompt = f"""You are a technical writer generating API documentation.

Analyse the code below and produce a complete API reference in Markdown covering:

1. **Endpoints / Public Functions** — For each endpoint or exported function, document:
   - Method + path (for HTTP) or function signature
   - Description of what it does
   - Parameters (name, type, required/optional, description)
   - Response / return value (type + description)
   - Example request/response or usage snippet

2. **Authentication** — How is the API secured? What headers or tokens are needed?

3. **Error codes** — List all error responses or exception types with their meaning.

4. **Data models** — Document key request/response schemas or data classes.

Use proper Markdown with headers, tables, and code blocks. Be thorough and specific — reference actual function/route names from the code.

Code:
{code[:5000]}

Directory structure:
{dir_string[:1500]}"""
    return query_fn(prompt, max_tokens=1500)


# ─── 2. Architecture Diagram (Mermaid) ───────────────────────────────────────

def generate_architecture_mermaid(dir_string: str, code_flow_json: str, query_fn) -> str:
    prompt = f"""You are a software architect. Generate a Mermaid.js architecture diagram for this project.

CRITICAL RULES — you must follow these exactly:
- Output ONLY the raw Mermaid diagram code. No explanation, no intro sentence, no markdown fences.
- Start your response with exactly: graph TD
- Node labels must not contain special characters like (), <>, [], quotes, or colons — use simple words only
- Arrow labels must be short (1-3 words) with no special characters
- Do NOT use parentheses inside node labels — use square brackets instead: A[My Node] not A(My Node)
- Keep it simple — max 15 nodes, no deeply nested subgraphs
- Every node ID must be a simple alphanumeric string like A, B, Frontend, Backend

Directory structure:
{dir_string[:2000]}

Call graph:
{code_flow_json[:1000]}

Output only the Mermaid diagram code:"""
    raw = query_fn(prompt, max_tokens=800)
    return _clean_mermaid(raw)


# ─── 3. Sequence Diagram (Mermaid) ───────────────────────────────────────────

def generate_sequence_mermaid(repo_dir: str, dir_string: str, query_fn) -> str:
    code = _read_files(repo_dir, (".py", ".js", ".ts"), max_files=6)
    prompt = f"""You are a software architect. Generate a Mermaid.js sequence diagram for THIS specific project only.

STRICT RULES:
- Output ONLY raw Mermaid syntax. No explanation, no markdown fences, no intro text.
- Start with exactly: sequenceDiagram
- Base EVERY participant name and message on the ACTUAL code provided below. Do NOT invent names, URLs, services, or flows that are not in the code.
- Participant names: single CamelCase words only, no spaces
- Arrow syntax: use ->> for requests, -->> for responses. NEVER use ->
- Message labels: plain words only — NO semicolons, quotes, slashes, backticks, angle brackets, or special characters
- Max 10 steps total. Do NOT repeat any step.
- Show only what is genuinely present in the code below

Code samples:
{code[:3000]}

Directory structure:
{dir_string[:1000]}

Output only the Mermaid sequenceDiagram code:"""
    raw = query_fn(prompt, max_tokens=700)
    return _clean_mermaid(raw)


# ─── 4. Setup Instructions ────────────────────────────────────────────────────

def generate_setup_instructions(repo_dir: str, dir_string: str, query_fn) -> str:
    # Read package files, requirements, env examples for context
    context_files = []
    for fname in ["requirements.txt", "package.json", ".env.example", "README.md",
                  "docker-compose.yml", "Makefile", "setup.py", "pyproject.toml"]:
        path = os.path.join(repo_dir, fname)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    context_files.append(f"### {fname}\n{fh.read(2000)}")
            except Exception:
                pass

    context = "\n\n".join(context_files) or "No config files found."
    prompt = f"""You are a DevOps engineer writing a complete setup guide for this project.

Write clear, step-by-step setup instructions in Markdown covering:

## Prerequisites
- Required runtime versions (Python, Node, etc.)
- External services needed (databases, APIs, cloud accounts)
- Required CLI tools

## Installation
- Exact commands to clone and install dependencies

## Configuration
- Every environment variable needed, with description and example value
- How to create/configure the .env file

## Running the project
- Command to start in development mode
- Command to start in production mode
- Any background services that need to be running

## Common Issues & Fixes
- Top 3-5 setup problems and their solutions

## Verification
- How to verify everything is working correctly

Be precise — use actual file names and exact commands from the config files below.

Config files:
{context[:4000]}

Directory structure:
{dir_string[:1000]}"""
    return query_fn(prompt, max_tokens=1200)


# ─── 5. Test Coverage Summary ─────────────────────────────────────────────────

def generate_test_summary(repo_dir: str, dir_string: str, query_fn) -> str:
    # Find test files
    test_snippets = []
    for root, _, files in os.walk(repo_dir):
        for f in files:
            if ("test" in f.lower() or "spec" in f.lower()) and f.endswith((".py", ".js", ".ts")):
                if len(test_snippets) < 6:
                    path = os.path.join(root, f)
                    try:
                        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                            content = fh.read(2000)
                        rel = os.path.relpath(path, repo_dir)
                        test_snippets.append(f"### {rel}\n{content}")
                    except Exception:
                        pass

    test_code = "\n\n".join(test_snippets) if test_snippets else "No test files found in the repository."

    prompt = f"""You are a QA engineer reviewing the test coverage of a codebase.

Analyse the test files and directory structure below and produce a test coverage report in Markdown covering:

## Test Coverage Overview
- Estimated coverage level (none / minimal / moderate / good / excellent) with justification
- Which parts of the codebase are tested vs untested

## Existing Tests
- List each test file and what it tests
- Note the testing framework being used (pytest, jest, unittest, etc.)
- Highlight well-written tests

## Coverage Gaps
- Which critical modules, functions, or flows have NO tests
- Which edge cases are likely untested
- Any integration or end-to-end test gaps

## Test Quality Assessment
- Are tests isolated and deterministic?
- Are there any flaky or poorly written tests?
- Is mocking used appropriately?

## Recommendations
- Top 5 tests that should be written first, ordered by importance
- Suggested testing tools or frameworks to add

{"No test files were found — provide recommendations for setting up testing from scratch." if not test_snippets else ""}

Test files:
{test_code[:4000]}

Directory structure:
{dir_string[:1000]}"""
    return query_fn(prompt, max_tokens=1200)