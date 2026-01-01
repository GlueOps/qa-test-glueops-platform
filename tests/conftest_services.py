"""
Service connection fixtures for GlueOps test suite.

This module provides fixtures for connecting to platform services
via port-forwarding, including Vault, Prometheus, and Alertmanager.

Fixtures:
    - prometheus_url: Port-forward to Prometheus and yield local URL
    - alertmanager_url: Port-forward to Alertmanager and yield local URL
    - vault_client: Vault client with automatic port-forward and cleanup
    - cleanup_vault_secrets_session: Session-scoped cleanup of orphaned secrets
    - vault_test_secrets: Vault secret manager with pre/post cleanup
"""
import pytest
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any

from tests.helpers.port_forward import PortForward


logger = logging.getLogger(__name__)


# =============================================================================
# PORT-FORWARD FIXTURES
# =============================================================================

@pytest.fixture
def prometheus_url():
    """
    Port-forward to Prometheus and yield local URL.
    
    Automatically establishes kubectl port-forward to Prometheus service
    and cleans up the connection after the test completes.
    
    Scope: function (new connection per test)
    
    Service Details:
        - Namespace: glueops-core-kube-prometheus-stack
        - Service: kps-prometheus
        - Port: 9090
    
    Returns:
        str: Local Prometheus URL (e.g., 'http://127.0.0.1:9090')
    
    Usage:
        def test_prometheus_metrics(prometheus_url):
            response = requests.get(f"{prometheus_url}/api/v1/query?query=up")
            assert response.status_code == 200
    """
    with PortForward("glueops-core-kube-prometheus-stack", "kps-prometheus", 9090) as pf:
        yield f"http://127.0.0.1:{pf.local_port}"


@pytest.fixture
def alertmanager_url():
    """
    Port-forward to Alertmanager and yield local URL.
    
    Automatically establishes kubectl port-forward to Alertmanager service
    and cleans up the connection after the test completes.
    
    Scope: function (new connection per test)
    
    Service Details:
        - Namespace: glueops-core-kube-prometheus-stack
        - Service: kps-alertmanager
        - Port: 9093
    
    Returns:
        str: Local Alertmanager URL (e.g., 'http://127.0.0.1:9093')
    
    Usage:
        def test_alertmanager(alertmanager_url):
            response = requests.get(f"{alertmanager_url}/api/v2/status")
            assert response.status_code == 200
    """
    with PortForward("glueops-core-kube-prometheus-stack", "kps-alertmanager", 9093) as pf:
        yield f"http://127.0.0.1:{pf.local_port}"


# =============================================================================
# VAULT CLIENT FIXTURE
# =============================================================================

@pytest.fixture
def vault_client(captain_domain, request):
    """
    Vault client with automatic port-forward and cleanup.
    
    Establishes kubectl port-forward to Vault, authenticates, and yields
    an authenticated hvac.Client. Automatically cleans up port-forward
    on test completion.
    
    Scope: function (new connection per test)
    
    Service Details:
        - Namespace: glueops-core-vault
        - Vault authentication via Kubernetes service account or token
    
    Dependencies:
        - captain_domain: Captain domain fixture for Vault configuration
    
    Returns:
        hvac.Client: Authenticated Vault client
    
    Raises:
        ImportError: If hvac library not installed
        pytest.skip: If required environment variables not set
    
    Usage:
        def test_vault_secrets(vault_client):
            # Create secret
            vault_client.secrets.kv.v2.create_or_update_secret(
                path="test/path",
                secret={"key": "value"}
            )
            
            # Read secret
            result = vault_client.secrets.kv.v2.read_secret_version(path="test/path")
            assert result['data']['data']['key'] == 'value'
    """
    from tests.helpers.vault import get_vault_client, cleanup_vault_client
    
    vault_namespace = "glueops-core-vault"
    
    client = get_vault_client(
        captain_domain, 
        vault_namespace=vault_namespace
    )
    
    yield client
    
    cleanup_vault_client(client)


# =============================================================================
# VAULT SECRET MANAGER (WITH CLEANUP)
# =============================================================================

@dataclass
class VaultSecretManager:
    """
    Manager for creating Vault secrets with automatic tracking.
    
    Provides methods for creating secrets and tracks all created paths
    for potential cleanup. Used by the vault_test_secrets fixture.
    
    Attributes:
        client: Authenticated hvac.Client
        created_paths: List of secret paths created by this manager
        mount_point: KV mount point (default: "secret")
    """
    client: Any
    created_paths: List[str] = field(default_factory=list)
    mount_point: str = "secret"
    
    def create_secret(self, path: str, data: Dict[str, Any]) -> str:
        """
        Create a single secret and track the path.
        
        Args:
            path: Secret path
            data: Dictionary of secret data
        
        Returns:
            str: The created secret path
        """
        from tests.helpers.vault import create_vault_secret
        
        create_vault_secret(self.client, path, data, self.mount_point)
        self.created_paths.append(path)
        return path
    
    def create_secrets(self, secret_configs: List[Dict[str, Any]]) -> tuple:
        """
        Create multiple secrets and track their paths.
        
        Args:
            secret_configs: List of dicts with 'path' and 'data' keys
        
        Returns:
            tuple: (created_paths, failures)
        """
        from tests.helpers.vault import create_multiple_vault_secrets
        
        created, failures = create_multiple_vault_secrets(
            self.client, secret_configs, self.mount_point
        )
        self.created_paths.extend(created)
        return created, failures


@pytest.fixture(scope="session")
def cleanup_vault_secrets_session(captain_domain):
    """
    Session-scoped cleanup of orphaned Vault secrets from previous runs.
    
    Runs once at session start before any tests. Cleans up all secrets
    from the 'secret' mount except the placeholder secret, then ensures
    the placeholder secret exists with updated timestamp.
    
    This handles orphaned secrets from crashed or interrupted test runs.
    
    Raises:
        RuntimeError: If cleanup fails (blocks test session)
    """
    from tests.helpers.vault import (
        get_vault_client,
        cleanup_vault_client,
        cleanup_all_vault_secrets,
        ensure_placeholder_secret
    )
    
    logger.info("\n" + "="*70)
    logger.info("SESSION STARTUP: Cleaning orphaned Vault secrets")
    logger.info("="*70)
    
    client = get_vault_client(captain_domain, vault_namespace="glueops-core-vault")
    
    try:
        # Clean up all secrets except placeholder
        cleanup_all_vault_secrets(client, mount_point='secret')
        
        # Ensure placeholder secret exists with updated timestamp
        ensure_placeholder_secret(client, mount_point='secret')
        
        logger.info("✓ Session Vault cleanup complete\n")
    finally:
        cleanup_vault_client(client)
    
    yield


@pytest.fixture
def vault_test_secrets(captain_domain, cleanup_vault_secrets_session):
    """
    Vault secret manager with pre-cleanup and post-cleanup.
    
    This fixture:
    1. Pre-cleanup: Deletes all secrets (except placeholder) before test
    2. Updates placeholder secret with current timestamp
    3. Yields VaultSecretManager for creating secrets
    4. Post-cleanup: Deletes all secrets (except placeholder) after test
    
    The session-scoped cleanup_vault_secrets_session runs first to handle
    orphaned secrets from previous runs.
    
    Dependencies:
        - captain_domain: Captain domain fixture for Vault configuration
        - cleanup_vault_secrets_session: Session cleanup (runs first)
    
    Returns:
        VaultSecretManager: Manager for creating and tracking secrets
    
    Raises:
        RuntimeError: If pre-cleanup or post-cleanup fails (fails the test)
    
    Usage:
        def test_my_vault_test(vault_test_secrets):
            # Create secrets using the manager
            vault_test_secrets.create_secret("my/path", {"key": "value"})
            
            # Or create multiple secrets
            vault_test_secrets.create_secrets([
                {"path": "path1", "data": {"key": "value1"}},
                {"path": "path2", "data": {"key": "value2"}}
            ])
            
            # Access the underlying client if needed
            client = vault_test_secrets.client
    """
    from tests.helpers.vault import (
        get_vault_client,
        cleanup_vault_client,
        cleanup_all_vault_secrets,
        ensure_placeholder_secret
    )
    
    logger.info("\n" + "="*70)
    logger.info("VAULT TEST SETUP: Pre-cleanup")
    logger.info("="*70)
    
    client = get_vault_client(captain_domain, vault_namespace="glueops-core-vault")
    
    try:
        # Pre-cleanup: Delete all secrets except placeholder
        cleanup_all_vault_secrets(client, mount_point='secret')
        
        # Ensure placeholder secret exists with updated timestamp
        ensure_placeholder_secret(client, mount_point='secret')
        
        logger.info("✓ Pre-cleanup complete\n")
        
        # Create manager and yield to test
        manager = VaultSecretManager(client=client, mount_point='secret')
        
        yield manager
        
        # Post-cleanup: Delete all secrets except placeholder
        logger.info("\n" + "="*70)
        logger.info("VAULT TEST TEARDOWN: Post-cleanup")
        logger.info("="*70)
        
        cleanup_all_vault_secrets(client, mount_point='secret')
        
        # Update placeholder timestamp after cleanup
        ensure_placeholder_secret(client, mount_point='secret')
        
        logger.info("✓ Post-cleanup complete\n")
        
    finally:
        cleanup_vault_client(client)
