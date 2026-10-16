# AI Architecture Guardian: web app

Run the back end and the front end in two terminals.

## Requirements

- Python 3.10+ with the project's packages (`pip install -r requirements.txt` from the repository root)
- Node.js 20+ and npm
- A knowledge base built once from the repository root: `python scripts/build_kb.py --manifest artifacts/gnn_embeddings_v3.json`
- Optional: `GROQ_API_KEY` in `.env` for the chatbot, and `GITHUB_TOKEN` for a higher GitHub rate limit on live PR analysis

## Start

Terminal 1, from the repository root (back end on port 8000):

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn api.main:app --port 8000
```

Terminal 2, from this folder (front end on port 5173):

```powershell
npm install
npm run dev
```

Open http://localhost:5173. The dev server forwards `/api` requests to port 8000, so the back end must be running.

## Production build

```powershell
npm run build
```

The output is in `dist/`. Serve it with any static host that forwards `/api` to the back end.
