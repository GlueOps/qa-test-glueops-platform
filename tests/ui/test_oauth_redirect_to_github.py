"""Test OAuth redirect to GitHub for all GlueOps services.

This consolidated test validates that unauthenticated access to GlueOps
services triggers OAuth2 flow and redirects to GitHub login page.
"""

import pytest


@pytest.mark.oauth_redirect
@pytest.mark.ui
@pytest.mark.parametrize(
    "service_name,url_path",
    [
        ("argocd", "argocd"),
        ("vault", "vault"),
        ("grafana", "grafana"),
        ("cluster-info", "cluster-info"),
    ],
)
def test_oauth_redirect_to_github(page, captain_domain, screenshots, service_name, url_path):
    """
    Test that service redirects to GitHub OAuth login in incognito mode.
    
    Validates that unauthenticated access to the service triggers OAuth2 flow
    and redirects to GitHub login page.
    
    Args:
        page: Playwright page fixture (incognito context)
        captain_domain: Cluster domain (e.g., 'nonprod.example.com')
        screenshots: Screenshot capture fixture
        service_name: Human-readable service name for reporting
        url_path: URL path component for the service
    
    Environment Variables:
        CAPTAIN_DOMAIN: Cluster domain (e.g., 'nonprod.example.com')
    
    Timeouts:
        - Navigation: 120 seconds
        - OAuth redirect wait: 3 seconds
    
    Fails if final URL does not contain 'github.com/login'.
    
    Cluster Impact: READ-ONLY (browser navigation only)
    """
    # Navigate to service
    service_url = f"https://{url_path}.{captain_domain}"
    page.goto(service_url, wait_until="load", timeout=120000)
    
    # Wait for OAuth redirect chain to complete
    page.wait_for_timeout(3000)
    
    # Check if we're at GitHub login
    final_url = page.url
    assert "github.com/login" in final_url, (
        f"{service_name} did not redirect to GitHub OAuth login. Final URL: {final_url}"
    )
    
    # Capture screenshot of GitHub OAuth page (fixture handles summary logging)
    screenshots.capture(page, final_url, description=f"{service_name} - GitHub OAuth Login")
