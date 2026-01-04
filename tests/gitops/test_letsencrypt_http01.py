"""
GitOps LetsEncrypt HTTP01 Challenge Tests

Tests cert-manager integration with LetsEncrypt using HTTP01 challenge.
Uses wildcard DNS services for automatic DNS resolution without managing DNS records.
"""
import pytest
import os
import uuid
import logging
from tests.helpers.assertions import (
    assert_argocd_healthy,
    assert_pods_healthy,
    assert_certificates_ready,
    assert_tls_secrets_valid,
    assert_https_endpoints_valid
)
from tests.helpers.k8s import get_ingress_load_balancer_ip
from tests.helpers.github import create_github_file
from tests.helpers.argocd import wait_for_appset_apps_created_and_healthy, calculate_expected_app_count
from tests.helpers.utils import print_section_header, print_summary_list

logger = logging.getLogger(__name__)

# Get number of DNS services to determine retry count
_dns_services_env = os.getenv('WILDCARD_DNS_SERVICES')
if not _dns_services_env:
    raise ValueError("WILDCARD_DNS_SERVICES environment variable is required but not set")
_dns_services_count = len([s.strip() for s in _dns_services_env.split(',')])
_reruns = max(0, _dns_services_count - 1)  # If 3 services, need 2 reruns


@pytest.mark.flaky(reruns=_reruns, reruns_delay=10)
@pytest.mark.gitops
@pytest.mark.letsencrypt
@pytest.mark.captain_manifests
def test_letsencrypt_http01_challenge(captain_manifests, ephemeral_github_repo, custom_api, core_v1, networking_v1, platform_namespaces):
    """
    Test LetsEncrypt certificate issuance via HTTP01 challenge.
    
    Supports multiple DNS services via WILDCARD_DNS_SERVICES env var.
    Will automatically retry with next DNS service on failure.
    
    Creates 3 applications with cert-manager configured for LetsEncrypt using
    wildcard DNS for automatic domain resolution to the load balancer IP.
    
    Validates:
    - Load balancer IP discovery
    - ArgoCD deployment and sync
    - cert-manager certificate issuance
    - TLS secret creation and validity
    - HTTPS endpoints with valid certificates
    
    Applications use pattern: letsencrypt-test-<guid>-<lb-ip>.{wildcard_dns_service}
    """
    _ = captain_manifests  # Used for namespace/appproject/appset setup
    repo = ephemeral_github_repo
    
    # Get DNS service for this attempt (set by pytest_runtest_setup hook)
    wildcard_dns_service = os.getenv('_WILDCARD_DNS_SERVICE_CURRENT')
    if not wildcard_dns_service:
        pytest.fail("_WILDCARD_DNS_SERVICE_CURRENT not set - this is an internal error")
    logger.info(f"📋 Using DNS service: {wildcard_dns_service}")
    
    # Get the ingress load balancer IP
    print_section_header("STEP 1: Getting Load Balancer IP")
    
    lb_ip = get_ingress_load_balancer_ip(
        networking_v1,
        ingress_class_name='public',
        
        fail_on_none=True
    )
    
    lb_ip_dashed = lb_ip.replace(".", "-")
    
    # Create applications with LetsEncrypt certificates
    print_section_header("STEP 2: Creating Applications with LetsEncrypt")
    
    # Template for values.yaml with cert-manager configuration
    from tests.templates import load_template
    
    def create_values_yaml(app_name, hostname):
        return load_template('letsencrypt-app-values.yaml', 
                           app_name=app_name, 
                           hostname=hostname)
    
    # Create 3 applications with dynamic GUIDs
    num_apps = 3
    app_info = []  # Store app details for validation
    
    for i in range(1, num_apps + 1):
        # Generate a short random GUID
        random_guid = str(uuid.uuid4())[:8]
        app_name = f"letsencrypt-test-{random_guid}"
        hostname = f"{app_name}-{lb_ip_dashed}.{wildcard_dns_service}"
        
        app_info.append({
            'name': app_name,
            'hostname': hostname,
            'url': f"https://{hostname}",
            'cert_name': app_name,
            'secret_name': f"{app_name}"
        })
        
        file_path = f"apps/{app_name}/envs/prod/values.yaml"
        file_content = create_values_yaml(app_name, hostname)
        
        create_github_file(
            repo=repo,
            file_path=file_path,
            content=file_content,
            commit_message=f"Add {app_name} with LetsEncrypt certificate"
        )
    
    print_summary_list(
        [{'name': app['name'], 'hostname': app['hostname']} for app in app_info],
        title="Applications to validate"
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
    
    # Validate ArgoCD applications
    print_section_header("STEP 3: Checking ArgoCD Application Status")
    
    assert_argocd_healthy(custom_api, namespace_filter=None)
    
    # Validate pod health
    print_section_header("STEP 4: Checking Pod Health")
    
    assert_pods_healthy(core_v1, platform_namespaces)
    
    # Wait for certificates to be issued
    print_section_header("STEP 5: Waiting for LetsEncrypt Certificates")
    
    assert_certificates_ready(
        custom_api,
        cert_info_list=app_info,
        namespace='nonprod',
    )
    
    # Validate TLS secrets
    print_section_header("STEP 6: Validating TLS Secrets")
    
    cert_infos = assert_tls_secrets_valid(
        core_v1,
        secret_info_list=app_info,
        namespace='nonprod',
    )
    
    # Validate HTTPS endpoints
    print_section_header("STEP 7: Validating HTTPS Endpoints")
    
    assert_https_endpoints_valid(
        endpoint_info_list=app_info,
        validate_cert=True,
        validate_app=False,
    )
    
    # Final summary
    print_section_header("FINAL SUMMARY")
    
    logger.info(f"\n✅ SUCCESS: LetsEncrypt certificates issued and validated")
    logger.info(f"   ✓ DNS Service: {wildcard_dns_service}")
    logger.info(f"   ✓ {len(app_info)} applications deployed")
    logger.info(f"   ✓ {len(app_info)} certificates issued")
    logger.info(f"   ✓ All validations passed\n")
