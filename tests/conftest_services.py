"""
Service connection fixtures for GlueOps test suite.

This module provides fixtures for connecting to platform services
via port-forwarding, including Vault, Prometheus, and Alertmanager.

Fixtures:
    - prometheus_url: Port-forward to Prometheus and yield local URL
    - alertmanager_url: Port-forward to Alertmanager and yield local URL
    - vault_client: Vault client with automatic port-forward and cleanup
"""
import pytest
import logging

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
