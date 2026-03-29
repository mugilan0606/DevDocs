# DevDocs.ai

DevDocs.ai is an AI-powered developer documentation platform that analyzes public GitHub repositories and generates structured project documentation automatically.

It produces a downloadable PDF report, API documentation, setup instructions, test summaries, Mermaid diagrams, and repo-aware chat using a lightweight RAG pipeline.

## Features

- Generate documentation from a GitHub repository URL
- Create a PDF report with architecture and codebase summaries
- Produce API docs, setup guides, and test summaries
- Render Mermaid sequence diagrams
- Ask questions about the analyzed repository with RAG-powered chat
- Support both OpenAI and Groq as LLM providers
- Save user/job history with Google Sign-In and SQLite
- Store generated PDF reports in AWS S3

## Tech Stack

- Frontend: React, Vite
- Backend: Flask, Python
- AI: OpenAI, Groq
- Storage: SQLite, AWS S3
- Auth: Google Sign-In
- PDF generation: ReportLab

## Project Structure

```text
DevDocs/
|- frontend/   # React + Vite client
|- backend/    # Flask API, pipeline, RAG, PDF generation
|- render.yaml # Render deployment config
|- SETUP.md    # Extended setup guide
```

## Quick Start

### Backend

```bash
cd backend
pip install -r requirements.txt
python server.py
```

Backend runs on `http://localhost:5001`.

Create `backend/.env` using `backend/.env.example` and configure:

```env
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
OPENAI_API_KEY=sk-...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
S3_BUCKET=your-bucket-name
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:3000`.

Create `frontend/.env` using `frontend/.env.example`:

```env
VITE_GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
```

## Output Types

- PDF report with architecture summary and generated documentation
- API docs
- Setup instructions
- Test coverage summary
- Mermaid sequence diagram
- Repo-aware chat

## Deployment

- Frontend can be deployed on Vercel
- Backend can be deployed on Render using `render.yaml`
- Generated PDF reports are stored in AWS S3

## Notes

- Groq can be used as a free LLM provider with a personal API key
- SQLite is used for user history and job metadata
- Only public GitHub repositories are supported

For more setup details, see `SETUP.md`.
