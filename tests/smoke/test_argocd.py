"""ArgoCD Application health checks"""
import pytest


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
    apps = custom_api.list_cluster_custom_object(
        group="argoproj.io",
        version="v1alpha1",
        plural="applications"
    )
    
    # Filter by namespace if specified
    if namespace_filter:
        apps['items'] = [app for app in apps['items'] 
                       if app['metadata'].get('namespace') == namespace_filter]
    
    # Fail if no applications found
    assert apps['items'], "No ArgoCD applications found in cluster"
    
    print(f"Checking {len(apps['items'])} ArgoCD applications")
    
    problems = []
    for app in apps['items']:
        name = app['metadata']['name']
        namespace = app['metadata'].get('namespace', 'default')
        health = app.get('status', {}).get('health', {}).get('status', 'Unknown')
        sync = app.get('status', {}).get('sync', {}).get('status', 'Unknown')
        
        if health != 'Healthy' or sync != 'Synced':
            problems.append(f"{namespace}/{name} (health: {health}, sync: {sync})")
        else:
            print(f"  ✓ {namespace}/{name}: {health}/{sync}")
    
    # Assert no problems found
    if problems:
        error_msg = f"{len(problems)} ArgoCD application(s) unhealthy or out of sync:\n"
        for p in problems:
            error_msg += f"  - {p}\n"
        pytest.fail(error_msg)
