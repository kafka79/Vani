import asyncio
from contextlib import asynccontextmanager
import logging
import os
import time
from collections import defaultdict
import threading
from collections import defaultdict
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST, CollectorRegistry, multiprocess
from concurrent.futures import ProcessPoolExecutor
import redis.asyncio as redis

from phonetic_engine import engine, compare_with_weights
from admin import router as admin_router

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IndicSync")

redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)

# --- Prometheus Metrics Initialization ---
metrics_registry = CollectorRegistry()

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total number of HTTP requests processed.",
    ["method", "endpoint", "status"],
    registry=metrics_registry
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "Total duration of HTTP requests in seconds.",
    ["method", "endpoint"],
    registry=metrics_registry
)

REDIS_CONNECTION_ERRORS_TOTAL = Counter(
    "redis_connection_errors_total",
    "Total number of Redis connection failures.",
    registry=metrics_registry
)

RATE_LIMITER_BYPASSED_TOTAL = Counter(
    "rate_limiter_bypassed_total",
    "Total number of rate limiter checks that failed open/fallback.",
    registry=metrics_registry
)

def init_worker():
    """Initializer for process pool workers to subscribe to dynamic configuration updates."""
    import threading
    import redis
    import json
    from phonetic_engine import engine
    
    def config_listener():
        try:
            r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
            pubsub = r.pubsub()
            pubsub.subscribe("config_updates")
            for message in pubsub.listen():
                if message["type"] == "message":
                    w_data = r.get("weights")
                    if w_data:
                        engine.update_weights(json.loads(w_data))
        except Exception:
            pass

    # Fetch initial state
    try:
        r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)
        initial_weights = r.get("weights")
        if initial_weights:
            engine.update_weights(json.loads(initial_weights))
    except Exception:
        pass
        
    t = threading.Thread(target=config_listener, daemon=True)
    t.start()

# Global Process Pool with configurable limits
worker_count = int(os.getenv("WORKER_COUNT", max(1, (os.cpu_count() or 2) // 2)))
process_pool = ProcessPoolExecutor(max_workers=worker_count, initializer=init_worker)

class AsyncRedisCircuitBreaker:
    def __init__(self, failure_threshold=3, recovery_time=60):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF-OPEN
        self.last_state_change = 0

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.last_state_change = time.time()
            logger.error("Redis (Async) Circuit Breaker tripped to OPEN.")

    def is_allowed(self):
        if self.state == "OPEN":
            if time.time() - self.last_state_change > self.recovery_time:
                self.state = "HALF-OPEN"
                return True
            return False
        return True

class RedisRateLimiter:
    """Lightweight Redis-based sliding window rate limiter with fail-open circuit breaker."""
    def __init__(self, limit: int, window: int):
        self.limit = limit
        self.window = window
        self.breaker = AsyncRedisCircuitBreaker()

    async def is_allowed(self, client_ip: str, fail_open: bool = True) -> bool:
        now = time.time()
        key = f"rate_limit:{client_ip}"
        
        if not self.breaker.is_allowed():
            RATE_LIMITER_BYPASSED_TOTAL.inc()
            return fail_open
            
        try:
            async with redis_client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, 0, now - self.window)
                pipe.zcard(key)
                pipe.zadd(key, {str(now): now})
                pipe.expire(key, self.window)
                results = await pipe.execute()
                
            current_requests = results[1]
            self.breaker.record_success()
            return current_requests < self.limit
        except Exception as e:
            logger.warning(f"Rate limiter redis error: {e}")
            self.breaker.record_failure()
            REDIS_CONNECTION_ERRORS_TOTAL.inc()
            RATE_LIMITER_BYPASSED_TOTAL.inc()
            return fail_open

# Limit to 100 requests per 60 seconds per IP
rate_limiter = RedisRateLimiter(limit=100, window=60)

def rate_limit_dependency(fail_open: bool = True):
    async def dependency(request: Request):
        ip = request.client.host if request.client else "127.0.0.1"
        if not await rate_limiter.is_allowed(ip, fail_open=fail_open):
            status = 429 if rate_limiter.breaker.is_allowed() else 503
            detail = "Too many requests. Please slow down and try again later." if status == 429 else "Service temporarily unavailable due to high load."
            raise HTTPException(status_code=status, detail=detail)
    return dependency

# --- Lifespan Context Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    logger.info("Initializing Indic Phonetic Similarity Service...")
    # Setup multiprocess environment for Prometheus if specified
    multiproc_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if multiproc_dir:
        os.makedirs(multiproc_dir, exist_ok=True)
        from prometheus_client import multiprocess
        multiprocess.MultiProcessCollector(metrics_registry)
        
    # Fetch config asynchronously
    async def fetch_and_apply_config():
        try:
            weights_data = await redis_client.get("weights")
            if weights_data:
                weights = json.loads(weights_data)
                engine.update_weights(weights)
                logger.info("Successfully fetched weights from Redis on startup.")
        except Exception as e:
            logger.warning(f"Could not connect to Redis on startup. Using default config. Error: {e}")

    await fetch_and_apply_config()
    
    # Start background Pub/Sub listener for config updates
    async def listen_config_updates():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("config_updates")
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    logger.info("Redis Pub/Sub signal received. Reloading configuration...")
                    await fetch_and_apply_config()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in config update Pub/Sub listener: {e}")
        finally:
            await pubsub.unsubscribe("config_updates")

    config_listener_task = asyncio.create_task(listen_config_updates())
    
    yield
    
    # Shutdown logic
    config_listener_task.cancel()
    try:
        await config_listener_task
    except asyncio.CancelledError:
        pass
        
    logger.info("Shutting down Indic Phonetic Similarity Service...")
    process_pool.shutdown(wait=True)
    if multiproc_dir and os.path.exists(multiproc_dir):
        import shutil
        try:
            shutil.rmtree(multiproc_dir)
        except Exception as e:
            logger.error(f"Failed to clear multiprocess metrics folder: {e}")

app = FastAPI(
    title="Indic Phonetic Similarity API",
    description="Production-grade phonetic similarity engine for Indic names and entities.",
    lifespan=lifespan
)

# Include Admin Router
app.include_router(admin_router)

# --- Middleware ---
@app.middleware("http")
async def record_metrics(request: Request, call_next):
    # Skip endpoints we don't want to track in standard application metrics
    path = request.url.path
    if path in ["/metrics", "/health"] or path.startswith("/static") or "." in path.split("/")[-1]:
        return await call_next(request)
        
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        duration = time.perf_counter() - start_time
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            endpoint=path,
            status=response.status_code
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method,
            endpoint=path
        ).observe(duration)
        return response
    except Exception as e:
        duration = time.perf_counter() - start_time
        HTTP_REQUESTS_TOTAL.labels(
            method=request.method,
            endpoint=path,
            status=500
        ).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=request.method,
            endpoint=path
        ).observe(duration)
        raise e

# CORS Configuration
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
if allowed_origins_env:
    origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
    logger.info(f"CORS: Allowed origins configured: {origins}")
else:
    origins = []
    logger.warning("CORS: ALLOWED_ORIGINS not set. CORS requests will be blocked.")

# FASTAPI/Starlette strictly forbids wildcard origins with credentials enabled
credentials = True if origins and "*" not in origins else False

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Models ---
class ComparisonRequest(BaseModel):
    name1: str = Field(..., description="First name/word to compare")
    name2: str = Field(..., description="Second name/word to compare")
    enable_aliases: bool = Field(default=True, description="Whether to check synonym aliases")
    threshold: float = Field(default=None, description="Optional override for matching threshold", ge=0.0, le=100.0)
    locale: Optional[str] = Field(default=None, description="Optional locale for phonetic mapping (e.g., 'bn', 'hi', 'ta')")

class BatchRequest(BaseModel):
    pairs: List[ComparisonRequest] = Field(..., max_length=100, description="List of comparison pairs")
    enable_aliases: bool = Field(True, description="Enable administrative/historical alias synonym matching globally")
    threshold: float = Field(default=None, ge=0.0, le=100.0, description="Optional custom similarity threshold override globally")
    locale: Optional[str] = Field(default=None, description="Optional locale for phonetic mapping (e.g., 'bn', 'hi', 'ta')")

def validate_input(name: str, identifier: str):
    """Performs validation checks on input names with sanitized error messages."""
    trimmed = name.strip()
    if not trimmed:
        raise ValueError(f"Input for {identifier} must contain non-whitespace characters.")
    
    normalized = engine.normalize(trimmed)
    if not normalized:
        raise ValueError(f"Input for {identifier} contains no valid Latin characters. Please use English transliterations.")

# --- Public Endpoints ---
@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/metrics")
async def get_metrics():
    # If multiprocess collector directory is configured, regenerate latest dynamically
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        reg = CollectorRegistry()
        multiprocess.MultiProcessCollector(reg)
        data = generate_latest(reg)
    else:
        data = generate_latest(metrics_registry)
    return PlainTextResponse(data, media_type=CONTENT_TYPE_LATEST)

@app.post("/compare", dependencies=[Depends(rate_limit_dependency(fail_open=True))])
async def compare_names(request_data: ComparisonRequest, request: Request):
    try:
        validate_input(request_data.name1, "Name 1")
        validate_input(request_data.name2, "Name 2")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    is_alias_match = False
    if request_data.enable_aliases:
        norm1 = engine.normalize(request_data.name1, locale=request_data.locale).lower()
        norm2 = engine.normalize(request_data.name2, locale=request_data.locale).lower()
        try:
            if await redis_client.sismember(f"alias:{norm1}", norm2):
                is_alias_match = True
        except Exception as e:
            logger.warning(f"Failed to check Redis aliases: {e}")

    start_time = time.perf_counter()
    loop = asyncio.get_running_loop()

    try:
        result = await loop.run_in_executor(
            process_pool,
            engine.compare,
            request_data.name1,
            request_data.name2,
            request_data.enable_aliases,
            request_data.threshold,
            is_alias_match,
            request_data.locale
        )
        duration_ms = (time.perf_counter() - start_time) * 1000
        result["processing_time_ms"] = round(duration_ms, 3)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error during comparison: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error during processing")

def validate_and_normalize_chunk(param_list):
    """Worker helper to validate and normalize a chunk of strings in process pool."""
    results = []
    for pair, aliases_flag, locale_val in param_list:
        try:
            validate_input(pair.name1, "Name 1")
            validate_input(pair.name2, "Name 2")
            norm1 = engine.normalize(pair.name1, locale=locale_val).lower() if aliases_flag else None
            norm2 = engine.normalize(pair.name2, locale=locale_val).lower() if aliases_flag else None
            results.append((True, norm1, norm2, None))
        except ValueError as e:
            results.append((False, None, None, str(e)))
        except Exception as e:
            results.append((False, None, None, "Internal validation error"))
    return results

def compare_chunk_worker(valid_items):
    """Worker helper to run comparisons in process pool for a chunk."""
    results = []
    for pair, aliases_flag, threshold_val, locale_val, is_alias_match in valid_items:
        try:
            res = engine.compare(pair.name1, pair.name2, aliases_flag, threshold_val, is_alias_match, locale_val)
            results.append({"status": "success", "data": res})
        except ValueError as e:
            results.append({"status": "error", "error": str(e)})
        except Exception as e:
            results.append({"status": "error", "error": "Internal comparison error"})
    return results

@app.post("/compare-batch", dependencies=[Depends(rate_limit_dependency(fail_open=False))])
async def compare_batch(batch_request: BatchRequest, request: Request):
    if not batch_request.pairs:
        raise HTTPException(status_code=400, detail="Batch request must contain at least one comparison pair.")
    if len(batch_request.pairs) > 100:
        raise HTTPException(status_code=400, detail="Batch request size cannot exceed 100 pairs.")

    start_time = time.perf_counter()
    loop = asyncio.get_running_loop()
    
    results = []
    
    # 1. Resolve parameters and offload validation/normalization to process pool chunk
    param_list = []
    for pair in batch_request.pairs:
        aliases_flag = pair.enable_aliases if pair.enable_aliases is not None else batch_request.enable_aliases
        locale_val = pair.locale if pair.locale is not None else batch_request.locale
        param_list.append((pair, aliases_flag, locale_val))
        
    val_results = await loop.run_in_executor(process_pool, validate_and_normalize_chunk, param_list)
    
    # 2. Pipelined Redis alias lookup from main thread
    valid_items = []
    alias_checks = []
    
    for idx, (is_valid, norm1, norm2, err_msg) in enumerate(val_results):
        pair, aliases_flag, locale_val = param_list[idx]
        threshold_val = pair.threshold if pair.threshold is not None else batch_request.threshold
        if not is_valid:
            results.append({"status": "error", "error": err_msg})
        else:
            if aliases_flag and norm1 and norm2:
                alias_checks.append((norm1, norm2, idx))
            valid_items.append((pair, aliases_flag, threshold_val, locale_val, idx, False))
            
    alias_map = {}
    if alias_checks:
        try:
            async with redis_client.pipeline(transaction=False) as pipe:
                for norm1, norm2, _ in alias_checks:
                    pipe.sismember(f"alias:{norm1}", norm2)
                alias_redis_results = await pipe.execute()
                for i, (_, _, original_idx) in enumerate(alias_checks):
                    alias_map[original_idx] = bool(alias_redis_results[i])
        except Exception as e:
            logger.warning(f"Batch Redis alias check failed: {e}")
            
    # Update is_alias_match
    final_valid_items = []
    for pair, aliases_flag, threshold_val, locale_val, idx, _ in valid_items:
        is_alias_match = alias_map.get(idx, False)
        final_valid_items.append((pair, aliases_flag, threshold_val, locale_val, is_alias_match))
        
    # 3. CPU bound processing via Process Pool chunk
    if final_valid_items:
        compare_results = await loop.run_in_executor(process_pool, compare_chunk_worker, final_valid_items)
        results.extend(compare_results)
    
    errors = [r for r in results if r["status"] == "error"]
    successes = [r for r in results if r["status"] == "success"]
    
    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(f"Batch of {len(batch_request.pairs)} comparisons completed in {duration_ms:.2f}ms")
    
    status_code = 200
    if errors and successes:
        status_code = 207
    elif errors and not successes:
        status_code = 400
        
    return JSONResponse(status_code=status_code, content={
        "results": successes,
        "errors": errors,
        "processing_time_ms": round(duration_ms, 3)
    })

# Mount static frontend
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
    dev_mode = os.getenv("DEV_MODE", "false").lower() == "true"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=dev_mode)
