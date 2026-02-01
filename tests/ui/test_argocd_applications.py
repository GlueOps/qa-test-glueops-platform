"""
Test ArgoCD applications viewing with deployed apps.

This test deploys applications via captain manifests and verifies they appear
correctly in the ArgoCD UI.

Required environment variables:
- GITHUB_USERNAME: GitHub username or email
- GITHUB_PASSWORD: GitHub password
- GITHUB_OTP_SECRET: TOTP secret key for 2FA
- CAPTAIN_DOMAIN: The captain domain (e.g., nonprod.foobar.onglueops.rocks)
- CAPTAIN_DOMAIN_REPO_URL: Captain domain GitHub repository URL
- CAPTAIN_DOMAIN_GITHUB_TOKEN: GitHub token for captain repo access
- TENANT_GITHUB_ORGANIZATION_NAME: Tenant GitHub org
- DEPLOYMENT_CONFIGURATIONS_TEMPLATE_REPO: Template repo URL
"""

import logging
import pytest

log = logging.getLogger(__name__)


@pytest.mark.authenticated
@pytest.mark.visual
@pytest.mark.ui
@pytest.mark.captain_manifests
@pytest.mark.write
@pytest.mark.flaky(reruns=0, reruns_delay=300)
def test_argocd_applications(captain_manifests, authenticated_argocd_page, captain_domain, screenshots):
    """Test ArgoCD applications page with deployed fixture apps.
    
    This test:
    1. Uses captain_manifests fixture to deploy applications
    2. Authenticates to ArgoCD UI
    3. Navigates to applications page
    4. Takes screenshot showing deployed applications
    
    The captain_manifests fixture automatically:
    - Creates namespace, AppProject, and ApplicationSet
    - Deploys fixture apps (http-debug instances)
    - Waits for apps to become healthy
    - Cleans up after test completes
    """
    page = authenticated_argocd_page
    
    # Get fixture app info
    fixture_app_count = captain_manifests['fixture_app_count']
    namespace = captain_manifests['namespace']
    
    log.info("\n" + "="*70)
    log.info("Viewing ArgoCD applications")
    log.info("="*70)
    log.info(f"  Namespace: {namespace}")
    log.info(f"  Fixture apps deployed: {fixture_app_count}")
    log.info(f"  Captain domain: {captain_domain}")
    
    # Navigate to ArgoCD applications page
    applications_url = f"https://argocd.{captain_domain}/applications"
    
    log.info(f"\nNavigating to applications page: {applications_url}")
    page.goto(applications_url, wait_until="load", timeout=30000)
    
    # Wait for applications to render
    log.info("Waiting for applications to render...")
    page.wait_for_timeout(5000)
    
    # Verify we're on the applications page
    if "argocd" not in page.url or "/applications" not in page.url:
        log.error(f"Not on ArgoCD applications page. Current URL: {page.url}")
        raise Exception(f"Failed to load ArgoCD applications page. Current URL: {page.url}")
    
    log.info("✅ ArgoCD applications page loaded successfully")
    log.info(f"   Fixture apps should be visible: {fixture_app_count} apps")
    
    # List fixture apps for reference
    for app in captain_manifests['fixture_apps']:
        log.info(f"   - {app['name']} ({app['replicas']} replicas)")
    
    log.info("="*70 + "\n")
    
    # Capture screenshot showing the applications with visual regression baseline
    screenshots.capture(
        page, page.url,
        description="ArgoCD Applications Page with Deployed Apps",
        baseline_key="argocd_applications_deployed",
        threshold=0.5
    )
    
    # Assert no visual regressions
    assert not screenshots.get_visual_failures(), "Visual regression detected in ArgoCD applications page"
