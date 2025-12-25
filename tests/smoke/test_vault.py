"""Vault secrets tests"""
import pytest
import json
import time
from pathlib import Path
from lib.port_forward import PortForward

try:
    import hvac
    import urllib3
except ImportError:
    hvac = None
    urllib3 = None


def get_vault_root_token(captain_domain):
    """Extract Vault root token from terraform state file.
    
    Reads terraform state from:
    /workspaces/glueops/{captain_domain}/terraform/vault/configuration/terraform.tfstate
    
    Searches for aws_s3_object.vault_access data source and parses
    the body JSON to extract root_token.
    
    Args:
        captain_domain: Domain name used in directory path
    
    Returns: Vault root token string
    
    Raises:
        FileNotFoundError: If terraform.tfstate file doesn't exist
        ValueError: If root_token not found in state file
    """
    tfstate_path = Path(f"/workspaces/glueops/{captain_domain}/terraform/vault/configuration/terraform.tfstate")
    
    if not tfstate_path.exists():
        raise FileNotFoundError(f"Terraform state not found: {tfstate_path}")
    
    with open(tfstate_path, 'r') as f:
        tfstate = json.load(f)
    
    # Find the vault_access data source
    for resource in tfstate.get('resources', []):
        if (resource.get('type') == 'aws_s3_object' and 
            resource.get('name') == 'vault_access' and
            resource.get('mode') == 'data'):
            
            for instance in resource.get('instances', []):
                body = instance.get('attributes', {}).get('body')
                if body:
                    vault_data = json.loads(body)
                    return vault_data.get('root_token')
    
    raise ValueError("Root token not found in terraform state")


def get_vault_client(captain_domain, vault_namespace="glueops-core-vault", vault_service="vault"):
    """Create authenticated Vault client with kubectl port-forward.
    
    Establishes port-forward to Vault service and creates hvac client.
    
    Process:
    1. Extracts root token from terraform state
    2. Creates port-forward to vault:8200 service
    3. Creates hvac.Client with token authentication (SSL verification disabled)
    4. Verifies authentication
    
    The port-forward is attached to the client object (_port_forward attribute)
    and must be cleaned up with cleanup_vault_client() after use.
    
    Args:
        captain_domain: Domain for locating terraform state
        vault_namespace: Kubernetes namespace (default: glueops-core-vault)
        vault_service: Kubernetes service name (default: vault)
    
    Returns: Authenticated hvac.Client with _port_forward attached
    
    Raises:
        ImportError: If hvac library not installed
        Exception: If authentication fails
    """
    if hvac is None:
        raise ImportError("hvac library not installed. Run: pip install hvac")
    
    token = get_vault_root_token(captain_domain)
    
    # Use port-forward context manager
    port_forward = PortForward(namespace=vault_namespace, service=vault_service, port=8200)
    port_forward.__enter__()
    vault_addr = f"https://127.0.0.1:{port_forward.local_port}"
    
    # Disable SSL warnings for local connections
    if urllib3:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    client = hvac.Client(url=vault_addr, token=token, verify=False)
    
    if not client.is_authenticated():
        port_forward.__exit__(None, None, None)
        raise Exception("Failed to authenticate with Vault")
    
    # Attach port_forward to client so it stays alive
    client._port_forward = port_forward
    
    return client


def cleanup_vault_client(client):
    """Cleanup Vault client and terminate port-forward.
    
    Closes the port-forward process attached to the client.
    Must be called after get_vault_client() to avoid leaving kubectl processes running.
    
    Args:
        client: hvac.Client returned from get_vault_client()
    """
    if hasattr(client, '_port_forward'):
        client._port_forward.__exit__(None, None, None)


@pytest.mark.slow
@pytest.mark.write
@pytest.mark.vault
def test_vault_secret_creation(captain_domain, request):
    """Create test secrets in Vault to validate write performance and capacity (WRITE operation).
    
    Performance test that creates multiple secrets to validate:
    - Vault can handle concurrent/sequential writes
    - No errors during secret creation
    - Secrets are readable after creation
    
    Creates secrets at paths: secret/test/path-{i}/secret
    Each secret contains: {"test_key": "test_value_{i}", "index": i, "purpose": "smoke_test"}
    
    Waits 30 seconds after creation to allow propagation, then cleans up.
    
    Cluster Impact: WRITE (creates and deletes Vault secrets)
    """
    if hvac is None:
        pytest.skip("hvac library not installed. Run: pip install hvac")
    
    num_secrets = 10  # Default to 10 for faster testing
    secret_prefix = "test"
    cleanup = True
    verbose = request.config.option.verbose > 0
    vault_namespace = "glueops-core-vault"
    
    client = None
    try:
        if verbose:
            print(f"  Setting up port-forward to Vault in {vault_namespace}...")
        
        client = get_vault_client(captain_domain, vault_namespace=vault_namespace)
        
        if verbose:
            print(f"  Connected to Vault, creating {num_secrets} secrets...")
        
        created_paths = []
        failures = []
        
        # Create secrets
        for i in range(num_secrets):
            path = f"{secret_prefix}/path-{i}/secret"
            data = {
                "test_key": f"test_value_{i}",
                "index": i,
                "purpose": "smoke_test"
            }
            
            try:
                client.secrets.kv.v2.create_or_update_secret(
                    path=path,
                    secret=data,
                    mount_point='secret'
                )
                created_paths.append(path)
                
                if verbose and (i + 1) % 10 == 0:
                    print(f"  Created {i + 1}/{num_secrets} secrets...")
                    
            except Exception as e:
                failures.append(f"path-{i}: {str(e)}")
        
        # Verify secrets were created
        verification_failures = []
        for path in created_paths[:5]:  # Verify first 5 as sample
            try:
                secret = client.secrets.kv.v2.read_secret_version(
                    path=path,
                    mount_point='secret',
                    raise_on_deleted_version=False
                )
                if not secret['data']['data']:
                    verification_failures.append(f"{path}: empty data")
            except Exception as e:
                verification_failures.append(f"{path}: {str(e)}")
        
        if verbose:
            print(f"  ✓ All {len(created_paths)} secrets created successfully!")
            if cleanup:
                print(f"  ⏸  Waiting 30 seconds before cleanup (check Vault UI now)...")
                time.sleep(30)
        
        # Cleanup if requested
        if cleanup:
            cleanup_failures = []
            if verbose:
                print(f"  🧹 Starting cleanup...")
            
            for path in created_paths:
                try:
                    client.secrets.kv.v2.delete_metadata_and_all_versions(
                        path=path,
                        mount_point='secret'
                    )
                except Exception as e:
                    cleanup_failures.append(f"{path}: {str(e)}")
            
            if verbose:
                print(f"  Cleaned up {len(created_paths) - len(cleanup_failures)}/{len(created_paths)} secrets")
        
        # Assert no failures
        if failures:
            pytest.fail(f"Failed to create {len(failures)}/{num_secrets} secrets:\n" +
                       "\n".join(f"  - {f}" for f in failures[:5]))
        
        if verification_failures:
            pytest.fail(f"Created but failed to verify {len(verification_failures)} secrets:\n" +
                       "\n".join(f"  - {v}" for v in verification_failures))
        
        if cleanup and cleanup_failures:
            pytest.fail(f"Created successfully but failed to cleanup {len(cleanup_failures)} secrets:\n" +
                       "\n".join(f"  - {c}" for c in cleanup_failures[:5]))
        
        action = "created and cleaned up" if cleanup else "created"
        print(f"✓ {num_secrets} secrets {action}")
    
    finally:
        if client:
            cleanup_vault_client(client)
