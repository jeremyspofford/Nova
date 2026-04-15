import re


def _extract_json(text: str) -> str:
    """Strip markdown code fences if present, return raw JSON string."""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        return match.group(1).strip()
    return text.strip()
