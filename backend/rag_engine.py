"""
rag_engine.py — Lightweight RAG for repo-aware chat.
Chunks source files, indexes them with BM25-style retrieval,
and generates answers using GPT or Ollama with retrieved context.
Zero external dependencies beyond the standard library + requests.
"""

import os
import re
import math
import json
from collections import Counter

SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".rs",
    ".php", ".swift", ".kt", ".cs", ".scala", ".c", ".cpp", ".cc", ".h", ".hpp",
    ".css", ".scss", ".html", ".xml", ".yaml", ".yml", ".toml", ".json",
    ".md", ".txt", ".sh", ".bash", ".zsh", ".dockerfile", ".sql",
    ".env.example", ".gitignore", ".dockerignore",
}

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", "vendor", "target", "bin", "obj",
    ".idea", ".vscode", ".cache", "coverage",
}

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
MAX_FILES = 200
MAX_FILE_SIZE = 50_000


# ─── Chunking ─────────────────────────────────────────────────────────────────

def chunk_repository(repo_dir: str) -> list[dict]:
    """Walk repo, read source files, split into overlapping chunks."""
    chunks = []
    file_count = 0

    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fname in sorted(files):
            if file_count >= MAX_FILES:
                break
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS and fname.lower() not in {
                "makefile", "dockerfile", "rakefile", "gemfile",
                "readme", "license", "changelog",
            }:
                continue

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read(MAX_FILE_SIZE)
            except Exception:
                continue

            if not content.strip():
                continue

            rel_path = os.path.relpath(fpath, repo_dir)
            file_count += 1

            file_chunks = _split_text(content, rel_path)
            chunks.extend(file_chunks)

    return chunks


def _split_text(text: str, file_path: str) -> list[dict]:
    """Split a file's content into overlapping chunks with metadata."""
    lines = text.split("\n")
    chunks = []
    i = 0
    char_count = 0
    chunk_start = 0

    while i < len(lines):
        line = lines[i]
        char_count += len(line) + 1

        if char_count >= CHUNK_SIZE:
            chunk_text = "\n".join(lines[chunk_start:i + 1])
            chunks.append({
                "file": file_path,
                "start_line": chunk_start + 1,
                "end_line": i + 1,
                "text": chunk_text,
            })

            overlap_chars = 0
            overlap_start = i
            while overlap_start > chunk_start and overlap_chars < CHUNK_OVERLAP:
                overlap_chars += len(lines[overlap_start]) + 1
                overlap_start -= 1
            chunk_start = overlap_start + 1
            char_count = sum(len(lines[j]) + 1 for j in range(chunk_start, i + 1))

        i += 1

    if chunk_start < len(lines):
        remaining = "\n".join(lines[chunk_start:])
        if remaining.strip():
            chunks.append({
                "file": file_path,
                "start_line": chunk_start + 1,
                "end_line": len(lines),
                "text": remaining,
            })

    return chunks


# ─── BM25-style Retrieval ──────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z_]\w*", text.lower())


def _build_idf(corpus_tokens: list[list[str]]) -> dict[str, float]:
    n = len(corpus_tokens)
    df = Counter()
    for doc in corpus_tokens:
        for token in set(doc):
            df[token] += 1
    return {t: math.log((n - freq + 0.5) / (freq + 0.5) + 1) for t, freq in df.items()}


def retrieve(query: str, chunks: list[dict], top_k: int = 6) -> list[dict]:
    """BM25-based retrieval of the most relevant chunks for a query."""
    if not chunks:
        return []

    query_tokens = _tokenize(query)
    if not query_tokens:
        return chunks[:top_k]

    corpus_tokens = [_tokenize(c["text"] + " " + c["file"]) for c in chunks]
    idf = _build_idf(corpus_tokens)
    avg_dl = sum(len(d) for d in corpus_tokens) / len(corpus_tokens) if corpus_tokens else 1

    k1, b = 1.5, 0.75
    scores = []

    for i, doc_tokens in enumerate(corpus_tokens):
        dl = len(doc_tokens)
        tf = Counter(doc_tokens)
        score = 0.0
        for qt in set(query_tokens):
            if qt not in tf:
                continue
            freq = tf[qt]
            tf_norm = (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * dl / avg_dl))
            score += idf.get(qt, 0) * tf_norm
        scores.append((score, i))

    scores.sort(key=lambda x: -x[0])
    return [chunks[i] for _, i in scores[:top_k] if _ > 0]


# ─── Answer Generation ─────────────────────────────────────────────────────────

def _build_context(relevant_chunks: list[dict]) -> str:
    parts = []
    for c in relevant_chunks:
        header = f"--- {c['file']} (lines {c['start_line']}-{c['end_line']}) ---"
        parts.append(f"{header}\n{c['text']}")
    return "\n\n".join(parts)


def build_chat_prompt(query: str, relevant_chunks: list[dict], chat_history: list[dict] = None) -> str:
    context = _build_context(relevant_chunks)

    history_text = ""
    if chat_history:
        recent = chat_history[-6:]
        history_text = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in recent
        )
        history_text = f"\nRecent conversation:\n{history_text}\n"

    return f"""You are a knowledgeable assistant that answers questions about a software repository.
Use ONLY the code context provided below to answer. If the context doesn't contain enough information, say so honestly.
Always reference specific file names and line numbers when relevant.
Give clear, concise, technically accurate answers.
{history_text}
Repository code context:
{context}

Question: {query}"""


def answer_with_gpt(query: str, chunks: list[dict], api_key: str, model: str = "gpt-3.5-turbo",
                    chat_history: list[dict] = None) -> dict:
    """Retrieve relevant chunks and generate an answer using OpenAI GPT."""
    import requests

    relevant = retrieve(query, chunks, top_k=6)
    prompt = build_chat_prompt(query, relevant, chat_history)

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are an expert code assistant with deep knowledge of the repository being discussed."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1000,
                "temperature": 0.2,
            },
            timeout=60,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        answer = f"[ERROR] {e}"

    sources = [{"file": c["file"], "lines": f"{c['start_line']}-{c['end_line']}"} for c in relevant]
    return {"answer": answer, "sources": sources}


def answer_with_groq(query: str, chunks: list[dict], api_key: str,
                     model: str = "llama-3.1-70b-versatile",
                     chat_history: list[dict] = None) -> dict:
    """Retrieve relevant chunks and generate an answer using Groq (free Llama)."""
    import requests

    relevant = retrieve(query, chunks, top_k=6)
    prompt = build_chat_prompt(query, relevant, chat_history)

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are an expert code assistant with deep knowledge of the repository being discussed."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1000,
                "temperature": 0.2,
            },
            timeout=60,
        )
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        answer = f"[ERROR] {e}"

    sources = [{"file": c["file"], "lines": f"{c['start_line']}-{c['end_line']}"} for c in relevant]
    return {"answer": answer, "sources": sources}
