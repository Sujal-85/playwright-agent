import asyncio
import base64
import logging
import os
import subprocess
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Set

from playwright.async_api import async_playwright

from ai_agent import AIAgent
from login_handler import LoginHandler
from utils import normalize_url, is_same_domain, should_skip_url

logger = logging.getLogger(__name__)

_xvfb_proc = None


def ensure_display():
    """Start Xvfb virtual display if DISPLAY is not set."""
    global _xvfb_proc
    # Set playwright browsers path to pre-installed location
    if not os.environ.get('PLAYWRIGHT_BROWSERS_PATH'):
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '/pw-browsers'
    if os.environ.get('DISPLAY'):
        return
    # Kill stale Xvfb
    subprocess.run(['pkill', '-f', 'Xvfb :99'], capture_output=True)
    time.sleep(0.5)
    try:
        _xvfb_proc = subprocess.Popen(
            ['Xvfb', ':99', '-screen', '0', '1920x1080x24', '-nolisten', 'tcp'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(1.5)
        os.environ['DISPLAY'] = ':99'
        logger.info("Xvfb started on :99")
    except Exception as e:
        logger.warning(f"Could not start Xvfb: {e} — running headless as fallback")


CHROME_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)


class WebCrawler:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.playwright = None
        self.browser = None
        self.context = None
        self.visited_urls: Set[str] = set()
        self.page_results: List[dict] = []
        self.start_time: Optional[float] = None
        self.is_stopped = False
        self.ai_agent = AIAgent()
        self.login_handler = LoginHandler()

    async def launch_browser(self):
        """Launch Chromium in headed mode with Xvfb."""
        ensure_display()
        self.playwright = await async_playwright().start()
        headed = bool(os.environ.get('DISPLAY'))
        logger.info(f"Launching browser headless={not headed}")
        self.browser = await self.playwright.chromium.launch(
            headless=not headed,
            args=[
                '--start-maximized',
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-extensions',
            ]
        )
        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent=CHROME_USER_AGENT,
            ignore_https_errors=True,
        )
        # Anti-detection script
        await self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logger.info("Browser launched successfully")

    async def crawl(
        self,
        start_url: str,
        credentials: Optional[Dict],
        max_pages: int,
        max_depth: int,
        ws_callback: Callable
    ):
        """Main BFS crawl loop."""
        self.start_time = time.time()
        await self.launch_browser()

        queue = deque([(start_url, 0)])
        self.visited_urls = set()
        logged_in = False

        await ws_callback({
            "event": "crawl_started",
            "data": {
                "url": start_url,
                "max_pages": max_pages,
                "max_depth": max_depth,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        })

        while queue and len(self.visited_urls) < max_pages and not self.is_stopped:
            url, depth = queue.popleft()

            # Skip if already visited or too deep
            norm_url = normalize_url(url, start_url)
            if not norm_url or norm_url in self.visited_urls:
                continue
            if depth > max_depth:
                continue
            if should_skip_url(norm_url):
                continue
            if not is_same_domain(norm_url, start_url):
                continue

            self.visited_urls.add(norm_url)

            page_data = await self._visit_page(
                norm_url, depth, start_url, credentials, logged_in, ws_callback
            )

            if page_data:
                self.page_results.append(page_data)

                # Check if login was handled
                if page_data.get('login_result', {}).get('success'):
                    logged_in = True

                # Add discovered links to queue
                for link in page_data.get('all_links', [])[:50]:
                    if link not in self.visited_urls:
                        queue.append((link, depth + 1))

            # Polite crawling delay
            if not self.is_stopped:
                await asyncio.sleep(1)

        elapsed = round(time.time() - self.start_time, 1)
        await ws_callback({
            "event": "crawl_complete",
            "data": {
                "total_pages": len(self.visited_urls),
                "elapsed_seconds": elapsed,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        })
        logger.info(f"Crawl complete: {len(self.visited_urls)} pages in {elapsed}s")

    async def _visit_page(
        self,
        url: str,
        depth: int,
        base_url: str,
        credentials: Optional[Dict],
        already_logged_in: bool,
        ws_callback: Callable
    ) -> Optional[dict]:
        """Visit a single page and return page data."""
        page = None
        try:
            page = await self.context.new_page()
            logger.info(f"Visiting: {url} (depth={depth})")

            # Navigate
            response = None
            status = 0
            try:
                response = await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                status = response.status if response else 0
                await page.wait_for_timeout(1500)
            except Exception as nav_err:
                logger.warning(f"Navigation error {url}: {nav_err}")
                status = 0

            title = await page.title()

            # Take screenshot
            screenshot_b64 = ''
            try:
                screenshot_bytes = await page.screenshot(type='png', full_page=False)
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            except Exception as ss_err:
                logger.warning(f"Screenshot error: {ss_err}")

            # Login detection
            login_result = {"detected": False}
            if not already_logged_in:
                try:
                    login_result = await self.login_handler.check_and_handle_login(page, credentials)
                    if login_result.get('detected'):
                        if login_result.get('success'):
                            await ws_callback({
                                "event": "login_success",
                                "data": {"url": url, "message": "Login successful"}
                            })
                        else:
                            await ws_callback({
                                "event": "login_detected",
                                "data": {
                                    "url": url,
                                    "reason": login_result.get('reason', 'unknown'),
                                    "message": login_result.get('message', '')
                                }
                            })
                        # Retake screenshot after login attempt
                        try:
                            screenshot_bytes = await page.screenshot(type='png', full_page=False)
                            screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                        except Exception:
                            pass
                except Exception as login_err:
                    logger.warning(f"Login handler error: {login_err}")

            # AI page analysis
            ai_analysis = {}
            try:
                html = await page.content()
                ai_analysis = await self.ai_agent.analyze_page(html, url, title)
            except Exception as ai_err:
                logger.warning(f"AI analysis error: {ai_err}")
                ai_analysis = {"page_type": "other", "notes": "AI unavailable"}

            # Extract links
            all_links = await self.extract_links(page, base_url)

            page_data = {
                "url": url,
                "title": title,
                "status": status,
                "page_type": ai_analysis.get("page_type", "other"),
                "screenshot": screenshot_b64,
                "links_found": len(all_links),
                "all_links": all_links,
                "depth": depth,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "notes": ai_analysis.get("notes", ""),
                "interesting_elements": ai_analysis.get("interesting_elements", []),
                "has_login_form": ai_analysis.get("has_login_form", False),
                "risk_level": ai_analysis.get("risk_level", "low"),
                "login_result": login_result,
                "requires_auth": login_result.get("detected") and not login_result.get("success"),
            }

            # Send event (without all_links to reduce payload)
            event_data = {k: v for k, v in page_data.items() if k != 'all_links'}
            await ws_callback({
                "event": "page_visited",
                "data": event_data
            })

            return page_data

        except Exception as e:
            logger.error(f"Error visiting {url}: {e}")
            await ws_callback({
                "event": "page_error",
                "data": {
                    "url": url,
                    "error": str(e)[:300],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            })
            return None
        finally:
            if page:
                try:
                    await page.close()
                except Exception:
                    pass

    async def extract_links(self, page, base_url: str) -> List[str]:
        """Extract all same-domain links from the page."""
        try:
            hrefs = await page.eval_on_selector_all(
                'a[href]',
                'elements => elements.map(el => el.href)'
            )
            links = []
            seen = set()
            for href in hrefs:
                norm = normalize_url(href, base_url)
                if norm and norm not in seen and not should_skip_url(norm) and is_same_domain(norm, base_url):
                    seen.add(norm)
                    links.append(norm)
            return links
        except Exception as e:
            logger.warning(f"Link extraction error: {e}")
            return []

    async def close(self):
        """Close browser and cleanup."""
        self.is_stopped = True
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        logger.info(f"Crawler {self.session_id} closed")
