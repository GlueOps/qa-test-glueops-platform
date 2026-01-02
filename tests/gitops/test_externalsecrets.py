"""
GitOps External Secrets Tests

Tests External Secrets Operator integration with Vault.
Creates secrets in Vault, deploys apps that reference them,
and validates the secrets are synced as environment variables.
"""
import pytest
import uuid
import random
import string
from tests.helpers.assertions import (
    assert_argocd_healthy,
    assert_pods_healthy,
    assert_ingress_valid,
    assert_ingress_dns_valid
)
from tests.helpers.k8s import validate_whoami_env_vars
from tests.helpers.github import create_github_file
from tests.helpers.argocd import wait_for_appset_apps_created_and_healthy, calculate_expected_app_count
from tests.helpers.utils import print_section_header, print_summary_list


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
@pytest.mark.captain_manifests
@pytest.mark.vault
@pytest.mark.flaky(reruns=1, reruns_delay=300)
def test_externalsecrets_vault_integration(vault_test_secrets, captain_manifests, ephemeral_github_repo, custom_api, core_v1, networking_v1, platform_namespaces):
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
    
    Uses vault_test_secrets fixture which handles cleanup before and after test.
    """
    captain_domain = captain_manifests['captain_domain']
    repo = ephemeral_github_repo
    
    # Generate applications and vault secrets
    print_section_header("STEP 1: Creating Vault Secrets")
    
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
    
    # Create secrets in Vault using the manager
    created_paths, create_failures = vault_test_secrets.create_secrets(vault_secrets_config)
    
    if create_failures:
        pytest.fail(f"Failed to create {len(create_failures)} vault secret(s): {create_failures}")
    
    # Create applications in GitHub
    print_section_header("STEP 2: Creating Applications in GitHub")
    
    from tests.templates import load_template
    
    for i, app in enumerate(app_info, 1):
        app_name = app['name']
        hostname = app['hostname']
        
        file_path = f"apps/{app_name}/envs/prod/values.yaml"
        file_content = load_template('externalsecrets-app-values.yaml', 
                                     app_name=app_name, 
                                     hostname=hostname)
        
        create_github_file(
            repo=repo,
            file_path=file_path,
            content=file_content,
            commit_message=f"Add {app_name} with External Secrets"
        )
    
    print_summary_list(
        [{'name': app['name'], 'hostname': app['hostname']} for app in app_info],
        title="Applications to validate"
    )
    
    # Wait for ApplicationSet to discover and sync the apps we just created
    expected_total = calculate_expected_app_count(captain_manifests, num_apps)
    apps_ready = wait_for_appset_apps_created_and_healthy(
        custom_api,
        namespace=captain_manifests['namespace'],
        expected_count=expected_total
    )
    
    if not apps_ready:
        pytest.fail(f"ApplicationSet did not create/sync {num_apps} apps within timeout")
    
    # Check ArgoCD application health and sync status
    print_section_header("STEP 3: Checking ArgoCD Application Status")
    
    assert_argocd_healthy(custom_api, namespace_filter=None)
    
    # Check pod health across all platform namespaces
    print_section_header("STEP 4: Checking Pod Health")
    
    assert_pods_healthy(core_v1, platform_namespaces)
    
    # Validate Ingress configuration
    print_section_header("STEP 5: Validating Ingress Configuration")
    
    assert_ingress_valid(networking_v1, platform_namespaces)
    
    # Validate DNS resolution for Ingress hosts
    print_section_header("STEP 6: Validating Ingress DNS Resolution")
    
    assert_ingress_dns_valid(
        networking_v1,
        platform_namespaces,
        dns_server='1.1.1.1'
    )
    
    # Validate environment variables from Vault
    print_section_header("STEP 7: Validating Environment Variables from Vault")
    
    validation_errors = []
    
    for idx, app in enumerate(app_info, 1):
        app_name = app['name']
        url = app['url']
        
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
            retry_delays=[10, 30, 60]
        )
        
        if problems:
            validation_errors.extend(problems)
    
    # Assert no validation errors occurred
    if validation_errors:
        pytest.fail(f"External Secrets validation failed with {len(validation_errors)} error(s):\n" +
                   "\n".join(f"  - {e}" for e in validation_errors))
    
