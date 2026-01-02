"""
Test Grafana dashboard viewing.

This test verifies that users can access Grafana dashboards after authentication.
Specifically tests the Kubernetes Compute Resources dashboard.

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
def test_grafana_dashboard(authenticated_grafana_page, captain_domain, screenshots):
    """Test Grafana Kubernetes dashboard access.
    
    Uses authenticated_grafana_page fixture which handles the complete OAuth flow.
    
    This test verifies:
    1. OAuth authentication succeeds
    2. Kubernetes Compute Resources dashboard loads
    3. Dashboard displays correctly
    """
    page = authenticated_grafana_page
    
    # Navigate to Kubernetes Compute Resources dashboard
    dashboard_url = (
        f"https://grafana.{captain_domain}/d/85a562078cdf77779eaa1add43ccec1e/"
        f"kubernetes-compute-resources-namespace-pods"
        f"?orgId=1&refresh=10s&var-datasource=default&var-cluster=&var-namespace=glueops-core"
    )
    
    log.info(f"Navigating to Kubernetes dashboard: {dashboard_url}")
    page.goto(dashboard_url, wait_until="networkidle", timeout=60000)
    
    # Wait for dashboard to fully render
    log.info("Waiting for dashboard to render...")
    page.wait_for_timeout(5000)
    
    # Verify we're on the dashboard
    if "grafana" not in page.url or "/d/" not in page.url:
        log.error(f"Not on Grafana dashboard. Current URL: {page.url}")
        raise Exception(f"Failed to load Grafana dashboard. Current URL: {page.url}")
    
    log.info("✅ Grafana dashboard loaded successfully")
    
    # Capture screenshot with visual regression baseline
    screenshots.capture(
        page, page.url,
        description="Kubernetes Compute Resources Dashboard",
        baseline_key="grafana_k8s_compute_dashboard",
        threshold=2.0
    )
    
    # Assert no visual regressions
    assert not screenshots.get_visual_failures(), "Visual regression detected in Grafana dashboard"
