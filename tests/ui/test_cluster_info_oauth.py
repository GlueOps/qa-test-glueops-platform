"""
UI tests for Cluster Info GitHub OAuth redirect functionality.

This module tests that cluster-info redirects to GitHub OAuth login
when accessed in incognito mode.
"""

import logging
import pytest

log = logging.getLogger(__name__)


@pytest.mark.oauth_redirect
@pytest.mark.ui
def test_cluster_info_github_oauth_redirect(page, captain_domain, screenshots):
    """
    Test cluster-info redirects to GitHub OAuth login in incognito mode.
    
    Validates that unauthenticated access to cluster-info triggers OAuth2 flow
    and redirects to GitHub login page.
    
    Environment Variables:
        CAPTAIN_DOMAIN: Cluster domain (e.g., 'nonprod.example.com')
    
    Timeouts:
        - Navigation: 120 seconds
        - OAuth redirect wait: 3 seconds
    
    Fails if final URL does not contain 'github.com/login'.
    
    Cluster Impact: READ-ONLY (browser navigation only)
    """
    # Navigate to cluster-info
    cluster_info_url = f"https://cluster-info.{captain_domain}/"
    page.goto(cluster_info_url, wait_until="load", timeout=120000)
    
    # Wait for OAuth redirect chain to complete
    page.wait_for_timeout(3000)
    
    # Check if we're at GitHub login
    final_url = page.url
    assert "github.com/login" in final_url, f"Cluster-info did not redirect to GitHub OAuth login. Final URL: {final_url}"
    
    # Capture screenshot of GitHub OAuth page (fixture handles summary logging)
    screenshots.capture(page, final_url, description="GitHub OAuth Login")
