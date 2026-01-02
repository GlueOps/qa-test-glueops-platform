"""
UI Test Template - Browser Automation with Playwright

Copy this file to tests/ui/ and customize for your test.

Usage:
    cp tests/templates/_test_ui_template.py tests/ui/test_my_ui.py

UI tests require:
1. Chrome running with remote debugging: ./start_chrome.sh
2. Environment variables: GITHUB_USERNAME, GITHUB_PASSWORD, GITHUB_OTP_SECRET
3. CAPTAIN_DOMAIN set to your cluster domain

See tests/ui/CLAUDE.md for comprehensive UI testing guide.
"""
import pytest
import logging

log = logging.getLogger(__name__)


# =============================================================================
# AUTHENTICATED UI TEST - Service login via GitHub OAuth
# =============================================================================
@pytest.mark.ui
@pytest.mark.authenticated
@pytest.mark.visual  # Has visual regression baseline
@pytest.mark.flaky(reruns=1, reruns_delay=300)  # Retry once on failure
def test_example_authenticated_page(authenticated_argocd_page, captain_domain, screenshots):
    """
    Test authenticated access to a service via GitHub OAuth.
    
    Uses authenticated_argocd_page fixture which handles the complete OAuth flow.
    Replace with authenticated_grafana_page or authenticated_vault_page as needed.
    
    Validates:
    - OAuth authentication succeeds
    - Target page loads correctly
    - Visual appearance matches baseline
    
    Cluster Impact: READ-ONLY (views only)
    
    Required Environment Variables:
    - GITHUB_USERNAME: GitHub username or email
    - GITHUB_PASSWORD: GitHub password
    - GITHUB_OTP_SECRET: TOTP secret for 2FA
    - CAPTAIN_DOMAIN: Cluster domain (e.g., nonprod.example.com)
    """
    page = authenticated_argocd_page
    expected_url_fragment = "/applications"
    
    # Verify we're on the expected page
    if expected_url_fragment not in page.url:
        log.error(f"Not on expected page. Current URL: {page.url}")
        raise AssertionError(f"Failed to reach expected page. Current URL: {page.url}")
    
    log.info("✅ Target page fully loaded")
    
    # Capture screenshot with visual regression check
    screenshots.capture(
        page,
        page.url,
        description="ArgoCD Applications Page",
        baseline_key="argocd_applications_page",  # Unique key for baseline
        threshold=0.0  # 0% difference allowed (strict match)
    )
    
    # Assert no visual regressions
    failures = screenshots.get_visual_failures()
    assert not failures, f"Visual regression detected: {failures}"


# =============================================================================
# OAUTH REDIRECT TEST - Verify redirect to GitHub
# =============================================================================
@pytest.mark.ui
@pytest.mark.oauth_redirect
def test_example_oauth_redirect(page, captain_domain):
    """
    Test that a protected service redirects to GitHub for authentication.
    
    Uses unauthenticated `page` fixture (no login performed).
    
    Validates:
    - Service redirects to GitHub OAuth
    - Redirect URL contains expected parameters
    
    Cluster Impact: READ-ONLY
    """
    service_url = f"https://argocd.{captain_domain}"
    
    # Navigate to protected service
    page.goto(service_url, wait_until="domcontentloaded", timeout=30000)
    
    # Should redirect to GitHub
    assert "github.com" in page.url, f"Expected GitHub redirect, got: {page.url}"
    
    log.info(f"✅ {service_url} correctly redirects to GitHub OAuth")


# =============================================================================
# MANUAL LOGIN FLOW - When you need custom OAuth handling
# =============================================================================
@pytest.mark.ui
@pytest.mark.authenticated
def test_example_manual_oauth(page, github_credentials, captain_domain, screenshots):
    """
    Test with manual OAuth flow handling.
    
    Uses raw `page` fixture and handles OAuth manually.
    Useful when you need custom login behavior.
    
    Cluster Impact: READ-ONLY
    """
    from tests.helpers.browser import complete_github_oauth_flow
    
    service_url = f"https://argocd.{captain_domain}"
    
    # Navigate to service
    page.goto(service_url, wait_until="load", timeout=30000)
    
    # Handle OAuth if redirected
    if "github.com" in page.url:
        log.info("Handling GitHub OAuth flow...")
        complete_github_oauth_flow(page, github_credentials)
    
    # Wait for page to fully load after OAuth
    page.wait_for_load_state("networkidle", timeout=30000)
    
    # Capture final state
    screenshots.capture(page, page.url, description="After login")
    
    log.info("✅ Successfully logged in via GitHub OAuth")


# =============================================================================
# PAGE CONTENT VALIDATION - Check specific elements
# =============================================================================
@pytest.mark.ui
@pytest.mark.authenticated
def test_example_content_validation(authenticated_grafana_page, captain_domain):
    """
    Test that specific content appears on the page.
    
    Cluster Impact: READ-ONLY
    """
    page = authenticated_grafana_page
    
    # Wait for specific element
    page.wait_for_selector("[data-testid='dashboard-panel']", timeout=10000)
    
    # Check page title
    title = page.title()
    assert "Grafana" in title, f"Expected 'Grafana' in title, got: {title}"
    
    # Check for specific text content
    body_text = page.locator("body").inner_text()
    assert "Home" in body_text, "Expected 'Home' link on dashboard"
    
    log.info("✅ Dashboard content validated")


# =============================================================================
# PARAMETERIZED UI TEST - Test multiple services
# =============================================================================
@pytest.mark.ui
@pytest.mark.oauth_redirect
@pytest.mark.parametrize("service,expected_path", [
    ("argocd", "/applications"),
    ("grafana", "/login"),
    ("vault", "/ui/vault/auth"),
])
def test_example_parameterized(page, captain_domain, service, expected_path):
    """
    Test OAuth redirect for multiple services.
    
    Cluster Impact: READ-ONLY
    """
    service_url = f"https://{service}.{captain_domain}"
    
    page.goto(service_url, wait_until="domcontentloaded", timeout=30000)
    
    # Should redirect to GitHub
    assert "github.com" in page.url, f"{service}: Expected GitHub redirect"
    
    log.info(f"✅ {service} correctly redirects to GitHub")
