"""
server.py — DevDocs.ai Flask API
Endpoints:
  POST /api/generate          { repo_url, model, api_key, provider, user_id }
  GET  /api/status/<job_id>   → { status, logs, has_pdf }
  GET  /api/report/<job_id>   → redirect to S3 presigned URL (or local fallback)
  GET  /api/jobs              → all in-memory jobs
  GET  /api/user/jobs/<uid>   → jobs for a logged-in user (SQLite)
  POST /api/auth/google       { token } → verify Google ID token, return user info
  GET  /api/health
"""

import os
import re
import uuid
import shutil
import sqlite3
import threading
import traceback
import importlib.util
import subprocess

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

from datetime import datetime
from flask import Flask, jsonify, request, send_file, Response
from flask_cors import CORS

app = Flask(__name__)
_allowed_origins = os.getenv("CORS_ORIGINS", "").strip()
CORS(app, origins=[o.strip().rstrip("/") for o in _allowed_origins.split(",") if o.strip()] or "*")

JOBS_DIR = os.path.join(os.path.dirname(__file__), "jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

jobs: dict = {}

# ─── S3 setup ─────────────────────────────────────────────────────────────────
try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    from botocore.config import Config
    _s3 = boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        config=Config(signature_version="s3v4"),
    )
    S3_BUCKET = os.getenv("S3_BUCKET", "")
    # Quick connectivity check
    _s3.head_bucket(Bucket=S3_BUCKET)
    S3_OK = True
    print(f"[server] S3 connected — PDFs will be stored in bucket '{S3_BUCKET}'.")
except Exception as e:
    _s3 = None
    S3_OK = False
    S3_BUCKET = ""
    print(f"[server] S3 not available ({e}) — falling back to local PDF storage.")


def s3_upload(local_path: str, job_id: str, filename: str) -> str:
    """Upload a file to S3 and return the S3 key."""
    key = f"reports/{job_id}/{filename}"
    _s3.upload_file(local_path, S3_BUCKET, key, ExtraArgs={"ContentType": "application/pdf"})
    return key


def s3_stream(key: str, filename: str, download: bool = False):
    """Stream a file from S3 directly through Flask (avoids presigned URL auth issues)."""
    import io
    from flask import Response
    obj = _s3.get_object(Bucket=S3_BUCKET, Key=key)
    data = obj["Body"].read()
    disposition = f'attachment; filename="{filename}"' if download else f'inline; filename="{filename}"'
    return Response(
        data,
        mimetype="application/pdf",
        headers={"Content-Disposition": disposition},
    )


def s3_delete(key: str):
    """Delete a file from S3 (best-effort)."""
    try:
        _s3.delete_object(Bucket=S3_BUCKET, Key=key)
    except Exception as e:
        print(f"[s3] delete error: {e}")


# ─── SQLite setup ──────────────────────────────────────────────────────────────
DB_PATH = os.path.join(os.path.dirname(__file__), "devdocs.db")


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id       TEXT PRIMARY KEY,
                email         TEXT,
                name          TEXT,
                picture       TEXT,
                openai_api_key TEXT
            )
        """)
        # Add openai_api_key column if upgrading from older schema
        try:
            conn.execute("ALTER TABLE users ADD COLUMN openai_api_key TEXT")
        except Exception:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_history (
                job_id     TEXT PRIMARY KEY,
                user_id    TEXT,
                repo_url   TEXT,
                status     TEXT,
                provider   TEXT,
                created_at TEXT,
                has_pdf    INTEGER DEFAULT 0,
                s3_key     TEXT,
                tab_data   TEXT
            )
        """)
        # Add columns if upgrading from older schema
        for col in ["s3_key TEXT", "tab_data TEXT"]:
            try:
                conn.execute(f"ALTER TABLE job_history ADD COLUMN {col}")
            except Exception:
                pass
        conn.commit()


_init_db()
print("[server] SQLite database ready — user history enabled.")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def parse_github_url(url: str):
    pattern = r"https?://github\.com/([^/]+)/([^/]+)(?:/(?:tree|blob)/[^/]+/?(.*))?"
    m = re.match(pattern, url.rstrip("/"))
    if not m:
        return url, ""
    owner, repo, subpath = m.group(1), m.group(2), m.group(3) or ""
    repo = repo.removesuffix(".git")
    return f"https://github.com/{owner}/{repo}.git", subpath


def job_dir(job_id: str) -> str:
    d = os.path.join(JOBS_DIR, job_id)
    os.makedirs(d, exist_ok=True)
    return d


def log(job_id: str, msg: str):
    ts   = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    jobs[job_id]["logs"].append(line)
    print(line)


def load_module(name: str, src_dir: str):
    path = os.path.join(src_dir, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"{name}_{uuid.uuid4().hex[:6]}", path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def save_job_to_db(job: dict):
    """Persist a job record to SQLite (only if user is logged in)."""
    if not job.get("user_id"):
        return
    try:
        import json as _json
        has_pdf = bool(job.get("s3_key") or (job.get("pdf_path") and os.path.exists(job.get("pdf_path") or "")))
        with _get_db() as conn:
            conn.execute("""
                INSERT INTO job_history (job_id, user_id, repo_url, status, provider, created_at, has_pdf, s3_key, tab_data)
                VALUES (:job_id, :user_id, :repo_url, :status, :provider, :created_at, :has_pdf, :s3_key, :tab_data)
                ON CONFLICT(job_id) DO UPDATE SET
                    status   = excluded.status,
                    has_pdf  = excluded.has_pdf,
                    s3_key   = excluded.s3_key,
                    tab_data = excluded.tab_data
            """, {
                "job_id":     job["job_id"],
                "user_id":    job["user_id"],
                "repo_url":   job["repo_url"],
                "status":     job["status"],
                "provider":   job.get("provider", "gpt"),
                "created_at": job["created_at"],
                "has_pdf":    1 if has_pdf else 0,
                "s3_key":     job.get("s3_key"),
                "tab_data":   _json.dumps(job.get("tab_data") or {}),
            })
            conn.commit()
    except Exception as e:
        print(f"[sqlite] save error: {e}")


# ─── Pipeline ─────────────────────────────────────────────────────────────────

def run_pipeline(job_id: str, repo_url: str, model: str):
    jdir         = job_dir(job_id)
    original_cwd = os.getcwd()
    os.chdir(jdir)
    src_dir = os.path.abspath(os.path.dirname(__file__))

    try:
        jobs[job_id]["status"] = "running"
        provider = jobs[job_id].get("provider", "gpt")

        fonts_src = os.path.join(src_dir, "fonts")
        if os.path.exists(fonts_src):
            shutil.copytree(fonts_src, os.path.join(jdir, "fonts"), dirs_exist_ok=True)
        os.makedirs(os.path.join(jdir, "TimePass"),       exist_ok=True)

        # ── Step 1: Clone ──────────────────────────────────────────────────────
        clone_url, subfolder = parse_github_url(repo_url)
        log(job_id, f"Cloning {clone_url} ...")
        local_dir = os.path.join(jdir, "code_repo")
        if os.path.exists(local_dir):
            shutil.rmtree(local_dir)
        result = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, local_dir],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "not found" in stderr.lower() or "repository" in stderr.lower():
                raise RuntimeError(
                    f"Repository not found: {clone_url}\n"
                    "Please check:\n"
                    "  • The URL is correct (no typos or extra words)\n"
                    "  • The repository is public\n"
                    "  • Example: https://github.com/owner/repo-name"
                )
            elif "could not resolve host" in stderr.lower():
                raise RuntimeError("Network error: could not reach GitHub. Check your internet connection.")
            elif "authentication" in stderr.lower() or "credential" in stderr.lower():
                raise RuntimeError("Authentication required: this repository is private. Only public repos are supported.")
            else:
                raise RuntimeError(f"git clone failed: {stderr}")
        if subfolder:
            target = os.path.join(local_dir, subfolder)
            if not os.path.exists(target):
                raise RuntimeError(f"Subfolder '{subfolder}' not found in repo.")
            local_dir = target
            log(job_id, f"Focusing on subfolder: {subfolder}")
        log(job_id, "Clone complete.")

        # ── Step 2: Directory structure ────────────────────────────────────────
        log(job_id, "Parsing directory structure ...")
        dsc = load_module("directory_structure_creator", src_dir)
        directory_json = dsc.list_directory_tree_json(local_dir)
        log(job_id, "Directory structure parsed.")

        # ── Step 3: LLM querying ───────────────────────────────────────────────
        if provider == "groq":
            log(job_id, f"Using Groq/Llama (model={model}) ...")
            gq_free = load_module("groq_querier", src_dir)
            gq_free.GROQ_MODEL = model
            gq_free.GROQ_API_KEY = jobs[job_id].get("api_key", "")
            directory_json = gq_free.generate_docs_for_repo(
                directory_json, repo_dir=local_dir,
                log_fn=lambda msg: log(job_id, msg),
            )
            dir_string = dsc.get_finalized_text_string(local_dir, directory_json)
            readme     = _read_readme(local_dir)
            log(job_id, "Generating repo-level analysis via Groq ...")
            overview     = gq_free.generate_repo_overview(local_dir, dir_string, readme)
            architecture = gq_free.generate_architecture_summary(dir_string, "")
            dependencies = gq_free.generate_dependency_analysis(local_dir)
            entry_points = gq_free.generate_entry_points(local_dir, dir_string)
            code_quality = gq_free.generate_code_quality_notes(local_dir)
        else:
            log(job_id, f"Using GPT (model={model}) ...")
            os.environ["OPENAI_API_KEY"] = jobs[job_id].get("api_key", "")
            os.environ["OPENAI_MODEL"]   = model
            gq = load_module("gpt_querier", src_dir)
            directory_json = gq.generate_docs_for_repo(
                directory_json, repo_dir=local_dir,
                log_fn=lambda msg: log(job_id, msg), max_workers=4,
            )
            dir_string = dsc.get_finalized_text_string(local_dir, directory_json)
            readme     = _read_readme(local_dir)
            log(job_id, "Generating repo-level analysis via GPT ...")
            overview     = gq.generate_repo_overview(local_dir, dir_string, readme)
            architecture = gq.generate_architecture_summary(dir_string, "")
            dependencies = gq.generate_dependency_analysis(local_dir)
            entry_points = gq.generate_entry_points(local_dir, dir_string)
            code_quality = gq.generate_code_quality_notes(local_dir)

        log(job_id, "All analysis complete.")

        # ── Step 4b: Generate tab content ─────────────────────────────────────
        log(job_id, "Generating diagrams and tab content ...")
        try:
            import sys as _sys
            _sys.path.insert(0, src_dir)
            from tab_generators import (
                generate_api_docs,
                generate_sequence_mermaid, generate_setup_instructions,
                generate_test_summary,
            )

            # Pick the right query function based on provider
            if provider == "groq":
                def _qfn(prompt, max_tokens=800):
                    return gq_free.query_groq(prompt)
            else:
                def _qfn(prompt, max_tokens=800):
                    return gq.query_gpt(prompt, max_tokens=max_tokens)

            tab_data = {}

            log(job_id, "  → API docs ...")
            tab_data["api_docs"] = generate_api_docs(local_dir, dir_string, _qfn)

            log(job_id, "  → Sequence diagram ...")
            tab_data["sequence_mermaid"] = generate_sequence_mermaid(local_dir, dir_string, _qfn)

            log(job_id, "  → Setup instructions ...")
            tab_data["setup"] = generate_setup_instructions(local_dir, dir_string, _qfn)

            log(job_id, "  → Test coverage summary ...")
            tab_data["test_summary"] = generate_test_summary(local_dir, dir_string, _qfn)

            jobs[job_id]["tab_data"] = tab_data
            log(job_id, "Tab content generated.")
        except Exception as _te:
            log(job_id, f"[WARN] Tab generation failed: {_te}")
            jobs[job_id]["tab_data"] = {}

        # ── Step 5: PDF ────────────────────────────────────────────────────────
        log(job_id, "Generating PDF report ...")
        real_repo_name = repo_url.rstrip("/").split("/")[-1]
        real_repo_name = re.sub(r"\.git$", "", real_repo_name)
        pdf_path = os.path.join(jdir, "DevDocs_Report.pdf")
        rg = load_module("report_generator", src_dir)
        rg.generate_report(pdf_path, local_dir, gpt_data={
            "repo_name":      real_repo_name,
            "overview":       overview,
            "architecture":   architecture,
            "dependencies":   dependencies,
            "entry_points":   entry_points,
            "code_quality":   code_quality,
            "directory_json": directory_json,
            "dir_string":     dir_string,
        })
        log(job_id, "PDF saved locally.")

        # ── Step 6: Upload to S3 ───────────────────────────────────────────────
        s3_key = None
        if S3_OK:
            try:
                log(job_id, "Uploading PDF to S3 ...")
                s3_key = s3_upload(pdf_path, job_id, f"{real_repo_name}_DevDocs.pdf")
                jobs[job_id]["s3_key"] = s3_key
                # Delete local PDF after successful S3 upload to save disk space
                os.remove(pdf_path)
                log(job_id, f"PDF uploaded to S3 and local copy removed.")
            except Exception as e:
                log(job_id, f"[WARN] S3 upload failed ({e}), keeping local PDF.")

        # ── Step 7: Build RAG index ────────────────────────────────────────────
        log(job_id, "Building RAG index for chat ...")
        try:
            rag = load_module("rag_engine", src_dir)
            rag_chunks = rag.chunk_repository(local_dir)
            jobs[job_id]["rag_chunks"] = rag_chunks
            if "tab_data" not in jobs[job_id] or not isinstance(jobs[job_id]["tab_data"], dict):
                jobs[job_id]["tab_data"] = {}
            jobs[job_id]["tab_data"]["rag_chunks"] = rag_chunks
            log(job_id, f"RAG index built ({len(rag_chunks)} chunks from repo).")
        except Exception as _re:
            log(job_id, f"[WARN] RAG index failed: {_re}")
            jobs[job_id]["rag_chunks"] = []

        # ── Cleanup cloned repo ────────────────────────────────────────────────
        repo_root = os.path.join(jdir, "code_repo")
        if os.path.exists(repo_root):
            shutil.rmtree(repo_root, ignore_errors=True)
            log(job_id, "Cloned repo deleted (storage cleanup).")

        jobs[job_id]["status"]   = "done"
        jobs[job_id]["pdf_path"] = pdf_path if not s3_key else None
        save_job_to_db(jobs[job_id])

    except Exception:
        err = traceback.format_exc()
        log(job_id, f"[ERROR] {err}")
        jobs[job_id]["status"] = "error"
        save_job_to_db(jobs[job_id])
    finally:
        os.chdir(original_cwd)


def _read_readme(repo_dir: str) -> str:
    for name in ["README.md", "README.txt", "readme.md"]:
        p = os.path.join(repo_dir, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8", errors="ignore") as f:
                return f.read(3000)
    return ""


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/api/generate", methods=["POST"])
def generate():
    data     = request.get_json(force=True)
    repo_url = (data.get("repo_url") or "").strip()
    provider = (data.get("provider") or "gpt").strip()
    api_key  = (data.get("api_key") or "").strip()
    model    = (data.get("model") or ("gpt-3.5-turbo" if provider == "gpt" else "llama-3.1-70b-versatile")).strip()
    user_id  = (data.get("user_id") or "").strip()

    if not repo_url:
        return jsonify({"error": "repo_url is required"}), 400
    if "github.com" not in repo_url:
        return jsonify({"error": "Please provide a GitHub URL"}), 400

    # Validate the URL looks like a real repo path: github.com/owner/repo
    import re as _re
    _clean = repo_url.rstrip("/").split("?")[0]  # strip query strings
    _match = _re.search(r"github\.com/([^/]+)/([^/]+)", _clean)
    if not _match:
        return jsonify({"error": "URL must be in the format: https://github.com/owner/repo"}), 400
    _owner, _repo = _match.group(1), _match.group(2)
    _repo = _re.sub(r"\.git$", "", _repo)
    # Warn about obviously wrong repo names (too long, has spaces, etc.)
    if len(_repo) > 100 or " " in _repo:
        return jsonify({"error": f"Repo name '{_repo}' looks invalid. Please check the URL."}), 400
    if provider == "gpt" and not api_key and user_id:
        try:
            with _get_db() as conn:
                row = conn.execute(
                    "SELECT openai_api_key FROM users WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            api_key = ((row["openai_api_key"] if row else "") or "").strip()
        except Exception:
            api_key = ""

    if provider == "gpt" and not api_key:
        api_key = (os.getenv("OPENAI_API_KEY") or "").strip()

    if provider == "gpt" and not api_key:
        return jsonify({"error": "OpenAI API key is required for GPT mode"}), 400

    if provider == "groq" and not api_key:
        api_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if provider == "groq" and not api_key:
        return jsonify({"error": "Groq API key is required. Get a free one at console.groq.com"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "job_id":     job_id,
        "status":     "queued",
        "logs":       [],
        "created_at": datetime.now().isoformat(),
        "repo_url":   repo_url,
        "provider":   provider,
        "model":      model,
        "api_key":    api_key,
        "user_id":    user_id,
        "pdf_path":   None,
        "s3_key":     None,
        "tab_data":   {},
    }

    threading.Thread(target=run_pipeline, args=(job_id, repo_url, model), daemon=True).start()
    return jsonify({"job_id": job_id}), 202


@app.route("/api/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        with _get_db() as conn:
            row = conn.execute("SELECT * FROM job_history WHERE job_id = ?", (job_id,)).fetchone()
        if row:
            # Check if PDF exists — either on S3 or locally
            has_pdf = bool(row["s3_key"]) or os.path.exists(
                os.path.join(JOBS_DIR, job_id, "DevDocs_Report.pdf")
            )
            return jsonify({
                "job_id":   job_id,
                "status":   row["status"],
                "logs":     [],
                "repo_url": row["repo_url"],
                "provider": row["provider"],
                "has_pdf":  has_pdf,
            })
        return jsonify({"error": "Job not found"}), 404

    has_pdf = (
        bool(job.get("s3_key")) or
        bool(job.get("pdf_path") and os.path.exists(job.get("pdf_path") or ""))
    )
    return jsonify({
        "job_id":   job_id,
        "status":   job["status"],
        "logs":     job["logs"],
        "repo_url": job["repo_url"],
        "provider": job.get("provider", "gpt"),
        "has_pdf":  has_pdf,
    })


@app.route("/api/report/<job_id>")
def report(job_id):
    dl = request.args.get("dl") == "1"

    # Look up job — check memory first, then SQLite
    job    = jobs.get(job_id)
    s3_key = job.get("s3_key") if job else None
    repo_url = job.get("repo_url", "") if job else ""

    if not s3_key:
        with _get_db() as conn:
            row = conn.execute("SELECT * FROM job_history WHERE job_id = ?", (job_id,)).fetchone()
        if row:
            s3_key   = row["s3_key"]
            repo_url = row["repo_url"]

    repo_name = repo_url.rstrip("/").split("/")[-1]
    repo_name = re.sub(r"\.git$", "", repo_name) or "DevDocs_Report"
    safe_name = re.sub(r"[^\w\-.]", "_", repo_name)
    filename  = f"{safe_name}_DevDocs.pdf"

    # ── Serve from S3 by streaming through Flask ──────────────────────────────
    if s3_key and S3_OK:
        try:
            return s3_stream(s3_key, filename, download=dl)
        except Exception as e:
            print(f"[s3] stream error: {e}")

    # ── Fallback: serve from local disk ───────────────────────────────────────
    pdf_path = os.path.join(JOBS_DIR, job_id, "DevDocs_Report.pdf")
    if os.path.exists(pdf_path):
        return send_file(pdf_path, mimetype="application/pdf",
                         as_attachment=dl, download_name=filename)

    return jsonify({"error": "PDF not found"}), 404


@app.route("/api/jobs")
def list_jobs():
    return jsonify([
        {"job_id": j["job_id"], "status": j["status"],
         "repo_url": j["repo_url"], "created_at": j["created_at"],
         "provider": j.get("provider", "gpt")}
        for j in sorted(jobs.values(), key=lambda x: x["created_at"], reverse=True)
    ])


@app.route("/api/user/jobs/<user_id>")
def user_jobs(user_id):
    """Return all jobs for a logged-in user from SQLite."""
    try:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM job_history WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
                (user_id,)
            ).fetchall()
        records = []
        for r in rows:
            has_pdf = bool(r["s3_key"]) or os.path.exists(
                os.path.join(JOBS_DIR, r["job_id"], "DevDocs_Report.pdf")
            )
            records.append({
                "job_id":     r["job_id"],
                "user_id":    r["user_id"],
                "repo_url":   r["repo_url"],
                "status":     r["status"],
                "provider":   r["provider"],
                "created_at": r["created_at"],
                "has_pdf":    has_pdf,
            })
        return jsonify(records)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/auth/google", methods=["POST"])
def auth_google():
    token = (request.get_json(force=True) or {}).get("token", "")
    if not token:
        return jsonify({"error": "No token provided"}), 400
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as g_requests
        CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
        info = id_token.verify_oauth2_token(token, g_requests.Request(), CLIENT_ID)
        user = {
            "user_id": info["sub"],
            "email":   info.get("email", ""),
            "name":    info.get("name", ""),
            "picture": info.get("picture", ""),
        }
        with _get_db() as conn:
            conn.execute("""
                INSERT INTO users (user_id, email, name, picture)
                VALUES (:user_id, :email, :name, :picture)
                ON CONFLICT(user_id) DO UPDATE SET
                    email   = excluded.email,
                    name    = excluded.name,
                    picture = excluded.picture
            """, user)
            conn.commit()
        return jsonify(user)
    except Exception as e:
        return jsonify({"error": f"Token verification failed: {e}"}), 401


@app.route("/api/job/<job_id>", methods=["DELETE"])
def delete_job(job_id):
    """Delete a job from history and its PDF from S3/disk."""
    user_id = request.args.get("user_id", "")
    try:
        with _get_db() as conn:
            row = conn.execute("SELECT * FROM job_history WHERE job_id = ? AND user_id = ?",
                               (job_id, user_id)).fetchone()
        if not row:
            return jsonify({"error": "Job not found or not yours"}), 404

        # Delete from S3
        if row["s3_key"] and S3_OK:
            s3_delete(row["s3_key"])

        # Delete local PDF if it exists
        pdf_path = os.path.join(JOBS_DIR, job_id, "DevDocs_Report.pdf")
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

        # Delete from SQLite
        with _get_db() as conn:
            conn.execute("DELETE FROM job_history WHERE job_id = ?", (job_id,))
            conn.commit()

        # Remove from in-memory store
        jobs.pop(job_id, None)

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/user/<user_id>/apikey", methods=["POST"])
def save_api_key(user_id):
    """Save the OpenAI API key for a user (encrypted at rest is ideal but out of scope here)."""
    data    = request.get_json(force=True) or {}
    api_key = (data.get("api_key") or "").strip()
    try:
        with _get_db() as conn:
            cursor = conn.execute(
                "UPDATE users SET openai_api_key = ? WHERE user_id = ?",
                (api_key, user_id),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return jsonify({"error": "User not found"}), 404
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/user/<user_id>/apikey", methods=["GET"])
def get_api_key(user_id):
    """Retrieve the saved OpenAI API key for a user."""
    try:
        with _get_db() as conn:
            row = conn.execute("SELECT openai_api_key FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row and row["openai_api_key"]:
            return jsonify({"api_key": row["openai_api_key"]})
        return jsonify({"api_key": ""})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tabs/<job_id>")
def get_tabs(job_id):
    """Return generated tab content (diagrams, docs, etc.) for a job."""
    import json as _json

    # Check in-memory first
    job = jobs.get(job_id)
    if job and job.get("tab_data"):
        tab_data = job["tab_data"]
    else:
        # Fall back to SQLite
        with _get_db() as conn:
            row = conn.execute("SELECT tab_data FROM job_history WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return jsonify({"error": "Job not found"}), 404
        try:
            tab_data = _json.loads(row["tab_data"] or "{}")
        except Exception:
            tab_data = {}

    return jsonify(tab_data)


@app.route("/api/chat/<job_id>", methods=["POST"])
def chat(job_id):
    """RAG-powered chat: answer questions about a repo using its indexed chunks."""
    import json as _json

    data      = request.get_json(force=True) or {}
    query     = (data.get("query") or "").strip()
    provider  = (data.get("provider") or "gpt").strip()
    api_key   = (data.get("api_key") or "").strip()
    model     = (data.get("model") or "gpt-3.5-turbo").strip()
    history   = data.get("history") or []

    if not query:
        return jsonify({"error": "query is required"}), 400

    # Load RAG chunks — check in-memory first, then SQLite
    rag_chunks = None
    job = jobs.get(job_id)
    if job and job.get("rag_chunks"):
        rag_chunks = job["rag_chunks"]
    else:
        try:
            with _get_db() as conn:
                row = conn.execute("SELECT tab_data FROM job_history WHERE job_id = ?", (job_id,)).fetchone()
            if row:
                td = _json.loads(row["tab_data"] or "{}")
                rag_chunks = td.get("rag_chunks")
        except Exception:
            pass

    if not rag_chunks:
        return jsonify({"error": "No RAG index found for this job. Re-generate the report to enable chat."}), 404

    src_dir = os.path.abspath(os.path.dirname(__file__))
    rag = load_module("rag_engine", src_dir)

    try:
        if provider == "groq":
            if not api_key:
                api_key = (os.getenv("GROQ_API_KEY") or "").strip()
            if not api_key:
                return jsonify({"error": "Groq API key required for chat."}), 400
            result = rag.answer_with_groq(query, rag_chunks, api_key=api_key, model=model, chat_history=history)
        else:
            if not api_key:
                user_id = (data.get("user_id") or "").strip()
                if user_id:
                    try:
                        with _get_db() as conn:
                            urow = conn.execute("SELECT openai_api_key FROM users WHERE user_id = ?", (user_id,)).fetchone()
                        api_key = ((urow["openai_api_key"] if urow else "") or "").strip()
                    except Exception:
                        pass
                if not api_key:
                    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
            if not api_key:
                return jsonify({"error": "OpenAI API key required for GPT chat."}), 400
            result = rag.answer_with_gpt(query, rag_chunks, api_key=api_key, model=model, chat_history=history)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def health():
    return jsonify({"ok": True, "db": "sqlite", "s3": S3_OK, "s3_bucket": S3_BUCKET if S3_OK else None})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")