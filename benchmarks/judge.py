"""LLM-as-judge scoring for memory retrieval results.

Each retrieved memory chunk is scored 0-3 for relevance to the query.
If ground_truth labels are provided, the LLM call is skipped entirely.
"""

from __future__ import annotations

import logging

import httpx

from .config import BenchmarkConfig

log = logging.getLogger(__name__)

JUDGE_PROMPT = """\
You are evaluating memory retrieval results. Given a query and a retrieved memory chunk, rate its relevance on a 0-3 scale:
0 = Irrelevant (no connection to query)
1 = Tangential (loosely related but doesn't help answer)
2 = Relevant (contains useful information for answering)
3 = Directly answers (the query is specifically about this)

Query: {query}
Retrieved chunk: {content}

Respond with ONLY a single number: 0, 1, 2, or 3."""


async def score_results(
    llm_gateway_url: str,
    query: str,
    results: list[dict],  # [{content, score, id}]
    ground_truth: list[dict] | None = None,  # [{content, relevance_grade}]
    config: BenchmarkConfig | None = None,
) -> tuple[list[float], int]:
    """Score each result 0-3 for relevance using LLM-as-judge.

    If ground_truth is provided, uses those scores directly (no LLM call).

    Returns:
        Tuple of (scores list, total tokens used for judging).
    """
    if config is None:
        config = BenchmarkConfig()

    # Fast path: use ground truth if available
    if ground_truth is not None:
        gt_map = {item["content"].strip(): item["relevance_grade"] for item in ground_truth}
        scores = []
        for r in results:
            content = r.get("content", "").strip()
            grade = gt_map.get(content, 0)
            scores.append(float(grade))
        return scores, 0

    # LLM-as-judge path
    scores: list[float] = []
    total_tokens = 0

    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        for r in results:
            content = r.get("content", "")
            if not content:
                scores.append(0.0)
                continue

            prompt = JUDGE_PROMPT.format(query=query, content=content)
            score, tokens = await _call_judge(client, llm_gateway_url, prompt, config)
            scores.append(score)
            total_tokens += tokens

    return scores, total_tokens


async def _call_judge(
    client: httpx.AsyncClient,
    llm_gateway_url: str,
    prompt: str,
    config: BenchmarkConfig,
) -> tuple[float, int]:
    """Make a single judge call to the LLM gateway.

    Returns (score, tokens_used). Defaults to 0 on any failure.
    """
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 4,
    }
    if config.judge_model != "auto":
        payload["model"] = config.judge_model

    try:
        resp = await client.post(
            f"{llm_gateway_url.rstrip('/')}/complete",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

        content = data.get("content", "").strip()
        tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)

        # Parse the score — expect a single digit 0-3
        score = _parse_score(content)
        return score, tokens

    except httpx.HTTPStatusError as e:
        log.warning("Judge LLM call failed (HTTP %d): %s", e.response.status_code, e.response.text[:200])
        return 0.0, 0
    except httpx.RequestError as e:
        log.warning("Judge LLM call failed (network): %s", e)
        return 0.0, 0
    except Exception as e:
        log.warning("Judge scoring failed: %s", e)
        return 0.0, 0


def _parse_score(content: str) -> float:
    """Extract a 0-3 integer score from LLM output.

    Handles common formats: bare digit, digit with period, digit with explanation.
    Returns 0.0 if unparseable.
    """
    content = content.strip()
    if not content:
        return 0.0

    # Try the first character
    first_char = content[0]
    if first_char in "0123":
        return float(int(first_char))

    # Try parsing the whole thing
    try:
        val = int(float(content))
        if 0 <= val <= 3:
            return float(val)
    except (ValueError, TypeError):
        pass

    log.warning("Could not parse judge score from: %r — defaulting to 0", content[:50])
    return 0.0
