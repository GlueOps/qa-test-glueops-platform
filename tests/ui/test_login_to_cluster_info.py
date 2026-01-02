"""
Test cluster-info login via GitHub OAuth.

This test shows how to handle OAuth flows where services (like cluster-info)
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
@pytest.mark.flaky(reruns=1, reruns_delay=60)
def test_login_to_cluster_info(authenticated_cluster_info_page, captain_domain, screenshots):
    """Test cluster-info login via GitHub OAuth flow.
    
    Uses authenticated_cluster_info_page fixture which handles the complete OAuth flow.
    
    This test verifies:
    1. OAuth authentication succeeds
    2. Cluster-info page loads correctly
    3. Screenshot capture works
    """
    page = authenticated_cluster_info_page
    cluster_info_url = f"https://cluster-info.{captain_domain}/"
    
    # Verify we're on the cluster-info page
    if "cluster-info" not in page.url:
        log.error(f"Not on cluster-info page. Current URL: {page.url}")
        raise Exception(f"Failed to reach cluster-info page. Current URL: {page.url}")
    
    log.info("✅ Cluster-info page fully loaded")
    
    # Capture final state with visual regression baseline
    screenshots.capture(
        page, page.url,
        description="Cluster Info Landing Page",
        baseline_key="cluster_info_landing",
        threshold=0.0
    )
    
    # Assert no visual regressions
    assert not screenshots.get_visual_failures(), "Visual regression detected in cluster-info page"
