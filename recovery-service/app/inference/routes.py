"""API routes for inference backend management."""
import logging

from fastapi import APIRouter, Depends

from app.inference.hardware import detect_hardware, get_backend_recommendation, get_hardware
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
