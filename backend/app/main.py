import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router


def create_app() -> FastAPI:
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
    frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    allowed_origins = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
    if frontend_origin.strip():
        allowed_origins.add(frontend_origin.strip())

    app = FastAPI(title="YouTube Transcript to Article API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
