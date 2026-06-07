"""Dashboard routes — static file serving handled in main.py."""
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()
STATIC_DIR = Path(__file__).parent.parent.parent / "static"


@router.get("/")
async def serve_dashboard():
    """Serve the dashboard index.html."""
    return FileResponse(STATIC_DIR / "index.html")
