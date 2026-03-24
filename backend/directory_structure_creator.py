"""
directory_structure_creator.py
-------------------------------
Parses a repository directory and extracts functions/methods from:
  Python, JavaScript/TypeScript, Java, C/C++, Go, Ruby, Rust,
  PHP, Swift, Kotlin, C#, Scala
"""

import os
import re
import ast
import json
from PIL import Image, ImageDraw, ImageFont

LOCAL_REPO_DIR = "code_repo"
TIMEPASS_DIR   = "TimePass"

# ─── Per-language function extractors ─────────────────────────────────────────

# Files to always skip
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "env", "dist", "build", ".next", "vendor", "target",
    "bin", "obj", ".idea", ".vscode",
}

# Supported extensions → language tag
SUPPORTED_EXTENSIONS = {
    # Python
    ".py":   "python",
    # JavaScript / TypeScript
    ".js":   "javascript",
    ".jsx":  "javascript",
    ".ts":   "typescript",
    ".tsx":  "typescript",
    # Java
    ".java": "java",
    # C / C++
    ".c":    "c",
    ".cpp":  "cpp",
    ".cc":   "cpp",
    ".cxx":  "cpp",
    ".h":    "c",
    ".hpp":  "cpp",
    # Go
    ".go":   "go",
    # Ruby
    ".rb":   "ruby",
    # Rust
    ".rs":   "rust",
    # PHP
    ".php":  "php",
    # Swift
    ".swift":"swift",
    # Kotlin
    ".kt":   "kotlin",
    # C#
    ".cs":   "csharp",
    # Scala
    ".scala":"scala",
}


def extract_functions(file_path: str, lang: str) -> list[str]:
    """Return a list of function/method names found in the file."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            source = fh.read()
    except Exception:
        return []

    try:
        if lang == "python":
            return _extract_python(source, file_path)
        elif lang in ("javascript", "typescript"):
            return _extract_js_ts(source)
        elif lang == "java":
            return _extract_java(source)
        elif lang in ("c", "cpp"):
            return _extract_c_cpp(source)
        elif lang == "go":
            return _extract_go(source)
        elif lang == "ruby":
            return _extract_ruby(source)
        elif lang == "rust":
            return _extract_rust(source)
        elif lang == "php":
            return _extract_php(source)
        elif lang == "swift":
            return _extract_swift(source)
        elif lang == "kotlin":
            return _extract_kotlin(source)
        elif lang == "csharp":
            return _extract_csharp(source)
        elif lang == "scala":
            return _extract_scala(source)
    except Exception:
        pass
    return []


def _extract_python(source: str, file_path: str) -> list[str]:
    tree = ast.parse(source, filename=file_path)
    return [n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _extract_js_ts(source: str) -> list[str]:
    patterns = [
        r'(?:^|\s)function\s+([a-zA-Z_$][\w$]*)\s*\(',          # function foo(
        r'(?:^|\s)async\s+function\s+([a-zA-Z_$][\w$]*)\s*\(',  # async function foo(
        r'(?:const|let|var)\s+([a-zA-Z_$][\w$]*)\s*=\s*(?:async\s*)?\(',  # const foo = (
        r'(?:const|let|var)\s+([a-zA-Z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\([^)]*\)\s*=>)', # arrow
        r'^\s*([a-zA-Z_$][\w$]*)\s*\([^)]*\)\s*\{',             # method shorthand
        r'^\s*(?:public|private|protected|static|async)*\s*([a-zA-Z_$][\w$]*)\s*\(', # class method
    ]
    funcs = []
    for pat in patterns:
        funcs.extend(re.findall(pat, source, re.MULTILINE))
    # Deduplicate preserving order, filter keywords
    keywords = {"if","for","while","switch","catch","constructor","return","import","export"}
    seen = set()
    result = []
    for f in funcs:
        if f not in seen and f not in keywords:
            seen.add(f)
            result.append(f)
    return result


def _extract_java(source: str) -> list[str]:
    # Match method declarations (not constructors, not annotations)
    pattern = r'(?:public|private|protected|static|final|native|synchronized|abstract|transient)*\s+(?:[\w<>\[\]]+)\s+([a-zA-Z_]\w*)\s*\([^)]*\)\s*(?:throws\s+[\w,\s]+)?\s*\{'
    return list(dict.fromkeys(re.findall(pattern, source)))


def _extract_c_cpp(source: str) -> list[str]:
    # Match function definitions (return_type func_name(params) {)
    pattern = r'(?:^|\n)[\w\s\*]+\s+([a-zA-Z_]\w*)\s*\([^;]*\)\s*(?:const\s*)?\{'
    keywords = {"if","for","while","switch","else","do","struct","class","namespace"}
    funcs = re.findall(pattern, source, re.MULTILINE)
    return [f for f in dict.fromkeys(funcs) if f not in keywords]


def _extract_go(source: str) -> list[str]:
    # func (receiver) FuncName(params) or func FuncName(params)
    pattern = r'^func\s+(?:\([^)]+\)\s+)?([A-Za-z_]\w*)\s*\('
    return list(dict.fromkeys(re.findall(pattern, source, re.MULTILINE)))


def _extract_ruby(source: str) -> list[str]:
    pattern = r'^\s*def\s+([a-zA-Z_]\w*[?!]?)'
    return list(dict.fromkeys(re.findall(pattern, source, re.MULTILINE)))


def _extract_rust(source: str) -> list[str]:
    pattern = r'(?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z_]\w*)\s*[<(]'
    return list(dict.fromkeys(re.findall(pattern, source)))


def _extract_php(source: str) -> list[str]:
    pattern = r'(?:public|private|protected|static|abstract|final)*\s*function\s+([a-zA-Z_]\w*)\s*\('
    return list(dict.fromkeys(re.findall(pattern, source)))


def _extract_swift(source: str) -> list[str]:
    pattern = r'(?:func)\s+([a-zA-Z_]\w*)\s*(?:<[^>]*>)?\s*\('
    return list(dict.fromkeys(re.findall(pattern, source)))


def _extract_kotlin(source: str) -> list[str]:
    pattern = r'(?:fun)\s+([a-zA-Z_]\w*)\s*(?:<[^>]*>)?\s*\('
    return list(dict.fromkeys(re.findall(pattern, source)))


def _extract_csharp(source: str) -> list[str]:
    pattern = r'(?:public|private|protected|internal|static|virtual|override|abstract|async)*\s+(?:[\w<>\[\]?]+)\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*(?:where\s+[^{]+)?\{'
    keywords = {"if","for","while","switch","catch","using","foreach"}
    funcs = re.findall(pattern, source)
    return [f for f in dict.fromkeys(funcs) if f not in keywords]


def _extract_scala(source: str) -> list[str]:
    pattern = r'(?:def)\s+([a-zA-Z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:\([^)]*\))?\s*(?::\s*[\w\[\], ]+)?\s*='
    return list(dict.fromkeys(re.findall(pattern, source)))


# ─── Directory tree builders ───────────────────────────────────────────────────

def list_directory_tree_json(directory: str) -> dict:
    """
    Walk directory, extract functions from all supported languages,
    return nested dict and save directory_structure.json.
    """
    def list_tree(dir_path: str) -> dict:
        structure = {}
        try:
            items = sorted(os.listdir(dir_path))
        except PermissionError:
            return structure

        for item in items:
            if item.startswith(".") or item in SKIP_DIRS:
                continue
            path = os.path.join(dir_path, item)
            if os.path.isdir(path):
                sub = list_tree(path)
                if sub is not None:
                    structure[item] = sub
            else:
                ext = os.path.splitext(item)[1].lower()
                lang = SUPPORTED_EXTENSIONS.get(ext)
                if lang:
                    funcs = extract_functions(path, lang)
                    structure[item] = {
                        "language":  lang,
                        "summary":   None,
                        "functions": [{fn: None} for fn in funcs],
                    }
                else:
                    structure[item] = None
        return structure

    result = list_tree(directory)
    with open("directory_structure.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=4)
    print("-> Directory structure saved to directory_structure.json")
    return result


def add_function_info(directory: dict, timepass_dir: str = TIMEPASS_DIR) -> dict:
    """Load cached GPT responses from TimePass/ into the directory JSON."""
    if not os.path.exists(timepass_dir):
        return directory

    def traverse(sub_dir: dict):
        for key, value in sub_dir.items():
            if isinstance(value, dict) and "functions" in value:
                for func_entry in value["functions"]:
                    for func_name in func_entry:
                        cache = os.path.join(timepass_dir, f"response_{key}_{func_name}.txt")
                        if os.path.exists(cache):
                            with open(cache, "r", encoding="utf-8") as fh:
                                func_entry[func_name] = fh.read()
            elif isinstance(value, dict):
                traverse(value)

    traverse(directory)
    with open("directory_structure.json", "w", encoding="utf-8") as fh:
        json.dump(directory, fh, indent=4)
    print("-> Function info added to directory_structure.json")
    return directory


def get_finalized_text_string(repo: str, directory: dict) -> str:
    """Return a tree-formatted string of the directory for the PDF report."""
    def traverse(sub_dir, indent=""):
        lines = []
        for key, value in sub_dir.items():
            if key.startswith(".") or key in SKIP_DIRS:
                continue
            if isinstance(value, dict) and "functions" in value:
                lang = value.get("language", "")
                tag  = f" [{lang}]" if lang else ""
                lines.append(f"{indent}+-- {key}{tag}")
                for func in value["functions"]:
                    for fn in func:
                        lines.append(f"{indent}|          +---> {fn}")
            elif isinstance(value, dict):
                lines.append(f"{indent}+-- {key}/")
                lines.extend(traverse(value, indent + "|      "))
            else:
                lines.append(f"{indent}+-- {key}")
        return lines

    return "\n".join([repo] + traverse(directory))


def create_finalized_text_file(directory: dict, repo_name: str = LOCAL_REPO_DIR):
    text = get_finalized_text_string(repo_name, directory)
    with open("finalized_directory_structure.txt", "w", encoding="utf-8") as fh:
        fh.write(text)
    print("-> Finalized directory structure saved.")