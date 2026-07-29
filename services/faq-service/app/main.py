from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import kb, directory, entry, search

app = FastAPI(title="FAQ Service")
app.add_middleware(CORSMiddleware,
                   allow_origins=["http://localhost:5173", "http://localhost:3000"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
for r in (kb.router, directory.router, entry.router, search.router):
    app.include_router(r)


@app.get("/health")
def health(): return {"status": "ok"}
