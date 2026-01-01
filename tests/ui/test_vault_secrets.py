"""
Test Vault secrets creation and viewing.

This test creates secrets via Vault API, then verifies they can be viewed in the Vault UI.

Required environment variables:
- GITHUB_USERNAME: GitHub username or email
- GITHUB_PASSWORD: GitHub password
- GITHUB_OTP_SECRET: TOTP secret key for 2FA
- CAPTAIN_DOMAIN: The captain domain (e.g., nonprod.foobar.onglueops.rocks)
"""

import logging
import pytest
import uuid
from datetime import datetime

log = logging.getLogger(__name__)


@pytest.mark.authenticated
@pytest.mark.visual
@pytest.mark.ui
@pytest.mark.write
def test_vault_secrets(vault_client, authenticated_vault_page, captain_domain, screenshots, github_credentials):
    """Test Vault secrets creation and UI viewing.
    
    This test:
    1. Creates 5 test secrets via Vault API
    2. Authenticates to Vault UI
    3. Navigates to secrets list page
    4. Takes screenshot showing created secrets
    """
    page = authenticated_vault_page
    
    # Generate test secret names with guid-YYYYMMDD format
    date_suffix = datetime.now().strftime("%Y%m%d")
    secret_names = []
    
    log.info("\n" + "="*70)
    log.info("Creating test secrets in Vault...")
    log.info("="*70)
    
    for i in range(1, 6):
        guid = str(uuid.uuid4())[:8]
        secret_name = f"test-secret-{i}-{guid}-{date_suffix}"
        secret_names.append(secret_name)
        
        # Create secret at top level
        log.info(f"Creating secret: {secret_name}")
        vault_client.secrets.kv.v2.create_or_update_secret(
            path=secret_name,
            secret={
                "key": f"value-{i}",
                "created_by": "automated-test",
                "timestamp": datetime.now().isoformat()
            }
        )
    
    log.info(f"✅ Created {len(secret_names)} test secrets")
    log.info("="*70 + "\n")
    
    # Check if we need to complete Vault authentication
    if "/auth" in page.url or page.url.endswith("/ui/"):
        log.info("Completing Vault authentication...")
        page.get_by_role("textbox", name="Role").fill("reader")
        page.wait_for_timeout(1000)
        
        # Use real GitHub credentials for popup authentication
        from tests.helpers.browser import handle_vault_oidc_popup_auth
        handle_vault_oidc_popup_auth(page, page.context, github_credentials, screenshots=screenshots)
    
    # The authenticated_vault_page fixture navigates to /ui/vault/secrets
    # We need to navigate to the secrets list instead
    secrets_list_url = f"https://vault.{captain_domain}/ui/vault/secrets/secret/list"
    
    log.info(f"Navigating to secrets list: {secrets_list_url}")
    page.goto(secrets_list_url, wait_until="networkidle", timeout=60000)
    
    # Wait for secrets to load in UI
    log.info("Waiting for secrets list to render...")
    page.wait_for_timeout(5000)
    
    # Verify we're on the secrets list page  
    if "vault" not in page.url or "secrets" not in page.url:
        log.error(f"Not on Vault secrets list page. Current URL: {page.url}")
        raise Exception(f"Failed to load Vault secrets list. Current URL: {page.url}")
    
    log.info("✅ Vault secrets list page loaded successfully")
    log.info(f"   Created secrets: {', '.join(secret_names)}")
    
    # Capture screenshot showing the secrets with visual regression baseline
    screenshots.capture(
        page, page.url,
        description="Vault Secrets List",
        baseline_key="vault_secrets_list",
        threshold=0.0
    )
    
    # Assert no visual regressions
    assert not screenshots.get_visual_failures(), "Visual regression detected in Vault secrets list"
    
    # Cleanup: Delete test secrets
    log.info("\n🧹 Cleaning up test secrets...")
    for secret_name in secret_names:
        try:
            vault_client.secrets.kv.v2.delete_metadata_and_all_versions(path=secret_name)
            log.info(f"   Deleted: {secret_name}")
        except Exception as e:
            log.warning(f"   Failed to delete {secret_name}: {e}")
    
    log.info("✅ Cleanup complete\n")
