"""
Vault helper functions for secret management.

This module provides utilities for interacting with HashiCorp Vault
during test automation, including secret creation, reading, and cleanup.
"""
import json
import random
import logging
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)

try:
    import hvac
    import urllib3
except ImportError:
    hvac = None
    urllib3 = None

from tests.helpers.port_forward import PortForward


def get_vault_root_token(captain_domain):
    """
    Extract Vault root token from terraform state file.
    
    Reads terraform state from:
    /workspaces/glueops/{captain_domain}/terraform/vault/configuration/terraform.tfstate
    
    Args:
        captain_domain: Domain name used in directory path
    
    Returns:
        str: Vault root token
    
    Raises:
        FileNotFoundError: If terraform.tfstate file doesn't exist
        ValueError: If root_token not found in state file
    """
    tfstate_path = Path(f"/workspaces/glueops/{captain_domain}/terraform/vault/configuration/terraform.tfstate")
    
    logger.info(f"  📂 Looking for terraform state: {tfstate_path}")
    
    if not tfstate_path.exists():
        raise FileNotFoundError(f"Terraform state not found: {tfstate_path}")
    
    logger.info(f"  ✓ Found terraform state file")
    
    with open(tfstate_path, 'r') as f:
        tfstate = json.load(f)
    
    logger.info(f"  🔍 Searching for vault_access in terraform state...")
    for resource in tfstate.get('resources', []):
        if (resource.get('type') == 'aws_s3_object' and 
            resource.get('name') == 'vault_access' and
            resource.get('mode') == 'data'):
            
            for instance in resource.get('instances', []):
                body = instance.get('attributes', {}).get('body')
                if body:
                    vault_data = json.loads(body)
                    token = vault_data.get('root_token')
                    if token:
                        logger.info(f"  ✓ Extracted Vault root token (length: {len(token)})")
                        return token
    
    raise ValueError("Root token not found in terraform state")


def get_vault_client(captain_domain, vault_namespace="glueops-core-vault", vault_service="vault", verbose=True):
    """
    Create authenticated Vault client with kubectl port-forward.
    
    Args:
        captain_domain: Domain for locating terraform state
        vault_namespace: Kubernetes namespace (default: glueops-core-vault)
        vault_service: Kubernetes service name (default: vault)
        verbose: Print detailed progress messages (default: True)
    
    Returns:
        hvac.Client: Authenticated client with _port_forward attached
    
    Raises:
        ImportError: If hvac library not installed
        Exception: If authentication fails
    """
    if hvac is None:
        raise ImportError("hvac library not installed. Run: pip install hvac")
    
    if verbose:
        logger.info(f"\n🔐 Connecting to Vault...")
        logger.info(f"  Namespace: {vault_namespace}")
        logger.info(f"  Service: {vault_service}")
    
    token = get_vault_root_token(captain_domain)
    
    if verbose:
        logger.info(f"  🔌 Establishing port-forward to {vault_namespace}/{vault_service}:8200...")
    
    port_forward = PortForward(namespace=vault_namespace, service=vault_service, port=8200)
    port_forward.__enter__()
    vault_addr = f"https://127.0.0.1:{port_forward.local_port}"
    
    if verbose:
        logger.info(f"  ✓ Port-forward established on localhost:{port_forward.local_port}")
    
    if urllib3:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    if verbose:
        logger.info(f"  🔑 Authenticating with Vault...")
    
    client = hvac.Client(url=vault_addr, token=token, verify=False)
    
    if not client.is_authenticated():
        port_forward.__exit__(None, None, None)
        raise Exception("Failed to authenticate with Vault")
    
    if verbose:
        logger.info(f"  ✓ Successfully authenticated with Vault\n")
    
    client._port_forward = port_forward
    
    return client


def cleanup_vault_client(client, verbose=True):
    """
    Cleanup Vault client and terminate port-forward.
    
    Args:
        client: hvac.Client returned from get_vault_client()
        verbose: Print cleanup message (default: True)
    """
    if hasattr(client, '_port_forward'):
        if verbose:
            logger.info(f"  🔌 Closing port-forward...")
        client._port_forward.__exit__(None, None, None)
        if verbose:
            logger.info(f"  ✓ Port-forward closed\n")


@contextmanager
def vault_client_context(captain_domain, vault_namespace="glueops-core-vault", verbose=True):
    """
    Context manager for Vault client with automatic cleanup.
    
    Usage:
        with vault_client_context(captain_domain, verbose=True) as client:
            create_vault_secret(client, "path", {"key": "value"})
    
    Args:
        captain_domain: Domain name
        vault_namespace: Vault namespace (default: "glueops-core-vault")
        verbose: Print status messages (default: True)
    
    Yields:
        hvac.Client: Authenticated Vault client
    """
    client = None
    try:
        client = get_vault_client(captain_domain, vault_namespace, verbose=verbose)
        yield client
    finally:
        if client:
            cleanup_vault_client(client, verbose)


def create_vault_secret(client, path, data, mount_point='secret'):
    """
    Create or update a secret in Vault KV v2.
    
    Args:
        client: Authenticated hvac.Client
        path: Secret path
        data: Dictionary of secret data
        mount_point: KV mount point (default: "secret")
    
    Returns:
        dict: Response from Vault API
    """
    return client.secrets.kv.v2.create_or_update_secret(
        path=path,
        secret=data,
        mount_point=mount_point
    )


def read_vault_secret(client, path, mount_point='secret', raise_on_deleted_version=False):
    """
    Read a secret from Vault KV v2.
    
    Args:
        client: Authenticated hvac.Client
        path: Secret path
        mount_point: KV mount point (default: "secret")
        raise_on_deleted_version: Whether to raise on deleted versions
    
    Returns:
        dict: Secret data
    """
    return client.secrets.kv.v2.read_secret_version(
        path=path,
        mount_point=mount_point,
        raise_on_deleted_version=raise_on_deleted_version
    )


def delete_vault_secret(client, path, mount_point='secret'):
    """
    Delete a secret and all its versions from Vault KV v2.
    
    Args:
        client: Authenticated hvac.Client
        path: Secret path
        mount_point: KV mount point (default: "secret")
    """
    client.secrets.kv.v2.delete_metadata_and_all_versions(
        path=path,
        mount_point=mount_point
    )


def create_multiple_vault_secrets(client, secret_configs, mount_point='secret', verbose=False):
    """
    Create multiple secrets in Vault with error tracking.
    
    Args:
        client: Authenticated hvac.Client
        secret_configs: List of dicts with 'path' and 'data' keys
        mount_point: KV mount point (default: "secret")
        verbose: Print progress messages (default: False)
    
    Returns:
        tuple: (created_paths, failures)
    """
    created_paths = []
    failures = []
    total = len(secret_configs)
    
    if verbose:
        logger.info(f"  📝 Creating {total} secrets...")
    
    for idx, config in enumerate(secret_configs, 1):
        path = config['path']
        data = config['data']
        
        try:
            create_vault_secret(client, path, data, mount_point)
            created_paths.append(path)
            
            if verbose and idx % 10 == 0:
                percentage = (idx / total) * 100
                logger.info(f"     [{idx}/{total}] {percentage:.0f}% complete...")
                
        except Exception as e:
            error_msg = f"{path}: {str(e)}"
            failures.append(error_msg)
            if verbose:
                logger.info(f"     ✗ Failed: {error_msg}")
    
    if verbose:
        success_count = len(created_paths)
        logger.info(f"  ✓ Created {success_count}/{total} secrets successfully")
        if failures:
            logger.info(f"  ✗ Failed to create {len(failures)} secrets")
    
    return created_paths, failures


def delete_multiple_vault_secrets(client, paths, mount_point='secret', verbose=False):
    """
    Delete multiple secrets from Vault with error tracking.
    
    Args:
        client: Authenticated hvac.Client
        paths: List of secret paths to delete
        mount_point: KV mount point (default: "secret")
        verbose: Print progress messages (default: False)
    
    Returns:
        tuple: (deleted_paths, failures)
    """
    deleted_paths = []
    failures = []
    total = len(paths)
    
    if verbose:
        logger.info(f"  🧹 Deleting {total} secrets...")
    
    for idx, path in enumerate(paths, 1):
        try:
            delete_vault_secret(client, path, mount_point)
            deleted_paths.append(path)
            
            if verbose and idx % 10 == 0:
                percentage = (idx / total) * 100
                logger.info(f"     [{idx}/{total}] {percentage:.0f}% complete...")
                
        except Exception as e:
            error_msg = f"{path}: {str(e)}"
            failures.append(error_msg)
            if verbose:
                logger.info(f"     ✗ Failed: {error_msg}")
    
    if verbose:
        success_count = len(deleted_paths)
        if failures:
            logger.info(f"  ⚠️  Deleted {success_count}/{total} secrets ({len(failures)} failed)")
        else:
            logger.info(f"  ✓ Successfully deleted {success_count} secrets")
    
    return deleted_paths, failures


def verify_vault_secrets(client, paths, mount_point='secret', sample_size=None, verbose=False):
    """
    Verify that secrets exist and are readable.
    
    Args:
        client: Authenticated hvac.Client
        paths: List of secret paths to verify
        mount_point: KV mount point (default: "secret")
        sample_size: If provided, only verify a random sample
        verbose: Print progress messages (default: False)
    
    Returns:
        list: List of error messages for failed verifications
    """
    failures = []
    paths_to_check = paths
    
    if sample_size and sample_size < len(paths):
        paths_to_check = random.sample(paths, sample_size)
        if verbose:
            logger.info(f"  🔍 Verifying random sample of {sample_size}/{len(paths)} secrets...")
    else:
        if verbose:
            logger.info(f"  🔍 Verifying {len(paths)} secrets...")
    
    for idx, path in enumerate(paths_to_check, 1):
        try:
            secret = read_vault_secret(client, path, mount_point, raise_on_deleted_version=False)
            if not secret.get('data', {}).get('data'):
                error_msg = f"{path}: empty data"
                failures.append(error_msg)
                if verbose:
                    logger.info(f"     ✗ {error_msg}")
            elif verbose and idx % 5 == 0:
                logger.info(f"     [{idx}/{len(paths_to_check)}] verified...")
        except Exception as e:
            error_msg = f"{path}: {str(e)}"
            failures.append(error_msg)
            if verbose:
                logger.info(f"     ✗ {error_msg}")
    
    if verbose:
        success_count = len(paths_to_check) - len(failures)
        logger.info(f"  ✓ Verified {success_count}/{len(paths_to_check)} secrets successfully")
        if failures:
            logger.info(f"  ✗ Failed to verify {len(failures)} secrets")
    
    return failures
