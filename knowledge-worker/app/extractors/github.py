"""GitHub platform extractor — profiles, repos, READMEs, and activity."""

import re
import logging
import base64

from .base import BaseExtractor

logger = logging.getLogger(__name__)


class GitHubExtractor(BaseExtractor):
    """Extracts profile, repos, READMEs, and activity from GitHub profiles."""

    GITHUB_API = "https://api.github.com"
    # Match github.com/username but NOT github.com/username/repo
    URL_PATTERN = re.compile(r"https?://github\.com/([a-zA-Z0-9\-]+)/?$")

    @staticmethod
    def matches(url: str) -> bool:
        return bool(GitHubExtractor.URL_PATTERN.match(url.rstrip("/")))

    async def extract(self, url: str, credential: dict | None = None) -> list[dict]:
        """Extract structured data from a GitHub profile."""
        import httpx

        match = self.URL_PATTERN.match(url.rstrip("/"))
        if not match:
            return []

        username = match.group(1)
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Nova/1.0",
        }
        if credential and credential.get("token"):
            headers["Authorization"] = f"Bearer {credential['token']}"

        items: list[dict] = []

        async with httpx.AsyncClient(headers=headers, timeout=30) as client:
            # 1. Profile info
            profile = await self._fetch_profile(client, username)
            if profile:
                items.append(profile)

            # 2. Repositories (up to 100, sorted by updated)
            repos = await self._fetch_repos(client, username)
            for repo_item in repos:
                items.append(repo_item)

            # 3. READMEs for top repos (by stars, max 10)
            top_repos = sorted(
                repos,
                key=lambda r: r.get("metadata", {}).get("stars", 0),
                reverse=True,
            )[:10]
            for repo_item in top_repos:
                repo_name = repo_item.get("metadata", {}).get("repo_name")
                if repo_name:
                    readme = await self._fetch_readme(client, username, repo_name)
                    if readme:
                        items.append(readme)

            # 4. Recent public activity
            activity = await self._fetch_activity(client, username)
            if activity:
                items.append(activity)

        logger.info("GitHub extractor: extracted %d items for %s", len(items), username)
        return items

    @staticmethod
    def _check_rate_limit(resp) -> None:
        """Log a warning when GitHub API rate limit is running low."""
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            try:
                left = int(remaining)
                if left < 20:
                    logger.warning(
                        "GitHub API rate limit low: %d requests remaining", left
                    )
            except ValueError:
                pass

    async def _fetch_profile(self, client, username: str) -> dict | None:
        """Fetch GitHub user profile."""
        try:
            resp = await client.get(f"{self.GITHUB_API}/users/{username}")
            self._check_rate_limit(resp)
            if resp.status_code != 200:
                return None
            data = resp.json()
            bio_parts = [f"GitHub profile: {data.get('name', username)}"]
            if data.get("bio"):
                bio_parts.append(f"Bio: {data['bio']}")
            if data.get("company"):
                bio_parts.append(f"Company: {data['company']}")
            if data.get("location"):
                bio_parts.append(f"Location: {data['location']}")
            if data.get("blog"):
                bio_parts.append(f"Website: {data['blog']}")
            bio_parts.append(f"Public repos: {data.get('public_repos', 0)}")
            bio_parts.append(f"Followers: {data.get('followers', 0)}")

            return {
                "title": f"GitHub Profile: {data.get('name', username)}",
                "body": "\n".join(bio_parts),
                "url": data.get("html_url", f"https://github.com/{username}"),
                "author": username,
                "metadata": {
                    "type": "github_profile",
                    "username": username,
                    "name": data.get("name"),
                    "blog": data.get("blog"),
                    "public_repos": data.get("public_repos"),
                    "followers": data.get("followers"),
                },
            }
        except Exception as e:
            logger.warning("Failed to fetch GitHub profile for %s: %s", username, e)
            return None

    async def _fetch_repos(self, client, username: str) -> list[dict]:
        """Fetch user's public repositories."""
        items: list[dict] = []
        try:
            resp = await client.get(
                f"{self.GITHUB_API}/users/{username}/repos",
                params={"sort": "updated", "per_page": 100, "type": "owner"},
            )
            self._check_rate_limit(resp)
            if resp.status_code != 200:
                return []

            for repo in resp.json():
                if repo.get("fork"):
                    continue  # Skip forks

                desc_parts = [f"Repository: {repo['full_name']}"]
                if repo.get("description"):
                    desc_parts.append(f"Description: {repo['description']}")
                if repo.get("language"):
                    desc_parts.append(f"Language: {repo['language']}")
                desc_parts.append(f"Stars: {repo.get('stargazers_count', 0)}")
                if repo.get("topics"):
                    desc_parts.append(f"Topics: {', '.join(repo['topics'])}")

                items.append({
                    "title": f"Repo: {repo['full_name']}",
                    "body": "\n".join(desc_parts),
                    "url": repo.get("html_url", ""),
                    "author": username,
                    "metadata": {
                        "type": "github_repo",
                        "repo_name": repo["name"],
                        "full_name": repo["full_name"],
                        "language": repo.get("language"),
                        "stars": repo.get("stargazers_count", 0),
                        "topics": repo.get("topics", []),
                        "fork": repo.get("fork", False),
                    },
                })
        except Exception as e:
            logger.warning("Failed to fetch repos for %s: %s", username, e)
        return items

    async def _fetch_readme(self, client, username: str, repo_name: str) -> dict | None:
        """Fetch README content for a repository."""
        try:
            resp = await client.get(
                f"{self.GITHUB_API}/repos/{username}/{repo_name}/readme"
            )
            self._check_rate_limit(resp)
            if resp.status_code != 200:
                return None
            data = resp.json()
            content = base64.b64decode(data.get("content", "")).decode(
                "utf-8", errors="replace"
            )
            if len(content) < 50:  # Skip trivially short READMEs
                return None
            return {
                "title": f"README: {username}/{repo_name}",
                "body": content[:10000],  # Cap size
                "url": data.get(
                    "html_url", f"https://github.com/{username}/{repo_name}"
                ),
                "author": username,
                "metadata": {
                    "type": "github_readme",
                    "repo_name": repo_name,
                },
            }
        except Exception as e:
            logger.debug("No README for %s/%s: %s", username, repo_name, e)
            return None

    async def _fetch_activity(self, client, username: str) -> dict | None:
        """Fetch recent public activity summary."""
        try:
            resp = await client.get(
                f"{self.GITHUB_API}/users/{username}/events/public",
                params={"per_page": 30},
            )
            self._check_rate_limit(resp)
            if resp.status_code != 200:
                return None
            events = resp.json()
            if not events:
                return None

            # Summarize activity types
            activity_types: dict[str, int] = {}
            repos_active: set[str] = set()
            for event in events:
                etype = event.get("type", "Unknown")
                activity_types[etype] = activity_types.get(etype, 0) + 1
                repo = event.get("repo", {}).get("name", "")
                if repo:
                    repos_active.add(repo)

            summary_parts = [f"Recent GitHub activity for {username}:"]
            for etype, count in sorted(
                activity_types.items(), key=lambda x: -x[1]
            ):
                summary_parts.append(f"  {etype}: {count}")
            summary_parts.append(
                f"Active repos: {', '.join(list(repos_active)[:10])}"
            )

            return {
                "title": f"GitHub Activity: {username}",
                "body": "\n".join(summary_parts),
                "url": f"https://github.com/{username}",
                "author": username,
                "metadata": {
                    "type": "github_activity",
                    "event_count": len(events),
                    "active_repos": list(repos_active)[:10],
                },
            }
        except Exception as e:
            logger.warning("Failed to fetch activity for %s: %s", username, e)
            return None
