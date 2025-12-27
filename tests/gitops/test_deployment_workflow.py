"""
GitOps Deployment Workflow Tests

Tests the end-to-end GitOps workflow for deploying applications
through the GlueOps platform.
"""
import pytest
from pathlib import Path
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
from tests.helpers.utils import display_progress_bar, print_section_header, print_summary_list
from tests.helpers.browser import get_browser_connection, create_incognito_context, cleanup_browser

logger = logging.getLogger(__name__)




@pytest.mark.gitops
@pytest.mark.gitops_deployment
def test_create_custom_deployment_repo(ephemeral_github_repo, captain_domain, custom_api, core_v1, networking_v1, platform_namespaces):
    """
    Test GitOps deployment workflow with custom repository.
    
    Creates 3 http-debug applications with dynamic GUIDs and validates end-to-end
    deployment through ArgoCD from a custom deployment repository.
    
    Validates:
    - Repository creation and app deployment
    - ArgoCD sync and application health
    - Pod health across platform
    - Ingress configuration and DNS resolution
    - HTTPS endpoints and JSON response format
    
    Applications use pattern: http-debug-<guid>.apps.{captain_domain}
    """
    repo = ephemeral_github_repo
    
    logger.info(f"✓ Captain domain: {captain_domain}")
    
    # Create applications with dynamic GUIDs
    print_section_header("STEP 1: Creating Applications")
    
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
            commit_message=f"Add {app_name} application with hostname {hostname}",
            verbose=True,
            log_content=True
        )
    
    print_summary_list(
        [{'name': app['name'], 'hostname': app['hostname']} for app in app_info],
        title="Applications to validate"
    )
    
    # Wait for deployments to be ready
    print_section_header("STEP 2: Waiting for GitOps sync and deployments")
    
    display_progress_bar(
        wait_time=300,
        interval=15,
        description="Waiting for ArgoCD sync and deployments (5 minutes)",
        verbose=True
    )
    
    # Check ArgoCD application health and sync status
    print_section_header("STEP 3: Checking ArgoCD Application Status")
    
    assert_argocd_healthy(custom_api, namespace_filter=None, verbose=True)
    
    # Check pod health across all platform namespaces
    print_section_header("STEP 4: Checking Pod Health")
    
    assert_pods_healthy(core_v1, platform_namespaces, verbose=True)
    
    # Validate Ingress configuration
    print_section_header("STEP 5: Validating Ingress Configuration")
    
    total_ingresses = assert_ingress_valid(networking_v1, platform_namespaces, verbose=True)
    
    # Validate DNS resolution for Ingress hosts
    print_section_header("STEP 6: Validating Ingress DNS Resolution")
    
    checked_count = assert_ingress_dns_valid(
        networking_v1,
        platform_namespaces,
        dns_server='1.1.1.1',
        verbose=True
    )
    
    # Validate JSON responses from each deployed application
    print_section_header("STEP 7: Validating deployed applications via HTTPS")
    
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
        for error in validation_errors:
            logger.info(f"   • {error}")
        pytest.fail(f"\n❌ Test failed with {len(validation_errors)} error(s)")
    
    logger.info(f"\n✅ SUCCESS: GitOps deployment workflow validated")
    logger.info(f"   ✓ {len(app_info)} applications deployed")
    logger.info(f"   ✓ {total_ingresses} Ingress resources configured")
    logger.info(f"   ✓ {checked_count} DNS entries validated")
    logger.info(f"   ✓ All validations passed\n")
