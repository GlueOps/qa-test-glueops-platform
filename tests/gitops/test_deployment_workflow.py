"""
GitOps Deployment Workflow Tests

Tests the end-to-end GitOps workflow for deploying applications
through the GlueOps platform.
"""
import pytest
import uuid
import logging
from tests.helpers.assertions import (
    assert_argocd_healthy,
    assert_pods_healthy,
    assert_ingress_valid,
    assert_ingress_dns_valid
)
from tests.helpers.k8s import validate_http_debug_app
from tests.helpers.github import create_github_file
from tests.helpers.argocd import wait_for_appset_apps_created_and_healthy, calculate_expected_app_count
from tests.helpers.utils import print_section_header, print_summary_list

logger = logging.getLogger(__name__)




@pytest.mark.gitops
@pytest.mark.gitops_deployment
@pytest.mark.captain_manifests
@pytest.mark.flaky(reruns=1, reruns_delay=300)
def test_create_custom_deployment_repo(captain_manifests, ephemeral_github_repo, custom_api, core_v1, networking_v1, platform_namespaces):
    """
    Test GitOps deployment workflow with custom repository.
    
    Creates 3 http-debug applications with dynamic GUIDs and validates end-to-end
    deployment through ArgoCD from a custom deployment repository.
    
    Note: Fixture applications are automatically deployed by captain_manifests fixture.
    
    Validates:
    - Repository creation and app deployment
    - ArgoCD sync and application health
    - Pod health across platform
    - Ingress configuration and DNS resolution
    - HTTPS endpoints and JSON response format
    
    Applications use pattern: http-debug-<guid>.apps.{captain_domain}
    """
    repo = ephemeral_github_repo
    captain_domain = captain_manifests['captain_domain']
    fixture_app_count = captain_manifests['fixture_app_count']
    
    logger.info(f"✓ Captain domain: {captain_domain}")
    logger.info(f"✓ Fixture apps deployed: {fixture_app_count}")
    
    # Create applications with dynamic GUIDs
    print_section_header("STEP 1: Creating Test-Specific Applications")
    
    # Template for values.yaml (based on example-app.yaml)
    from tests.templates import load_template
    
    def create_values_yaml(app_name, hostname):
        """Generate values.yaml for test http-debug application.
        
        Uses mendhak/http-https-echo container with standard settings.
        
        Args:
            app_name: Name of the application
            hostname: FQDN for ingress routing
            
        Returns:
            str: Complete values.yaml content as string
        """
        return load_template('http-debug-app-values.yaml',
                           hostname=hostname,
                           replicas=2,
                           cpu='100m',
                           memory='128Mi',
                           pdb_enabled='true')
    
    # Create 3 http-debug applications with dynamic GUIDs
    num_apps = 3
    app_info = []
    
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
        
        create_github_file(
            repo=repo,
            file_path=file_path,
            content=file_content,
            commit_message=f"Add {app_name} application with hostname {hostname}"
        )
    
    print_summary_list(
        [{'name': app['name'], 'hostname': app['hostname']} for app in app_info],
        title="Test-specific applications to validate"
    )
    
    # Wait for ApplicationSet to discover and sync the apps we just created
    expected_total = calculate_expected_app_count(captain_manifests, num_apps)
    logger.info(f"\n⏳ Waiting for ApplicationSet to sync {num_apps} test-specific app(s) (total: {expected_total})...")
    apps_ready = wait_for_appset_apps_created_and_healthy(
        custom_api,
        namespace=captain_manifests['namespace'],
        expected_count=expected_total,
    )
    
    if not apps_ready:
        pytest.fail(f"ApplicationSet did not create/sync {num_apps} apps within timeout")
    
    # Check ArgoCD application health and sync status
    print_section_header("STEP 2: Checking ArgoCD Application Status")
    
    assert_argocd_healthy(custom_api, namespace_filter=None)
    
    # Check pod health across all platform namespaces
    print_section_header("STEP 3: Checking Pod Health")
    
    assert_pods_healthy(core_v1, platform_namespaces)
    
    # Validate Ingress configuration
    print_section_header("STEP 4: Validating Ingress Configuration")
    
    total_ingresses = assert_ingress_valid(networking_v1, platform_namespaces)
    
    # Validate DNS resolution for Ingress hosts
    print_section_header("STEP 5: Validating Ingress DNS Resolution")
    
    checked_count = assert_ingress_dns_valid(
        networking_v1,
        platform_namespaces,
        dns_server='1.1.1.1',
    )
    
    # Validate JSON responses from each deployed application
    print_section_header("STEP 6: Validating deployed applications via HTTPS")
    
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
        )
        
        if problems:
            validation_errors.extend(problems)
        
        logger.info("")
    
    # Assert no validation errors occurred
    print_section_header("FINAL SUMMARY")
    
    if validation_errors:
        for error in validation_errors:
            logger.info(f"   • {error}")
        pytest.fail(f"\n❌ Test failed with {len(validation_errors)} error(s)")
    
    logger.info(f"\n✅ SUCCESS: GitOps deployment workflow validated")
    logger.info(f"   ✓ {len(app_info)} applications deployed")
    logger.info(f"   ✓ {total_ingresses} Ingress resources configured")
    logger.info(f"   ✓ {checked_count} DNS entries validated")
    logger.info(f"   ✓ All validations passed\n")
