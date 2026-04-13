from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.settings import settings
from app.routers import auth, entries
from app.services.seed_loader import deterministic_reset_and_seed

app = FastAPI(title="machs_main_api", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.allow_origins.split(",") if x.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(entries.router)

app.mount("/ui", StaticFiles(directory="app/static", html=True), name="ui")


@app.on_event("startup")
def startup_event() -> None:
    if settings.reset_on_start:
        deterministic_reset_and_seed()


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "machs_main_api",
        "revocation_enabled": settings.enable_experimental_revocation,
        "current_epoch": settings.current_epoch,
    }


@app.get("/")
def root() -> dict:
    return {"message": "MACHS2 main api", "ui": "/ui/"}
