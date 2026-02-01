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

import logging
import pytest

log = logging.getLogger(__name__)


@pytest.mark.authenticated
@pytest.mark.visual
@pytest.mark.ui
@pytest.mark.flaky(reruns=0, reruns_delay=300)
def test_login_to_argocd(authenticated_argocd_page, captain_domain, screenshots):
    """Test ArgoCD login via GitHub OAuth flow.
    
    Uses authenticated_argocd_page fixture which handles the complete OAuth flow.
    
    This test verifies:
    1. OAuth authentication succeeds
    2. ArgoCD applications page loads correctly
    3. Screenshot capture works
    """
    page = authenticated_argocd_page
    argocd_applications_url = f"https://argocd.{captain_domain}/applications"
    
    # Verify we're on the applications page
    if "/applications" not in page.url:
        log.error(f"Not on applications page. Current URL: {page.url}")
        raise Exception(f"Failed to reach applications page. Current URL: {page.url}")
    
    log.info("✅ ArgoCD applications page fully loaded")
    
    # Capture final state with visual regression baseline
    screenshots.capture(
        page, page.url,
        description="ArgoCD Applications Page",
        baseline_key="argocd_applications_page",
        threshold=0.0
    )
    
    # Assert no visual regressions
    assert not screenshots.get_visual_failures(), "Visual regression detected in ArgoCD applications page"
