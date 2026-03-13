"""Model catalog search — HuggingFace API for vLLM/SGLang, Ollama registry."""
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

HF_API = "https://huggingface.co/api/models"


async def search_models(
    query: str,
    backend: str = "vllm",
    max_vram_gb: Optional[float] = None,
    limit: int = 20,
) -> list[dict]:
    """Search model catalogs by backend type."""
    if backend in ("vllm", "sglang"):
        return await _search_huggingface(query, max_vram_gb, limit)
    elif backend == "ollama":
        return []  # Ollama doesn't have a public search API
    return []


async def _search_huggingface(
    query: str,
    max_vram_gb: Optional[float],
    limit: int,
) -> list[dict]:
    """Search HuggingFace for text-generation models."""
    params = {
        "search": query,
        "pipeline_tag": "text-generation",
        "sort": "downloads",
        "direction": "-1",
        "limit": limit * 2,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(HF_API, params=params)
            r.raise_for_status()
            models = r.json()
    except Exception as e:
        logger.warning("HuggingFace search failed: %s", e)
        return []

    results = []
    for m in models:
        model_id = m.get("modelId", m.get("id", ""))
        safetensors = m.get("safetensors", {})
        params_total = safetensors.get("total", 0) if isinstance(safetensors, dict) else 0

        is_quantized = any(tag in model_id.lower() for tag in ["awq", "gptq", "gguf", "exl2"])
        bytes_per_param = 0.5 if is_quantized else 2.0
        vram_estimate_gb = round((params_total * bytes_per_param) / (1024**3) + 1.0, 1) if params_total else None

        if max_vram_gb and vram_estimate_gb and vram_estimate_gb > max_vram_gb:
            continue

        results.append({
            "id": model_id,
            "description": m.get("pipeline_tag", "text-generation"),
            "downloads": m.get("downloads", 0),
            "likes": m.get("likes", 0),
            "vram_estimate_gb": vram_estimate_gb,
            "quantized": is_quantized,
            "tags": m.get("tags", [])[:5],
        })

        if len(results) >= limit:
            break

    return results
