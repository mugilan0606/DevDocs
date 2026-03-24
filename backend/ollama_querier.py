"""
ollama_querier.py — Free/local LLM via Ollama
Same interface as gpt_querier.py so server.py can swap them.
Requires: ollama serve  (default: http://localhost:11434)
"""

import os, re, ast, requests
from concurrent.futures import ThreadPoolExecutor, as_completed

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "codellama")
TIMEPASS_DIR    = "TimePass"


def query_ollama(prompt: str, model: str = None) -> str:
    m = model or OLLAMA_MODEL
    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={"model": m, "prompt": prompt, "stream": False},
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except requests.exceptions.ConnectionError:
        return "[ERROR] Cannot connect to Ollama. Run: ollama serve"
    except Exception as e:
        return f"[ERROR] {e}"

# Alias so server.py can call query_gpt or query_ollama uniformly
query_gpt = query_ollama


def _extract_source(file_path: str, func_name: str):
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            source = fh.read()
        lines = source.splitlines()
    except Exception:
        return None
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".py":
        try:
            tree = ast.parse(source, filename=file_path)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                    return ast.get_source_segment(source, node)
        except Exception:
            pass
        return None
    patterns = [
        rf'\bfunc(?:tion)?\s+{re.escape(func_name)}\s*[(<]',
        rf'\bdef\s+{re.escape(func_name)}\s*[(\[]',
        rf'\bfn\s+{re.escape(func_name)}\s*[(<]',
        rf'[\w<>\[\]*&]+\s+{re.escape(func_name)}\s*\(',
    ]
    start = None
    for i, line in enumerate(lines):
        for pat in patterns:
            if re.search(pat, line):
                start = i; break
        if start is not None: break
    if start is None: return None
    brace, found, end = 0, False, min(start+80, len(lines))
    for i in range(start, end):
        brace += lines[i].count("{") - lines[i].count("}")
        if "{" in lines[i]: found = True
        if found and brace <= 0: end = i+1; break
    return "\n".join(lines[start:end])


def _read_file_safe(path, max_chars=6000):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(max_chars)
    except Exception:
        return ""


def build_prompt(func_name, func_source, file_name):
    ext = os.path.splitext(file_name)[1].lower()
    lang_map = {".py":"Python",".js":"JavaScript",".ts":"TypeScript",".java":"Java",
                ".go":"Go",".rb":"Ruby",".rs":"Rust",".php":"PHP",".swift":"Swift",
                ".kt":"Kotlin",".cs":"C#",".cpp":"C++",".c":"C",".scala":"Scala"}
    lang = lang_map.get(ext, "code")
    return f"""Document this {lang} function from `{file_name}`.
Cover: 1) Summary 2) Parameters 3) Return value 4) Logic walkthrough 5) Side effects 6) Error handling 7) Usage example.
Be specific and technical.

Function: {func_name}
```{lang.lower()}
{func_source}
```"""


def _build_file_summary_prompt(file_name, snippet):
    ext = os.path.splitext(file_name)[1].lower()
    lang_map = {".py":"Python",".js":"JavaScript",".ts":"TypeScript",".java":"Java",
                ".go":"Go",".rb":"Ruby",".rs":"Rust",".php":"PHP",".swift":"Swift",
                ".kt":"Kotlin",".cs":"C#",".cpp":"C++",".c":"C",".scala":"Scala"}
    lang = lang_map.get(ext, "code")
    return f"""Write a concise 2-4 sentence summary of what this {lang} file does.
Cover its purpose, the key responsibilities it owns, and how it fits into the larger project.
Do NOT list individual functions — just describe the file's role at a high level.

File: {file_name}

```{lang.lower()}
{snippet}
```"""


def generate_docs_for_repo(directory_json, repo_dir, log_fn=None, max_workers=2):
    os.makedirs(TIMEPASS_DIR, exist_ok=True)

    func_tasks    = []
    summary_tasks = []

    def collect(node, base):
        for key, value in node.items():
            if isinstance(value, dict) and "functions" in value:
                fp = os.path.join(base, key)

                sum_cache = os.path.join(TIMEPASS_DIR, f"summary_{key}.txt")
                if os.path.exists(sum_cache):
                    with open(sum_cache) as cf:
                        value["summary"] = cf.read()
                else:
                    snippet = _read_file_safe(fp, 2000)
                    if snippet:
                        summary_tasks.append((value, key, snippet, sum_cache))

                for fe in value["functions"]:
                    for fn in fe:
                        cache = os.path.join(TIMEPASS_DIR, f"response_{key}_{fn}.txt")
                        if os.path.exists(cache):
                            with open(cache) as cf: fe[fn] = cf.read()
                        else:
                            src = _extract_source(fp, fn) or f"# Source unavailable for {fn}"
                            func_tasks.append((fe, fn, key, src, cache))
            elif isinstance(value, dict):
                collect(value, os.path.join(base, key))

    collect(directory_json, repo_dir)

    all_tasks = []
    for t in summary_tasks:
        all_tasks.append(("summary", t))
    for t in func_tasks:
        all_tasks.append(("func", t))

    total = len(all_tasks)
    done = [0]

    def run_task(item):
        kind, payload = item
        if kind == "summary":
            node, file_name, snippet, cache = payload
            resp = query_ollama(_build_file_summary_prompt(file_name, snippet))
            with open(cache, "w") as cf: cf.write(resp)
            node["summary"] = resp
        else:
            fe, fn, fname, src, cache = payload
            resp = query_ollama(build_prompt(fn, src, fname))
            with open(cache, "w") as cf: cf.write(resp)
            fe[fn] = resp
        done[0] += 1
        if log_fn:
            label = payload[1] if kind == "summary" else f"{fname}::{fn}"
            log_fn(f"  [{done[0]}/{total}] {label}")

    if all_tasks:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for f in as_completed([pool.submit(run_task, t) for t in all_tasks]):
                if f.exception() and log_fn: log_fn(f"[WARN] {f.exception()}")
    elif log_fn:
        log_fn("  All functions cached.")
    return directory_json


def generate_repo_overview(repo_dir, dir_string, readme):
    return query_ollama(f"""Give a thorough overview (4-6 paragraphs) of this software repository covering:
1. Project purpose and who it's for
2. Technology stack and why each was chosen
3. Key features
4. How to get started

README:
{readme[:2000] or 'Not available.'}

Directory Structure:
{dir_string[:1500]}""")


def generate_architecture_summary(dir_string, code_flow_json):
    return query_ollama(f"""Describe the software architecture of this project (4-5 paragraphs):
1. Architectural style (MVC, layered, etc.)
2. Module breakdown and responsibilities
3. Data flow
4. Design patterns used
5. Scalability considerations

Directory Structure:
{dir_string[:1500]}

Call Graph:
{code_flow_json[:1000]}""")


_CODE_EXTENSIONS = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".rs",
    ".php", ".swift", ".kt", ".cs", ".scala", ".c", ".cpp", ".cc", ".h", ".hpp",
)


def generate_dependency_analysis(repo_dir):
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
    return query_ollama(f"""Analyse the dependency files below. For each dependency explain: what it is, why it's used here, and alternatives.

Dependency files:
{combined[:4000]}""")


def generate_entry_points(repo_dir, dir_string):
    return query_ollama(f"""Identify entry points and write a setup guide for this project covering:
1. Main files to run and how
2. Environment setup needed
3. Installation commands
4. Common errors

Directory:
{dir_string[:1500]}""")


def generate_code_quality_notes(repo_dir):
    snippets = []
    for root, _, files in os.walk(repo_dir):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in _CODE_EXTENSIONS and len(snippets) < 6:
                c = _read_file_safe(os.path.join(root, f), 1500)
                if c: snippets.append(f"# {f}\n{c}")
    combined = chr(10).join(snippets)[:4000] if snippets else "No source code files found."
    return query_ollama(f"""Review this code and report:
1. Bugs and logic errors
2. Missing error handling
3. Security concerns
4. Code quality issues
5. Positive observations
6. Top 5 priority improvements

Code:
{combined}""")
