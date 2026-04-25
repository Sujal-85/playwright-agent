import os
import json
import re
import logging
import time
from typing import List

from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger(__name__)

DEFAULT_ANALYSIS = {
    "page_type": "other",
    "important_links": [],
    "has_login_form": False,
    "interesting_elements": [],
    "risk_level": "low",
    "notes": "AI analysis unavailable"
}


def _parse_json(text: str) -> dict:
    """Robustly extract JSON from LLM response."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # Extract from code block
    match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', text)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    # Find JSON object
    match = re.search(r'\{[\s\S]+\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    return {}


class AIAgent:
    def __init__(self):
        self.api_key = os.environ.get('EMERGENT_LLM_KEY', '')
        self.enabled = bool(self.api_key)
        if not self.enabled:
            logger.warning("EMERGENT_LLM_KEY not set — AI analysis disabled")

    def _make_chat(self, session_id: str) -> LlmChat:
        return LlmChat(
            api_key=self.api_key,
            session_id=session_id,
            system_message=(
                "You are a web testing agent. Analyze webpages and respond ONLY with valid JSON. "
                "No markdown, no explanation — just the JSON object."
            )
        ).with_model("anthropic", "claude-4-sonnet-20250514")

    async def analyze_page(self, html_snippet: str, page_url: str, page_title: str) -> dict:
        """Analyze a page and return structured insights."""
        if not self.enabled:
            return {**DEFAULT_ANALYSIS, "notes": "AI disabled (no API key)"}

        try:
            snippet = html_snippet[:4000] if len(html_snippet) > 4000 else html_snippet
            prompt = (
                f"URL: {page_url}\n"
                f"Title: {page_title}\n"
                f"HTML snippet:\n{snippet}\n\n"
                "Return JSON with these exact keys:\n"
                '{"page_type": "home|login|dashboard|product|article|form|error|other", '
                '"important_links": ["list of href URLs worth visiting"], '
                '"has_login_form": true/false, '
                '"interesting_elements": ["notable buttons, forms, inputs"], '
                '"risk_level": "low|medium|high", '
                '"notes": "brief observation"}'
            )
            chat = self._make_chat(f"analyze-{hash(page_url)}-{int(time.time())}")
            response = await chat.send_message(UserMessage(text=prompt))
            result = _parse_json(response)
            return {**DEFAULT_ANALYSIS, **result} if result else DEFAULT_ANALYSIS
        except Exception as e:
            logger.error(f"AI analyze_page error: {e}")
            return {**DEFAULT_ANALYSIS, "notes": f"AI error: {str(e)[:100]}"}

    async def decide_priority_urls(self, all_links: List[str], already_visited: set) -> List[str]:
        """Ask Claude to rank and pick top URLs to visit next."""
        if not self.enabled or not all_links:
            return all_links[:10]

        new_links = [l for l in all_links if l not in already_visited]
        if not new_links:
            return []

        try:
            links_str = '\n'.join(new_links[:50])
            prompt = (
                f"From this list of URLs, pick the top 10 most interesting/important to crawl next.\n"
                f"Prefer: home, about, dashboard, product, login, contact pages. Avoid duplicates.\n"
                f"URLs:\n{links_str}\n\n"
                "Return JSON: {\"priority_urls\": [\"url1\", \"url2\", ...]}"
            )
            chat = self._make_chat(f"priority-{int(time.time())}")
            response = await chat.send_message(UserMessage(text=prompt))
            result = _parse_json(response)
            return result.get("priority_urls", new_links[:10])
        except Exception as e:
            logger.error(f"AI decide_priority_urls error: {e}")
            return new_links[:10]
