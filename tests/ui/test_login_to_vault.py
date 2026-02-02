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

import logging
import pytest

log = logging.getLogger(__name__)


@pytest.mark.authenticated
@pytest.mark.visual
@pytest.mark.ui
@pytest.mark.flaky(reruns=0, reruns_delay=300)
def test_login_to_vault(page, github_credentials, captain_domain, screenshots):
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
        from tests.helpers.browser import complete_github_oauth_flow
        oauth_success = complete_github_oauth_flow(page, github_credentials)
        if not oauth_success:
            log.error(f"OAuth failed on initial GitHub redirect. Current URL: {page.url}")
            raise Exception(f"Initial GitHub OAuth authentication failed - URL: {page.url}")
        log.info(f"After OAuth, current URL: {page.url}")
        page.wait_for_timeout(3000)
    
    # If we ended up on auth/login page, fill role and click OIDC button
    if "/auth" in page.url or page.url.endswith("/ui/"):
        log.info("On Vault auth page - filling role field and clicking OIDC button")
        page.get_by_role("textbox", name="Role").fill("reader")
        page.wait_for_timeout(1000)
        
        from tests.helpers.browser import handle_vault_oidc_popup_auth
        handle_vault_oidc_popup_auth(page, page.context, github_credentials, screenshots=screenshots)
    
    # Wait for Vault to load
    page.wait_for_timeout(3000)
    
    # Verify we're authenticated (should be on secrets page)
    if "/auth" in page.url or page.url.endswith("/ui/"):
        log.error(f"Still on auth page. Current URL: {page.url}")
        raise Exception("Failed to login to Vault - still on auth page")
    
    log.info("✅ Vault secrets page fully loaded")
    
    # Capture final state with visual regression baseline
    screenshots.capture(
        page, page.url,
        description="Vault Secrets Page",
        baseline_key="vault_secrets_page",
        threshold=1.0
    )
    
    # Assert no visual regressions
    assert not screenshots.get_visual_failures(), "Visual regression detected in Vault secrets page"

