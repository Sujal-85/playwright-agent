import asyncio
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

USERNAME_SELECTORS = [
    'input[type="email"]',
    'input[type="text"][name*="user" i]',
    'input[type="text"][name*="email" i]',
    'input[type="text"][id*="user" i]',
    'input[type="text"][id*="email" i]',
    'input[type="text"][placeholder*="email" i]',
    'input[type="text"][placeholder*="username" i]',
    'input[name="username"]',
    'input[name="email"]',
    'input[name="login"]',
    'input[id="username"]',
    'input[id="email"]',
]

PASSWORD_SELECTOR = 'input[type="password"]'

SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Login")',
    'button:has-text("Sign in")',
    'button:has-text("Log in")',
    'button:has-text("Continue")',
    'button:has-text("Sign In")',
]


class LoginHandler:

    async def check_and_handle_login(self, page, credentials: Optional[Dict]) -> Dict:
        """
        Detect and handle login forms on the page.
        Returns dict with success status and metadata.
        """
        has_login = await self._detect_login_form(page)
        if not has_login:
            return {"detected": False}

        logger.info(f"Login form detected at {page.url}")

        # Check for social login providers
        social_providers = await self._detect_social_login(page)

        # Detect captcha
        has_captcha = await self.detect_captcha(page)
        if has_captcha:
            return {
                "detected": True,
                "success": False,
                "reason": "captcha",
                "message": "CAPTCHA detected — cannot auto-login"
            }

        if not credentials or not credentials.get('username') or not credentials.get('password'):
            return {
                "detected": True,
                "success": False,
                "reason": "no_credentials",
                "skip": True,
                "social_providers": social_providers
            }

        return await self._attempt_login(page, credentials, social_providers)

    async def _detect_login_form(self, page) -> bool:
        """Check if page has a login/password form."""
        try:
            pwd_field = page.locator(PASSWORD_SELECTOR).first
            return await pwd_field.is_visible(timeout=2000)
        except Exception:
            return False

    async def _detect_social_login(self, page) -> list:
        """Find social login buttons."""
        providers = []
        social_texts = ['Google', 'GitHub', 'Facebook', 'Twitter', 'Microsoft', 'Apple']
        for text in social_texts:
            try:
                el = page.locator(f'button:has-text("{text}"), a:has-text("{text}")')
                if await el.count() > 0:
                    providers.append(text)
            except Exception:
                pass
        return providers

    async def detect_captcha(self, page) -> bool:
        """Detect CAPTCHA presence on page."""
        captcha_selectors = [
            'iframe[src*="recaptcha"]',
            '.g-recaptcha',
            '#captcha',
            'iframe[src*="hcaptcha"]',
            '.h-captcha',
        ]
        for selector in captcha_selectors:
            try:
                count = await page.locator(selector).count()
                if count > 0:
                    return True
            except Exception:
                pass
        return False

    async def _attempt_login(self, page, credentials: Dict, social_providers: list) -> Dict:
        """Fill and submit login form."""
        try:
            # Find and fill username field
            username_filled = False
            for selector in USERNAME_SELECTORS:
                try:
                    el = page.locator(selector).first
                    if await el.is_visible(timeout=1000):
                        await el.fill('')
                        await el.type(credentials['username'], delay=50)
                        username_filled = True
                        logger.debug(f"Filled username with selector: {selector}")
                        break
                except Exception:
                    continue

            # Fill password
            pwd_el = page.locator(PASSWORD_SELECTOR).first
            await pwd_el.fill('')
            await pwd_el.type(credentials['password'], delay=50)

            # Find and click submit
            submitted = False
            for selector in SUBMIT_SELECTORS:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        submitted = True
                        break
                except Exception:
                    continue

            if not submitted:
                # Try pressing Enter on password field
                await pwd_el.press('Enter')
                submitted = True

            # Wait for navigation
            await asyncio.sleep(2)
            try:
                await page.wait_for_load_state('domcontentloaded', timeout=10000)
            except Exception:
                pass

            # Verify login success
            success = await self._verify_login_success(page)
            return {
                "detected": True,
                "success": success,
                "method": "form_fill",
                "username_filled": username_filled,
                "social_providers": social_providers,
                "message": "Login successful" if success else "Login attempt made — result unclear"
            }

        except Exception as e:
            logger.error(f"Login attempt error: {e}")
            return {
                "detected": True,
                "success": False,
                "reason": "error",
                "message": str(e)[:200]
            }

    async def _verify_login_success(self, page) -> bool:
        """Check if we successfully logged in."""
        try:
            # Check if password field is gone (good sign)
            pwd_count = await page.locator(PASSWORD_SELECTOR).count()
            if pwd_count == 0:
                return True
            # Check if URL changed to dashboard/home
            url = page.url.lower()
            success_indicators = ['dashboard', 'home', 'account', 'profile', 'portal', 'app']
            for indicator in success_indicators:
                if indicator in url:
                    return True
        except Exception:
            pass
        return False
