"""Vault secrets tests"""
import pytest
import logging
import time
from lib.vault_helpers import (
    get_vault_client,
    cleanup_vault_client,
    create_multiple_vault_secrets,
    delete_multiple_vault_secrets,
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
    
    logger.info("\\n" + "="*70)
    logger.info("VAULT SECRET CREATION TEST")
    logger.info("="*70)
    logger.info(f"  Secrets to create: {num_secrets}")
    logger.info(f"  Prefix: {secret_prefix}")
    logger.info(f"  Cleanup enabled: {cleanup}")
    logger.info("")
    
    client = None
    try:
        # Connect to Vault
        client = get_vault_client(captain_domain, vault_namespace=vault_namespace, verbose=verbose)
        
        # Prepare secret configurations
        logger.info(f"\ud83d\udcdd Preparing {num_secrets} secret configurations...")
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
        logger.info(f"  \u2713 Configurations prepared\\n")
        
        # Create secrets
        logger.info("="*70)
        logger.info("STEP 1: Creating secrets")
        logger.info("="*70)
        created_paths, create_failures = create_multiple_vault_secrets(
            client, secret_configs, verbose=True
        )
        
        if create_failures:
            logger.info(f"\\n\u26a0\ufe0f  Encountered {len(create_failures)} error(s) during creation:")
            for error in create_failures[:5]:  # Show first 5 errors
                logger.info(f"     \u2022 {error}")
            if len(create_failures) > 5:
                logger.info(f"     ... and {len(create_failures) - 5} more")
        
        # Verify secrets (sample first 5)
        logger.info("\\n" + "="*70)
        logger.info("STEP 2: Verifying secrets")
        logger.info("="*70)
        verify_failures = verify_vault_secrets(
            client, created_paths, sample_size=5, verbose=True
        )
        
        if verify_failures:
            logger.info(f"\n⚠️  Encountered {len(verify_failures)} verification error(s):")
            for error in verify_failures:
                logger.info(f"     • {error}")
        
        # Wait before cleanup
        if verbose and cleanup and len(created_paths) > 0:
            logger.info("\n" + "="*70)
            logger.info("STEP 3: Waiting before cleanup")
            logger.info("="*70)
            logger.info(f"  ⏸  Waiting 30 seconds (check Vault UI now)...")
            logger.info(f"  📍 Check paths: secret/data/{secret_prefix}/path-*/secret")
            for i in range(30, 0, -5):
                logger.info(f"     {i} seconds remaining...")
                time.sleep(5)
            logger.info(f"  ✓ Wait complete\n")
        
        # Cleanup if requested
        cleanup_failures = []
        if cleanup and len(created_paths) > 0:
            logger.info("="*70)
            logger.info("STEP 4: Cleanup")
            logger.info("="*70)
            cleanup_failures = delete_multiple_vault_secrets(
                client, created_paths, verbose=True
            )
            
            if cleanup_failures:
                logger.info(f"\n⚠️  Encountered {len(cleanup_failures)} cleanup error(s):")
                for error in cleanup_failures[:5]:
                    logger.info(f"     • {error}")
                if len(cleanup_failures) > 5:
                    logger.info(f"     ... and {len(cleanup_failures) - 5} more")
        
        # Final summary
        logger.info("\n" + "="*70)
        logger.info("TEST SUMMARY")
        logger.info("="*70)
        logger.info(f"  Created: {len(created_paths)}/{num_secrets} secrets")
        logger.info(f"  Create failures: {len(create_failures)}")
        logger.info(f"  Verify failures: {len(verify_failures)}")
        if cleanup:
            logger.info(f"  Cleanup failures: {len(cleanup_failures)}")
        logger.info("")
        
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
        
        if cleanup and cleanup_failures:
            pytest.fail(
                f"❌ Created successfully but failed to cleanup {len(cleanup_failures)} secrets:\n" +
                "\n".join(f"  - {c}" for c in cleanup_failures[:5])
            )
        
        action = "created and cleaned up" if cleanup else "created"
        logger.info(f"✅ SUCCESS: {num_secrets} secrets {action}")
    
    finally:
        if client:
            cleanup_vault_client(client, verbose=verbose)
