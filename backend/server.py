import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.cors import CORSMiddleware

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="Playwright Web Crawler Agent")
api_router = APIRouter(prefix="/api")

# ── In-memory session storage ──────────────────────────────────────────────────
sessions: Dict[str, dict] = {}
active_crawlers: Dict[str, object] = {}
ws_connections: Dict[str, WebSocket] = {}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ── Models ─────────────────────────────────────────────────────────────────────
class CrawlStartRequest(BaseModel):
    url: str
    username: Optional[str] = None
    password: Optional[str] = None
    max_pages: int = Field(default=50, ge=1, le=200)
    max_depth: int = Field(default=3, ge=1, le=5)


class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str


# ── Existing status routes ─────────────────────────────────────────────────────
@api_router.get("/")
async def root():
    return {"message": "Playwright Web Crawler Agent API"}


@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_obj = StatusCheck(**input.model_dump())
    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()
    await db.status_checks.insert_one(doc)
    return status_obj


@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    checks = await db.status_checks.find({}, {"_id": 0}).to_list(1000)
    for c in checks:
        if isinstance(c['timestamp'], str):
            c['timestamp'] = datetime.fromisoformat(c['timestamp'])
    return checks


# ── Crawler routes ─────────────────────────────────────────────────────────────
@api_router.post("/crawl/start")
async def start_crawl(req: CrawlStartRequest):
    session_id = str(uuid.uuid4())

    sessions[session_id] = {
        "session_id": session_id,
        "status": "running",
        "url": req.url,
        "start_time": datetime.now(timezone.utc).isoformat(),
        "end_time": None,
        "events": [],
        "pages": [],
        "stats": {"total_pages": 0, "errors": 0, "auth_required": 0},
    }

    credentials = None
    if req.username and req.password:
        credentials = {"username": req.username, "password": req.password}

    task = asyncio.create_task(
        _run_crawl(session_id, req.url, credentials, req.max_pages, req.max_depth)
    )
    active_crawlers[session_id] = task

    return {"session_id": session_id, "status": "started"}


async def _run_crawl(session_id: str, url: str, credentials, max_pages: int, max_depth: int):
    """Background crawl task."""
    from crawler import WebCrawler

    crawler = WebCrawler(session_id)

    async def ws_callback(event: dict):
        if session_id in sessions:
            sessions[session_id]['events'].append(event)
            evtype = event.get('event', '')
            if evtype == 'page_visited':
                sessions[session_id]['stats']['total_pages'] += 1
                sessions[session_id]['pages'].append(event['data'])
            elif evtype == 'page_error':
                sessions[session_id]['stats']['errors'] += 1
            elif evtype in ('crawl_complete', 'crawl_error'):
                sessions[session_id]['status'] = 'completed' if evtype == 'crawl_complete' else 'failed'
                sessions[session_id]['end_time'] = datetime.now(timezone.utc).isoformat()
        ws = ws_connections.get(session_id)
        if ws:
            try:
                await ws.send_json(event)
            except Exception as e:
                logger.warning(f"WS send error for {session_id}: {e}")

    try:
        await crawler.crawl(url, credentials, max_pages, max_depth, ws_callback)
    except Exception as e:
        logger.error(f"Crawl task error {session_id}: {e}")
        await ws_callback({
            "event": "crawl_error",
            "data": {"error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}
        })
    finally:
        await crawler.close()
        active_crawlers.pop(session_id, None)


@api_router.get("/crawl/{session_id}/status")
async def get_crawl_status(session_id: str):
    if session_id not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    session = sessions[session_id]
    return {
        "session_id": session_id,
        "status": session["status"],
        "stats": session["stats"],
        "start_time": session["start_time"],
        "end_time": session["end_time"],
    }


@api_router.get("/crawl/{session_id}/report")
async def get_crawl_report(session_id: str):
    if session_id not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    session = sessions[session_id]
    return {
        "session_id": session_id,
        "url": session["url"],
        "status": session["status"],
        "stats": session["stats"],
        "start_time": session["start_time"],
        "end_time": session["end_time"],
        "pages": session["pages"],
    }


@api_router.post("/crawl/{session_id}/stop")
async def stop_crawl(session_id: str):
    if session_id not in sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    task = active_crawlers.get(session_id)
    if task:
        task.cancel()
        active_crawlers.pop(session_id, None)

    if session_id in sessions:
        sessions[session_id]['status'] = 'stopped'
        sessions[session_id]['end_time'] = datetime.now(timezone.utc).isoformat()

    ws = ws_connections.get(session_id)
    if ws:
        try:
            await ws.send_json({
                "event": "crawl_stopped",
                "data": {"message": "Crawl stopped by user"}
            })
        except Exception:
            pass

    return {"session_id": session_id, "status": "stopped"}


# ── WebSocket endpoint ─────────────────────────────────────────────────────────
@app.websocket("/api/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    ws_connections[session_id] = websocket
    logger.info(f"WebSocket connected: {session_id}")

    try:
        # Replay past events so UI is up-to-date on reconnect
        if session_id in sessions:
            for event in sessions[session_id].get('events', []):
                try:
                    await websocket.send_json(event)
                except Exception:
                    break

        # Keep connection open until client disconnects
        while True:
            try:
                msg = await websocket.receive()
                if msg.get('type') == 'websocket.disconnect':
                    break
            except WebSocketDisconnect:
                break
            except Exception:
                break
    finally:
        ws_connections.pop(session_id, None)
        logger.info(f"WebSocket disconnected: {session_id}")


# ── App assembly ───────────────────────────────────────────────────────────────
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
