"""Shared helpers for UI tests."""
import os
import logging
import pyotp
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

log = logging.getLogger(__name__)


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
            
            # Create session via REST API (sync)
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
            # Clean up playwright instance if session creation fails
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
    
    Creates a new context for each test to ensure no cookies, storage,
    or session data carries over between tests.
    
    Args:
        browser: Playwright browser instance
        
    Returns:
        BrowserContext: Fresh isolated browser context
    """
    log.info("Creating fresh incognito context for test isolation...")
    
    # Create a completely fresh context with no persistence
    context = browser.new_context(
        ignore_https_errors=False,
        accept_downloads=False,
        user_agent=None  # Use default
    )
    
    log.info("✅ Fresh context created - no cookies or session data")
    return context


def create_new_page(context: BrowserContext) -> Page:
    """
    Create a new page using the browser's default viewport.
    
    When connected via CDP, the viewport is determined by the Chrome window size.
    
    Args:
        context: Browser context
        
    Returns:
        Page: New page
    """
    page = context.new_page()
    log.info("Created new page (using browser default viewport)")
    return page


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


def verify_github_oauth_redirect(page: Page, url: str, attach_screenshot_fn, timeout: int = 120000):
    """
    Navigate to a URL and verify it redirects to GitHub OAuth login.
    
    Each test gets a fresh browser context with no cookies or session data,
    so no explicit cookie clearing is needed before navigation.
    
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
    
    # Wait for OAuth redirect chain to complete (oauth2-proxy -> github)
    # Check multiple times as redirects can take a moment
    max_attempts = 10
    for attempt in range(max_attempts):
        current_url = page.url
        log.info(f"Attempt {attempt + 1}/{max_attempts} - Current URL: {current_url}")
        
        # Check if we're at GitHub login or oauth2-proxy
        if "github.com/login" in current_url:
            log.info("✅ Successfully redirected to GitHub OAuth login")
            take_screenshot(page, f"GitHub OAuth - {url.split('//')[-1].split('/')[0]}", attach_screenshot_fn)
            return True
        elif "oauth2" in current_url and "/oauth2/start" in current_url:
            log.info("📍 At oauth2-proxy, waiting for GitHub redirect...")
            page.wait_for_timeout(1000)
        else:
            # Wait a bit and check again
            page.wait_for_timeout(500)
    
    # Final check
    final_url = page.url
    is_github = "github.com/login" in final_url
    
    if not is_github:
        log.warning(f"❌ Did not redirect to GitHub login after {max_attempts} attempts. Final URL: {final_url}")
        take_screenshot(page, f"Not GitHub - {url.split('//')[-1].split('/')[0]}", attach_screenshot_fn)
    
    return is_github


def log_browserbase_session(session):
    """
    Log BrowserBase session information at the end of a test.
    
    Args:
        session: BrowserBase session ID (string) or None
    """
    if session:
        log.info("🎥 BrowserBase Session Recording:")
        log.info(f"   View session at: https://www.browserbase.com/sessions/{session}")
        log.info(f"   Session ID: {session}")


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
    
    # Close page first
    try:
        if page and not page.is_closed():
            log.info("Closing page...")
            page.close()
            time.sleep(0.5)  # Give it a moment to clean up
    except Exception as e:
        log.warning(f"Error closing page: {e}")
    
    # Then close context
    try:
        if context:
            log.info("Closing context...")
            context.close()
            time.sleep(0.5)  # Give it a moment to clean up
    except Exception as e:
        log.warning(f"Error closing context: {e}")
    
    # Log session info if applicable
    log_browserbase_session(session)
    
    # Stop playwright last
    try:
        if playwright:
            log.info("Stopping Playwright...")
            playwright.stop()
    except Exception as e:
        log.warning(f"Error stopping Playwright: {e}")


def login_to_service_via_github_sso(
    page: Page,
    context: BrowserContext,
    service_url: str,
    service_name: str,
    credentials: dict,
    sso_button_config: dict,
    success_url_pattern: str = None,
    success_check_fn = None
):
    """
    Centralized function to login to any service via GitHub SSO.
    
    This handles the complete flow:
    1. Navigate to service login page
    2. Click SSO button/link (handles both buttons and links, and popups)
    3. Complete GitHub OAuth (login, OTP, authorization)
    4. Wait for redirect back to service
    5. Verify logged in
    
    Args:
        page: Playwright page object
        context: Browser context (needed for popup handling)
        service_url: URL to navigate to (e.g., "https://argocd.example.com/login")
        service_name: Name of service for logging (e.g., "ArgoCD", "Grafana", "Vault")
        credentials: Dict with GitHub credentials {'username', 'password', 'otp_secret'}
        sso_button_config: Dict with SSO button configuration:
            - 'type': 'button' or 'link' or 'button_with_popup'
            - 'name': Button/link text (e.g., "Log in via GitHub SSO")
            - 'role_field': Optional - dict with {'name': 'Role', 'value': 'reader'} for Vault-like services
        success_url_pattern: Optional - URL pattern to wait for (e.g., "**/applications")
        success_check_fn: Optional - Function to verify login success (takes page as arg, returns bool)
    
    Returns:
        bool: True if login successful, False otherwise
    """
    log.info(f"="*60)
    log.info(f"Starting {service_name} login via GitHub SSO")
    log.info(f"="*60)
    
    try:
        # Navigate to service
        log.info(f"Navigating to {service_name} at {service_url}...")
        page.goto(service_url)
        page.wait_for_load_state("networkidle")
        log.info(f"After navigation, current URL: {page.url}")
        
        # Check if already redirected to GitHub (cookies from previous test)
        if "github.com" in page.url:
            log.info(f"Already redirected to GitHub (cookies present) - completing OAuth...")
            complete_github_oauth_flow(page, credentials)
            
            # Wait for redirect back to service
            log.info(f"Waiting to return to {service_name}...")
            page.wait_for_load_state("networkidle", timeout=20000)
            log.info(f"Returned to service - URL: {page.url}")
            
        else:
            # Still on service login page - need to click SSO button/link
            log.info(f"On {service_name} login page - looking for SSO button/link...")
            
            # Fill in role field if specified (for Vault-like services)
            if sso_button_config.get('role_field'):
                role_config = sso_button_config['role_field']
                log.info(f"Filling role field: {role_config['name']} = {role_config['value']}")
                role_field = page.get_by_role("textbox", name=role_config['name'])
                role_field.fill(role_config['value'])
            
            button_type = sso_button_config['type']
            button_name = sso_button_config['name']
            
            if button_type == 'button_with_popup':
                # Vault-style: button opens popup
                log.info(f"Setting up popup handler for {service_name}...")
                popup_pages = []
                
                def handle_page(new_page):
                    popup_pages.append(new_page)
                    log.info(f"Popup detected! URL: {new_page.url}")
                
                context.on("page", handle_page)
                
                # Click button
                page.get_by_role("button", name=button_name).click()
                log.info(f"Clicked '{button_name}' - waiting for popup...")
                
                # Wait for popup
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
                # ArgoCD-style: button redirects in same page
                page.get_by_role("button", name=button_name).click()
                log.info(f"Clicked button '{button_name}'")
                page.wait_for_load_state("networkidle")
                log.info(f"After clicking, URL: {page.url}")
                
                # Complete GitHub OAuth if redirected
                if "github.com" in page.url:
                    complete_github_oauth_flow(page, credentials)
                
            elif button_type == 'link':
                # Grafana-style: link redirects in same page
                page.get_by_role("link", name=button_name).click()
                log.info(f"Clicked link '{button_name}'")
                page.wait_for_load_state("networkidle")
                log.info(f"After clicking, URL: {page.url}")
                
                # Complete GitHub OAuth if redirected
                if "github.com" in page.url:
                    complete_github_oauth_flow(page, credentials)
                
                # Grafana sometimes needs a second click
                if "/login" in page.url and page.url.count("grafana") > 0:
                    log.info("Still on login page - trying SSO link again...")
                    try:
                        page.get_by_role("link", name=button_name).click(timeout=2000)
                        page.wait_for_load_state("networkidle")
                        if "github.com" in page.url:
                            complete_github_oauth_flow(page, credentials)
                    except:
                        pass
        
        # Wait for successful login
        log.info(f"Waiting for {service_name} to finish loading...")
        page.wait_for_load_state("networkidle", timeout=15000)
        
        # Check success condition
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


def complete_github_oauth_flow(page: Page, credentials: dict):
    """
    Complete the full GitHub OAuth flow after being redirected to GitHub.
    
    This centralized function handles all GitHub OAuth scenarios:
    1. Already on OAuth authorization page (already logged in) - click Authorize
    2. On GitHub login page - login with credentials, handle OTP, then authorize
    3. On GitHub sessions page - similar to login flow
    
    This should be called after clicking an SSO button that redirects to GitHub.
    
    Args:
        page: Playwright page object (should be on a GitHub page)
        credentials: Dict with 'username', 'password', 'otp_secret' keys
    
    Returns:
        bool: True if OAuth flow completed successfully, False otherwise
    """
    current_url = page.url
    log.info(f"Starting GitHub OAuth flow from URL: {current_url}")
    
    # Scenario 1: Already on OAuth authorization page (user is already logged in to GitHub)
    if "github.com/login/oauth/authorize" in current_url:
        log.info("Already on GitHub OAuth authorization page - looking for Authorize button...")
        try:
            # Button text starts with "Authorize " but may have app name after it
            authorize_button = page.locator("button[type='submit']:has-text('Authorize')").first
            authorize_button.click(timeout=5000)
            page.wait_for_load_state("networkidle")
            log.info("✅ OAuth authorization granted")
            return True
        except Exception as e:
            log.warning(f"Could not find/click Authorize button: {e}")
            return False
    
    # Scenario 2: On GitHub login page (need to authenticate first)
    elif "github.com/login" in current_url or "github.com/sessions" in current_url:
        log.info("On GitHub login page - completing authentication...")
        
        try:
            # Fill in credentials
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
            
            # Handle passkeys prompt if shown
            try:
                dont_ask_button = page.get_by_role("button", name="Don't ask again for this browser")
                dont_ask_button.wait_for(state="visible", timeout=5000)
                log.info("Passkeys prompt detected - clicking 'Don't ask again for this browser'")
                dont_ask_button.click()
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            
            # Wait a moment for any redirects to complete
            page.wait_for_timeout(2000)
            
            # Now check if we're on the OAuth authorization page
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
                # Already redirected back to the service
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
