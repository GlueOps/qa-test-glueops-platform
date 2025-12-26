"""Test ArgoCD UI and GitHub OAuth redirect."""
import pytest
from tests.ui.helpers import ScreenshotManager


@pytest.mark.oauth_redirect
@pytest.mark.ui
def test_argocd_github_oauth_redirect(page, captain_domain, request):
    """
    Test ArgoCD redirects to GitHub OAuth login in incognito mode.
    
    - Uses incognito browser context
    - Navigates to ArgoCD
    - Verifies redirect to https://github.com/login
    - Screenshots captured manually using ScreenshotManager
    - Supports BrowserBase and local Chrome
    """
    # Navigate to ArgoCD
    argocd_url = f"https://argocd.{captain_domain}"
    page.goto(argocd_url, wait_until="load", timeout=120000)
    
    # Wait for OAuth redirect chain to complete
    page.wait_for_timeout(3000)
    
    # Initialize screenshot manager
    screenshot_manager = ScreenshotManager(test_name="argocd_oauth", request=request)
    
    # Check if we're at GitHub login
    final_url = page.url
    assert "github.com/login" in final_url, f"ArgoCD did not redirect to GitHub OAuth login. Final URL: {final_url}"
    
    # Capture screenshot of GitHub OAuth page
    screenshot_manager.capture(page, final_url, description="GitHub OAuth Login")
    
    # Log summary
    screenshot_manager.log_summary()
