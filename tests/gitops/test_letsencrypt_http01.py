"""
GitOps LetsEncrypt HTTP01 Challenge Tests

Tests cert-manager integration with LetsEncrypt using HTTP01 challenge.
Uses sslip.io for automatic DNS resolution without managing DNS records.
"""
import pytest
from pathlib import Path
import sys
import uuid
import logging
from lib.k8s_assertions import (
    assert_argocd_healthy,
    assert_pods_healthy,
    assert_certificates_ready,
    assert_tls_secrets_valid,
    assert_https_endpoints_valid
)
from lib.k8s_utils import get_ingress_load_balancer_ip
from lib.github_helpers import clear_apps_directory, create_github_file
from lib.test_utils import display_progress_bar, print_section_header, print_summary_list

logger = logging.getLogger(__name__)

# Add parent directory to path to import UI helpers
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.gitops
@pytest.mark.letsencrypt
def test_letsencrypt_http01_challenge(ephemeral_github_repo, custom_api, core_v1, networking_v1, platform_namespaces):
    """
    Test LetsEncrypt certificate issuance via HTTP01 challenge.
    
    This test:
    1. Gets the ingress load balancer IP from the cluster
    2. Generates sslip.io hostnames that resolve to the LB IP automatically
    3. Creates applications with cert-manager annotations for LetsEncrypt
    4. Waits for certificates to be issued (up to 10 minutes)
    5. Validates Certificate resources are Ready
    6. Validates TLS secrets contain valid certificates
    7. Validates HTTPS endpoints work with valid LetsEncrypt certificates
    8. Validates certificate details (issuer, expiration, SANs)
    
    The test creates 2 applications with unique sslip.io hostnames:
    - letsencrypt-test-{guid1}-{lb-ip}.sslip.io
    - letsencrypt-test-{guid2}-{lb-ip}.sslip.io
    
    Each application is validated to ensure:
    - ArgoCD reports it as Healthy and Synced
    - Pods are running without issues
    - Certificate resource status is Ready
    - TLS secret contains valid certificate
    - Certificate is issued by Let's Encrypt
    - HTTPS works with the certificate
    - Certificate matches the hostname
    """
    repo = ephemeral_github_repo
    
    # Verify the repository was created
    assert repo is not None
    assert repo.name is not None
    logger.info(f"✓ Created test repository: {repo.full_name}")
    
    # Clear the apps directory
    print_section_header("STEP 1: Preparing Repository")
    clear_apps_directory(repo, verbose=True)
    
    # Get the ingress load balancer IP
    print_section_header("STEP 2: Getting Load Balancer IP")
    
    lb_ip = get_ingress_load_balancer_ip(
        networking_v1,
        ingress_class_name='public',
        verbose=True
    )
    assert lb_ip is not None, "Could not find load balancer IP for ingressClassName 'public'"
    
    lb_ip_dashed = lb_ip.replace(".", "-")
    logger.info(f"✓ sslip.io format: {lb_ip_dashed}")
    
    # Create applications with LetsEncrypt certificates
    print_section_header("STEP 3: Creating Applications with LetsEncrypt")
    
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
    - secretName: {app_name}-tls
      hosts:
          - {hostname}
podDisruptionBudget:
  enabled: false
"""
    
    # Create 3 applications with dynamic GUIDs
    num_apps = 3
    app_info = []  # Store app details for validation
    
    logger.info(f"\nGenerating {num_apps} applications with LetsEncrypt certificates...")
    
    for i in range(1, num_apps + 1):
        # Generate a short random GUID
        random_guid = str(uuid.uuid4())[:8]
        app_name = f"letsencrypt-test-{random_guid}"
        hostname = f"{app_name}-{lb_ip_dashed}.sslip.io"
        
        app_info.append({
            'name': app_name,
            'hostname': hostname,
            'url': f"https://{hostname}",
            'cert_name': app_name,
            'secret_name': f"{app_name}-tls"
        })
        
        file_path = f"apps/{app_name}/envs/prod/values.yaml"
        file_content = create_values_yaml(app_name, hostname)
        
        logger.info(f"\n[{i}/{num_apps}] Application: {app_name}")
        logger.info(f"      GUID: {random_guid}")
        logger.info(f"      Hostname: {hostname}")
        logger.info(f"      Certificate: {app_name}")
        logger.info(f"      TLS Secret: {app_name}-tls")
        
        create_github_file(
            repo=repo,
            file_path=file_path,
            content=file_content,
            commit_message=f"Add {app_name} with LetsEncrypt certificate",
            verbose=True
        )
    
    logger.info(f"\n✓ Successfully created {num_apps} applications")
    print_summary_list(
        [{'name': app['name'], 'hostname': app['hostname']} for app in app_info],
        title="Applications to validate"
    )
    
    # Wait for ArgoCD sync and deployments
    print_section_header("STEP 4: Waiting for GitOps Sync")
    logger.info(f"\n   Repository: {repo.html_url}")
    logger.info(f"   Apps created: {len(app_info)}")
    logger.info(f"\n   What's happening:")
    logger.info(f"   - ArgoCD detects changes and syncs")
    logger.info(f"   - Creates Deployments, Services, Ingresses")
    logger.info(f"   - cert-manager sees ingress annotations")
    logger.info(f"   - Creates Certificate and CertificateRequest resources")
    logger.info(f"   - Starts HTTP01 challenge process")
    
    display_progress_bar(
        wait_time=300,
        interval=15,
        description="Waiting for ArgoCD sync and deployments (5 minutes)",
        verbose=True
    )
    
    # Validate ArgoCD applications
    print_section_header("STEP 5: Checking ArgoCD Application Status")
    logger.info(f"\n🔍 Validating ArgoCD applications...\n")
    
    assert_argocd_healthy(custom_api, namespace_filter=None, verbose=True)
    
    logger.info(f"\n✓ All ArgoCD applications are Healthy and Synced")
    
    # Validate pod health
    print_section_header("STEP 6: Checking Pod Health")
    logger.info(f"\n🔍 Validating pod health...\n")
    
    assert_pods_healthy(core_v1, platform_namespaces, verbose=True)
    
    logger.info(f"\n✓ All pods are healthy")
    
    # Wait for certificates to be issued
    print_section_header("STEP 7: Waiting for LetsEncrypt Certificates (up to 10 min)")
    logger.info(f"\n🔍 Waiting for {len(app_info)} certificate(s) to be issued...")
    logger.info(f"\n   What's happening:")
    logger.info(f"   - cert-manager creates HTTP01 challenge pod")
    logger.info(f"   - LetsEncrypt validates /.well-known/acme-challenge/")
    logger.info(f"   - Certificate is issued upon successful validation")
    logger.info(f"   - TLS secret is created with certificate\n")
    
    assert_certificates_ready(
        custom_api,
        cert_info_list=app_info,
        namespace='nonprod',
        timeout=600,
        poll_interval=10,
        verbose=True
    )
    
    logger.info(f"\n✓ All {len(app_info)} certificates issued successfully")
    
    # Validate TLS secrets
    print_section_header("STEP 8: Validating TLS Secrets")
    logger.info(f"\n🔍 Validating {len(app_info)} TLS secret(s)...\n")
    
    cert_infos = assert_tls_secrets_valid(
        core_v1,
        secret_info_list=app_info,
        namespace='nonprod',
        verbose=True
    )
    
    logger.info(f"\n✓ All {len(app_info)} TLS secrets are valid")
    
    # Validate HTTPS endpoints
    print_section_header("STEP 9: Validating HTTPS Endpoints")
    logger.info(f"\n🔍 Testing {len(app_info)} HTTPS endpoint(s)...\n")
    
    assert_https_endpoints_valid(
        endpoint_info_list=app_info,
        validate_cert=True,
        validate_app=False,
        verbose=True
    )
    
    logger.info(f"\n✓ All {len(app_info)} HTTPS endpoints are working")
    
    # Final summary
    print_section_header("FINAL SUMMARY")
    
    logger.info(f"\n✅ SUCCESS: LetsEncrypt HTTP01 challenge test completed!")
    logger.info(f"   ✓ Created {len(app_info)} applications with sslip.io hostnames")
    logger.info(f"   ✓ All ArgoCD applications Healthy and Synced")
    logger.info(f"   ✓ All pods healthy")
    logger.info(f"   ✓ All {len(app_info)} LetsEncrypt certificates issued")
    logger.info(f"   ✓ All {len(app_info)} TLS secrets valid")
    logger.info(f"   ✓ All {len(app_info)} HTTPS endpoints working")
    logger.info(f"\n🎉 Test complete, repository ready for cleanup...\n")
