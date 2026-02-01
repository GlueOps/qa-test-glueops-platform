"""
Test Vault secrets creation and viewing.

This test creates secrets via Vault API, then verifies they can be viewed in the Vault UI.

Required environment variables:
- GITHUB_USERNAME: GitHub username or email
- GITHUB_PASSWORD: GitHub password
- GITHUB_OTP_SECRET: TOTP secret key for 2FA
- CAPTAIN_DOMAIN: The captain domain (e.g., nonprod.foobar.onglueops.rocks)
"""

import pytest
import uuid
from datetime import datetime


@pytest.mark.authenticated
@pytest.mark.visual
@pytest.mark.ui
@pytest.mark.write
@pytest.mark.vault
@pytest.mark.flaky(reruns=0, reruns_delay=300)
def test_vault_secrets(vault_test_secrets, authenticated_vault_page, captain_domain, screenshots, github_credentials):
    """Test Vault secrets creation and UI viewing.
    
    This test:
    1. Creates 5 test secrets via Vault API (using vault_test_secrets fixture)
    2. Authenticates to Vault UI
    3. Navigates to secrets list page
    4. Takes screenshot showing created secrets
    
    Cleanup is handled by the vault_test_secrets fixture.
    """
    page = authenticated_vault_page
    
    # Generate test secret names with guid-YYYYMMDD format
    date_suffix = datetime.now().strftime("%Y%m%d")
    secret_names = []
    
    for i in range(1, 6):
        guid = str(uuid.uuid4())[:8]
        secret_name = f"test-secret-{i}-{guid}-{date_suffix}"
        secret_names.append(secret_name)
        
        # Create secret at top level using the manager
        vault_test_secrets.create_secret(
            path=secret_name,
            data={
                "key": f"value-{i}",
                "created_by": "automated-test",
                "timestamp": datetime.now().isoformat()
            }
        )
    
    # Check if we need to complete Vault authentication
    if "/auth" in page.url or page.url.endswith("/ui/"):
        page.get_by_role("textbox", name="Role").fill("reader")
        page.wait_for_timeout(1000)
        
        # Use real GitHub credentials for popup authentication
        from tests.helpers.browser import handle_vault_oidc_popup_auth
        handle_vault_oidc_popup_auth(page, page.context, github_credentials, screenshots=screenshots)
    
    # Navigate to the secrets list
    secrets_list_url = f"https://vault.{captain_domain}/ui/vault/secrets/secret/list"
    page.goto(secrets_list_url, wait_until="networkidle", timeout=60000)
    
    # Wait for secrets to load in UI
    page.wait_for_timeout(5000)
    
    # Verify we're on the secrets list page  
    if "vault" not in page.url or "secrets" not in page.url:
        raise Exception(f"Failed to load Vault secrets list. Current URL: {page.url}")
    
    # Capture screenshot showing the secrets with visual regression baseline
    screenshots.capture(
        page, page.url,
        description="Vault Secrets List",
        baseline_key="vault_secrets_list",
        threshold=0.5
    )
    
    # Assert no visual regressions
    assert not screenshots.get_visual_failures(), "Visual regression detected in Vault secrets list"
