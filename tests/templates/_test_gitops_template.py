"""
GitOps Test Template - Deployment Workflow Tests

Copy this file to tests/gitops/ and customize for your test.

Usage:
    cp tests/templates/_test_gitops_template.py tests/gitops/test_my_workflow.py

GitOps tests typically:
1. Create YAML files in ephemeral GitHub repo
2. Wait for ArgoCD ApplicationSet to sync
3. Validate deployed resources
4. Cleanup is automatic (ephemeral_github_repo fixture handles it)
"""
import pytest
import uuid
import logging
from tests.helpers.assertions import (
    assert_argocd_healthy,
    assert_pods_healthy,
    assert_ingress_valid,
)
from tests.helpers.github import create_github_file
from tests.helpers.argocd import wait_for_appset_apps_created_and_healthy, calculate_expected_app_count
from tests.helpers.utils import print_section_header, print_summary_list
from tests.templates import load_template

logger = logging.getLogger(__name__)


# =============================================================================
# STANDARD GITOPS DEPLOYMENT TEST
# =============================================================================
@pytest.mark.gitops
@pytest.mark.gitops_deployment  # or @pytest.mark.externalsecrets, @pytest.mark.letsencrypt
@pytest.mark.captain_manifests
@pytest.mark.flaky(reruns=0, reruns_delay=300)  # Retry once on failure (network issues, etc.)
def test_example_deployment(
    captain_manifests,
    ephemeral_github_repo,
    custom_api,
    core_v1,
    networking_v1,
    platform_namespaces
):
    """
    Test GitOps deployment workflow with custom applications.
    
    Creates N applications via GitOps and validates end-to-end deployment.
    
    Validates:
    - GitHub file creation triggers ArgoCD sync
    - Applications become Healthy and Synced
    - Pods are running correctly
    - Ingress is configured properly
    
    Applications use pattern: my-app-<guid>.apps.{captain_domain}
    
    Cluster Impact: WRITE (creates ArgoCD applications, pods, ingress)
    """
    repo = ephemeral_github_repo
    captain_domain = captain_manifests['captain_domain']
    fixture_app_count = captain_manifests['fixture_app_count']
    namespace = captain_manifests['namespace']
    
    logger.info(f"✓ Captain domain: {captain_domain}")
    logger.info(f"✓ Fixture apps deployed: {fixture_app_count}")
    
    # =========================================================================
    # STEP 1: Create Applications
    # =========================================================================
    print_section_header("STEP 1: Creating Test Applications")
    
    num_apps = 2  # Number of test-specific apps to create
    app_info = []
    
    for i in range(1, num_apps + 1):
        random_guid = str(uuid.uuid4())[:8]
        app_name = f"my-app-{random_guid}"
        hostname = f"{app_name}.apps.{captain_domain}"
        
        app_info.append({
            'name': app_name,
            'hostname': hostname,
            'url': f"https://{hostname}"
        })
        
        # Generate values.yaml using template
        file_content = load_template(
            'http-debug-app-values.yaml',
            hostname=hostname,
            replicas=2,
            cpu='100m',
            memory='128Mi',
            pdb_enabled='true'
        )
        
        file_path = f"apps/{app_name}/envs/prod/values.yaml"
        create_github_file(
            repo=repo,
            file_path=file_path,
            content=file_content,
            commit_message=f"Add {app_name} application"
        )
    
    print_summary_list(
        [{'name': app['name'], 'hostname': app['hostname']} for app in app_info],
        title="Test applications created"
    )
    
    # =========================================================================
    # STEP 2: Wait for ArgoCD Sync
    # =========================================================================
    print_section_header("STEP 2: Waiting for ArgoCD Sync")
    
    # IMPORTANT: Include fixture apps in expected count!
    expected_total = calculate_expected_app_count(captain_manifests, num_apps)
    logger.info(f"⏳ Waiting for {num_apps} new apps (total: {expected_total})...")
    
    apps_ready = wait_for_appset_apps_created_and_healthy(
        custom_api,
        namespace=namespace,
        expected_count=expected_total,
    )
    
    if not apps_ready:
        pytest.fail(f"ApplicationSet did not sync {num_apps} apps within timeout")
    
    # =========================================================================
    # STEP 3: Validate ArgoCD Health
    # =========================================================================
    print_section_header("STEP 3: Validating ArgoCD Health")
    assert_argocd_healthy(custom_api)
    
    # =========================================================================
    # STEP 4: Validate Pod Health
    # =========================================================================
    print_section_header("STEP 4: Validating Pod Health")
    assert_pods_healthy(core_v1, platform_namespaces)
    
    # =========================================================================
    # STEP 5: Validate Ingress
    # =========================================================================
    print_section_header("STEP 5: Validating Ingress Configuration")
    assert_ingress_valid(networking_v1, platform_namespaces)
    
    # =========================================================================
    # STEP 6: Custom Validation (Optional)
    # =========================================================================
    print_section_header("STEP 6: Custom Validation")
    
    for app in app_info:
        # Add your custom validation here
        # Example: HTTP health check, JSON response validation, etc.
        logger.info(f"✅ {app['name']} validated at {app['url']}")
    
    logger.info(f"\n🎉 All {num_apps} applications deployed and validated successfully!")


# =============================================================================
# SIMPLER VERSION - Minimal GitOps test
# =============================================================================
@pytest.mark.gitops
@pytest.mark.captain_manifests
def test_simple_deployment(captain_manifests, ephemeral_github_repo, custom_api):
    """
    Minimal GitOps deployment test.
    
    Cluster Impact: WRITE (creates ArgoCD application)
    """
    repo = ephemeral_github_repo
    captain_domain = captain_manifests['captain_domain']
    
    # Create one app
    app_name = f"simple-app-{str(uuid.uuid4())[:8]}"
    hostname = f"{app_name}.apps.{captain_domain}"
    
    content = load_template('http-debug-app-values.yaml', hostname=hostname)
    create_github_file(repo, f"apps/{app_name}/envs/prod/values.yaml", content, f"Add {app_name}")
    
    # Wait for sync
    expected = calculate_expected_app_count(captain_manifests, 1)
    assert wait_for_appset_apps_created_and_healthy(
        custom_api,
        namespace=captain_manifests['namespace'],
        expected_count=expected
    ), "App did not sync"
    
    logger.info(f"✅ {app_name} deployed successfully")
