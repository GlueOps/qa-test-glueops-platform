"""
Browser and authenticated page fixtures for GlueOps test suite.

This module provides fixtures for browser automation and authenticated
page access via GitHub OAuth for various platform services.

Fixtures:
    - page: Basic Playwright page fixture with browser connection
    - screenshots: Screenshot manager with automatic summary logging
    - authenticated_argocd_page: ArgoCD page authenticated via GitHub OAuth
    - authenticated_grafana_page: Grafana page authenticated via GitHub OAuth
    - authenticated_vault_page: Vault page authenticated via GitHub OAuth
    - authenticated_cluster_info_page: Cluster-info page authenticated via GitHub OAuth

Helper Functions:
    - _navigate_and_authenticate: Shared OAuth navigation logic
"""
import pytest
import logging
from typing import Callable, Optional

from tests.helpers.browser import (
    get_browser_connection,
    create_incognito_context,
    cleanup_browser,
    complete_github_oauth_flow,
    ScreenshotManager,
)


logger = logging.getLogger(__name__)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _navigate_and_authenticate(
    page,
    service_url: str,
    github_credentials: dict,
    sso_button_locator: Optional[Callable] = None,
    sso_button_role: Optional[str] = None,
    sso_button_name: Optional[str] = None,
    login_path_check: str = "/login"
):
    """
    Navigate to a service and complete GitHub OAuth authentication.
    
    This helper encapsulates the common OAuth flow pattern used by
    all authenticated page fixtures:
    1. Navigate to service URL
    2. If redirected to GitHub, complete OAuth
    3. If on login page, click SSO button and complete OAuth
    4. Navigate back to service URL to confirm authentication
    
    Args:
        page: Playwright page object
        service_url: URL of the service to authenticate to
        github_credentials: Dict with username, password, otp_secret
        sso_button_locator: Optional custom locator function for SSO button
        sso_button_role: Role for get_by_role (e.g., "button", "link")
        sso_button_name: Name for get_by_role
        login_path_check: Path substring to check if on login page
    
    Returns:
        Page: Authenticated page object
    """
    # Navigate to service
    page.goto(service_url, wait_until="load", timeout=30000)
    
    # Handle GitHub OAuth if redirected
    if "github.com" in page.url:
        complete_github_oauth_flow(page, github_credentials)
        page.wait_for_timeout(3000)
    
    # If on login page, click SSO button
    if login_path_check in page.url:
        try:
            if sso_button_locator is not None:
                sso_button_locator(page).click()
            elif sso_button_role is not None and sso_button_name is not None:
                page.get_by_role(sso_button_role, name=sso_button_name).click()
            
            page.wait_for_timeout(5000)
            
            if "github.com" in page.url:
                complete_github_oauth_flow(page, github_credentials)
                page.wait_for_timeout(3000)
        except Exception:
            # Button might not be present if already authenticated
            pass
    
    # Navigate to service one final time to ensure we're there
    page.goto(service_url, wait_until="load", timeout=30000)
    page.wait_for_timeout(3000)
    
    return page


# =============================================================================
# BASIC BROWSER FIXTURES
# =============================================================================

@pytest.fixture
def page(request, captain_domain):
    """Playwright page fixture for UI tests with auto screenshot capture.
    
    This fixture:
    - Creates a browser connection (BrowserBase or local Chrome)
    - Sets up an incognito context for test isolation
    - Exposes the page to pytest-html-plus for automatic screenshot capture
    - Automatically cleans up browser resources after the test
    
    Scope: function (new page per test)
    
    Dependencies:
        - captain_domain: Captain domain for service URLs
    
    Requires: tests.helpers.browser module for browser management
    """
    playwright, browser, session = get_browser_connection()
    context = create_incognito_context(browser)
    page_instance = context.new_page()
    
    # Attach page to request for pytest-html-plus to find it
    request.node.page_for_screenshot = page_instance
    
    yield page_instance
    
    # Cleanup
    cleanup_browser(playwright, page_instance, context, session)


@pytest.fixture
def screenshots(request):
    """
    Screenshot manager with automatic summary logging.
    
    Creates a ScreenshotManager configured for the current test and
    automatically logs a summary of all captured screenshots on teardown.
    
    Scope: function
    
    Returns:
        ScreenshotManager: Manager instance for capturing screenshots
    
    Usage:
        def test_ui_flow(page, screenshots):
            page.goto("https://example.com")
            screenshots.capture(page, "https://example.com", "Homepage")
            
            page.click("button[name='login']")
            screenshots.capture(page, page.url, "After clicking login")
            
            # Summary automatically logged at test end
    """
    # Extract clean test name
    test_name = request.node.name.replace('test_', '')
    manager = ScreenshotManager(test_name=test_name, request=request)
    
    yield manager
    
    manager.log_summary()


# =============================================================================
# AUTHENTICATED PAGE FIXTURES
# =============================================================================

@pytest.fixture
def authenticated_argocd_page(page, github_credentials, captain_domain):
    """
    Browser page authenticated to ArgoCD via GitHub OAuth.
    
    Handles the complete OAuth flow including:
    - Navigating to ArgoCD
    - Detecting and completing GitHub OAuth login
    - Handling SSO button clicks
    - Managing redirects
    
    Scope: function
    
    Dependencies:
        - page: Playwright page fixture
        - github_credentials: GitHub credentials for OAuth
        - captain_domain: Captain domain for ArgoCD URL
    
    Returns:
        Page: Playwright page object authenticated to ArgoCD
    
    Usage:
        def test_argocd_apps(authenticated_argocd_page):
            # Page is already authenticated and on ArgoCD
            authenticated_argocd_page.goto(f"https://argocd.{captain_domain}/applications")
            # ... perform test actions ...
    """
    argocd_url = f"https://argocd.{captain_domain}/applications"
    
    _navigate_and_authenticate(
        page=page,
        service_url=argocd_url,
        github_credentials=github_credentials,
        sso_button_role="button",
        sso_button_name="Log in via GitHub SSO"
    )
    
    yield page


@pytest.fixture
def authenticated_grafana_page(page, github_credentials, captain_domain):
    """
    Browser page authenticated to Grafana via GitHub OAuth.
    
    Handles the complete OAuth flow including:
    - Navigating to Grafana
    - Detecting and completing GitHub OAuth login
    - Handling SSO link clicks
    - Managing redirects
    
    Scope: function
    
    Dependencies:
        - page: Playwright page fixture
        - github_credentials: GitHub credentials for OAuth
        - captain_domain: Captain domain for Grafana URL
    
    Returns:
        Page: Playwright page object authenticated to Grafana
    
    Usage:
        def test_grafana_dashboards(authenticated_grafana_page):
            # Page is already authenticated and on Grafana
            authenticated_grafana_page.goto(f"https://grafana.{captain_domain}/dashboards")
            # ... perform test actions ...
    """
    grafana_url = f"https://grafana.{captain_domain}"
    
    _navigate_and_authenticate(
        page=page,
        service_url=grafana_url,
        github_credentials=github_credentials,
        sso_button_role="link",
        sso_button_name="Sign in with GitHub SSO"
    )
    
    yield page


@pytest.fixture
def authenticated_vault_page(page, github_credentials, captain_domain):
    """
    Browser page authenticated to Vault via GitHub OAuth.
    
    Handles the complete OAuth flow including:
    - Navigating to Vault
    - Detecting and completing GitHub OAuth login
    - Handling OIDC button clicks
    - Managing redirects
    
    Note: Vault uses OIDC provider button, not GitHub SSO button directly.
    The login check also includes 'method=oidc' to detect auth state.
    
    Scope: function
    
    Dependencies:
        - page: Playwright page fixture
        - github_credentials: GitHub credentials for OAuth
        - captain_domain: Captain domain for Vault URL
    
    Returns:
        Page: Playwright page object authenticated to Vault
    
    Usage:
        def test_vault_ui(authenticated_vault_page):
            # Page is already authenticated and on Vault
            authenticated_vault_page.goto(f"https://vault.{captain_domain}/ui/vault/secrets")
            # ... perform test actions ...
    """
    vault_url = f"https://vault.{captain_domain}/ui/"
    
    # Navigate to Vault
    page.goto(vault_url, wait_until="load", timeout=30000)
    
    # Handle GitHub OAuth if redirected
    if "github.com" in page.url:
        complete_github_oauth_flow(page, github_credentials)
        page.wait_for_timeout(3000)
    
    # Vault has a unique login flow - check for login page or missing OIDC method
    if "/login" in page.url or "method=oidc" not in page.url:
        try:
            page.get_by_role("button", name="Sign in with OIDC Provider").click()
            page.wait_for_timeout(5000)
            
            if "github.com" in page.url:
                complete_github_oauth_flow(page, github_credentials)
                page.wait_for_timeout(3000)
        except Exception:
            # Button might not be present if already authenticated
            pass
    
    # Navigate to Vault one final time to ensure we're there
    page.goto(vault_url, wait_until="load", timeout=30000)
    page.wait_for_timeout(3000)
    
    yield page


@pytest.fixture
def authenticated_cluster_info_page(page, github_credentials, captain_domain):
    """
    Browser page authenticated to cluster-info via GitHub OAuth.
    
    Handles the complete OAuth flow including:
    - Navigating to cluster-info
    - Detecting and completing GitHub OAuth login
    - Managing redirects
    
    Note: Cluster-info doesn't have a separate SSO button - it redirects
    directly to GitHub OAuth when not authenticated.
    
    Scope: function
    
    Dependencies:
        - page: Playwright page fixture
        - github_credentials: GitHub credentials for OAuth
        - captain_domain: Captain domain for cluster-info URL
    
    Returns:
        Page: Playwright page object authenticated to cluster-info
    
    Usage:
        def test_cluster_info(authenticated_cluster_info_page):
            # Page is already authenticated and on cluster-info
            # ... perform test actions ...
    """
    cluster_info_url = f"https://cluster-info.{captain_domain}/"
    
    # Navigate to cluster-info
    page.goto(cluster_info_url, wait_until="load", timeout=30000)
    
    # Handle GitHub OAuth if redirected (cluster-info has direct OAuth redirect)
    if "github.com" in page.url:
        complete_github_oauth_flow(page, github_credentials)
        page.wait_for_timeout(3000)
    
    # Navigate to cluster-info one final time to ensure we're there
    page.goto(cluster_info_url, wait_until="load", timeout=30000)
    page.wait_for_timeout(3000)
    
    yield page
