"""
Example test demonstrating Grafana login via GitHub OAuth.

This test shows how to handle OAuth flows where services (like Grafana)
redirect to GitHub for authentication, then redirect back after login.

Required environment variables:
- GITHUB_USERNAME: GitHub username or email
- GITHUB_PASSWORD: GitHub password
- GITHUB_OTP_SECRET: TOTP secret key for 2FA
- CAPTAIN_DOMAIN: The captain domain (e.g., nonprod.foobar.onglueops.rocks)
"""

import os
import logging
import pytest
from tests.helpers.browser import ScreenshotManager

log = logging.getLogger(__name__)


@pytest.mark.authenticated
@pytest.mark.ui
def test_grafana_login_via_github(page, github_credentials, captain_domain, request):
    """
    Test Grafana login via GitHub OAuth flow.
    
    This test demonstrates:
    1. Navigate to Grafana login page
    2. Click "Sign in with GitHub SSO" button
    3. Complete GitHub login (automatically handles credentials and OTP)
    4. Handle OAuth authorization if needed
    5. Get redirected back to Grafana
    6. Verify successful login to Grafana
    7. Take screenshot of logged-in state
    
    The github_credentials fixture automatically reads from environment variables
    and skips the test if they're not set.
    
    Required environment variables:
    - GITHUB_USERNAME: GitHub username or email
    - GITHUB_PASSWORD: GitHub password
    - GITHUB_OTP_SECRET: TOTP secret key for 2FA
    - CAPTAIN_DOMAIN: The captain domain (e.g., nonprod.foobar.onglueops.rocks)
    
    Usage:
        export GITHUB_USERNAME="your-email@example.com"
        export GITHUB_PASSWORD="your-password"
        export GITHUB_OTP_SECRET="your-totp-secret"
        export CAPTAIN_DOMAIN="nonprod.foobar.onglueops.rocks"
        pytest tests/ui/test_grafana_login_example.py::test_grafana_login_via_github -v -s
    """
    # Build Grafana URLs using captain_domain
    grafana_url = f"https://grafana.{captain_domain}"
    grafana_home_url = f"{grafana_url}/"
    
    # Navigate directly to Grafana home page - will redirect to login if needed
    log.info(f"Navigating to Grafana home page: {grafana_home_url}")
    page.goto(grafana_home_url, wait_until="load", timeout=30000)
    log.info(f"After navigation, current URL: {page.url}")
    
    # Handle GitHub OAuth if redirected
    if "github.com" in page.url:
        log.info("Redirected to GitHub - completing OAuth...")
        from tests.helpers.browser import complete_github_oauth_flow
        complete_github_oauth_flow(page, github_credentials)
        log.info(f"After OAuth, current URL: {page.url}")
        page.wait_for_timeout(3000)
    
    # If we ended up on login page, click the SSO link
    if "/login" in page.url:
        log.info("On Grafana login page - clicking 'Sign in with GitHub SSO' link")
        page.get_by_role("link", name="Sign in with GitHub SSO").click()
        log.info("Clicked SSO link, waiting for redirect...")
        page.wait_for_timeout(5000)
        
        # If redirected to GitHub again, complete OAuth
        if "github.com" in page.url:
            log.info("Redirected to GitHub again - completing OAuth...")
            from tests.helpers.browser import complete_github_oauth_flow
            complete_github_oauth_flow(page, github_credentials)
            log.info(f"After second OAuth, current URL: {page.url}")
            page.wait_for_timeout(3000)
    
    # Now navigate to home page one final time
    log.info(f"Final navigation to home page: {grafana_home_url}")
    page.goto(grafana_home_url, wait_until="load", timeout=30000)
    log.info(f"Final URL: {page.url}")
    
    # Wait for Grafana to load
    page.wait_for_timeout(5000)
    
    # Verify we're not stuck on login page
    if "/login" in page.url:
        log.error(f"Still on login page. Current URL: {page.url}")
        raise Exception("Failed to login to Grafana - still on login page")
    
    log.info("✅ Grafana home page fully loaded")
    
    # Initialize screenshot manager and capture final state
    screenshot_manager = ScreenshotManager(test_name="grafana_login", request=request)
    screenshot_manager.capture(page, page.url, description="Grafana Home Page")
    
    # Log summary
    screenshot_manager.log_summary()
