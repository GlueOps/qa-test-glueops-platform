"""
Smoke Test Template - Read-Only Validation

Copy this file to tests/smoke/ and customize for your test.

Usage:
    cp tests/templates/_test_smoke_template.py tests/smoke/test_my_feature.py
"""
import pytest
import logging
from tests.helpers.k8s import validate_all_argocd_apps
# Other imports you might need:
# from tests.helpers.k8s import validate_pod_health, validate_ingress_configuration
# from tests.helpers.assertions import assert_argocd_healthy, assert_pods_healthy

logger = logging.getLogger(__name__)


# =============================================================================
# BASIC SMOKE TEST - Using validators directly
# =============================================================================
@pytest.mark.smoke
@pytest.mark.quick  # or @pytest.mark.slow for tests >30s
@pytest.mark.critical  # or @pytest.mark.important or @pytest.mark.informational
@pytest.mark.readonly
@pytest.mark.argocd  # Add component marker(s): argocd, workloads, vault, backup, etc.
def test_example_validation(custom_api, namespace_filter, capsys):
    """Check something is in the expected state.
    
    Validates:
    - First thing this test checks
    - Second thing this test checks
    
    Fails if any validation fails.
    
    Cluster Impact: READ-ONLY (queries only, no modifications)
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        namespace_filter: Optional namespace filter from CLI
        capsys: Pytest fixture for capturing stdout
    """
    logger.info("\n" + "=" * 70)
    logger.info("MY VALIDATION CHECK")
    logger.info("=" * 70)
    
    # Call validator function - returns list of problems
    problems = validate_all_argocd_apps(custom_api, namespace_filter)
    
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    
    # Fail if problems found
    if problems:
        error_msg = f"❌ {len(problems)} issue(s) found:\n"
        for p in problems:
            error_msg += f"  - {p}\n"
        pytest.fail(error_msg)
    
    logger.info("✅ All checks passed\n")


# =============================================================================
# SIMPLER VERSION - Using assertion helpers
# =============================================================================
@pytest.mark.smoke
@pytest.mark.quick
@pytest.mark.critical
@pytest.mark.readonly
@pytest.mark.argocd
def test_example_using_assertions(custom_api, namespace_filter):
    """Check something is in the expected state (simpler version).
    
    Uses assertion helpers that handle logging and pytest.fail() internally.
    
    Cluster Impact: READ-ONLY
    """
    from tests.helpers.assertions import assert_argocd_healthy
    
    # One-liner - handles everything internally
    assert_argocd_healthy(custom_api, namespace_filter)


# =============================================================================
# EXAMPLE: Multi-namespace validation
# =============================================================================
@pytest.mark.smoke
@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.workloads
def test_example_multi_namespace(core_v1, platform_namespaces, capsys):
    """Check pods across all platform namespaces.
    
    Validates:
    - Pods are not in CrashLoopBackOff
    - Pods are not OOMKilled
    - Pod restart count is reasonable
    
    Cluster Impact: READ-ONLY
    """
    from tests.helpers.k8s import validate_pod_health
    
    problems = validate_pod_health(core_v1, platform_namespaces)
    
    if problems:
        pytest.fail(f"❌ {len(problems)} pod issue(s):\n" + "\n".join(f"  - {p}" for p in problems))
    
    logger.info(f"✅ All pods healthy across {len(platform_namespaces)} namespaces")
