from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from phonetic_engine import engine
import os

router = APIRouter(prefix="/admin", tags=["admin"])

# Retrieve keys from environment variables
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "admin-secret-key-change-me")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_admin_key(api_key: str = Security(api_key_header)):
    if not api_key or api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing X-API-Key header.")
    return api_key

@router.post("/reload-aliases")
async def reload_aliases(api_key: str = Depends(verify_admin_key)):
    """Triggers hot-reloading of the aliases JSON configuration."""
    success = engine.reload_aliases()
    if not success:
        raise HTTPException(status_code=500, detail="Failed to reload aliases config.")
    return {"status": "success", "message": "Aliases configuration reloaded successfully."}
