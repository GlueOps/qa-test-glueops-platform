"""
GitOps Deployment Workflow Tests

Tests the end-to-end GitOps workflow for deploying applications
through the GlueOps platform.
"""
import pytest
from github import GithubException
from pathlib import Path
from datetime import datetime
import sys
import os

# Add parent directory to path to import UI helpers
sys.path.insert(0, str(Path(__file__).parent.parent))
from ui.helpers import get_browser_connection, create_incognito_context, cleanup_browser


def delete_directory_contents(repo, path):
    """
    Recursively delete all contents of a directory in a GitHub repository.
    
    Args:
        repo: GitHub Repository object
        path: Path to the directory to delete
    """
    try:
        contents = repo.get_contents(path)
        
        if not isinstance(contents, list):
            contents = [contents]
        
        for item in contents:
            if item.type == "dir":
                # Recursively delete subdirectory
                print(f"  Deleting directory: {item.path}")
                delete_directory_contents(repo, item.path)
            else:
                # Delete file
                print(f"  Deleting file: {item.path}")
                repo.delete_file(
                    path=item.path,
                    message=f"Clear apps directory: remove {item.path}",
                    sha=item.sha
                )
    except GithubException as e:
        if e.status == 404:
            # Already deleted or doesn't exist
            pass
        else:
            raise


@pytest.mark.gitops
def test_create_custom_deployment_repo(ephemeral_github_repo, captain_domain):
    """
    Test creating a custom deployment repository from template.
    
    This test:
    1. Creates an ephemeral repo from the deployment-configurations template
    2. Clears out the apps/ directory in the new repo
    3. Creates http-debug applications with custom values.yaml files
    4. Waits 5 minutes for deployments to be ready
    5. Takes screenshots of each deployed application
    
    The test creates 3 applications with unique hostnames:
    - http-debug-1.apps.{captain_domain}
    - http-debug-2.apps.{captain_domain}
    - http-debug-3.apps.{captain_domain}
    """
    repo = ephemeral_github_repo
    
    # Verify the repository was created
    assert repo is not None
    assert repo.name is not None
    print(f"Created test repository: {repo.full_name}")
    print(f"Using captain domain: {captain_domain}")
    
    # Get the apps directory contents
    try:
        apps_contents = repo.get_contents("apps")
        
        if not isinstance(apps_contents, list):
            apps_contents = [apps_contents]
        
        print(f"Found {len(apps_contents)} items in apps/ directory")
        
        # Delete all contents within the apps/ folder (files and directories)
        # Note: We're only deleting from OUR copy, not the template
        for item in apps_contents:
            if item.type == "dir":
                print(f"Deleting directory: apps/{item.name}")
                delete_directory_contents(repo, item.path)
            else:
                print(f"Deleting file: apps/{item.name}")
                repo.delete_file(
                    path=item.path,
                    message=f"Clear apps directory: remove {item.name}",
                    sha=item.sha
                )
        
        print("Successfully cleared apps/ directory")
        
        # Verify apps directory is now empty
        try:
            remaining = repo.get_contents("apps")
            if isinstance(remaining, list):
                assert len(remaining) == 0, f"apps/ directory should be empty but has {len(remaining)} items"
            else:
                pytest.fail("apps/ directory should be empty but still contains content")
        except GithubException as e:
            # 404 is expected if directory is now empty/doesn't exist
            if e.status == 404:
                print("apps/ directory is now empty (404 returned)")
            else:
                raise
    
    except GithubException as e:
        if e.status == 404:
            print("apps/ directory does not exist in template - this is fine")
        else:
            raise
    
    # Create http-debug applications with values.yaml files
    print("\nCreating http-debug applications...")
    import time
    
    # Template for values.yaml (based on example-app.yaml)
    def create_values_yaml(app_name, hostname):
        return f"""#https://github.com/luszczynski/quarkus-debug?tab=readme-ov-file
image:
  registry: dockerhub.repo.gpkg.io
  repository: mendhak/http-https-echo
  tag: 37@sha256:f55000d9196bd3c853d384af7315f509d21ffb85de315c26e9874033b9f83e15
  port: 8080
service:
  enabled: true
deployment:
  replicas: 2
  enabled: true
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
ingress:
  enabled: true
  ingressClassName: public
  entries:
    - name: public
      hosts:
        - hostname: {hostname}
podDisruptionBudget:
  enabled: true
"""
    
    # Create 3 http-debug applications
    app_urls = []
    for i in range(1, 4):
        app_name = f"http-debug-{i}"
        hostname = f"{app_name}.apps.{captain_domain}"
        app_urls.append(f"https://{hostname}")
        file_path = f"apps/{app_name}/envs/prod/values.yaml"
        file_content = create_values_yaml(app_name, hostname)
        
        print(f"Creating: {file_path}")
        print(f"  Hostname: {hostname}")
        repo.create_file(
            path=file_path,
            message=f"Add {app_name} application with hostname {hostname}",
            content=file_content
        )
    
    print(f"\n✓ Successfully created 3 http-debug applications in apps/ directory")
    
    # Verify the structure
    apps_contents = repo.get_contents("apps")
    print(f"Verification: apps/ directory now contains {len(apps_contents)} items")
    
    # Wait 5 minutes for deployments to be ready
    print("\n⏳ Waiting 5 minutes for deployments to be ready...")
    print(f"   Repository URL: {repo.html_url}")
    wait_time = 300  # 5 minutes
    for remaining in range(wait_time, 0, -30):
        print(f"   {remaining} seconds remaining...")
        time.sleep(30)
    print("✓ Wait complete, proceeding to take screenshots...")
    
    # Take screenshots of each deployed application
    print("\n📸 Taking screenshots of deployed applications...")
    playwright, browser, session = get_browser_connection()
    context = create_incognito_context(browser)
    page = context.new_page()
    
    try:
        screenshot_dir = Path("./reports/screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        
        for i, url in enumerate(app_urls, 1):
            app_name = f"http-debug-{i}"
            print(f"\nVisiting: {url}")
            
            try:
                # Navigate to the application
                page.goto(url, timeout=60000, wait_until="networkidle")
                
                # Wait a bit for page to fully render
                time.sleep(2)
                
                # Take screenshot
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                screenshot_path = screenshot_dir / f"gitops_{app_name}_{timestamp}.png"
                page.screenshot(path=str(screenshot_path), full_page=True)
                print(f"✓ Screenshot saved: {screenshot_path}")
                
            except Exception as e:
                print(f"⚠️  Failed to screenshot {app_name}: {e}")
                # Continue with other apps even if one fails
        
        print("\n✓ Screenshot capture complete")
        
    finally:
        # Cleanup browser resources
        cleanup_browser(playwright, page, context, session)
    
    print("\n✓ Test complete, repository ready for cleanup...")
