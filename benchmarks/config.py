"""Benchmark configuration via pydantic_settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BenchmarkConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BENCH_", extra="ignore")

    llm_gateway_url: str = "http://localhost:8001"
    embed_model: str = "nomic-embed-text"
    judge_model: str = "auto"  # Uses gateway's default
    relevance_threshold: float = 2.0  # Score >= this counts as relevant
    top_k: int = 5
    timeout_seconds: float = 30.0
