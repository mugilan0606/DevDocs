"""
gpt_querier.py
--------------
Replaces ollama_querier.py — uses OpenAI GPT-3.5-turbo for all LLM calls.
Set OPENAI_API_KEY in your environment or a .env file.
"""

import os
import re
import ast
import json
import requests

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
TIMEPASS_DIR   = "TimePass"


# ─── Core API call ────────────────────────────────────────────────────────────

def query_gpt(prompt: str, system: str = "You are an expert software engineer.", max_tokens: int = 600) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return "[ERROR] OPENAI_API_KEY not set. Add it to your environment."
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.HTTPError as e:
        return f"[ERROR] OpenAI API error: {e} — {resp.text}"
    except Exception as e:
        return f"[ERROR] {e}"


# ─── Source extraction ────────────────────────────────────────────────────────

def _extract_source(file_path: str, func_name: str):
    """
    Extract source of `func_name` from `file_path`.
    Uses AST for Python; regex + brace-counting for all other languages.
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            source = fh.read()
        lines = source.splitlines()
    except Exception:
        return None

    ext = os.path.splitext(file_path)[1].lower()

    # Python — precise AST extraction
    if ext == ".py":
        try:
            tree = ast.parse(source, filename=file_path)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and node.name == func_name:
                    return ast.get_source_segment(source, node)
        except Exception:
            pass
        return None

    # All other languages — find definition line then grab brace-balanced block
    patterns = [
        rf'\bfunc(?:tion)?\s+{re.escape(func_name)}\s*[(<]',
        rf'\bdef\s+{re.escape(func_name)}\s*[(\[]',
        rf'\bfn\s+{re.escape(func_name)}\s*[(<]',
        rf'[\w<>\[\]*&]+\s+{re.escape(func_name)}\s*\(',
    ]

    start_line = None
    for i, line in enumerate(lines):
        for pat in patterns:
            if re.search(pat, line):
                start_line = i
                break
        if start_line is not None:
            break

    if start_line is None:
        return None

    brace_count = 0
    found_open  = False
    end_line    = min(start_line + 80, len(lines))
    for i in range(start_line, end_line):
        brace_count += lines[i].count("{") - lines[i].count("}")
        if "{" in lines[i]:
            found_open = True
        if found_open and brace_count <= 0:
            end_line = i + 1
            break

    return "\n".join(lines[start_line:end_line])


def _read_file_safe(path: str, max_chars: int = 6000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read(max_chars)
    except Exception:
        return ""


# ─── Per-function documentation ───────────────────────────────────────────────

def build_prompt(func_name: str, func_source: str, file_name: str) -> str:
    ext  = os.path.splitext(file_name)[1].lower()
    lang_map = {
        ".py":"Python",".js":"JavaScript",".jsx":"JavaScript",
        ".ts":"TypeScript",".tsx":"TypeScript",".java":"Java",
        ".c":"C",".cpp":"C++",".cc":"C++",".h":"C",".hpp":"C++",
        ".go":"Go",".rb":"Ruby",".rs":"Rust",".php":"PHP",
        ".swift":"Swift",".kt":"Kotlin",".cs":"C#",".scala":"Scala",
    }
    lang = lang_map.get(ext, "code")
    return f"""You are a senior software engineer writing detailed technical documentation for a developer audience.

Analyse the {lang} function `{func_name}` from the file `{file_name}` and produce thorough documentation covering ALL of the following:

1. SUMMARY — A clear 2-3 sentence description of what this function does, why it exists, and where it fits in the codebase.
2. PARAMETERS — For each parameter: name, inferred type, whether it's required or optional, and a detailed description of its purpose and expected values.
3. RETURN VALUE — The type and a full description of what is returned, including edge cases (e.g. returns None if not found).
4. LOGIC WALKTHROUGH — A step-by-step explanation of the key logic inside the function (what it computes, transforms, queries, etc.)
5. SIDE EFFECTS — Any external state changes, database writes, file I/O, network calls, or global mutations.
6. ERROR HANDLING — What exceptions might be raised and under what conditions. Note any missing error handling.
7. USAGE EXAMPLE — A realistic one-liner or short snippet showing how this function would be called.

Be specific, detailed, and technical. Reference the actual variable names and logic from the source code.

Function: {func_name}
File: {file_name}

```{lang.lower()}
{func_source}
```"""


def generate_repo_overview(repo_dir: str, dir_string: str, readme: str) -> str:
    prompt = f"""You are a senior software architect reviewing a codebase for a new team member joining the project.

Based on the directory structure and README below, write a thorough overview (5-7 paragraphs) covering:

1. PROJECT PURPOSE — What problem does this project solve? Who is it built for? What is the business or technical value?
2. TECHNOLOGY STACK — List and explain every major framework, library, and language used and why each was chosen.
3. SYSTEM OVERVIEW — Describe the high-level system: is it a web app, CLI tool, API, library, data pipeline, etc.? What are its inputs and outputs?
4. KEY FEATURES — What are the 3-5 most important capabilities this project provides?
5. PROJECT MATURITY — Based on the code structure, README completeness, and patterns used, assess the maturity level (prototype, production-ready, etc.) and note any obvious gaps.
6. GETTING STARTED — Summarise how a new developer would set up and run this project.

Be detailed and specific — reference actual file names, class names, and technologies found in the code.

README:
{readme[:3000] if readme else "Not available."}

Directory Structure:
{dir_string[:2500]}"""
    return query_gpt(prompt, max_tokens=1000)


def generate_architecture_summary(dir_string: str, code_flow_json: str) -> str:
    prompt = f"""You are a software architect writing an architecture document for this repository.

Write a detailed architecture summary (5-6 paragraphs) covering:

1. ARCHITECTURAL STYLE — What architectural pattern is used? (MVC, layered, microservices, monolith, pipeline, etc.) Justify your assessment based on the file structure.
2. MODULE BREAKDOWN — Describe the role of each major file or folder. What responsibility does each own?
3. DATA FLOW — Trace how data enters the system, gets processed, and exits. What are the main data transformations?
4. COMPONENT RELATIONSHIPS — Which modules depend on which? What are the core vs peripheral components?
5. DESIGN PATTERNS — Identify any design patterns in use (factory, decorator, singleton, repository, etc.) with specific examples from the code.
6. SCALABILITY & EXTENSIBILITY — How easy would it be to add new features? What are the coupling points or bottlenecks?

Reference actual file and function names from the structure below.

Directory Structure:
{dir_string[:2500]}

Call Graph:
{code_flow_json[:2000]}"""
    return query_gpt(prompt, max_tokens=900)


_CODE_EXTENSIONS = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".rs",
    ".php", ".swift", ".kt", ".cs", ".scala", ".c", ".cpp", ".cc", ".h", ".hpp",
)


def generate_dependency_analysis(repo_dir: str) -> str:
    dep_files_content = []
    dep_names = [
        "requirements.txt", "Pipfile", "pyproject.toml", "setup.py", "setup.cfg",
        "package.json", "package-lock.json", "yarn.lock",
        "go.mod", "Cargo.toml", "Gemfile", "build.gradle", "pom.xml",
        "composer.json", "Package.swift", "build.sbt",
    ]
    for name in dep_names:
        p = os.path.join(repo_dir, name)
        if os.path.exists(p):
            dep_files_content.append(f"### {name}\n{_read_file_safe(p, 3000)}")

    if not dep_files_content:
        for root, _, files in os.walk(repo_dir):
            for f in files:
                if f in dep_names and len(dep_files_content) < 5:
                    dep_files_content.append(f"### {f}\n{_read_file_safe(os.path.join(root, f), 2000)}")

    combined = "\n\n".join(dep_files_content) if dep_files_content else "No dependency files found."

    prompt = f"""You are a software engineer reviewing the dependencies of this repository.

Analyse the dependency/config files below and produce a detailed dependency report covering:
1. WHAT EACH DEPENDENCY IS — A clear description.
2. WHY IT'S USED HERE — How it fits into this project.
3. KEY FEATURES USED — What specific APIs are likely leveraged.
4. ALTERNATIVES — 1-2 alternatives with trade-offs.
5. POTENTIAL RISKS — Deprecations, security concerns, or licensing issues.

Be thorough — write 3-5 sentences per dependency. Group related dependencies together.

Dependency files:
{combined[:5000]}"""
    return query_gpt(prompt, max_tokens=1000)


def generate_entry_points(repo_dir: str, dir_string: str) -> str:
    prompt = f"""You are documenting this repository for a developer who wants to run it for the first time.

Based on the directory structure below, identify ALL entry points and provide a complete setup guide covering:

1. MAIN ENTRY POINTS — List every file that can be run directly (look for `if __name__ == "__main__"`, `app.run()`, CLI scripts, etc.). For each one explain what it does when run.
2. ENVIRONMENT SETUP — What environment variables, config files, or `.env` files are needed? List each one with its purpose and an example value.
3. INSTALLATION STEPS — Exact commands to install dependencies (pip install, npm install, etc.)
4. RUN COMMANDS — The exact terminal commands to start the application in development and production modes.
5. PREREQUISITES — Python version, external services (databases, message queues, APIs) that must be running first.
6. COMMON ERRORS — Anticipate 2-3 common setup mistakes and how to fix them.

Directory structure:
{dir_string[:2500]}"""
    return query_gpt(prompt, max_tokens=800)


def generate_code_quality_notes(repo_dir: str) -> str:
    snippets = []
    for root, _, files in os.walk(repo_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in _CODE_EXTENSIONS and len(snippets) < 8:
                content = _read_file_safe(os.path.join(root, f), max_chars=1800)
                if content:
                    snippets.append(f"# File: {f}\n{content}")

    combined = "\n\n---\n\n".join(snippets) if snippets else "No source code files found."
    prompt = f"""You are a senior code reviewer conducting a thorough review of this codebase.

Analyse the code samples below and produce a detailed code quality report covering:

1. BUGS & LOGIC ERRORS — Any code that will definitely or likely fail at runtime. Be specific about file and line context.
2. ERROR HANDLING GAPS — Missing try/except blocks, unhandled edge cases, or places where the code assumes inputs are valid.
3. SECURITY CONCERNS — Hardcoded credentials, SQL injection risks, insecure use of eval/exec, exposed secrets, unvalidated inputs.
4. CODE SMELL & DESIGN ISSUES — Overly long functions, duplicate code, poor naming, magic numbers, deep nesting, or violations of single-responsibility principle.
5. MISSING DOCUMENTATION — Functions or modules with no docstrings or comments where they're critically needed.
6. PERFORMANCE CONCERNS — Inefficient loops, unnecessary database calls, missing indexes, memory leaks, or blocking I/O.
7. POSITIVE OBSERVATIONS — What the code does well — good patterns, clean structure, sensible abstractions.
8. PRIORITY IMPROVEMENTS — A ranked list of the top 5 things to fix or improve, ordered by impact.

Be specific — always reference the actual file name and function name when raising an issue.

Code samples:
{combined[:5000]}"""
    return query_gpt(prompt, max_tokens=1000)


def _build_file_summary_prompt(file_name: str, snippet: str) -> str:
    ext  = os.path.splitext(file_name)[1].lower()
    lang_map = {
        ".py":"Python",".js":"JavaScript",".jsx":"JavaScript",
        ".ts":"TypeScript",".tsx":"TypeScript",".java":"Java",
        ".c":"C",".cpp":"C++",".cc":"C++",".h":"C",".hpp":"C++",
        ".go":"Go",".rb":"Ruby",".rs":"Rust",".php":"PHP",
        ".swift":"Swift",".kt":"Kotlin",".cs":"C#",".scala":"Scala",
    }
    lang = lang_map.get(ext, "code")
    return f"""Write a concise 2-4 sentence summary of what this {lang} file does.
Cover its purpose, the key responsibilities it owns, and how it fits into the larger project.
Do NOT list individual functions — just describe the file's role at a high level.

File: {file_name}

```{lang.lower()}
{snippet}
```"""


def generate_docs_for_repo(directory_json: dict, repo_dir: str, log_fn=None, max_workers: int = 4) -> dict:
    """Walk directory_json, query GPT for each function and each file summary, cache results in TimePass/."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    os.makedirs(TIMEPASS_DIR, exist_ok=True)

    func_tasks    = []
    summary_tasks = []

    def collect_tasks(node, base_path):
        for key, value in node.items():
            if isinstance(value, dict) and "functions" in value:
                file_path = os.path.join(base_path, key)

                # File summary task
                sum_cache = os.path.join(TIMEPASS_DIR, f"summary_{key}.txt")
                if os.path.exists(sum_cache):
                    with open(sum_cache) as cf:
                        value["summary"] = cf.read()
                else:
                    snippet = _read_file_safe(file_path, max_chars=2000)
                    if snippet:
                        summary_tasks.append((value, key, snippet, sum_cache))

                # Function-level tasks
                for func_entry in value["functions"]:
                    for func_name in func_entry:
                        cache = os.path.join(TIMEPASS_DIR, f"response_{key}_{func_name}.txt")
                        if os.path.exists(cache):
                            with open(cache) as cf:
                                func_entry[func_name] = cf.read()
                        else:
                            src = _extract_source(file_path, func_name) or f"# Source unavailable for {func_name}"
                            func_tasks.append((func_entry, func_name, key, src, cache))
            elif isinstance(value, dict):
                collect_tasks(value, os.path.join(base_path, key))

    collect_tasks(directory_json, repo_dir)

    all_tasks = []
    for t in summary_tasks:
        all_tasks.append(("summary", t))
    for t in func_tasks:
        all_tasks.append(("func", t))

    total = len(all_tasks)
    done  = [0]

    def run_task(item):
        kind, payload = item
        if kind == "summary":
            node, file_name, snippet, cache = payload
            response = query_gpt(_build_file_summary_prompt(file_name, snippet), max_tokens=300)
            with open(cache, "w") as cf:
                cf.write(response)
            node["summary"] = response
        else:
            func_entry, func_name, file_name, src, cache = payload
            response = query_gpt(build_prompt(func_name, src, file_name))
            with open(cache, "w") as cf:
                cf.write(response)
            func_entry[func_name] = response
        done[0] += 1
        if log_fn:
            label = file_name if kind == "summary" else f"{file_name}::{payload[1]}"
            log_fn(f"  [{done[0]}/{total}] {label}")

    if all_tasks:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(run_task, t) for t in all_tasks]
            for f in as_completed(futures):
                exc = f.exception()
                if exc and log_fn:
                    log_fn(f"[WARN] query failed: {exc}")
    elif log_fn:
        log_fn("  All functions cached — skipping GPT queries.")

    return directory_json