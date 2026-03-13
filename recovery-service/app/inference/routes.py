"""API routes for inference backend management."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.inference.controller import (
    get_backend_status, list_backends, start_backend, stop_backend, switch_model,
)
from app.inference.hardware import detect_hardware, get_backend_recommendation, get_hardware
from app.inference.model_search import search_models as do_search_models
from app.routes import _check_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/recovery/inference", tags=["inference"])


@router.get("/hardware")
async def get_hardware_info(_: None = Depends(_check_admin)):
    """Return detected hardware info (GPU, CPU, RAM, disk)."""
    hw = await get_hardware()
    recommendation = get_backend_recommendation(hw)
    return {**hw, "recommended_backend": recommendation}


@router.post("/hardware/detect")
async def redetect_hardware(_: None = Depends(_check_admin)):
    """Force re-detection of hardware."""
    hw = await detect_hardware()
    recommendation = get_backend_recommendation(hw)
    return {**hw, "recommended_backend": recommendation}


# ── Backend lifecycle ─────────────────────────────────────────────────────────


@router.get("/backend")
async def get_inference_backend(_: None = Depends(_check_admin)):
    """Get current inference backend status."""
    return await get_backend_status()


@router.get("/backends")
async def list_inference_backends(_: None = Depends(_check_admin)):
    """List all available inference backends."""
    return await list_backends()


@router.post("/backend/stop")
async def stop_inference_backend(_: None = Depends(_check_admin)):
    """Stop the active inference backend."""
    return await stop_backend()


@router.post("/backend/{backend_name}/start")
async def start_inference_backend(backend_name: str, _: None = Depends(_check_admin)):
    """Start (or switch to) an inference backend."""
    try:
        return await start_backend(backend_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))


# ── Model switching ──────────────────────────────────────────────────────────


class SwitchModelRequest(BaseModel):
    model: str


@router.post("/backend/{backend_name}/switch-model", status_code=202)
async def switch_inference_model(
    backend_name: str,
    body: SwitchModelRequest,
    _: None = Depends(_check_admin),
):
    """Switch the model on a single-model backend (vLLM, SGLang)."""
    try:
        return await switch_model(backend_name, body.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/models/search")
async def search_models_endpoint(
    q: str,
    backend: str = "vllm",
    max_vram_gb: float | None = None,
    _: None = Depends(_check_admin),
):
    """Search model catalogs (HuggingFace for vLLM/SGLang, Ollama registry)."""
    return await do_search_models(q, backend, max_vram_gb)
