"""ArgoCD Application health checks"""
import pytest
import logging
from tests.helpers.k8s import validate_all_argocd_apps

logger = logging.getLogger(__name__)


@pytest.mark.smoke
@pytest.mark.quick
@pytest.mark.critical
@pytest.mark.readonly
@pytest.mark.argocd
def test_argocd_applications(custom_api, namespace_filter, capsys):
    """Check ArgoCD Applications are Healthy and Synced.
    
    Validates all ArgoCD Application custom resources:
    - Health status must be "Healthy"
    - Sync status must be "Synced"
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        namespace_filter: Optional namespace filter
        capsys: Pytest fixture for capturing stdout
    
    Fails if any application has health != "Healthy" or sync != "Synced"
    
    Cluster Impact: READ-ONLY (queries ArgoCD Application CRDs)
    """
    logger.info("\n" + "="*70)
    logger.info("ARGOCD APPLICATION HEALTH CHECK")
    logger.info("="*70)
    
    problems = validate_all_argocd_apps(custom_api, namespace_filter, verbose=True)
    
    logger.info("\n" + "="*70)
    logger.info("SUMMARY")
    logger.info("="*70)
    
    # Assert no problems found
    if problems:
        error_msg = f"❌ {len(problems)} ArgoCD application(s) unhealthy or out of sync:\n"
        for p in problems:
            error_msg += f"  - {p}\n"
        pytest.fail(error_msg)
    
    logger.info(f"✅ All ArgoCD applications are Healthy and Synced\n")
