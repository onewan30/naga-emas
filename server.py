from fastapi import FastAPI, APIRouter, HTTPException, Header, Depends
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime
import secrets

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
db_name = os.environ.get('DB_NAME', 'naga_emas_db')
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

# Admin API Key - CHANGE THIS IN PRODUCTION!
ADMIN_API_KEY = os.environ.get('ADMIN_API_KEY', 'naga-emas-secret-key-2024')

# Create the main app without a prefix
app = FastAPI(title="Naga Emas API", version="1.0.0")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# ============== MODELS ==============

class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class StatusCheckCreate(BaseModel):
    client_name: str

# Remote Config Model
class AppConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    app_name: str = "Naga Emas"
    loading_text: str = "Sedang Memuat Halaman"
    mode: str = "webview"  # "game" or "webview"
    webview_url: str = "https://google.com"
    announcement: str = ""
    show_announcement: bool = False
    primary_color: str = "#FFB347"
    secondary_color: str = "#87CEEB"
    background_color: str = "#E8F4FD"
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class AppConfigUpdate(BaseModel):
    app_name: Optional[str] = None
    loading_text: Optional[str] = None
    mode: Optional[str] = None
    webview_url: Optional[str] = None
    announcement: Optional[str] = None
    show_announcement: Optional[bool] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    background_color: Optional[str] = None

# High Score Model
class HighScore(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    player_name: str
    score: int
    created_at: datetime = Field(default_factory=datetime.utcnow)

class HighScoreCreate(BaseModel):
    player_name: str
    score: int


# ============== AUTH DEPENDENCY ==============

async def verify_admin_key(x_admin_key: str = Header(None)):
    """Verify admin API key for protected endpoints"""
    if x_admin_key != ADMIN_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Use X-Admin-Key header."
        )
    return True


# ============== PUBLIC ENDPOINTS ==============

@api_router.get("/")
async def root():
    return {"message": "Naga Emas Game API", "version": "1.0.0"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# GET Config - PUBLIC (app needs to read this)
@api_router.get("/config", response_model=AppConfig)
async def get_app_config():
    """Get current app configuration (Public)"""
    config = await db.app_config.find_one({"_id": "main_config"})
    if not config:
        # Create default config if not exists
        default_config = AppConfig()
        config_dict = default_config.dict()
        config_dict["_id"] = "main_config"
        await db.app_config.insert_one(config_dict)
        return default_config
    return AppConfig(**config)

# GET High Scores - PUBLIC
@api_router.get("/highscores", response_model=List[HighScore])
async def get_high_scores(limit: int = 10):
    """Get top high scores (Public)"""
    highscores = await db.highscores.find().sort("score", -1).limit(limit).to_list(limit)
    return [HighScore(**hs) for hs in highscores]

# POST High Score - PUBLIC (players submit scores)
@api_router.post("/highscores", response_model=HighScore)
async def create_high_score(input: HighScoreCreate):
    """Submit a new high score (Public)"""
    highscore = HighScore(
        player_name=input.player_name,
        score=input.score
    )
    await db.highscores.insert_one(highscore.dict())
    return highscore

@api_router.get("/highscores/top", response_model=HighScore)
async def get_top_score():
    """Get the highest score (Public)"""
    top = await db.highscores.find_one(sort=[("score", -1)])
    if not top:
        return HighScore(player_name="-", score=0)
    return HighScore(**top)


# ============== PROTECTED ENDPOINTS (Require API Key) ==============

@api_router.put("/config", response_model=AppConfig)
async def update_app_config(
    config_update: AppConfigUpdate,
    authenticated: bool = Depends(verify_admin_key)
):
    """Update app configuration (Protected - requires X-Admin-Key header)"""
    update_data = {k: v for k, v in config_update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.utcnow()
    
    result = await db.app_config.find_one_and_update(
        {"_id": "main_config"},
        {"$set": update_data},
        return_document=True
    )
    
    if not result:
        # Create new config if not exists
        new_config = AppConfig(**update_data)
        config_dict = new_config.dict()
        config_dict["_id"] = "main_config"
        await db.app_config.insert_one(config_dict)
        return new_config
    
    return AppConfig(**result)

@api_router.delete("/highscores/{score_id}")
async def delete_high_score(
    score_id: str,
    authenticated: bool = Depends(verify_admin_key)
):
    """Delete a high score (Protected - requires X-Admin-Key header)"""
    result = await db.highscores.delete_one({"id": score_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Score not found")
    return {"message": "Score deleted successfully"}

@api_router.delete("/highscores")
async def clear_all_high_scores(
    authenticated: bool = Depends(verify_admin_key)
):
    """Clear all high scores (Protected - requires X-Admin-Key header)"""
    result = await db.highscores.delete_many({})
    return {"message": f"Deleted {result.deleted_count} scores"}


# ============== STATUS ENDPOINTS ==============

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.dict()
    status_obj = StatusCheck(**status_dict)
    await db.status_checks.insert_one(status_obj.dict())
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find().to_list(1000)
    return [StatusCheck(**status_check) for status_check in status_checks]


# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
