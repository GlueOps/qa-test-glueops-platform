"""
Example test demonstrating Vault login via GitHub OAuth.

This test shows how to handle OAuth flows where services (like Vault)
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
from tests.ui.helpers import (
    get_browser_connection,
    create_incognito_context,
    create_new_page,
    take_screenshot,
    cleanup_browser
)

log = logging.getLogger(__name__)


@pytest.fixture
def attach_screenshot(request):
    """Fixture to attach screenshots to test reports."""
    def _attach(screenshot_path, description):
        if not hasattr(request.node, '_screenshots'):
            request.node._screenshots = []
        request.node._screenshots.append((screenshot_path, description))
    return _attach


@pytest.mark.authenticated
@pytest.mark.ui
def test_vault_login_via_github(attach_screenshot, github_credentials, captain_domain):
    """
    Test Vault login via GitHub OAuth flow.
    
    This test demonstrates:
    1. Navigate to Vault login page
    2. Fill in "Role" field with "reader"
    3. Click "Sign in with OIDC Provider" button (may open popup)
    4. Complete GitHub login (automatically handles credentials and OTP)
    5. Handle OAuth authorization if needed
    6. Get redirected back to Vault
    7. Verify successful login to Vault
    8. Take screenshot of logged-in state
    
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
        pytest tests/ui/test_vault_login_example.py::test_vault_login_via_github -v -s
    """
    playwright, browser, session = get_browser_connection()
    
    try:
        # Create incognito context
        context = create_incognito_context(browser)
        page = create_new_page(context)
        
        # Build Vault URL using captain_domain
        vault_url = f"https://vault.{captain_domain}"
        vault_secrets_url = f"{vault_url}/ui/vault/secrets"
        
        # Navigate directly to Vault secrets page - will redirect to login if needed
        log.info(f"Navigating to Vault secrets page: {vault_secrets_url}")
        page.goto(vault_secrets_url, wait_until="load", timeout=30000)
        log.info(f"After navigation, current URL: {page.url}")
        
        # Handle GitHub OAuth if redirected
        if "github.com" in page.url:
            log.info("Redirected to GitHub - completing OAuth...")
            from tests.ui.helpers import complete_github_oauth_flow
            complete_github_oauth_flow(page, github_credentials)
            log.info(f"After OAuth, current URL: {page.url}")
            page.wait_for_timeout(3000)
        
        # If we ended up on auth/login page, fill role and click OIDC button
        if "/auth" in page.url or page.url.endswith("/ui/"):
            log.info("On Vault auth page - filling role field and clicking OIDC button")
            page.get_by_role("textbox", name="Role").fill("reader")
            page.wait_for_timeout(1000)
            log.info("Clicking 'Sign in with OIDC Provider' button")
            
            # Wait for navigation after clicking the button
            with page.expect_navigation(wait_until="load", timeout=30000):
                page.get_by_role("button", name="Sign in with OIDC Provider").click()
            
            log.info(f"After clicking OIDC button, current URL: {page.url}")
            page.wait_for_timeout(3000)
            
            # If redirected to GitHub again, complete OAuth
            if "github.com" in page.url:
                log.info("Redirected to GitHub again - completing OAuth...")
                from tests.ui.helpers import complete_github_oauth_flow
                complete_github_oauth_flow(page, github_credentials)
                log.info(f"After second OAuth, current URL: {page.url}")
                page.wait_for_timeout(3000)
        
        # Wait for Vault to load
        page.wait_for_timeout(3000)
        
        # Verify we're authenticated (should be on secrets page)
        if "/auth" in page.url or page.url.endswith("/ui/"):
            log.error(f"Still on auth page. Current URL: {page.url}")
            take_screenshot(page, "Vault Login Failed", attach_screenshot)
            raise Exception("Failed to login to Vault - still on auth page")
        
        log.info("Vault secrets page fully loaded, taking screenshot...")
        
        # Take screenshot of Vault logged-in page
        take_screenshot(page, "Vault Logged In", attach_screenshot)
        
    finally:
        cleanup_browser(playwright, page, context, session)

