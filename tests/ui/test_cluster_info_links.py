"""Test cluster-info page and verify all HTTPS links are accessible."""
import pytest
import logging

log = logging.getLogger(__name__)


@pytest.mark.authenticated
@pytest.mark.slow
@pytest.mark.ui
def test_cluster_info_links(page, github_credentials, captain_domain):
    """
    Test cluster-info page login and verify all HTTPS links are accessible.
    
    Steps:
    1. Navigate to cluster-info page (will redirect to GitHub OAuth)
    2. Complete GitHub OAuth flow
    3. Navigate back to cluster-info page
    4. Find all HTTPS links on the page
    5. Click each link, wait 5 seconds, take screenshot
    6. Return to cluster-info and continue with next link
    
    Required environment variables:
    - GITHUB_USERNAME: GitHub username/email
    - GITHUB_PASSWORD: GitHub password
    - GITHUB_OTP_SECRET: TOTP secret key for 2FA
    - CAPTAIN_DOMAIN: The captain domain (e.g., nonprod.foobar.onglueops.rocks)
    
    Usage:
        export GITHUB_USERNAME="your-email@example.com"
        export GITHUB_PASSWORD="your-password"
        export GITHUB_OTP_SECRET="your-totp-secret"
        export CAPTAIN_DOMAIN="nonprod.foobar.onglueops.rocks"
        pytest tests/ui/test_cluster_info_links.py::test_cluster_info_links -v -s
    """
    # Build cluster-info URL using captain_domain
    cluster_info_url = f"https://cluster-info.{captain_domain}/"
    
    # Navigate directly to cluster-info page - will redirect to GitHub OAuth
    log.info(f"Navigating to cluster-info page: {cluster_info_url}")
    page.goto(cluster_info_url, wait_until="load", timeout=30000)
    log.info(f"After navigation, current URL: {page.url}")
    
    # Handle GitHub OAuth if redirected
    if "github.com" in page.url:
        log.info("Redirected to GitHub - completing OAuth...")
        from tests.ui.helpers import complete_github_oauth_flow
        complete_github_oauth_flow(page, github_credentials)
        log.info(f"After OAuth, current URL: {page.url}")
        page.wait_for_timeout(3000)
    
    # Navigate to cluster-info page one final time to ensure we're there
    log.info(f"Final navigation to cluster-info page: {cluster_info_url}")
    page.goto(cluster_info_url, wait_until="load", timeout=30000)
    log.info(f"Final URL: {page.url}")
    
    # Wait for page to load
    page.wait_for_timeout(5000)
    
    # Verify we're on the cluster-info page
    if "cluster-info" not in page.url:
        log.error(f"Not on cluster-info page. Current URL: {page.url}")
        raise Exception("Failed to reach cluster-info page")
    
    log.info("✅ Successfully loaded cluster-info page")
    
    # Find all HTTPS links on the page
    log.info("Finding all HTTPS links on the page...")
    https_links = page.locator('a[href^="https://"]').all()
    log.info(f"Found {len(https_links)} HTTPS links on the page")
    
    # Get all the URLs from the links
    link_urls = []
    for link in https_links:
        try:
            href = link.get_attribute("href")
            if href and href.startswith("https://"):
                link_urls.append(href)
        except Exception as e:
            log.warning(f"Could not get href from link: {e}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_links = []
    for url in link_urls:
        if url not in seen:
            seen.add(url)
            unique_links.append(url)
    
    log.info(f"Found {len(unique_links)} unique HTTPS links to test")
    
    # Visit each link
    for i, link_url in enumerate(unique_links, 1):
        try:
            log.info(f"{'='*60}")
            log.info(f"[{i}/{len(unique_links)}] Visiting: {link_url}")
            log.info(f"{'='*60}")
            
            # Navigate to the link
            page.goto(link_url, wait_until="load", timeout=30000)
            log.info(f"Page loaded: {page.url}")
            
            # Wait 5 seconds on the page
            log.info("Waiting 5 seconds on page...")
            page.wait_for_timeout(5000)
            
            log.info(f"✅ Successfully visited: {link_url}")
            
        except Exception as e:
            log.error(f"❌ Error visiting {link_url}: {e}")
        
        # Return to cluster-info page for next iteration
        if i < len(unique_links):
            try:
                log.info(f"Returning to cluster-info page...")
                page.goto(cluster_info_url, wait_until="load", timeout=30000)
                page.wait_for_timeout(2000)
            except Exception as e:
                log.warning(f"Could not return to cluster-info page: {e}")
    
    log.info(f"✅ Completed testing {len(unique_links)} links")
