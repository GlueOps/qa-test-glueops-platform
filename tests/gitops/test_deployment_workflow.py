"""
GitOps Deployment Workflow Tests

Tests the end-to-end GitOps workflow for deploying applications
through the GlueOps platform.
"""
import pytest
from pathlib import Path
import sys
import uuid
import logging
from lib.k8s_assertions import (
    assert_argocd_healthy,
    assert_pods_healthy,
    assert_ingress_valid,
    assert_ingress_dns_valid
)
from lib.k8s_validators import validate_http_debug_app
from lib.github_helpers import clear_apps_directory, create_github_file
from lib.test_utils import display_progress_bar, print_section_header, print_summary_list

logger = logging.getLogger(__name__)

# Add parent directory to path to import UI helpers
sys.path.insert(0, str(Path(__file__).parent.parent))
from ui.helpers import get_browser_connection, create_incognito_context, cleanup_browser




@pytest.mark.gitops
def test_create_custom_deployment_repo(ephemeral_github_repo, captain_domain, custom_api, core_v1, networking_v1, platform_namespaces):
    """
    Test creating a custom deployment repository from template.
    
    This test:
    1. Creates an ephemeral repo from the deployment-configurations template
    2. Clears out the apps/ directory in the new repo
    3. Creates http-debug applications with dynamically generated GUID names
    4. Waits 5 minutes for deployments to be ready
    5. Validates ArgoCD application health and sync status
    6. Validates pod health across platform namespaces
    7. Validates ALL Ingress resources are properly configured (not just new apps)
    8. Validates DNS resolution for ALL Ingress hosts (not just new apps)
    9. Validates JSON responses from each deployed application over HTTPS
    
    The test creates 3 applications with unique hostnames:
    - http-debug-<guid>.apps.{captain_domain}
    - http-debug-<guid>.apps.{captain_domain}
    - http-debug-<guid>.apps.{captain_domain}
    
    Each application is validated to ensure:
    - ArgoCD reports it as Healthy and Synced
    - Pods are running without issues
    - Ingress resources exist across the entire platform
    - DNS resolves correctly for all Ingress hosts
    - x-scheme is "https"
    - hostname matches the expected value
    - method is "GET"
    """
    repo = ephemeral_github_repo
    
    # Verify the repository was created
    assert repo is not None
    assert repo.name is not None
    logger.info(f"✓ Created test repository: {repo.full_name}")
    logger.info(f"✓ Using captain domain: {captain_domain}")
    
    # Clear the apps directory
    print_section_header("STEP 1: Preparing Repository")
    clear_apps_directory(repo, verbose=True)
    
    # Create applications with dynamic GUIDs
    print_section_header("STEP 2: Creating Applications")
    
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
    
    # Create 3 http-debug applications with dynamic GUIDs
    num_apps = 3
    app_info = []  # Store app name and hostname for validation
    
    logger.info(f"\nGenerating {num_apps} applications with random GUIDs...\n")
    
    for i in range(1, num_apps + 1):
        # Generate a short random GUID
        random_guid = str(uuid.uuid4())[:8]
        app_name = f"http-debug-{random_guid}"
        hostname = f"{app_name}.apps.{captain_domain}"
        app_info.append({
            'name': app_name,
            'hostname': hostname,
            'url': f"https://{hostname}"
        })
        file_path = f"apps/{app_name}/envs/prod/values.yaml"
        file_content = create_values_yaml(app_name, hostname)
        
        logger.info(f"[{i}/{num_apps}] Creating application:")
        logger.info(f"      GUID: {random_guid}")
        logger.info(f"      App Name: {app_name}")
        logger.info(f"      Hostname: {hostname}")
        logger.info(f"      File Path: {file_path}")
        logger.info(f"      URL: https://{hostname}")
        logger.info(f"\n      Full Manifest Content:")
        logger.info("      " + "="*60)
        for line in file_content.split('\n'):
            logger.info(f"      {line}")
        logger.info("      " + "="*60)
        
        repo.create_file(
            path=file_path,
            message=f"Add {app_name} application with hostname {hostname}",
            content=file_content
        )
        logger.info(f"      ✓ Committed to repository\n")
    
    logger.info(f"\n✓ Successfully created 3 http-debug applications in apps/ directory")
    
    # Verify the structure
    apps_contents = repo.get_contents("apps")
    logger.info(f"\n✓ Verification: apps/ directory now contains {len(apps_contents)} items")
    
    # Log what's actually in the GitHub repo
    logger.info(f"\nVerifying GitHub repo contents:")
    for item in apps_contents:
        logger.info(f"  - {item.path} (type: {item.type})")
    
    # Verify app_info matches what we just created
    logger.info(f"\nVerifying app_info list (what we'll validate later):")
    for idx, app in enumerate(app_info, 1):
        logger.info(f"  [{idx}] {app['name']} -> {app['hostname']}")
    
    # Wait 5 minutes for deployments to be ready
    logger.info("\n" + "="*70)
    logger.info("STEP 3: Waiting for GitOps sync and deployments")
    logger.info("="*70)
    logger.info(f"\n⏳ Waiting 5 minutes for ArgoCD to sync and deploy applications...")
    logger.info(f"   Repository: {repo.html_url}")
    logger.info(f"   Apps created: {len(app_info)}")
    logger.info(f"\n   What's happening:")
    logger.info(f"   - ArgoCD detects changes in the deployment repository")
    logger.info(f"   - Creates Kubernetes resources (Deployments, Services, Ingresses)")
    logger.info(f"   - Waits for pods to be ready and healthy")
    logger.info(f"   - Configures ingress routes and certificates")
    logger.info(f"\n   Progress:")
    
    wait_time = 300  # 5 minutes
    start_time = time.time()
    
    for remaining in range(wait_time, 0, -15):
        elapsed = wait_time - remaining
        elapsed_min = elapsed // 60
        elapsed_sec = elapsed % 60
        remaining_min = remaining // 60
        remaining_sec = remaining % 60
        
        # Progress bar
        progress_pct = (elapsed / wait_time) * 100
        filled = int(progress_pct / 5)  # 20 segments (100/5)
        bar = "█" * filled + "░" * (20 - filled)
        
        timestamp = datetime.now().strftime('%H:%M:%S')
        logger.info(f"   [{timestamp}] {bar} {progress_pct:5.1f}% | "
              f"Elapsed: {elapsed_min:02d}:{elapsed_sec:02d} | "
              f"Remaining: {remaining_min:02d}:{remaining_sec:02d}")
        
        time.sleep(15)
    
    logger.info(f"\n✓ Wait complete! Total time: {int(time.time() - start_time)}s")
    logger.info(f"\nProceeding to validate deployments...")
    
    # Check ArgoCD application health and sync status
    logger.info("\n" + "="*70)
    logger.info("STEP 4: Checking ArgoCD Application Status")
    logger.info("="*70)
    logger.info(f"\n🔍 Validating ALL ArgoCD applications (ensures new apps didn't break anything)...\n")
    
    assert_argocd_healthy(custom_api, namespace_filter=None, verbose=True)
    
    logger.info(f"\n✓ All ArgoCD applications are Healthy and Synced")
    
    # Check pod health across all platform namespaces
    print_section_header("STEP 5: Checking Pod Health")
    logger.info(f"\n🔍 Validating pod health across platform namespaces...\n")
    
    assert_pods_healthy(core_v1, platform_namespaces, verbose=True)
    
    logger.info(f"\n✓ All pods are healthy")
    
    # Validate Ingress configuration
    print_section_header("STEP 6: Validating Ingress Configuration")
    logger.info(f"\n🔍 Checking Ingress resources across platform...\n")
    
    total_ingresses = assert_ingress_valid(networking_v1, platform_namespaces, verbose=True)
    
    logger.info(f"\n✓ All {total_ingresses} Ingress resources are properly configured")
    
    # Validate DNS resolution for Ingress hosts
    print_section_header("STEP 7: Validating Ingress DNS Resolution")
    logger.info(f"\n🔍 Checking DNS resolution for all Ingress hosts...\n")
    
    checked_count = assert_ingress_dns_valid(
        networking_v1,
        platform_namespaces,
        dns_server='1.1.1.1',
        verbose=True
    )
    
    logger.info(f"\n✓ All {checked_count} Ingress hosts resolve correctly via DNS")
    
    # Validate JSON responses from each deployed application
    print_section_header("STEP 8: Validating deployed applications via HTTPS")
    logger.info(f"\n🔍 Testing {len(app_info)} applications...\n")
    
    validation_errors = []
    
    for idx, app in enumerate(app_info, 1):
        app_name = app['name']
        hostname = app['hostname']
        url = app['url']
        
        logger.info(f"[{idx}/{len(app_info)}] {app_name}")
        
        # Use helper function to validate http-debug app
        problems, response_data = validate_http_debug_app(
            url=url,
            expected_hostname=hostname,
            app_name=app_name,
            max_retries=3,
            retry_delays=[10, 30, 60],
            verbose=True
        )
        
        if problems:
            validation_errors.extend(problems)
        
        logger.info("")
    
    # Assert no validation errors occurred
    print_section_header("FINAL SUMMARY")
    
    if validation_errors:
        logger.info(f"\n❌ {len(validation_errors)} HTTP validation error(s) occurred:\n")
        for error in validation_errors:
            logger.info(f"   • {error}")
        pytest.fail(f"\n❌ Test failed with {len(validation_errors)} error(s)")
    
    logger.info(f"\n✅ SUCCESS: GitOps deployment workflow completed successfully!")
    logger.info(f"   ✓ Created {len(app_info)} applications with dynamic GUIDs")
    logger.info(f"   ✓ All ArgoCD applications Healthy and Synced")
    logger.info(f"   ✓ All pods healthy across platform")
    logger.info(f"   ✓ All {total_ingresses} Ingress resources properly configured")
    logger.info(f"   ✓ All {checked_count} Ingress hosts resolve via DNS")
    logger.info(f"   ✓ All {len(app_info)} apps responding to HTTPS requests")
    logger.info(f"   ✓ All JSON fields match expected values")
    logger.info(f"\n🎉 Test complete, repository ready for cleanup...\n")
