"""LLM-based link relevance scoring with circuit breaker."""
import json
import logging

logger = logging.getLogger(__name__)


class RelevanceScorer:
    """LLM-based link relevance scoring with circuit breaker.

    When the LLM fails repeatedly, the circuit breaker opens and the scorer
    degrades to returning a default score for all links rather than blocking
    the crawl.
    """

    def __init__(self, llm_client, max_failures: int = 3):
        self._llm_client = llm_client
        self._max_failures = max_failures
        self._consecutive_failures = 0
        self._total_calls = 0

    @property
    def is_circuit_open(self) -> bool:
        return self._consecutive_failures >= self._max_failures

    @property
    def total_calls(self) -> int:
        return self._total_calls

    async def score_links(
        self,
        links: list[str],
        page_content: str,
        source_context: str,
    ) -> list[tuple[str, float]]:
        """Score each link 0-1 for relevance. Returns list of (url, score).

        If the circuit breaker is open, returns all links with score 1.0
        (follow everything -- degrade gracefully rather than stop crawling).
        """
        if not links:
            return []

        if self.is_circuit_open:
            logger.warning("Relevance scorer circuit breaker open -- following all links")
            return [(url, 1.0) for url in links]

        # Truncate page content for the prompt
        content_summary = page_content[:500] if page_content else "(empty page)"

        prompt = (
            "You are evaluating URLs discovered on a personal knowledge source page.\n"
            f"Source context: {source_context}\n"
            f"Page content summary: {content_summary}\n\n"
            "Score each URL 0.0-1.0 for how likely it contains meaningful information "
            "about this person/organization.\n"
            "1.0 = definitely relevant (project page, repo, portfolio piece, blog post)\n"
            "0.0 = definitely irrelevant (ads, unrelated external site, login pages, "
            "generic navigation)\n\n"
            f"URLs to score:\n{json.dumps(links[:20])}\n\n"
            'Return ONLY a JSON array: [{"url": "...", "score": 0.0}]'
        )

        try:
            resp = await self._llm_client.post(
                "/complete",
                json={
                    "messages": [{"role": "user", "content": prompt}],
                    "model": "auto",
                    "max_tokens": 1000,
                    "temperature": 0.1,
                },
                timeout=30,
            )

            self._total_calls += 1

            if resp.status_code != 200:
                raise RuntimeError(f"LLM returned {resp.status_code}")

            data = resp.json()
            content = data.get("content", "")

            # Parse JSON from response (handle markdown code blocks)
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]

            scores = json.loads(content.strip())
            self._consecutive_failures = 0

            score_map = {item["url"]: item["score"] for item in scores}
            result = []
            for url in links:
                score = score_map.get(url, 0.5)  # default 0.5 for unscored
                result.append((url, min(max(score, 0.0), 1.0)))
            return result

        except Exception as e:
            logger.warning("Relevance scoring failed: %s", e)
            self._consecutive_failures += 1
            self._total_calls += 1
            # On failure, give all links a moderate score so crawling continues
            return [(url, 0.7) for url in links]
