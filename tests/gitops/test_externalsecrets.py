"""
GitOps External Secrets Tests

Tests External Secrets Operator integration with Vault.
Creates secrets in Vault, deploys apps that reference them,
and validates the secrets are synced as environment variables.
"""
import pytest
from pathlib import Path
import sys
import uuid
import logging
import random
import string
from lib.k8s_assertions import (
    assert_argocd_healthy,
    assert_pods_healthy,
    assert_ingress_valid,
    assert_ingress_dns_valid
)
from lib.k8s_validators import validate_whoami_env_vars
from lib.github_helpers import create_github_file
from lib.test_utils import display_progress_bar, print_section_header, print_summary_list
from lib.vault_helpers import (
    get_vault_client,
    cleanup_vault_client,
    create_multiple_vault_secrets,
    delete_multiple_vault_secrets
)

logger = logging.getLogger(__name__)

# Add parent directory to path to import UI helpers
sys.path.insert(0, str(Path(__file__).parent.parent))


def generate_random_secrets(num_keys=5):
    """Generate random key-value pairs for vault secrets."""
    secrets = {}
    for i in range(1, num_keys + 1):
        key = f"KEY{i}"
        value = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
        secrets[key] = value
    return secrets


@pytest.mark.gitops
@pytest.mark.externalsecrets
def test_externalsecrets_vault_integration(ephemeral_github_repo, captain_domain, custom_api, core_v1, networking_v1, platform_namespaces):
    """
    Test External Secrets Operator integration with Vault.
    
    Creates 3 traefik/whoami applications with secrets stored in Vault that are
    synced to Kubernetes as environment variables via External Secrets Operator.
    
    Validates:
    - Vault secret creation and storage
    - ArgoCD deployment and sync
    - External Secrets Operator synchronization
    - Pod health and readiness
    - Ingress configuration and DNS resolution
    - Environment variables loaded from Vault secrets
    
    Applications use pattern: externalsecret-test-<guid>.apps.{captain_domain}
    Vault paths: secret/<app-name>/prod and secret/<app-name>/extra
    """
    repo = ephemeral_github_repo
    vault_client = None
    vault_secret_paths = []
    
    try:
        logger.info(f"✓ Captain domain: {captain_domain}")
        
        # Connect to Vault
        print_section_header("STEP 1: Connecting to Vault")
        vault_namespace = "glueops-core-vault"
        vault_client = get_vault_client(captain_domain, vault_namespace=vault_namespace, verbose=True)
        
        # Generate applications and vault secrets
        print_section_header("STEP 2: Creating Vault Secrets")
        
        num_apps = 3
        app_info = []
        vault_secrets_config = []
        
        for i in range(1, num_apps + 1):
            # Generate a short random GUID
            random_guid = str(uuid.uuid4())[:8]
            app_name = f"externalsecret-test-{random_guid}"
            hostname = f"{app_name}.apps.{captain_domain}"
            
            # Generate random secrets for this app
            app_secrets = generate_random_secrets(5)
            extra_secrets = generate_random_secrets(5)
            
            # Vault paths
            app_secret_path = f"{app_name}/prod"
            extra_secret_path = f"{app_name}/extra"
            
            # Track for cleanup
            vault_secret_paths.extend([app_secret_path, extra_secret_path])
            
            # Prepare vault secret configurations
            vault_secrets_config.extend([
                {
                    'path': app_secret_path,
                    'data': app_secrets
                },
                {
                    'path': extra_secret_path,
                    'data': extra_secrets
                }
            ])
            
            # Store app info for validation
            app_info.append({
                'name': app_name,
                'hostname': hostname,
                'url': f"https://{hostname}",
                'app_secrets': app_secrets,
                'extra_secrets': extra_secrets,
                'app_secret_path': app_secret_path,
                'extra_secret_path': extra_secret_path
            })
            
            logger.info(f"\n[{i}/{num_apps}] {app_name}")
            logger.info(f"      Hostname: {hostname}")
        
        # Create secrets in Vault
        created_paths, create_failures = create_multiple_vault_secrets(
            vault_client,
            vault_secrets_config,
            verbose=True
        )
        
        if create_failures:
            failure_msg = f"Failed to create {len(create_failures)} vault secret(s): {create_failures}"
            logger.error(failure_msg)
            pytest.fail(failure_msg)
        
        # Create applications in GitHub
        print_section_header("STEP 3: Creating Applications in GitHub")
        
        # Template for values.yaml with externalSecret configuration
        def create_values_yaml(app_name, hostname):
            return f"""#https://github.com/traefik/whoami
image:
  registry: dockerhub.repo.gpkg.io
  repository: traefik/whoami
  tag: latest
  port: 80
service:
  enabled: true
deployment:
  replicas: 2
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
podDisruptionBudget:
  enabled: true
externalSecret:
  enabled: true
  secrets:
    app-secrets:
      dataFrom:
        key: secret/{app_name}/prod
    extra-app-secrets:
      dataFrom:
        key: secret/{app_name}/extra
"""
        
        for i, app in enumerate(app_info, 1):
            app_name = app['name']
            hostname = app['hostname']
            
            file_path = f"apps/{app_name}/envs/prod/values.yaml"
            file_content = create_values_yaml(app_name, hostname)
            
            create_github_file(
                repo=repo,
                file_path=file_path,
                content=file_content,
                commit_message=f"Add {app_name} with External Secrets",
                verbose=True,
                log_content=True
            )
        
        print_summary_list(
            [{'name': app['name'], 'hostname': app['hostname']} for app in app_info],
            title="Applications to validate"
        )
        
        # Wait for deployments to be ready
        print_section_header("STEP 4: Waiting for GitOps sync and deployments")
        
        display_progress_bar(
            wait_time=300,
            interval=15,
            description="Waiting for ArgoCD sync, External Secrets sync, and deployments (5 minutes)",
            verbose=True
        )
        
        # Check ArgoCD application health and sync status
        print_section_header("STEP 5: Checking ArgoCD Application Status")
        
        assert_argocd_healthy(custom_api, namespace_filter=None, verbose=True)
        
        # Check pod health across all platform namespaces
        print_section_header("STEP 6: Checking Pod Health")
        
        assert_pods_healthy(core_v1, platform_namespaces, verbose=True)
        
        # Validate Ingress configuration
        print_section_header("STEP 7: Validating Ingress Configuration")
        
        total_ingresses = assert_ingress_valid(networking_v1, platform_namespaces, verbose=True)
        
        # Validate DNS resolution for Ingress hosts
        print_section_header("STEP 8: Validating Ingress DNS Resolution")
        
        checked_count = assert_ingress_dns_valid(
            networking_v1,
            platform_namespaces,
            dns_server='1.1.1.1',
            verbose=True
        )
        
        # Validate environment variables from Vault
        print_section_header("STEP 9: Validating Environment Variables from Vault")
        
        validation_errors = []
        
        for idx, app in enumerate(app_info, 1):
            app_name = app['name']
            url = app['url']
            
            logger.info(f"[{idx}/{len(app_info)}] {app_name}")
            
            # Combine all expected environment variables (spot check 3 from each)
            expected_env_vars = {}
            
            app_secret_keys = list(app['app_secrets'].keys())[:3]
            for key in app_secret_keys:
                expected_env_vars[key] = app['app_secrets'][key]
            
            extra_secret_keys = list(app['extra_secrets'].keys())[:3]
            for key in extra_secret_keys:
                expected_env_vars[key] = app['extra_secrets'][key]
            
            # Validate environment variables
            problems, env_vars = validate_whoami_env_vars(
                url=url,
                expected_env_vars=expected_env_vars,
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
        
        logger.info(f"\n✅ SUCCESS: External Secrets integration validated")
        logger.info(f"   ✓ {len(vault_secrets_config)} Vault secrets created")
        logger.info(f"   ✓ {len(app_info)} applications deployed")
        logger.info(f"   ✓ All validations passed\n")
    
    finally:
        # Cleanup vault secrets
        if vault_client and vault_secret_paths:
            print_section_header("CLEANUP: Deleting Vault Secrets")
            
            deleted_paths, delete_failures = delete_multiple_vault_secrets(
                vault_client,
                vault_secret_paths,
                verbose=True
            )
        
        # Cleanup vault client (terminates port-forward)
        if vault_client:
            cleanup_vault_client(vault_client)
