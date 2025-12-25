"""
UI tests for Cluster Info GitHub OAuth redirect functionality.

This module tests that cluster-info redirects to GitHub OAuth login
when accessed in incognito mode.
"""

import logging
import pytest
from tests.ui.helpers import (
    get_browser_connection,
    create_incognito_context,
    verify_github_oauth_redirect,
    log_browserbase_session,
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


@pytest.mark.oauth_redirect
@pytest.mark.ui
def test_cluster_info_github_oauth_redirect(attach_screenshot):
    """
    Test cluster-info redirects to GitHub OAuth login in incognito mode.
    
    - Uses incognito browser context
    - Navigates to cluster-info
    - Verifies redirect to https://github.com/login
    - Takes screenshot of GitHub login page
    - Supports BrowserBase and local Chrome
    """
    playwright, browser, session = get_browser_connection()
    
    try:
        # Create incognito context
        context = create_incognito_context(browser)
        page = context.new_page()
        
        # Navigate and verify GitHub OAuth redirect
        cluster_info_url = "https://cluster-info.nonprod.foobar.onglueops.rocks/"
        redirected = verify_github_oauth_redirect(page, cluster_info_url, attach_screenshot)
        
        # Assert that we got redirected to GitHub
        assert redirected, f"Cluster-info did not redirect to GitHub OAuth login"
        
    finally:
        cleanup_browser(playwright, page, context, session)
