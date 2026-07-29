from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth, users, internal, knowledge_base, directory, document, search

app = FastAPI(title="KB API")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(internal.router)
app.include_router(knowledge_base.router)
app.include_router(directory.router)
app.include_router(document.router)
app.include_router(search.router)

@app.get("/health")
def health(): return {"status": "ok"}
