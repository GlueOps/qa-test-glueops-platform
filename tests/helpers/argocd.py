"""
ArgoCD-specific helper functions.

This module provides high-level ArgoCD operations including:
- ApplicationSet discovery and synchronization
- Application health monitoring
- Project-based application management
"""
import time
import logging
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

# Polling configuration constants (10 minutes timeout, 15 second intervals)
DEFAULT_POLL_INTERVAL = 15
DEFAULT_TIMEOUT = 600


def calculate_expected_app_count(captain_manifests: dict, test_app_count: int) -> int:
    """
    Calculate total expected ArgoCD application count including fixture apps.
    
    The captain_manifests fixture automatically creates fixture applications that
    persist throughout the test session. When waiting for apps to become healthy,
    you must account for both fixture apps and test-specific apps.
    
    Args:
        captain_manifests: The captain_manifests fixture dictionary
        test_app_count: Number of test-specific apps being created
        
    Returns:
        int: Total expected app count (fixture_app_count + test_app_count)
        
    Example:
        # Test creates 3 apps, but there are also 3 fixture apps
        expected_total = calculate_expected_app_count(captain_manifests, num_apps=3)
        # Returns: 6 (3 fixture + 3 test)
        
        wait_for_appset_apps_created_and_healthy(
            custom_api,
            namespace=captain_manifests['namespace'],
            expected_count=expected_total  # Use calculated total
        )
    """
    fixture_app_count = captain_manifests['fixture_app_count']
    return fixture_app_count + test_app_count


def wait_for_appset_apps_created_and_healthy(custom_api, namespace: str, expected_count: int, verbose: bool = True) -> bool:
    """
    Wait for ApplicationSet to create expected number of apps and for them to become Healthy/Synced.
    
    This is used after committing apps to deployment-configurations repository.
    It waits for the ApplicationSet to discover and create Application CRs,
    then waits for all of them to reach Healthy/Synced state.
    
    The ApplicationSet typically discovers apps from the 'apps/' directory in
    the deployment-configurations repository. Each subdirectory becomes an Application.
    
    NOTE: Application CRs are created in 'glueops-core' namespace (where ApplicationSet lives),
    but they deploy workloads to the destination namespace (e.g., 'nonprod').
    This function looks for Application CRs in 'glueops-core' that target the specified namespace.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        namespace: Destination namespace where apps deploy workloads (e.g., 'nonprod')
        expected_count: Number of apps expected to be created
        verbose: Print status updates (default: True)
        
    Returns:
        bool: True if expected apps created and healthy within timeout, False otherwise
        
    Example:
        # After creating 3 apps in deployment-configurations repo
        success = wait_for_appset_apps_created_and_healthy(
            custom_api,
            namespace='nonprod',  # destination namespace for workloads
            expected_count=3
        )
    """
    start_time = time.time()
    argocd_namespace = 'glueops-core'  # Application CRs live here
    
    if verbose:
        logger.info(f"Waiting for ApplicationSet to create {expected_count} Application(s) targeting namespace '{namespace}'...")
    
    apps_created = False
    
    while time.time() - start_time < DEFAULT_TIMEOUT:
        try:
            # List all applications in glueops-core namespace (where Application CRs live)
            apps = custom_api.list_namespaced_custom_object(
                group="argoproj.io",
                version="v1alpha1",
                namespace=argocd_namespace,
                plural="applications"
            )
            
            # Filter apps that target our destination namespace
            app_list = [
                app for app in apps.get('items', [])
                if app.get('spec', {}).get('destination', {}).get('namespace') == namespace
            ]
            current_count = len(app_list)
            
            # Phase 1: Wait for expected number of apps to be created
            if not apps_created:
                if current_count >= expected_count:
                    apps_created = True
                    if verbose:
                        logger.info(f"✓ ApplicationSet has created {current_count} Application(s)")
                        logger.info(f"  Now waiting for them to become healthy...")
                else:
                    if verbose:
                        elapsed = int(time.time() - start_time)
                        logger.info(f"  {current_count}/{expected_count} apps created ({elapsed}s elapsed)")
                    
                    time.sleep(DEFAULT_POLL_INTERVAL)
                    continue
            
            # Phase 2: Wait for all apps to become Healthy/Synced
            unhealthy_apps = []
            healthy_count = 0
            
            for app in app_list:
                app_name = app['metadata']['name']
                status = app.get('status', {})
                health_status = status.get('health', {}).get('status', 'Unknown')
                sync_status = status.get('sync', {}).get('status', 'Unknown')
                
                if health_status == 'Healthy' and sync_status == 'Synced':
                    healthy_count += 1
                else:
                    unhealthy_apps.append({
                        'name': app_name,
                        'health': health_status,
                        'sync': sync_status
                    })
            
            if healthy_count >= expected_count and not unhealthy_apps:
                if verbose:
                    logger.info(f"✓ All {expected_count} Application(s) are Healthy and Synced")
                return True
            
            if verbose:
                elapsed = int(time.time() - start_time)
                logger.info(f"  {healthy_count}/{expected_count} apps healthy ({elapsed}s elapsed)")
                if len(unhealthy_apps) <= 5:
                    for app in unhealthy_apps:
                        logger.info(f"    {app['name']}: {app['health']}/{app['sync']}")
            
            time.sleep(DEFAULT_POLL_INTERVAL)
            
        except ApiException as e:
            if e.status == 404:
                if verbose:
                    logger.info(f"  Namespace '{namespace}' not found yet, waiting...")
                time.sleep(DEFAULT_POLL_INTERVAL)
                continue
            else:
                logger.error(f"Error checking Applications: {e}")
                return False
    
    # Timeout reached
    if verbose:
        logger.warning(f"⚠ Timeout waiting for apps to become healthy after {DEFAULT_TIMEOUT}s")
    
    return False


def wait_for_argocd_apps_by_project_deleted(custom_api, project_name: str, verbose: bool = True) -> bool:
    """
    Wait for all ArgoCD Application CRs that reference a specific project to be deleted.
    
    This checks ALL namespaces for Applications that have spec.project == project_name.
    Useful before deleting an AppProject to ensure no Applications reference it.
    
    This prevents the error: "Unable to delete application resources: error getting 
    app project 'nonprod': appproject.argoproj.io 'nonprod' not found"
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        project_name: Name of the AppProject to check for references
        verbose: Print status updates (default: True)
        
    Returns:
        bool: True if all apps deleted within timeout, False otherwise
    """
    start_time = time.time()
    
    if verbose:
        logger.info(f"Waiting for ArgoCD Applications referencing project '{project_name}' to be deleted...")
    
    while time.time() - start_time < DEFAULT_TIMEOUT:
        try:
            # List ALL applications across all namespaces
            apps = custom_api.list_cluster_custom_object(
                group="argoproj.io",
                version="v1alpha1",
                plural="applications"
            )
            
            # Filter for apps that reference this project
            matching_apps = [
                app for app in apps.get('items', [])
                if app.get('spec', {}).get('project') == project_name
            ]
            
            app_count = len(matching_apps)
            
            if app_count == 0:
                if verbose:
                    logger.info(f"✓ All ArgoCD Applications referencing project '{project_name}' have been deleted")
                return True
            
            if verbose:
                elapsed = int(time.time() - start_time)
                app_names = [f"{app['metadata']['namespace']}/{app['metadata']['name']}" for app in matching_apps[:5]]
                logger.info(f"  {app_count} application(s) still referencing '{project_name}' ({elapsed}s elapsed)")
                if len(app_names) <= 5:
                    logger.info(f"    Remaining: {', '.join(app_names)}")
            
            time.sleep(DEFAULT_POLL_INTERVAL)
            
        except ApiException as e:
            logger.error(f"Error checking Applications: {e}")
            return False
    
    # Timeout reached
    if verbose:
        logger.warning(f"⚠ Timeout waiting for Applications referencing '{project_name}' after {DEFAULT_TIMEOUT}s")
    
    return False
