"""
UI tests for Cluster Info GitHub OAuth redirect functionality.

This module tests that cluster-info redirects to GitHub OAuth login
when accessed in incognito mode.
"""

import logging
import pytest
from tests.ui.helpers import ScreenshotManager

log = logging.getLogger(__name__)


@pytest.mark.oauth_redirect
@pytest.mark.ui
def test_cluster_info_github_oauth_redirect(page, captain_domain, request):
    """
    Test cluster-info redirects to GitHub OAuth login in incognito mode.
    
    - Uses incognito browser context
    - Navigates to cluster-info
    - Verifies redirect to https://github.com/login
    - Screenshots automatically captured on failure by pytest-html-plus
    - Supports BrowserBase and local Chrome
    """
    # Navigate to cluster-info
    cluster_info_url = f"https://cluster-info.{captain_domain}/"
    page.goto(cluster_info_url, wait_until="load", timeout=120000)
    
    # Wait for OAuth redirect chain to complete
    page.wait_for_timeout(3000)
    
    # Initialize screenshot manager
    screenshot_manager = ScreenshotManager(test_name="cluster_info_oauth", request=request)
    
    # Check if we're at GitHub login
    final_url = page.url
    assert "github.com/login" in final_url, f"Cluster-info did not redirect to GitHub OAuth login. Final URL: {final_url}"
    
    # Capture screenshot of GitHub OAuth page
    screenshot_manager.capture(page, final_url, description="GitHub OAuth Login")
    
    # Log summary
    screenshot_manager.log_summary()
