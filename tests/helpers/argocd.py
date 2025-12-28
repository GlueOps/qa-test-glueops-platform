"""
ArgoCD-specific helper functions.

This module provides high-level ArgoCD operations including:
- ApplicationSet discovery and synchronization
- Application health monitoring
- Project-based application management
"""
import time
import logging
from typing import Optional
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

# Polling configuration constants (10 minutes timeout, 15 second intervals)
DEFAULT_POLL_INTERVAL = 15
DEFAULT_TIMEOUT = 600


def refresh_argocd_app(custom_api, app_name: str, namespace: str = 'glueops-core', wait_time: int = 5) -> bool:
    """
    Trigger an ArgoCD Application refresh to pick up Git repository changes.
    
    This is useful after making changes to the Git repository (like deleting files)
    to ensure ArgoCD detects the changes before checking the application status.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        app_name: Name of the Application CR to refresh
        namespace: Namespace where the Application CR lives (default: 'glueops-core')
        wait_time: Seconds to wait after triggering refresh (default: 5)
        
    Returns:
        bool: True if refresh was triggered successfully, False otherwise
        
    Example:
        # Trigger refresh after deleting a manifest file
        refresh_argocd_app(custom_api, 'captain-manifests')
        # Then wait for it to stabilize
        wait_for_argocd_app_healthy(custom_api, 'captain-manifests')
    """
    try:
        refresh_patch = {
            "metadata": {
                "annotations": {
                    "argocd.argoproj.io/refresh": "normal"
                }
            }
        }
        
        custom_api.patch_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=namespace,
            plural="applications",
            name=app_name,
            body=refresh_patch
        )
        
        logger.info(f"   🔄 Triggered refresh for '{app_name}', waiting {wait_time}s...")
        time.sleep(wait_time)
        return True
        
    except ApiException as e:
        logger.error(f"❌ Error refreshing Application '{app_name}': {e}")
        return False


def is_app_healthy(app_status: dict) -> bool:
    """
    Check if an ArgoCD Application status dict indicates healthy state.
    
    Args:
        app_status: The 'status' field from an Application CR
        
    Returns:
        bool: True if both Health=Healthy and Sync=Synced
    """
    health_status = app_status.get('health', {}).get('status', 'Unknown')
    sync_status = app_status.get('sync', {}).get('status', 'Unknown')
    return health_status == 'Healthy' and sync_status == 'Synced'


def get_argocd_app_sync_revision(custom_api, app_name: str, namespace: str = 'glueops-core') -> Optional[str]:
    """
    Get the Git commit SHA that an ArgoCD Application is currently synced to.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        app_name: Name of the Application CR to check
        namespace: Namespace where the Application CR lives (default: 'glueops-core')
        
    Returns:
        str: The Git commit SHA (full), or None if not found
        
    Example:
        sha = get_argocd_app_sync_revision(custom_api, 'captain-manifests')
        logger.info(f"App synced to: {sha}")
    """
    try:
        app = custom_api.get_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=namespace,
            plural="applications",
            name=app_name
        )
        
        status = app.get('status', {})
        sync_revision = status.get('sync', {}).get('revision')
        return sync_revision
        
    except ApiException as e:
        logger.error(f"❌ Error getting sync revision for '{app_name}': {e}")
        return None


def wait_for_argocd_app_healthy(custom_api, app_name: str, namespace: str = 'glueops-core', 
                                  expected_sha: Optional[str] = None) -> bool:
    """
    Wait for a specific ArgoCD Application to become Healthy and Synced.
    Optionally validates that it's synced to a specific Git commit SHA.
    
    This is a generic function that can check ANY ArgoCD Application CR.
    Works for apps in any namespace (defaults to glueops-core where most ArgoCD apps live).
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        app_name: Name of the Application CR to check
        namespace: Namespace where the Application CR lives (default: 'glueops-core')
        expected_sha: Optional Git commit SHA to verify sync against (full or short).
                      Get this from file operations: delete_file_if_exists(), create_or_update_file()
        
    Returns:
        bool: True if app is Healthy/Synced (and matches SHA if provided), False otherwise
        
    Example:
        # Check if captain-manifests app is healthy (no SHA validation)
        success = wait_for_argocd_app_healthy(
            custom_api,
            app_name='captain-manifests',
            namespace='glueops-core'
        )
        
        # Check with explicit SHA validation (RECOMMENDED)
        commit_sha = delete_file_if_exists(repo, 'manifests/file.yaml')
        if commit_sha:
            success = wait_for_argocd_app_healthy(
                custom_api,
                app_name='captain-manifests',
                expected_sha=commit_sha  # Validates against the specific commit
            )
    """
    start_time = time.time()
    
    if expected_sha:
        logger.info(f"⏳ Waiting for ArgoCD Application '{app_name}' to be healthy and synced to SHA {expected_sha[:8]}...")
    else:
        logger.info(f"⏳ Waiting for ArgoCD Application '{app_name}' to become healthy...")
    
    app_exists = False
    
    while time.time() - start_time < DEFAULT_TIMEOUT:
        try:
            app = custom_api.get_namespaced_custom_object(
                group="argoproj.io",
                version="v1alpha1",
                namespace=namespace,
                plural="applications",
                name=app_name
            )
            
            if not app_exists:
                app_exists = True
                logger.info(f"   ✓ Application '{app_name}' exists")
            
            status = app.get('status', {})
            
            # Check if healthy
            if is_app_healthy(status):
                # If SHA validation requested, verify it matches
                if expected_sha:
                    sync_revision = status.get('sync', {}).get('revision', '')
                    
                    # Support both full and short SHA comparison
                    sha_match = (sync_revision == expected_sha or 
                                sync_revision.startswith(expected_sha[:8]) or
                                expected_sha.startswith(sync_revision[:8]))
                    
                    if sha_match:
                        elapsed = int(time.time() - start_time)
                        logger.info(f"   ✓ Application '{app_name}' is Healthy and Synced to {sync_revision[:8]} (took {elapsed}s)")
                        return True
                    else:
                        elapsed = int(time.time() - start_time)
                        logger.info(f"   ⏳ Healthy but wrong SHA: expected {expected_sha[:8]}, got {sync_revision[:8]} ({elapsed}s elapsed)")
                else:
                    # No SHA validation, just check health
                    elapsed = int(time.time() - start_time)
                    sync_revision = status.get('sync', {}).get('revision', 'unknown')
                    logger.info(f"   ✓ Application '{app_name}' is Healthy and Synced to {sync_revision[:8]} (took {elapsed}s)")
                    return True
            
            health = status.get('health', {}).get('status', 'Unknown')
            sync = status.get('sync', {}).get('status', 'Unknown')
            sync_revision = status.get('sync', {}).get('revision', 'unknown')
            short_sha = sync_revision[:8] if sync_revision != 'unknown' else 'unknown'
            elapsed = int(time.time() - start_time)
            
            if expected_sha:
                logger.info(f"   Health={health}, Sync={sync}, SHA={short_sha} ({elapsed}s elapsed)")
            else:
                logger.info(f"   Health={health}, Sync={sync} ({elapsed}s elapsed)")
            
            time.sleep(DEFAULT_POLL_INTERVAL)
            
        except ApiException as e:
            if e.status == 404:
                if not app_exists:
                    elapsed = int(time.time() - start_time)
                    logger.info(f"   ⏳ Application '{app_name}' not found yet ({elapsed}s elapsed)")
                time.sleep(DEFAULT_POLL_INTERVAL)
                continue
            else:
                logger.error(f"❌ Error checking Application '{app_name}': {e}")
                logger.error(f"   Status code: {e.status}")
                logger.error(f"   Reason: {e.reason}")
                if hasattr(e, 'body'):
                    logger.error(f"   Body: {e.body}")
                return False
    
    # Timeout reached
    logger.error(f"❌ Timeout waiting for Application '{app_name}' after {DEFAULT_TIMEOUT}s")
    try:
        app = custom_api.get_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=namespace,
            plural="applications",
            name=app_name
        )
        status = app.get('status', {})
        health = status.get('health', {}).get('status', 'Unknown')
        sync = status.get('sync', {}).get('status', 'Unknown')
        logger.error(f"   Final status: Health={health}, Sync={sync}")
        
        # Log more details if degraded
        if health != 'Healthy':
            health_msg = status.get('health', {}).get('message', 'No message')
            logger.error(f"   Health message: {health_msg}")
        
        if sync != 'Synced':
            sync_revision = status.get('sync', {}).get('revision', 'Unknown')
            logger.error(f"   Sync revision: {sync_revision}")
            
    except ApiException as e:
        if e.status == 404:
            logger.error(f"   Application '{app_name}' does not exist")
        else:
            logger.error(f"   Could not fetch final status: {e}")
    
    return False


def refresh_and_wait_for_argocd_app(custom_api, app_name: str, namespace: str = 'glueops-core', 
                                     expected_sha: Optional[str] = None) -> bool:
    """
    Convenience function that triggers an ArgoCD refresh and waits for the app to become healthy.
    Optionally validates that it's synced to a specific Git commit SHA.
    
    This is useful after making changes to a Git repository (like adding/deleting files)
    to ensure ArgoCD picks up the changes and syncs to the expected state.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        app_name: Name of the Application CR to refresh and check
        namespace: Namespace where the Application CR lives (default: 'glueops-core')
        expected_sha: Git commit SHA to verify sync against (full or short).
                      Get this from file operations: delete_file_if_exists(), create_or_update_file()
        
    Returns:
        bool: True if refresh succeeded and app became healthy (and matches SHA if provided), False otherwise
        
    Example:
        # After deleting a manifest, validate sync to that specific commit
        commit_sha = delete_file_if_exists(captain_repo, 'manifests/file.yaml')
        if commit_sha:
            success = refresh_and_wait_for_argocd_app(
                custom_api,
                app_name='captain-manifests',
                expected_sha=commit_sha  # Validates to exact deletion commit
            )
        
        # After adding a manifest with known commit SHA
        result = create_or_update_file(captain_repo, 'manifests/new.yaml', content, 'Add manifest')
        success = refresh_and_wait_for_argocd_app(
            custom_api,
            app_name='captain-manifests',
            expected_sha=result['commit'].sha
        )
    """
    # Trigger refresh
    refresh_success = refresh_argocd_app(custom_api, app_name, namespace)
    if not refresh_success:
        logger.error(f"❌ Failed to trigger refresh for '{app_name}'")
        return False
    
    # Wait for app to become healthy and optionally validate SHA
    return wait_for_argocd_app_healthy(
        custom_api,
        app_name=app_name,
        namespace=namespace,
        expected_sha=expected_sha
    )


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


def wait_for_appset_apps_created_and_healthy(custom_api, namespace: str, expected_count: int) -> bool:
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
                    logger.info(f"✓ ApplicationSet has created {current_count} Application(s)")
                    logger.info(f"  Now waiting for them to become healthy...")
                else:
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
                
                if is_app_healthy(status):
                    healthy_count += 1
                else:
                    health_status = status.get('health', {}).get('status', 'Unknown')
                    sync_status = status.get('sync', {}).get('status', 'Unknown')
                    unhealthy_apps.append({
                        'name': app_name,
                        'health': health_status,
                        'sync': sync_status
                    })
            
            if healthy_count >= expected_count and not unhealthy_apps:
                logger.info(f"✓ All {expected_count} Application(s) are Healthy and Synced")
                return True
            
            elapsed = int(time.time() - start_time)
            logger.info(f"  {healthy_count}/{expected_count} apps healthy ({elapsed}s elapsed)")
            if len(unhealthy_apps) <= 5:
                for app in unhealthy_apps:
                    logger.info(f"    {app['name']}: {app['health']}/{app['sync']}")
            
            time.sleep(DEFAULT_POLL_INTERVAL)
            
        except ApiException as e:
            if e.status == 404:
                logger.info(f"  Namespace '{namespace}' not found yet, waiting...")
                time.sleep(DEFAULT_POLL_INTERVAL)
                continue
            else:
                logger.error(f"Error checking Applications: {e}")
                return False
    
    # Timeout reached
    logger.warning(f"⚠ Timeout waiting for apps to become healthy after {DEFAULT_TIMEOUT}s")
    
    return False


def wait_for_argocd_apps_by_project_deleted(custom_api, project_name: str) -> bool:
    """
    Wait for all ArgoCD Application CRs that reference a specific project to be deleted.
    
    This checks ALL namespaces for Applications that have spec.project == project_name.
    Useful before deleting an AppProject to ensure no Applications reference it.
    
    This prevents the error: "Unable to delete application resources: error getting 
    app project 'nonprod': appproject.argoproj.io 'nonprod' not found"
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        project_name: Name of the AppProject to check for references
        
    Returns:
        bool: True if all apps deleted within timeout, False otherwise
    """
    start_time = time.time()
    
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
                logger.info(f"✓ All ArgoCD Applications referencing project '{project_name}' have been deleted")
                return True
            
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
    logger.warning(f"⚠ Timeout waiting for Applications referencing '{project_name}' after {DEFAULT_TIMEOUT}s")
    
    return False
