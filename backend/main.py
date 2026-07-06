import asyncio
import os
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import List
import uvicorn
from phonetic_engine import engine

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IndicSync")

app = FastAPI(
    title="Indic Phonetic Similarity API",
    description="Production-grade phonetic similarity engine for Indic names and entities."
)

# Dedicated thread pool executor for CPU-bound computations to prevent event loop and default pool starvation
executor = ThreadPoolExecutor(max_workers=min(32, (os.cpu_count() or 1) + 4))

# CORS configuration
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
if allowed_origins_env:
    origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
    logger.info(f"CORS: Allowed origins configured: {origins}")
else:
    origins = ["*"]
    logger.warning("CORS: ALLOWED_ORIGINS not set. Falling back to wildcard '*' (Development only).")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True if origins != ["*"] else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ComparisonRequest(BaseModel):
    name1: str = Field(..., min_length=1, max_length=100, description="First name or place entity")
    name2: str = Field(..., min_length=1, max_length=100, description="Second name or place entity")
    enable_aliases: bool = Field(True, description="Enable administrative/historical alias synonym matching")

class BatchRequest(BaseModel):
    pairs: List[ComparisonRequest] = Field(..., max_items=1000, description="List of comparison pairs")

def validate_input(name: str, identifier: str):
    """Performs validation checks on input names."""
    trimmed = name.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail=f"{identifier} cannot be empty or contain only whitespaces.")
    
    # Check if the string contains only non-Latin characters (which normalize to empty string)
    normalized = engine.normalize(trimmed)
    if not normalized:
        raise HTTPException(
            status_code=400,
            detail=f"Input '{name}' for {identifier} contains no valid Latin characters. Please use English transliterations."
        )

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/compare")
async def compare_names(request: ComparisonRequest):
    # 1. Input Validation
    validate_input(request.name1, "First Name / Place")
    validate_input(request.name2, "Second Name / Place")
    
    start_time = time.perf_counter()
    try:
        # 2. Concurrency offloading: run CPU-bound phonetic comparison in dedicated ThreadPoolExecutor
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            executor,
            engine.compare,
            request.name1,
            request.name2,
            request.enable_aliases
        )
        duration_ms = (time.perf_counter() - start_time) * 1000
        result["processing_time_ms"] = round(duration_ms, 3)
        logger.info(f"Comparison of '{request.name1}' and '{request.name2}' completed in {duration_ms:.2f}ms")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error comparing '{request.name1}' and '{request.name2}': {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error during processing")

@app.post("/compare-batch")
async def compare_batch(request: BatchRequest):
    if not request.pairs:
        raise HTTPException(status_code=400, detail="Batch request must contain at least one comparison pair.")

    # Validate all inputs upfront
    for i, pair in enumerate(request.pairs):
        validate_input(pair.name1, f"Pair {i+1} Name 1")
        validate_input(pair.name2, f"Pair {i+1} Name 2")

    start_time = time.perf_counter()
    loop = asyncio.get_running_loop()
    
    # Run comparisons concurrently in bounded threadpool
    tasks = [
        loop.run_in_executor(
            executor,
            engine.compare,
            pair.name1,
            pair.name2,
            pair.enable_aliases
        )
        for pair in request.pairs
    ]
    try:
        results = await asyncio.gather(*tasks)
        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"Batch of {len(request.pairs)} comparisons completed in {duration_ms:.2f}ms")
        return {
            "results": results,
            "processing_time_ms": round(duration_ms, 3)
        }
    except Exception as e:
        logger.error(f"Error during batch comparison: {str(e)}")
        raise HTTPException(status_code=500, detail="Batch execution failed")

# Mount frontend static directory
try:
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../frontend"))
    if os.path.exists(frontend_dir):
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="static")
        logger.info(f"Mounted static frontend from {frontend_dir}")
    else:
        logger.warning(f"Frontend directory not found at {frontend_dir}. API mode only.")
except Exception as e:
    logger.error(f"Failed to mount frontend: {str(e)}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
