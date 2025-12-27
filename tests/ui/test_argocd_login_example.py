"""
Example test demonstrating ArgoCD login via GitHub OAuth.

This test shows how to handle OAuth flows where services (like ArgoCD)
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
def test_argocd_login_via_github(page, github_credentials, captain_domain, request):
    """
    Test ArgoCD login via GitHub OAuth flow.
    
    This test demonstrates:
    1. Navigate to ArgoCD (which redirects to GitHub OAuth)
    2. Complete GitHub login (automatically handles credentials and OTP)
    3. Handle OAuth authorization if needed
    4. Get redirected back to ArgoCD
    5. Verify successful login to ArgoCD
    6. Take screenshot of logged-in state
    
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
        pytest tests/ui/test_argocd_login_example.py::test_argocd_login_via_github -v -s
    """
    # Build ArgoCD URLs using captain_domain
    argocd_url = f"https://argocd.{captain_domain}"
    argocd_applications_url = f"{argocd_url}/applications"
    
    # Navigate directly to applications page - will redirect to login if needed
    log.info(f"Navigating to ArgoCD applications page: {argocd_applications_url}")
    page.goto(argocd_applications_url, wait_until="load", timeout=30000)
    log.info(f"After navigation, current URL: {page.url}")
    
    # Handle GitHub OAuth if redirected
    if "github.com" in page.url:
        log.info("Redirected to GitHub - completing OAuth...")
        from tests.helpers.browser import complete_github_oauth_flow
        complete_github_oauth_flow(page, github_credentials)
        log.info(f"After OAuth, current URL: {page.url}")
        # Wait for any redirects to complete
        page.wait_for_timeout(3000)
    
    # If we ended up on login page, click the SSO button
    if "/login" in page.url:
        log.info("On ArgoCD login page - clicking 'Log in via GitHub SSO' button")
        page.get_by_role("button", name="Log in via GitHub SSO").click()
        log.info("Clicked SSO button, waiting for redirect...")
        page.wait_for_timeout(5000)  # Give time for redirect to start
        
        # If redirected to GitHub again, complete OAuth
        if "github.com" in page.url:
            log.info("Redirected to GitHub again - completing OAuth...")
            from tests.helpers.browser import complete_github_oauth_flow
            complete_github_oauth_flow(page, github_credentials)
            log.info(f"After second OAuth, current URL: {page.url}")
            page.wait_for_timeout(3000)
    
    # Now navigate to applications page one final time
    log.info(f"Final navigation to applications page: {argocd_applications_url}")
    page.goto(argocd_applications_url, wait_until="load", timeout=30000)
    log.info(f"Final URL: {page.url}")
    
    # Wait for applications to load (ArgoCD uses websockets so networkidle won't work)
    page.wait_for_timeout(5000)
    
    # Verify we're on the applications page
    if "/applications" not in page.url:
        log.error(f"Not on applications page. Current URL: {page.url}")
        raise Exception(f"Failed to reach applications page. Current URL: {page.url}")
    
    log.info("✅ ArgoCD applications page fully loaded")
    
    # Initialize screenshot manager and capture final state
    screenshot_manager = ScreenshotManager(test_name="argocd_login", request=request)
    screenshot_manager.capture(page, page.url, description="ArgoCD Applications Page")
    
    # Log summary
    screenshot_manager.log_summary()
