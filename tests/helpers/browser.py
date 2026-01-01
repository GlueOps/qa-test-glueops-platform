"""
Browser helpers for UI tests.

This module provides utilities for Playwright-based browser automation,
including browser connection management, screenshot capture, and OAuth flows.
"""
import os
import logging
import pyotp
import uuid
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from typing import List, Tuple, Optional
import allure

log = logging.getLogger(__name__)


@dataclass
class VisualComparisonResult:
    """Result of a visual regression comparison."""
    baseline_key: str
    passed: bool
    diff_percent: float
    threshold: float
    diff_image_path: Optional[Path]
    baseline_created: bool = False  # True if baseline was auto-created


def handle_vault_oidc_popup_auth(page, context, credentials, button_name="Sign in with OIDC Provider", screenshots=None):
    """
    Handle Vault OIDC authentication that may open a GitHub OAuth reauthorization popup.
    
    This function:
    1. Clicks the OIDC button and waits up to 30 seconds for a potential popup
    2. If a popup appears, it's likely a GitHub OAuth reauthorization (as shown in attached screenshot)
    3. Handles the GitHub OAuth authorization in the popup
    4. Falls back to direct navigation if no popup appears
    
    Args:
        page: Main Playwright page object
        context: Browser context for popup detection
        credentials: Dict with GitHub credentials (username, password, otp_secret)
        button_name: Name of the OIDC button to click (default: "Sign in with OIDC Provider")
        screenshots: Optional ScreenshotManager to capture popup screenshots
        
    Raises:
        Exception: For any authentication failures with detailed context
    """
    log.info(f"Clicking '{button_name}' button")
    
    # Handle potential popup for reauthorization
    try:
        log.info("Setting up popup detection with 30-second timeout...")
        with context.expect_page(timeout=30000) as popup_info:
            page.get_by_role("button", name=button_name).click()
            log.info("Button clicked - waiting for potential popup...")
            popup = popup_info.value
        
        # Popup appeared - this is likely GitHub OAuth reauthorization
        log.info(f"Popup detected! URL: {popup.url}")
        
        # Take screenshot of popup for debugging
        if screenshots:
            try:
                log.info("📸 Capturing popup screenshot for debugging...")
                screenshots.capture(popup, popup.url, "GitHub OAuth Reauthorization Popup")
            except Exception as e:
                log.warning(f"Failed to capture popup screenshot: {e}")
        
        # Handle GitHub OAuth in the popup
        if "github.com" in popup.url:
            log.info("GitHub OAuth reauthorization popup detected - handling authorization...")
            popup.wait_for_load_state("networkidle", timeout=10000)
            
            oauth_success = complete_github_oauth_flow(popup, credentials)
            if not oauth_success:
                log.error(f"OAuth authorization failed in popup. URL: {popup.url}")
                raise Exception(f"GitHub OAuth authorization failed in popup - URL: {popup.url}")
            
            log.info("✅ GitHub OAuth authorization completed in popup")
            
            # Wait for popup to close after successful authorization
            try:
                log.info("Waiting for popup to close after authorization...")
                popup.wait_for_event("close", timeout=15000)
                log.info("✅ Popup closed successfully after authorization")
            except Exception as e:
                log.error(f"Popup didn't close after authorization: {e}")
                raise Exception(f"Popup authorization completed but popup didn't close: {e}")
                
        elif "vault" in popup.url and "callback" in popup.url:
            log.info("Vault callback popup detected - waiting for authentication to complete...")
            # This is likely a vault callback completing authentication, just wait for it to close
            try:
                popup.wait_for_event("close", timeout=30000)
                log.info("✅ Vault callback popup closed - authentication completed")
            except Exception as e:
                log.warning(f"Vault callback popup didn't close automatically: {e}")
                log.info("Authentication may have completed anyway, continuing...")
        else:
            log.error(f"Unexpected popup URL: {popup.url}")
            raise Exception(f"Popup appeared with unexpected URL: {popup.url}")
        
    except TimeoutError:
        log.info("No popup appeared - may have redirected directly")
        # Handle direct navigation case
        page.wait_for_timeout(2000)
        if "github.com" in page.url:
            log.info("Redirected to GitHub directly - completing OAuth...")
            oauth_success = complete_github_oauth_flow(page, credentials)
            if not oauth_success:
                log.error(f"OAuth failed on direct redirect. Current URL: {page.url}")
                raise Exception(f"Direct GitHub OAuth authentication failed - URL: {page.url}")
            log.info(f"After direct OAuth, current URL: {page.url}")
    
    page.wait_for_timeout(3000)
    log.info(f"After OIDC authentication, current URL: {page.url}")


# =============================================================================
# BROWSER CONNECTION MANAGEMENT
# =============================================================================

def get_browser_connection():
    """
    Connect to browser - either BrowserBase or local Chrome.
    
    Returns:
        tuple: (playwright, browser, session) where session is None for local Chrome
    """
    use_browserbase = os.environ.get("USE_BROWSERBASE", "false").lower() == "true"
    
    p = sync_playwright().start()
    
    if use_browserbase:
        try:
            log.info("Using BrowserBase remote browser...")
            import requests
            
            api_key = os.environ["BROWSERBASE_API_KEY"]
            project_id = os.environ["BROWSERBASE_PROJECT_ID"]
            
            response = requests.post(
                "https://www.browserbase.com/v1/sessions",
                headers={
                    "x-bb-api-key": api_key,
                    "Content-Type": "application/json"
                },
                json={"projectId": project_id}
            )
            response.raise_for_status()
            session_data = response.json()
            
            session_id = session_data["id"]
            connect_url = f"wss://connect.browserbase.com?apiKey={api_key}&sessionId={session_id}"
            
            browser = p.chromium.connect_over_cdp(connect_url)
            
            log.info("🎥 BrowserBase Session Created!")
            log.info(f"   Session ID: {session_id}")
            log.info(f"   View recording: https://www.browserbase.com/sessions/{session_id}")
            
            return p, browser, session_id
        except Exception as e:
            try:
                p.stop()
            except:
                pass
            raise
    else:
        log.info("Using local Chrome at localhost:9222...")
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        return p, browser, None


def create_incognito_context(browser: Browser) -> BrowserContext:
    """
    Create a fresh incognito browser context for complete isolation.
    
    Args:
        browser: Playwright browser instance
        
    Returns:
        BrowserContext: Fresh isolated browser context
    """
    log.info("Creating fresh incognito context for test isolation...")
    
    context = browser.new_context(
        ignore_https_errors=False,
        accept_downloads=False,
        user_agent=None
    )
    
    log.info("✅ Fresh context created - no cookies or session data")
    return context


def create_new_page(context: BrowserContext) -> Page:
    """
    Create a new page using the browser's default viewport.
    
    Args:
        context: Browser context
        
    Returns:
        Page: New page
    """
    page = context.new_page()
    log.info("Created new page (using browser default viewport)")
    return page


def cleanup_browser(playwright, page: Page, context: BrowserContext, session):
    """
    Clean up browser resources.
    
    Args:
        playwright: Playwright instance
        page: Page to close
        context: Context to close
        session: BrowserBase session (for logging)
    """
    import time
    
    try:
        if page and not page.is_closed():
            log.info("Closing page...")
            page.close()
            time.sleep(0.5)
    except Exception as e:
        log.warning(f"Error closing page: {e}")
    
    try:
        if context:
            log.info("Closing context...")
            context.close()
            time.sleep(0.5)
    except Exception as e:
        log.warning(f"Error closing context: {e}")
    
    log_browserbase_session(session)
    
    try:
        if playwright:
            log.info("Stopping Playwright...")
            playwright.stop()
    except Exception as e:
        log.warning(f"Error stopping Playwright: {e}")


def log_browserbase_session(session):
    """
    Log BrowserBase session information.
    
    Args:
        session: BrowserBase session ID or None
    """
    if session:
        log.info("🎥 BrowserBase Session Recording:")
        log.info(f"   View session at: https://www.browserbase.com/sessions/{session}")
        log.info(f"   Session ID: {session}")


# =============================================================================
# SCREENSHOT UTILITIES
# =============================================================================

def take_screenshot(page: Page, description: str, attach_screenshot_fn) -> Path:
    """
    Take a screenshot and attach it to the test report.
    
    Args:
        page: Playwright page instance
        description: Description for the screenshot
        attach_screenshot_fn: Function from attach_screenshot fixture
        
    Returns:
        Path: Path to the saved screenshot
    """
    screenshot_path = Path("./reports/screenshots") / f"{description.lower().replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(screenshot_path), full_page=True)
    attach_screenshot_fn(screenshot_path, f"SCREENSHOT: {description}")
    return screenshot_path


class ScreenshotManager:
    """
    Centralized screenshot management for UI tests.
    
    Handles screenshot capture with UUID7 filenames, relative path tracking,
    and summary generation for pytest-html reports. Supports visual regression
    testing with baseline comparison.
    """
    
    def __init__(self, screenshots_dir: Optional[str] = None, test_name: Optional[str] = None, request=None):
        """
        Initialize screenshot manager.
        
        Args:
            screenshots_dir: Directory to save screenshots
            test_name: Optional test name prefix
            request: Pytest request fixture
        """
        if screenshots_dir is None:
            if request and hasattr(request, 'config'):
                allure_dir = request.config.getoption("--alluredir", default=None)
                if allure_dir:
                    screenshots_dir = str(Path(allure_dir).parent / "screenshots")
                else:
                    screenshots_dir = "allure-results/screenshots"
            else:
                screenshots_dir = "allure-results/screenshots"
        self.screenshots_dir = Path(screenshots_dir)
        self.test_name = test_name or "test"
        self.screenshots: List[Tuple[str, str, str]] = []
        self.request = request
        
        # Visual regression support
        self.visual_results: List[VisualComparisonResult] = []
        self.baselines_dir = Path("baselines/screenshots")
        self.diffs_dir = Path("allure-results/diffs")
        self.update_baseline_mode = False
        
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
    
    def capture(
        self, 
        page: Page, 
        url: str, 
        description: Optional[str] = None,
        full_page: bool = True,
        baseline_key: Optional[str] = None,
        threshold: Optional[float] = None,
        always_generate_diff: bool = False
    ) -> Path:
        """
        Capture screenshot with optional visual regression baseline comparison.
        
        Args:
            page: Playwright page instance
            url: URL being captured
            description: Optional description for reporting
            full_page: Whether to capture full page (default: True)
            baseline_key: Key for baseline comparison (e.g., "login_page")
                         If provided, enables visual regression testing
            threshold: REQUIRED when baseline_key is set. 
                      Acceptable diff percentage (e.g., 0.1 = 0.1%)
            always_generate_diff: If True, generate diff image even when comparison passes.
                                 Useful for verification/documentation.
                      
        Raises:
            ValueError: If baseline_key provided without threshold
            
        Returns:
            Path: Absolute path to saved screenshot
        """
        # Validate required threshold
        if baseline_key is not None and threshold is None:
            raise ValueError(
                "threshold is required when baseline_key is provided for visual comparison. "
                "Example: capture(page, url, 'Login', baseline_key='login_page', threshold=0.1)"
            )
        
        # Determine filename based on baseline mode
        if baseline_key is not None:
            # Deterministic filename for baseline matching
            screenshot_filename = f"{baseline_key}.png"
        else:
            # UUID-based filename for documentation screenshots
            uuid_suffix = str(uuid.uuid4())[:8]
            base_name = self.test_name.replace(" ", "_").lower()
            screenshot_filename = f"{base_name}_{uuid_suffix}.png"
        
        screenshot_path = self.screenshots_dir / screenshot_filename
        
        log.info(f"📸 Capturing screenshot: {screenshot_filename}")
        screenshot_bytes = page.screenshot(path=str(screenshot_path), full_page=full_page)
        
        desc = description or url
        self.screenshots.append((screenshot_filename, url, desc))
        log.info(f"✅ Screenshot saved: {screenshot_filename}")
        
        # Attach to Allure report immediately
        allure.attach(
            screenshot_bytes,
            name=desc,
            attachment_type=allure.attachment_type.PNG
        )
        
        # Perform visual comparison if baseline_key provided
        if baseline_key is not None:
            # threshold is guaranteed to be float here due to validation above
            assert threshold is not None, "threshold validated above"
            result = self._compare_to_baseline(
                screenshot_path, 
                baseline_key, 
                threshold, 
                desc,
                always_generate_diff
            )
            self.visual_results.append(result)
        
        return screenshot_path.absolute()
    
    def get_relative_path(self, filename: str) -> str:
        """Get relative path for HTML report links."""
        return f"screenshots/{filename}"
    
    def log_summary(self):
        """Log summary of all captured screenshots."""
        if not self.screenshots:
            log.info("No screenshots captured")
            return
        
        log.info("\n" + "="*80)
        log.info(f"📸 SCREENSHOTS CAPTURED: {len(self.screenshots)} total")
        log.info("="*80)
        for i, (filename, url, desc) in enumerate(self.screenshots, 1):
            log.info(f"{i:2d}. {filename:50s} -> {url}")
        log.info("="*80)
    
    def get_screenshot_count(self) -> int:
        """Get total number of screenshots captured."""
        return len(self.screenshots)
    
    def get_screenshots(self) -> List[Tuple[str, str, str]]:
        """Get all captured screenshots metadata."""
        return self.screenshots.copy()

    def _compare_to_baseline(
        self, 
        screenshot_path: Path, 
        baseline_key: str, 
        threshold: float,
        description: str,
        always_generate_diff: bool = False
    ) -> VisualComparisonResult:
        """
        Compare screenshot to baseline or create baseline if missing.
        
        Args:
            screenshot_path: Path to current screenshot
            baseline_key: Baseline key
            threshold: Acceptable diff percentage
            description: Description for logging
            always_generate_diff: Generate diff image even on pass
            
        Returns:
            VisualComparisonResult with comparison details
        """
        try:
            from PIL import Image
            from pixelmatch.contrib.PIL import pixelmatch
        except ImportError as e:
            log.error(f"Visual regression dependencies not installed: {e}")
            log.error("Install with: pip install pixelmatch numpy Pillow")
            raise
        
        # Baseline path: baselines/screenshots/{test_name}/{baseline_key}.png
        baseline_dir = self.baselines_dir / self.test_name
        baseline_path = baseline_dir / f"{baseline_key}.png"
        
        # Update baseline mode - overwrite and return pass
        if self.update_baseline_mode:
            baseline_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy(screenshot_path, baseline_path)
            log.info(f"📝 Updated baseline: {baseline_path}")
            return VisualComparisonResult(
                baseline_key=baseline_key,
                passed=True,
                diff_percent=0.0,
                threshold=threshold,
                diff_image_path=None,
                baseline_created=True
            )
        
        # Baseline missing - create and pass with warning
        if not baseline_path.exists():
            baseline_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy(screenshot_path, baseline_path)
            log.warning(f"⚠️  Baseline missing - created new baseline: {baseline_path}")
            log.warning(f"   This test will PASS. Run again to perform actual comparison.")
            return VisualComparisonResult(
                baseline_key=baseline_key,
                passed=True,
                diff_percent=0.0,
                threshold=threshold,
                diff_image_path=None,
                baseline_created=True
            )
        
        # Load images
        baseline_img = Image.open(baseline_path).convert("RGBA")
        current_img = Image.open(screenshot_path).convert("RGBA")
        
        # Handle size mismatch - still generate a visual comparison
        size_mismatch = baseline_img.size != current_img.size
        if size_mismatch:
            log.error(f"❌ Image size mismatch: baseline {baseline_img.size} vs current {current_img.size}")
            
            # Generate side-by-side comparison for size mismatch
            from PIL import ImageDraw
            
            self.diffs_dir.mkdir(parents=True, exist_ok=True)
            size_mismatch_diff_path = self.diffs_dir / f"{self.test_name}_{baseline_key}_diff.png"
            
            # Create composite showing both images at their original sizes
            b_width, b_height = baseline_img.size
            c_width, c_height = current_img.size
            
            label_height = 60  # Extra height for size info
            max_height = max(b_height, c_height)
            total_width = b_width + c_width
            
            composite = Image.new("RGBA", (total_width, max_height + label_height), color="white")
            
            # Paste images below label area (top-aligned)
            composite.paste(baseline_img, (0, label_height))
            composite.paste(current_img, (b_width, label_height))
            
            # Add labels with size info
            draw = ImageDraw.Draw(composite)
            
            # Draw label backgrounds
            draw.rectangle([(0, 0), (b_width, label_height)], fill="#f0f0f0")
            draw.rectangle([(b_width, 0), (total_width, label_height)], fill="#fff3e0")  # Orange tint for mismatch
            
            # Draw vertical separator
            draw.line([(b_width, 0), (b_width, max_height + label_height)], fill="#cccccc", width=2)
            
            # Draw labels with size info
            draw.text((10, 10), f"BASELINE: {b_width}x{b_height}", fill="black")
            draw.text((b_width + 10, 10), f"CURRENT: {c_width}x{c_height}", fill="#d32f2f")
            draw.text((10, 32), "SIZE MISMATCH - Cannot compute pixel diff", fill="#d32f2f")
            
            composite.save(size_mismatch_diff_path)
            
            # Attach to Allure
            allure.attach.file(
                str(size_mismatch_diff_path),
                name=f"❌ SIZE MISMATCH: {description} (baseline {b_width}x{b_height} vs current {c_width}x{c_height})",
                attachment_type=allure.attachment_type.PNG
            )
            
            log.error(f"   Size mismatch diff saved: {size_mismatch_diff_path}")
            
            return VisualComparisonResult(
                baseline_key=baseline_key,
                passed=False,
                diff_percent=100.0,
                threshold=threshold,
                diff_image_path=size_mismatch_diff_path
            )
        
        # Create diff image
        width, height = baseline_img.size
        diff_img = Image.new("RGBA", (width, height))
        
        # Run pixelmatch
        mismatch_pixels = pixelmatch(
            baseline_img, 
            current_img, 
            diff_img,
            threshold=0.1,  # Anti-aliasing tolerance (0-1 scale)
            includeAA=False  # Don't highlight anti-aliasing differences
        )
        
        total_pixels = width * height
        diff_percent = (mismatch_pixels / total_pixels) * 100
        
        passed = diff_percent <= threshold
        
        log.info(f"{'✅' if passed else '❌'} Visual comparison: {baseline_key}")
        log.info(f"   Diff: {diff_percent:.4f}% (threshold: {threshold}%)")
        log.info(f"   Mismatched pixels: {mismatch_pixels:,} / {total_pixels:,}")
        
        # Save diff image if failed or forced
        diff_image_path: Optional[Path] = None
        if not passed or always_generate_diff:
            from PIL import ImageDraw
            
            self.diffs_dir.mkdir(parents=True, exist_ok=True)
            diff_image_path = self.diffs_dir / f"{self.test_name}_{baseline_key}_diff.png"
            
            # Create side-by-side composite with labels: baseline | current | diff
            label_height = 40  # Height for label bar at top
            composite = Image.new("RGBA", (width * 3, height + label_height), color="white")
            
            # Paste images below label area
            composite.paste(baseline_img, (0, label_height))
            composite.paste(current_img, (width, label_height))
            composite.paste(diff_img, (width * 2, label_height))
            
            # Add labels
            draw = ImageDraw.Draw(composite)
            
            # Draw label backgrounds
            draw.rectangle([(0, 0), (width, label_height)], fill="#f0f0f0")
            draw.rectangle([(width, 0), (width * 2, label_height)], fill="#f0f0f0")
            draw.rectangle([(width * 2, 0), (width * 3, label_height)], fill="#f0f0f0")
            
            # Draw vertical separators
            draw.line([(width, 0), (width, height + label_height)], fill="#cccccc", width=2)
            draw.line([(width * 2, 0), (width * 2, height + label_height)], fill="#cccccc", width=2)
            
            # Draw labels (using default font for maximum compatibility)
            # Position text at top-left of each panel with padding
            draw.text((10, 10), "BASELINE", fill="black")
            draw.text((width + 10, 10), "CURRENT", fill="black")
            
            # Diff label with percentage
            diff_color = "#d32f2f" if not passed else "#388e3c"  # Red if failed, green if passed
            draw.text((width * 2 + 10, 10), f"DIFF: {diff_percent:.4f}%", fill=diff_color)
            
            composite.save(diff_image_path)
            
            # Attach to Allure with appropriate status
            status_icon = "❌" if not passed else "✅"
            log_fn = log.error if not passed else log.info
            allure.attach.file(
                str(diff_image_path),
                name=f"{status_icon} DIFF: {description} ({diff_percent:.4f}% mismatch)",
                attachment_type=allure.attachment_type.PNG
            )
            
            log_fn(f"   Diff image saved: {diff_image_path}")
        
        return VisualComparisonResult(
            baseline_key=baseline_key,
            passed=passed,
            diff_percent=diff_percent,
            threshold=threshold,
            diff_image_path=diff_image_path
        )

    def get_visual_failures(self) -> List[VisualComparisonResult]:
        """
        Get all failed visual comparisons.
        
        Returns:
            List of VisualComparisonResult for failed comparisons
        """
        return [r for r in self.visual_results if not r.passed and not r.baseline_created]


# =============================================================================
# OAUTH FLOW HELPERS
# =============================================================================

def verify_github_oauth_redirect(page: Page, url: str, attach_screenshot_fn, timeout: int = 120000):
    """
    Navigate to a URL and verify it redirects to GitHub OAuth login.
    
    Args:
        page: Playwright page instance
        url: URL to navigate to
        attach_screenshot_fn: Function from attach_screenshot fixture
        timeout: Navigation timeout in milliseconds
        
    Returns:
        bool: True if redirected to GitHub login
    """
    log.info(f"Navigating to {url}...")
    page.goto(url, wait_until="load", timeout=timeout)
    
    max_attempts = 10
    for attempt in range(max_attempts):
        current_url = page.url
        log.info(f"Attempt {attempt + 1}/{max_attempts} - Current URL: {current_url}")
        
        if "github.com/login" in current_url:
            log.info("✅ Successfully redirected to GitHub OAuth login")
            take_screenshot(page, f"GitHub OAuth - {url.split('//')[-1].split('/')[0]}", attach_screenshot_fn)
            return True
        elif "oauth2" in current_url and "/oauth2/start" in current_url:
            log.info("📍 At oauth2-proxy, waiting for GitHub redirect...")
            page.wait_for_timeout(1000)
        else:
            page.wait_for_timeout(500)
    
    final_url = page.url
    is_github = "github.com/login" in final_url
    
    if not is_github:
        log.warning(f"❌ Did not redirect to GitHub login after {max_attempts} attempts. Final URL: {final_url}")
        take_screenshot(page, f"Not GitHub - {url.split('//')[-1].split('/')[0]}", attach_screenshot_fn)
    
    return is_github


def complete_github_oauth_flow(page: Page, credentials: dict):
    """
    Complete the full GitHub OAuth flow after being redirected to GitHub.
    
    Args:
        page: Playwright page object (should be on a GitHub page)
        credentials: Dict with 'username', 'password', 'otp_secret' keys
    
    Returns:
        bool: True if OAuth flow completed successfully
    """
    current_url = page.url
    log.info(f"Starting GitHub OAuth flow from URL: {current_url}")
    
    # Already on OAuth authorization page
    if "github.com/login/oauth/authorize" in current_url:
        log.info("Already on GitHub OAuth authorization page - looking for Authorize button...")
        try:
            authorize_button = page.locator("button[type='submit']:has-text('Authorize')").first
            authorize_button.click(timeout=5000)
            page.wait_for_load_state("networkidle")
            log.info("✅ OAuth authorization granted")
            return True
        except Exception as e:
            log.warning(f"Could not find/click Authorize button: {e}")
            return False
    
    # On GitHub login page
    elif "github.com/login" in current_url or "github.com/sessions" in current_url:
        log.info("On GitHub login page - completing authentication...")
        
        try:
            page.get_by_role("textbox", name="Username or email address").fill(credentials["username"])
            page.get_by_role("textbox", name="Password").fill(credentials["password"])
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.wait_for_load_state("networkidle")
            
            # Handle OTP if requested
            try:
                otp_field = page.get_by_role("textbox", name="Enter the verification code")
                otp_field.wait_for(state="visible", timeout=5000)
                
                totp = pyotp.TOTP(credentials["otp_secret"])
                otp_code = totp.now()
                log.info(f"GitHub OTP challenge detected - generated code: {otp_code}")
                otp_field.fill(otp_code)
                page.wait_for_load_state("networkidle", timeout=15000)
                log.info("✅ OTP submitted successfully")
            except Exception:
                log.info("No OTP requested")
            
            # Handle passkeys prompt
            try:
                dont_ask_button = page.get_by_role("button", name="Don't ask again for this browser")
                dont_ask_button.wait_for(state="visible", timeout=5000)
                log.info("Passkeys prompt detected - clicking 'Don't ask again for this browser'")
                dont_ask_button.click()
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            
            page.wait_for_timeout(2000)
            
            if "github.com/login/oauth/authorize" in page.url:
                log.info("Reached OAuth authorization page - looking for Authorize button...")
                try:
                    authorize_button = page.locator("button[type='submit']:has-text('Authorize')").first
                    authorize_button.click(timeout=5000)
                    page.wait_for_load_state("networkidle", timeout=15000)
                    log.info("✅ OAuth authorization granted")
                    return True
                except Exception as e:
                    log.warning(f"Could not find/click Authorize button: {e}")
                    return False
            elif "github.com" not in page.url:
                log.info(f"✅ Already redirected back to service - URL: {page.url}")
                return True
            else:
                log.info(f"✅ Authentication completed - current URL: {page.url}")
                return True
                
        except Exception as e:
            log.error(f"Error during GitHub login: {e}")
            return False
    
    else:
        log.warning(f"Unexpected URL - not a GitHub OAuth or login page: {current_url}")
        return False


def login_to_service_via_github_sso(
    page: Page,
    context: BrowserContext,
    service_url: str,
    service_name: str,
    credentials: dict,
    sso_button_config: dict,
    success_url_pattern: Optional[str] = None,
    success_check_fn = None
):
    """
    Centralized function to login to any service via GitHub SSO.
    
    Args:
        page: Playwright page object
        context: Browser context
        service_url: URL to navigate to
        service_name: Name of service for logging
        credentials: Dict with GitHub credentials
        sso_button_config: Dict with SSO button configuration
        success_url_pattern: Optional URL pattern to wait for
        success_check_fn: Optional function to verify login success
    
    Returns:
        bool: True if login successful
    """
    log.info(f"="*60)
    log.info(f"Starting {service_name} login via GitHub SSO")
    log.info(f"="*60)
    
    try:
        log.info(f"Navigating to {service_name} at {service_url}...")
        page.goto(service_url)
        page.wait_for_load_state("networkidle")
        log.info(f"After navigation, current URL: {page.url}")
        
        if "github.com" in page.url:
            log.info(f"Already redirected to GitHub (cookies present) - completing OAuth...")
            complete_github_oauth_flow(page, credentials)
            
            log.info(f"Waiting to return to {service_name}...")
            page.wait_for_load_state("networkidle", timeout=20000)
            log.info(f"Returned to service - URL: {page.url}")
            
        else:
            log.info(f"On {service_name} login page - looking for SSO button/link...")
            
            if sso_button_config.get('role_field'):
                role_config = sso_button_config['role_field']
                log.info(f"Filling role field: {role_config['name']} = {role_config['value']}")
                role_field = page.get_by_role("textbox", name=role_config['name'])
                role_field.fill(role_config['value'])
            
            button_type = sso_button_config['type']
            button_name = sso_button_config['name']
            
            if button_type == 'button_with_popup':
                log.info(f"Setting up popup handler for {service_name}...")
                popup_pages = []
                
                def handle_page(new_page):
                    popup_pages.append(new_page)
                    log.info(f"Popup detected! URL: {new_page.url}")
                
                context.on("page", handle_page)
                
                page.get_by_role("button", name=button_name).click()
                log.info(f"Clicked '{button_name}' - waiting for popup...")
                
                page.wait_for_timeout(3000)
                
                if popup_pages:
                    popup_page = popup_pages[0]
                    log.info(f"Handling OAuth in popup - URL: {popup_page.url}")
                    
                    try:
                        if not popup_page.is_closed() and "github.com" in popup_page.url:
                            popup_page.wait_for_load_state("networkidle", timeout=5000)
                            complete_github_oauth_flow(popup_page, credentials)
                            log.info("OAuth completed in popup")
                        else:
                            log.info(f"Popup already closed or on callback: {popup_page.url}")
                    except Exception as e:
                        log.info(f"Popup handling: {e}")
                
                context.remove_listener("page", handle_page)
                
            elif button_type == 'button':
                page.get_by_role("button", name=button_name).click()
                log.info(f"Clicked button '{button_name}'")
                page.wait_for_load_state("networkidle")
                log.info(f"After clicking, URL: {page.url}")
                
                if "github.com" in page.url:
                    complete_github_oauth_flow(page, credentials)
                
            elif button_type == 'link':
                page.get_by_role("link", name=button_name).click()
                log.info(f"Clicked link '{button_name}'")
                page.wait_for_load_state("networkidle")
                log.info(f"After clicking, URL: {page.url}")
                
                if "github.com" in page.url:
                    complete_github_oauth_flow(page, credentials)
                
                if "/login" in page.url and page.url.count("grafana") > 0:
                    log.info("Still on login page - trying SSO link again...")
                    try:
                        page.get_by_role("link", name=button_name).click(timeout=2000)
                        page.wait_for_load_state("networkidle")
                        if "github.com" in page.url:
                            complete_github_oauth_flow(page, credentials)
                    except:
                        pass
        
        log.info(f"Waiting for {service_name} to finish loading...")
        page.wait_for_load_state("networkidle", timeout=15000)
        
        if success_url_pattern:
            log.info(f"Waiting for URL pattern: {success_url_pattern}")
            page.wait_for_url(success_url_pattern, timeout=10000)
        
        if success_check_fn:
            log.info(f"Running custom success check...")
            if not success_check_fn(page):
                log.error(f"Success check failed for {service_name}")
                return False
        
        log.info(f"✅ Successfully logged into {service_name}")
        log.info(f"Final URL: {page.url}")
        return True
        
    except Exception as e:
        log.error(f"❌ Error logging into {service_name}: {e}")
        return False


# =============================================================================
# FRESH AUTHENTICATED PAGE FACTORY
# =============================================================================

def create_authenticated_page(
    browser: Browser,
    service: str,
    credentials: dict,
    captain_domain: Optional[str] = None
) -> tuple:
    """
    Create a fresh browser context and authenticate to a service.
    
    Each call creates a completely isolated browser context with its own
    cookies and session state. This allows multiple authenticated sessions
    to different services simultaneously.
    
    Args:
        browser: Playwright browser instance
        service: Service to authenticate to. One of:
            - 'github': Direct GitHub login (github.com/login)
            - 'argocd': ArgoCD via GitHub SSO
            - 'grafana': Grafana via GitHub SSO
        credentials: Dict with 'username', 'password', 'otp_secret' keys
        captain_domain: Required for argocd/grafana (e.g., 'nonprod.jupiter.onglueops.rocks')
        
    Returns:
        tuple: (page, context) - Both must be closed by caller when done
        
    Example:
        page, context = create_authenticated_page(browser, 'github', creds)
        page.goto("https://github.com/org/repo/pull/1")
        screenshots.capture(page, page.url, "PR Page")
        context.close()  # Clean up when done
    """
    log.info(f"🔐 Creating fresh authenticated page for: {service}")
    
    # Create isolated context
    context = browser.new_context(ignore_https_errors=False)
    page = context.new_page()
    
    if service == 'github':
        log.info("   Authenticating to GitHub directly...")
        page.goto("https://github.com/login", wait_until="load", timeout=30000)
        complete_github_oauth_flow(page, credentials)
        page.wait_for_timeout(2000)
        
        if "/login" in page.url or "/sessions" in page.url:
            context.close()
            raise Exception(f"GitHub login failed - still on login page: {page.url}")
        
        log.info(f"   ✓ GitHub authenticated - URL: {page.url}")
        
    elif service == 'argocd':
        if not captain_domain:
            context.close()
            raise ValueError("captain_domain required for ArgoCD authentication")
        
        log.info(f"   Authenticating to ArgoCD via GitHub SSO...")
        url = f"https://argocd.{captain_domain}/applications"
        page.goto(url, wait_until="load", timeout=30000)
        
        # Handle GitHub OAuth if redirected
        if "github.com" in page.url:
            complete_github_oauth_flow(page, credentials)
            page.wait_for_timeout(3000)
        
        # If on login page, click SSO button
        if "/login" in page.url:
            try:
                page.get_by_role("button", name="Log in via GitHub SSO").click()
                page.wait_for_timeout(5000)
                if "github.com" in page.url:
                    complete_github_oauth_flow(page, credentials)
                    page.wait_for_timeout(3000)
            except Exception:
                pass
        
        # Navigate to service one final time
        page.goto(url, wait_until="load", timeout=30000)
        page.wait_for_timeout(3000)
        log.info(f"   ✓ ArgoCD authenticated - URL: {page.url}")
        
    elif service == 'grafana':
        if not captain_domain:
            context.close()
            raise ValueError("captain_domain required for Grafana authentication")
        
        log.info(f"   Authenticating to Grafana via GitHub SSO...")
        url = f"https://grafana.{captain_domain}"
        page.goto(url, wait_until="load", timeout=30000)
        
        # Handle GitHub OAuth if redirected
        if "github.com" in page.url:
            complete_github_oauth_flow(page, credentials)
            page.wait_for_timeout(3000)
        
        # If on login page, click SSO link
        if "/login" in page.url:
            try:
                page.get_by_role("link", name="Sign in with GitHub SSO").click()
                page.wait_for_timeout(5000)
                if "github.com" in page.url:
                    complete_github_oauth_flow(page, credentials)
                    page.wait_for_timeout(3000)
            except Exception:
                pass
        
        # Navigate to service one final time
        page.goto(url, wait_until="load", timeout=30000)
        page.wait_for_timeout(3000)
        log.info(f"   ✓ Grafana authenticated - URL: {page.url}")
        
    else:
        context.close()
        raise ValueError(f"Unknown service: {service}. Must be 'github', 'argocd', or 'grafana'")
    
    return page, context
