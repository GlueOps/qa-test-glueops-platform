"""Vault secrets tests"""
import pytest
import logging
import time
from tests.helpers.vault import (
    verify_vault_secrets
)

logger = logging.getLogger(__name__)

try:
    import hvac
except ImportError:
    hvac = None


@pytest.mark.slow
@pytest.mark.write
@pytest.mark.vault
def test_vault_secret_creation(vault_test_secrets, request):
    """Create test secrets in Vault to validate write performance and capacity (WRITE operation).
    
    Performance test that creates multiple secrets to validate:
    - Vault can handle concurrent/sequential writes
    - No errors during secret creation
    - Secrets are readable after creation
    
    Creates secrets at paths: secret/test/path-{i}/secret
    Each secret contains: {"test_key": "test_value_{i}", "index": i, "purpose": "smoke_test"}
    
    Uses vault_test_secrets fixture which handles cleanup before and after test.
    
    Cluster Impact: WRITE (creates Vault secrets, cleanup handled by fixture)
    """
    if hvac is None:
        pytest.skip("hvac library not installed. Run: pip install hvac")
    
    num_secrets = 10
    secret_prefix = "test"
    verbose = request.config.option.verbose > 0
    
    # Prepare secret configurations
    secret_configs = [
        {
            'path': f"{secret_prefix}/path-{i}/secret",
            'data': {
                "test_key": f"test_value_{i}",
                "index": i,
                "purpose": "smoke_test"
            }
        }
        for i in range(num_secrets)
    ]
    
    # Create secrets using the manager
    created_paths, create_failures = vault_test_secrets.create_secrets(secret_configs)
    
    # Verify secrets (sample first 5)
    verify_failures = verify_vault_secrets(
        vault_test_secrets.client, created_paths, sample_size=5
    )
    
    # Wait before fixture cleanup (only in verbose mode for debugging)
    if verbose and len(created_paths) > 0:
        logger.info(f"⏸  Waiting 30 seconds for manual inspection (check Vault UI)...")
        logger.info(f"   Check paths: secret/data/{secret_prefix}/path-*/secret")
        time.sleep(30)
    
    # Assert no failures
    if create_failures:
        pytest.fail(
            f"❌ Failed to create {len(create_failures)}/{num_secrets} secrets:\n" +
            "\n".join(f"  - {f}" for f in create_failures[:5])
        )
    
    if verify_failures:
        pytest.fail(
            f"❌ Created but failed to verify {len(verify_failures)} secrets:\n" +
            "\n".join(f"  - {v}" for v in verify_failures)
        )
