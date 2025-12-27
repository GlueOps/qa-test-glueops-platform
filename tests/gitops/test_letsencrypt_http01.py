"""
GitOps LetsEncrypt HTTP01 Challenge Tests

Tests cert-manager integration with LetsEncrypt using HTTP01 challenge.
Uses sslip.io for automatic DNS resolution without managing DNS records.
"""
import pytest
from pathlib import Path
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
from tests.helpers.utils import display_progress_bar, print_section_header, print_summary_list

logger = logging.getLogger(__name__)


@pytest.mark.gitops
@pytest.mark.letsencrypt
def test_letsencrypt_http01_challenge(ephemeral_github_repo, custom_api, core_v1, networking_v1, platform_namespaces):
    """
    Test LetsEncrypt certificate issuance via HTTP01 challenge.
    
    Creates 3 applications with cert-manager configured for LetsEncrypt using
    wildcard DNS (sslip.io) for automatic domain resolution to the load balancer IP.
    
    Validates:
    - Load balancer IP discovery
    - ArgoCD deployment and sync
    - cert-manager certificate issuance
    - TLS secret creation and validity
    - HTTPS endpoints with valid certificates
    
    Applications use pattern: letsencrypt-test-<guid>-<lb-ip>.{wildcard_dns_service}
    """
    repo = ephemeral_github_repo
    
    # Get the ingress load balancer IP
    print_section_header("STEP 1: Getting Load Balancer IP")
    
    lb_ip = get_ingress_load_balancer_ip(
        networking_v1,
        ingress_class_name='public',
        verbose=True,
        fail_on_none=True
    )
    
    lb_ip_dashed = lb_ip.replace(".", "-")
    wildcard_dns_service = os.getenv('WILDCARD_DNS_SERVICE')
    
    # Create applications with LetsEncrypt certificates
    print_section_header("STEP 2: Creating Applications with LetsEncrypt")
    
    # Template for values.yaml with cert-manager configuration
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
  replicas: 1
  enabled: true
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
ingress:
  enabled: true
  ingressClassName: public
  entries:
    - name: public
      hosts:
        - hostname: {hostname}
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
  tls:
    - secretName: {app_name}
      hosts:
        - {hostname}
podDisruptionBudget:
  enabled: false
"""
    
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
            commit_message=f"Add {app_name} with LetsEncrypt certificate",
            verbose=True,
            log_content=True
        )
    
    print_summary_list(
        [{'name': app['name'], 'hostname': app['hostname']} for app in app_info],
        title="Applications to validate"
    )
    
    # Wait for ArgoCD sync and deployments
    print_section_header("STEP 3: Waiting for GitOps Sync")
    
    display_progress_bar(
        wait_time=300,
        interval=15,
        description="Waiting for ArgoCD sync and deployments (5 minutes)",
        verbose=True
    )
    
    # Validate ArgoCD applications
    print_section_header("STEP 4: Checking ArgoCD Application Status")
    
    assert_argocd_healthy(custom_api, namespace_filter=None, verbose=True)
    
    # Validate pod health
    print_section_header("STEP 5: Checking Pod Health")
    
    assert_pods_healthy(core_v1, platform_namespaces, verbose=True)
    
    # Wait for certificates to be issued
    print_section_header("STEP 6: Waiting for LetsEncrypt Certificates (up to 10 min)")
    
    assert_certificates_ready(
        custom_api,
        cert_info_list=app_info,
        namespace='nonprod',
        timeout=600,
        poll_interval=10,
        verbose=True
    )
    
    # Validate TLS secrets
    print_section_header("STEP 7: Validating TLS Secrets")
    
    cert_infos = assert_tls_secrets_valid(
        core_v1,
        secret_info_list=app_info,
        namespace='nonprod',
        verbose=True
    )
    
    # Validate HTTPS endpoints
    print_section_header("STEP 8: Validating HTTPS Endpoints")
    
    assert_https_endpoints_valid(
        endpoint_info_list=app_info,
        validate_cert=True,
        validate_app=False,
        verbose=True
    )
    
    # Final summary
    print_section_header("FINAL SUMMARY")
    
    logger.info(f"\n✅ SUCCESS: LetsEncrypt certificates issued and validated")
    logger.info(f"   ✓ {len(app_info)} applications deployed")
    logger.info(f"   ✓ {len(app_info)} certificates issued")
    logger.info(f"   ✓ All validations passed\n")
