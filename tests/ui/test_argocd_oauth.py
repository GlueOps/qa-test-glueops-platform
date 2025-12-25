"""Test ArgoCD UI and GitHub OAuth redirect."""
import pytest
from .helpers import (
    get_browser_connection,
    create_incognito_context,
    verify_github_oauth_redirect,
    cleanup_browser
)


@pytest.fixture
def attach_screenshot(request):
    """Pytest fixture to attach screenshots to HTML report."""
    if not hasattr(request.node, '_screenshots'):
        request.node._screenshots = []
    
    def _attach(screenshot_path, description: str = ""):
        request.node._screenshots.append((str(screenshot_path), description))
    
    yield _attach


@pytest.mark.oauth_redirect
@pytest.mark.ui
def test_argocd_github_oauth_redirect(attach_screenshot):
    """
    Test ArgoCD redirects to GitHub OAuth login in incognito mode.
    
    - Uses incognito browser context
    - Navigates to ArgoCD
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
        argocd_url = "https://argocd.nonprod.foobar.onglueops.rocks"
        redirected = verify_github_oauth_redirect(page, argocd_url, attach_screenshot)
        
        # Assert that we got redirected to GitHub
        assert redirected, f"ArgoCD did not redirect to GitHub OAuth login"
        
    finally:
        cleanup_browser(playwright, page, context, session)
