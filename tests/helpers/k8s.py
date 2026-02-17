"""
Kubernetes helper functions for test validation.

This module consolidates k8s_helpers.py, k8s_utils.py, and k8s_validators.py
into a single source of truth for Kubernetes-related utilities.

Functions are organized into categories:
- Namespace utilities
- Job/Pod validation
- ArgoCD validation
- Ingress validation
- Certificate validation
- HTTP endpoint validation
"""
import time
import logging
import ssl
import socket
import requests
import dns.resolver
from kubernetes.client.rest import ApiException
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

# Polling configuration for all wait operations
DEFAULT_POLL_INTERVAL = 15  # seconds between status checks
DEFAULT_TIMEOUT = 600  # 10 minutes max wait time


# =============================================================================
# NAMESPACE UTILITIES
# =============================================================================

def get_platform_namespaces(core_v1, namespace_filter=None):
    """
    Get list of platform namespaces to check.
    
    Args:
        core_v1: Kubernetes CoreV1Api client
        namespace_filter: Optional namespace filter (if provided, returns only this namespace)
    
    Returns:
        list: List of namespace names
    """
    if namespace_filter:
        return [namespace_filter]
    all_ns = core_v1.list_namespace()
    return [ns.metadata.name for ns in all_ns.items 
            if ns.metadata.name.startswith("glueops-") or ns.metadata.name == "nonprod"]


# =============================================================================
# JOB/POD VALIDATION
# =============================================================================

def wait_for_job_completion(batch_v1, job_name, namespace):
    """
    Wait for a job to complete and return its status.
    
    Args:
        batch_v1: Kubernetes BatchV1Api client
        job_name: Name of the Job resource
        namespace: Namespace of the Job
    
    Returns:
        str: 'succeeded', 'failed', or 'timeout'
    """
    start_time = time.time()
    
    while time.time() - start_time < DEFAULT_TIMEOUT:
        try:
            job = batch_v1.read_namespaced_job(name=job_name, namespace=namespace)
            if job.status.succeeded and job.status.succeeded > 0:
                return "succeeded"
            elif job.status.failed and job.status.failed > 0:
                return "failed"
        except ApiException:
            pass
        time.sleep(5)
    
    return "timeout"


def validate_pod_execution(core_v1, job_name, namespace):
    """
    Wait for a job to complete and return its status.
    
    Args:
        core_v1: Kubernetes CoreV1Api client
        job_name: Name of the Job resource
        namespace: Namespace of the Job
    
    Returns:
        tuple: (success: bool, message: str)
    """
    pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}")
    
    if not pods.items:
        return False, "No pods found for job"
    
    pod = pods.items[0]
    pod_status = pod.status.phase
    
    if pod_status == "Succeeded":
        return True, "Pod completed successfully"
    elif pod_status == "Failed":
        return False, "Pod failed"
    else:
        return False, f"Pod in unexpected phase: {pod_status}"


# =============================================================================
# ARGOCD VALIDATION
# =============================================================================

def validate_all_argocd_apps(custom_api, namespace_filter=None):
    """
    Check all ArgoCD applications for health and sync status.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        namespace_filter: Optional namespace filter for ArgoCD apps
    
    Returns:
        list: List of problem descriptions (empty if all healthy)
    """
    logger.info("Checking ArgoCD applications...")
    
    problems = []
    
    try:
        if namespace_filter:
            apps = custom_api.list_namespaced_custom_object(
                group="argoproj.io",
                version="v1alpha1",
                namespace=namespace_filter,
                plural="applications"
            )
        else:
            apps = custom_api.list_cluster_custom_object(
                group="argoproj.io",
                version="v1alpha1",
                plural="applications"
            )
    except ApiException as e:
        problems.append(f"Failed to list ArgoCD applications: {e}")
        return problems
    
    if not apps.get('items'):
        logger.info("  No ArgoCD applications found")
        return problems
    
    total_apps = len(apps['items'])
    healthy_count = 0
    
    for app in apps['items']:
        name = app['metadata']['name']
        namespace = app['metadata']['namespace']
        status = app.get('status', {})
        health = status.get('health', {}).get('status', 'Unknown')
        sync = status.get('sync', {}).get('status', 'Unknown')
        
        if health != 'Healthy':
            problems.append(f"{namespace}/{name}: Health={health} (expected Healthy)")
        
        if sync != 'Synced':
            problems.append(f"{namespace}/{name}: Sync={sync} (expected Synced)")
        
        if health == 'Healthy' and sync == 'Synced':
            healthy_count += 1
        
        status_icon = "✓" if (health == 'Healthy' and sync == 'Synced') else "✗"
        logger.info(f"  {status_icon} {namespace}/{name}: Health={health}, Sync={sync}")
    
    if not problems:
        logger.info(f"  All {total_apps} applications healthy and synced")
    
    return problems


def wait_for_argocd_apps_deleted(custom_api, namespace: str) -> bool:
    """
    Wait for all ArgoCD applications in a namespace to be deleted.
    
    This is used during teardown to ensure all applications are removed
    before deleting the AppProject and Namespace.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        namespace: Namespace to check for ArgoCD applications
        
    Returns:
        bool: True if all apps deleted within timeout, False otherwise
    """
    start_time = time.time()
    
    logger.info(f"Waiting for ArgoCD applications in namespace '{namespace}' to be deleted...")
    
    while time.time() - start_time < DEFAULT_TIMEOUT:
        try:
            apps = custom_api.list_namespaced_custom_object(
                group="argoproj.io",
                version="v1alpha1",
                namespace=namespace,
                plural="applications"
            )
            
            app_count = len(apps.get('items', []))
            
            if app_count == 0:
                logger.info(f"✓ All ArgoCD applications in '{namespace}' have been deleted")
                return True
            
            elapsed = int(time.time() - start_time)
            logger.info(f"  {app_count} application(s) remaining in '{namespace}' ({elapsed}s elapsed)")
            
            time.sleep(DEFAULT_POLL_INTERVAL)
            
        except ApiException as e:
            if e.status == 404:
                # Namespace or CRD not found - consider this as "deleted"
                logger.info(f"✓ Namespace '{namespace}' not found (already deleted)")
                return True
            else:
                raise
    
    # Timeout reached
    logger.warning(f"⚠ Timeout waiting for ArgoCD apps in '{namespace}' to be deleted after {DEFAULT_TIMEOUT}s")
    
    return False


def ensure_argocd_app_allows_empty(custom_api, app_name, namespace="glueops-core"):
    """
    Patch ArgoCD application to allow empty sync (no resources).
    This prevents the "auto-sync will wipe out all resources" error.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        app_name: Name of the ArgoCD Application to patch
        namespace: Namespace where the Application resource exists (default: glueops-core)
    
    Returns:
        bool: True if patch successful, False otherwise
    """
    try:
        logger.info(f"Ensuring '{app_name}' allows empty sync...")
        
        # Patch to add allowEmpty and enable auto-sync with prune
        # Comment added to indicate this was modified by test automation
        patch = {
            "spec": {
                "syncPolicy": {
                    "automated": {
                        "prune": True,
                        "allowEmpty": True,  # Added by testing automation - allows sync when manifests directory is empty
                        "selfHeal": True
                    }
                }
            }
        }
        
        custom_api.patch_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=namespace,
            plural="applications",
            name=app_name,
            body=patch
        )
        
        logger.info(f"  ✓ Patched '{app_name}' with allowEmpty=true")
        
        return True
        
    except ApiException as e:
        if e.status == 404:
            logger.warning(f"⚠ Application '{app_name}' not found")
            return False
        else:
            logger.error(f"Failed to patch '{app_name}': {e}")
            raise


def force_sync_argocd_app(custom_api, app_name, namespace="glueops-core"):
    """
    Force sync an ArgoCD application if not already syncing.
    
    First ensures the app allows empty sync, then checks if an operation 
    is running before triggering sync.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        app_name: Name of the ArgoCD Application to sync
        namespace: Namespace where the Application resource exists (default: glueops-core)
    
    Returns:
        bool: True if sync triggered or already running, False otherwise
    """
    try:
        logger.info(f"Force syncing ArgoCD application '{app_name}' in namespace '{namespace}'...")
        
        # Step 1: Ensure app allows empty sync (prevents "wipe out all resources" error)
        ensure_argocd_app_allows_empty(custom_api, app_name, namespace)
        
        # Step 2: Check if an operation is already running
        app = custom_api.get_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=namespace,
            plural="applications",
            name=app_name
        )
        
        operation_state = app.get('status', {}).get('operationState', {})
        phase = operation_state.get('phase', '')
        
        if phase in ['Running', 'Terminating']:
            logger.info(f"  ⚙️  Operation already {phase.lower()}, not triggering new sync")
            return True
        
        # Step 3: Trigger a refresh to ensure ArgoCD has latest repo state
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
        
        logger.info(f"  Triggered refresh for '{app_name}'")
        
        # Step 4: Force sync with prune enabled
        sync_patch = {
            "operation": {
                "initiatedBy": {
                    "username": "pytest-automation"
                },
                "sync": {
                    "revision": "HEAD",
                    "prune": True,
                    "syncOptions": ["CreateNamespace=true"]
                }
            }
        }
        
        custom_api.patch_namespaced_custom_object(
            group="argoproj.io",
            version="v1alpha1",
            namespace=namespace,
            plural="applications",
            name=app_name,
            body=sync_patch
        )
        
        logger.info(f"✓ Force sync triggered for '{app_name}'")
        
        return True
        
    except ApiException as e:
        if e.status == 404:
            logger.warning(f"⚠ Application '{app_name}' not found in namespace '{namespace}'")
            return False
        else:
            logger.error(f"Failed to force sync '{app_name}': {e}")
            raise


def wait_for_argocd_app_healthy(custom_api, app_name, namespace="glueops-core", allow_missing=False, timeout=DEFAULT_TIMEOUT):
    """
    Wait for an ArgoCD application to become Healthy and Synced.
    More lenient - considers app healthy if it has no resources to manage.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        app_name: Name of the ArgoCD Application to check
        namespace: Namespace where the Application resource exists (default: glueops-core)
        allow_missing: If True, treat missing app as success (default: False)
        timeout: Timeout in seconds (default: DEFAULT_TIMEOUT)
    
    Returns:
        bool: True if app becomes healthy within timeout, False otherwise
    """
    start_time = time.time()
    
    logger.info(f"Waiting for ArgoCD application '{app_name}' to stabilize...")
    
    last_error_type = None
    consecutive_good_checks = 0
    required_consecutive_checks = 2  # Need 2 consecutive good checks to be sure
    
    while time.time() - start_time < timeout:
        try:
            app = custom_api.get_namespaced_custom_object(
                group="argoproj.io",
                version="v1alpha1",
                namespace=namespace,
                plural="applications",
                name=app_name
            )
            
            status = app.get('status', {})
            health_status = status.get('health', {}).get('status', 'Unknown')
            sync_status = status.get('sync', {}).get('status', 'Unknown')
            
            # Check for sync errors
            conditions = status.get('conditions', [])
            sync_errors = [c for c in conditions if c.get('type') == 'SyncError']
            
            # If app has no resources to manage, it might show as "Missing" health
            # This is acceptable after cleanup
            resources = status.get('resources', [])
            has_resources = len(resources) > 0
            
            # Success conditions:
            # 1. Healthy + Synced (normal case)
            # 2. Missing health + Synced + no resources (empty app after cleanup)
            is_healthy = (
                (health_status == 'Healthy' and sync_status == 'Synced') or
                (health_status == 'Missing' and sync_status == 'Synced' and not has_resources)
            )
            
            if is_healthy:
                consecutive_good_checks += 1
                if consecutive_good_checks >= required_consecutive_checks:
                    state_desc = "Healthy/Synced" if health_status == 'Healthy' else "Synced (no resources)"
                    logger.info(f"✓ Application '{app_name}' is {state_desc}")
                    return True
                else:
                    logger.info(f"  {app_name}: {health_status}/{sync_status} (confirming... {consecutive_good_checks}/{required_consecutive_checks})")
            else:
                consecutive_good_checks = 0
                
                # Log sync errors if present
                if sync_errors:
                    error_msg = sync_errors[0].get('message', 'Unknown error')
                    if error_msg != last_error_type:
                        logger.info(f"  {app_name}: {health_status}/{sync_status} - {error_msg}")
                        last_error_type = error_msg
                else:
                    elapsed = int(time.time() - start_time)
                    logger.info(f"  {app_name}: {health_status}/{sync_status} (resources: {len(resources)}, {elapsed}s elapsed)")
            
            time.sleep(DEFAULT_POLL_INTERVAL)
            
        except ApiException as e:
            if e.status == 404:
                if allow_missing:
                    logger.info(f"✓ Application '{app_name}' not found (treated as success)")
                    return True
                else:
                    logger.warning(f"⚠ Application '{app_name}' not found")
                    return False
            else:
                raise
    
    # Timeout reached
    logger.warning(f"⚠ Timeout waiting for '{app_name}' to stabilize after {timeout}s")
    
    return False


# =============================================================================
# POD HEALTH VALIDATION
# =============================================================================

def validate_pod_health(core_v1, platform_namespaces):
    """
    Check pod health across platform namespaces.
    
    Checks for critical pod issues:
    - CrashLoopBackOff - container repeatedly crashing
    - ImagePullBackOff/ErrImagePull - cannot pull container image  
    - OOMKilled - container killed due to out of memory
    - High restart count (>5) - indicates intermittent failures
    - Failed/Unknown pod phase
    
    Args:
        core_v1: Kubernetes CoreV1Api client
        platform_namespaces: List of namespaces to check
    
    Returns:
        list: List of problem descriptions (empty if all healthy)
    """
    logger.info("Checking pod health across platform namespaces...")
    
    problems = []
    total_pods = 0
    healthy_pods = 0
    
    for namespace in platform_namespaces:
        pods = core_v1.list_namespaced_pod(namespace=namespace)
        
        if not pods.items:
            continue
        
        for pod in pods.items:
            total_pods += 1
            pod_name = pod.metadata.name
            pod_phase = pod.status.phase
            
            # Check for Failed/Unknown phase
            if pod_phase in ['Failed', 'Unknown']:
                problems.append(f"{namespace}/{pod_name}: Phase={pod_phase}")
                logger.info(f"  ✗ {namespace}/{pod_name}: Phase={pod_phase}")
                continue
            
            # Check container statuses
            container_statuses = pod.status.container_statuses or []
            pod_has_issues = False
            
            for container_status in container_statuses:
                container_name = container_status.name
                
                # Check restart count
                restart_count = container_status.restart_count
                if restart_count > 5:
                    problems.append(f"{namespace}/{pod_name}/{container_name}: {restart_count} restarts")
                    pod_has_issues = True
                
                # Check current state waiting reasons
                if container_status.state and container_status.state.waiting:
                    reason = container_status.state.waiting.reason
                    if reason in ['CrashLoopBackOff', 'ImagePullBackOff', 'ErrImagePull']:
                        problems.append(f"{namespace}/{pod_name}/{container_name}: {reason}")
                        pod_has_issues = True
                
                # Check last terminated state for OOMKilled
                if container_status.last_state and container_status.last_state.terminated:
                    if container_status.last_state.terminated.reason == 'OOMKilled':
                        problems.append(f"{namespace}/{pod_name}/{container_name}: OOMKilled")
                        pod_has_issues = True
                
                # Check current terminated state for OOMKilled
                if container_status.state and container_status.state.terminated:
                    if container_status.state.terminated.reason == 'OOMKilled':
                        problems.append(f"{namespace}/{pod_name}/{container_name}: Currently OOMKilled")
                        pod_has_issues = True
            
            if pod_has_issues:
                logger.info(f"  ✗ {namespace}/{pod_name}: Issues found")
            elif not pod_has_issues:
                healthy_pods += 1
    
    if problems:
        logger.info(f"  {healthy_pods}/{total_pods} pods healthy")
    else:
        logger.info(f"  All {total_pods} pods healthy")
    
    return problems


# =============================================================================
# JOB VALIDATION
# =============================================================================

def validate_failed_jobs(batch_v1, platform_namespaces, exclude_jobs=None):
    """
    Check for failed Jobs across platform namespaces.
    
    Args:
        batch_v1: Kubernetes BatchV1Api client
        platform_namespaces: List of namespaces to check
        exclude_jobs: Optional list of job name patterns to exclude from errors
    
    Returns:
        tuple: (problems, warnings) where:
            - problems: list of non-excluded failed jobs
            - warnings: list of excluded failed jobs
    """
    logger.info("Checking for failed jobs...")
    
    exclude_jobs = exclude_jobs or []
    problems = []
    warnings = []
    total_jobs = 0
    failed_jobs = 0
    
    for namespace in platform_namespaces:
        jobs = batch_v1.list_namespaced_job(namespace=namespace)
        
        for job in jobs.items:
            total_jobs += 1
            job_name = job.metadata.name
            
            # Check job conditions for actual status
            is_failed = False
            is_complete = False
            
            if job.status.conditions:
                for condition in job.status.conditions:
                    if condition.type == 'Failed' and condition.status == 'True':
                        is_failed = True
                    if condition.type == 'Complete' and condition.status == 'True':
                        is_complete = True
            
            # Only report jobs that are truly failed
            if is_failed and not is_complete:
                failed_jobs += 1
                failed_count = job.status.failed or 0
                
                # Check if job matches any exclusion pattern
                is_excluded = any(pattern in job_name for pattern in exclude_jobs)
                
                if is_excluded:
                    warnings.append(f"{namespace}/{job_name}: Failed (attempts: {failed_count}) [EXCLUDED]")
                    logger.info(f"  ⚠ {namespace}/{job_name}: Failed (attempts: {failed_count}) [EXCLUDED]")
                else:
                    problems.append(f"{namespace}/{job_name}: Failed (attempts: {failed_count})")
                    logger.info(f"  ✗ {namespace}/{job_name}: Failed (attempts: {failed_count})")
    
    logger.info(f"  Checked {total_jobs} jobs, {failed_jobs} with failures, {len(problems)} requiring attention")
    
    return problems, warnings


# =============================================================================
# INGRESS VALIDATION
# =============================================================================

def validate_ingress_configuration(networking_v1, platform_namespaces):
    """
    Validate Ingress resources have proper configuration.
    
    Validates:
    - Ingress spec exists and has rules defined
    - All rules have non-empty host values
    - Load balancer status exists with IP or hostname populated
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        platform_namespaces: List of namespaces to check
    
    Returns:
        tuple: (problems, total_ingresses)
    """
    logger.info("Validating Ingress configuration...")
    
    problems = []
    total_ingresses = 0
    
    for namespace in platform_namespaces:
        ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
        
        for ingress in ingresses.items:
            total_ingresses += 1
            name = f"{namespace}/{ingress.metadata.name}"
            
            # Check if spec exists
            if not ingress.spec:
                problems.append(f"{name}: Missing spec")
                logger.info(f"  ✗ {name}: Missing spec")
                continue
            
            # Check if rules exist
            if not ingress.spec.rules:
                problems.append(f"{name}: No rules defined")
                logger.info(f"  ✗ {name}: No rules defined")
                continue
            
            # Check each rule for host
            for i, rule in enumerate(ingress.spec.rules):
                if not rule.host or rule.host.strip() == "":
                    problems.append(f"{name}: Rule {i} has empty host")
                    logger.info(f"  ✗ {name}: Rule {i} has empty host")
            
            # Check load balancer status
            if not ingress.status or not ingress.status.load_balancer:
                problems.append(f"{name}: No load balancer status")
                logger.info(f"  ✗ {name}: No load balancer status")
                continue
            
            lb_ingress = ingress.status.load_balancer.ingress
            if not lb_ingress:
                problems.append(f"{name}: Load balancer has no ingress")
                logger.info(f"  ✗ {name}: Load balancer has no ingress")
                continue
            
            # Check if at least one LB ingress has IP or hostname
            has_address = any(lb.ip or lb.hostname for lb in lb_ingress)
            if not has_address:
                problems.append(f"{name}: Load balancer has no IP or hostname")
                logger.info(f"  ✗ {name}: Load balancer has no IP or hostname")
            else:
                logger.info(f"  ✓ {name}: Valid configuration")
    
    if not problems:
        logger.info(f"  All {total_ingresses} ingresses properly configured")
    
    return problems, total_ingresses


def validate_ingress_dns(networking_v1, platform_namespaces, dns_server='1.1.1.1'):
    """
    Validate DNS resolution for Ingress hosts.
    
    For each ingress with a load balancer:
    - If LB has IP: Queries DNS A records and compares resolved IPs
    - If LB has hostname: Queries DNS CNAME records and validates CNAME points to LB hostname
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        platform_namespaces: List of namespaces to check
        dns_server: DNS server to query (default: '1.1.1.1')
    
    Returns:
        tuple: (problems, checked_count)
    """
    logger.info(f"Validating DNS resolution (using {dns_server})...")
    
    problems = []
    checked_count = 0
    resolver = dns.resolver.Resolver()
    resolver.nameservers = [dns_server]
    
    for namespace in platform_namespaces:
        ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
        
        for ingress in ingresses.items:
            name = f"{namespace}/{ingress.metadata.name}"
            
            # Get expected IPs or hostnames from load balancer
            if not ingress.status or not ingress.status.load_balancer or not ingress.status.load_balancer.ingress:
                continue
            
            expected_ips = []
            expected_hostnames = []
            for lb in ingress.status.load_balancer.ingress:
                if lb.ip:
                    expected_ips.append(lb.ip)
                if lb.hostname:
                    expected_hostnames.append(lb.hostname)
            
            # Skip if no IPs or hostnames found
            if not expected_ips and not expected_hostnames:
                continue
            
            # Determine validation mode: CNAME for hostnames, A records for IPs
            use_cname_validation = bool(expected_hostnames) and not expected_ips
            
            # Check each host
            if not ingress.spec or not ingress.spec.rules:
                continue
            
            for rule in ingress.spec.rules:
                if not rule.host:
                    continue
                
                checked_count += 1
                host = rule.host
                
                if use_cname_validation:
                    # Validate CNAME points to load balancer hostname (AWS ELB/ALB/NLB)
                    try:
                        answers = resolver.resolve(host, 'CNAME')
                        cname_targets = [str(rdata.target).rstrip('.') for rdata in answers]
                        
                        # Check if any CNAME matches expected hostname
                        if any(cname in expected_hostnames or any(cname == expected.rstrip('.') for expected in expected_hostnames) for cname in cname_targets):
                            logger.info(f"  ✓ {host}: CNAME → {cname_targets[0]}")
                        else:
                            problems.append(f"{name} ({host}): CNAME points to {cname_targets}, expected {expected_hostnames}")
                            logger.info(f"  ✗ {host}: CNAME → {cname_targets} (expected {expected_hostnames})")
                            
                    except dns.resolver.NXDOMAIN:
                        problems.append(f"{name} ({host}): NXDOMAIN (does not exist)")
                        logger.info(f"  ✗ {host}: NXDOMAIN")
                    except dns.resolver.NoAnswer:
                        problems.append(f"{name} ({host}): No CNAME records")
                        logger.info(f"  ✗ {host}: No CNAME records")
                    except Exception as e:
                        problems.append(f"{name} ({host}): DNS error - {e}")
                        logger.info(f"  ✗ {host}: {e}")
                else:
                    # Validate A record points to load balancer IP (GCP, K3d)
                    try:
                        answers = resolver.resolve(host, 'A')
                        resolved_ips = [str(rdata) for rdata in answers]
                        
                        # Check if any resolved IP matches expected
                        if not any(ip in expected_ips for ip in resolved_ips):
                            problems.append(f"{name} ({host}): Resolves to {resolved_ips}, expected {expected_ips}")
                            logger.info(f"  ✗ {host}: A → {resolved_ips} (expected {expected_ips})")
                        else:
                            logger.info(f"  ✓ {host}: A → {resolved_ips[0]}")
                            
                    except dns.resolver.NXDOMAIN:
                        problems.append(f"{name} ({host}): NXDOMAIN (does not exist)")
                        logger.info(f"  ✗ {host}: NXDOMAIN")
                    except dns.resolver.NoAnswer:
                        problems.append(f"{name} ({host}): No A records")
                        logger.info(f"  ✗ {host}: No A records")
                    except Exception as e:
                        problems.append(f"{name} ({host}): DNS error - {e}")
                        logger.info(f"  ✗ {host}: {e}")
    
    if not problems:
        logger.info(f"  All {checked_count} hosts resolve correctly")
    
    return problems, checked_count


def get_ingress_load_balancer_ip(networking_v1, ingress_class_name, namespace=None, fail_on_none=False):
    """
    Get the load balancer IP from ingresses matching the specified class.
    
    Supports both direct IP addresses (GCP, K3d) and hostnames (AWS ELB/ALB/NLB).
    When a hostname is found, it will be resolved to an IP address.
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        ingress_class_name: Ingress class name to filter by
        namespace: Specific namespace to check (optional)
        fail_on_none: Whether to fail test if IP not found (default: False)
    
    Returns:
        str: Load balancer IP or None
    """
    logger.info(f"Searching for load balancer IP (ingressClassName: {ingress_class_name})...")
    
    try:
        if namespace:
            ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
        else:
            ingresses = networking_v1.list_ingress_for_all_namespaces()
        
        for ingress in ingresses.items:
            if ingress.spec.ingress_class_name != ingress_class_name:
                continue
            
            if (ingress.status and 
                ingress.status.load_balancer and 
                ingress.status.load_balancer.ingress):
                
                for lb in ingress.status.load_balancer.ingress:
                    # Check for direct IP (GCP, K3d)
                    if lb.ip:
                        logger.info(f"✓ Found load balancer IP: {lb.ip}")
                        return lb.ip
                    
                    # Check for hostname (AWS ELB/ALB/NLB) and resolve to IP
                    if lb.hostname:
                        try:
                            resolved_ip = socket.gethostbyname(lb.hostname)
                            logger.info(f"✓ Resolved load balancer hostname {lb.hostname} → {resolved_ip}")
                            return resolved_ip
                        except socket.gaierror as dns_error:
                            logger.error(f"Failed to resolve load balancer hostname {lb.hostname}: {dns_error}")
                            if fail_on_none:
                                import pytest
                                pytest.fail(f"Failed to resolve load balancer hostname {lb.hostname}: {dns_error}")
                            return None
        
        logger.warning(f"No load balancer IP or hostname found for ingressClassName: {ingress_class_name}")
        
        if fail_on_none:
            import pytest
            pytest.fail(f"Could not find load balancer IP for ingressClassName '{ingress_class_name}'")
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to get load balancer IP: {e}")
        
        if fail_on_none:
            import pytest
            pytest.fail(f"Failed to get load balancer IP: {e}")
        
        return None


# =============================================================================
# CERTIFICATE VALIDATION
# =============================================================================

def _get_certificate_detailed_error(custom_api, cert_name, namespace, cert_message=""):
    """
    Fetch detailed error information from CertificateRequest and Order resources.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        cert_name: Name of the Certificate resource
        namespace: Namespace of the Certificate
        cert_message: Basic error message from Certificate status
    
    Returns:
        str: Detailed error message including ACME errors, or cert_message if details unavailable
    """
    try:
        # List CertificateRequests for this certificate
        cert_requests = custom_api.list_namespaced_custom_object(
            group="cert-manager.io",
            version="v1",
            namespace=namespace,
            plural="certificaterequests",
            label_selector=f"cert-manager.io/certificate-name={cert_name}"
        )
        
        if not cert_requests.get('items'):
            return cert_message
        
        # Sort by creation timestamp and get the most recent
        sorted_requests = sorted(
            cert_requests['items'],
            key=lambda x: x['metadata']['creationTimestamp'],
            reverse=True
        )
        latest_request = sorted_requests[0]
        request_name = latest_request['metadata']['name']
        
        # Check CertificateRequest status for error details
        cr_status = latest_request.get('status', {})
        cr_conditions = cr_status.get('conditions', [])
        
        # Build error message from CertificateRequest
        cr_error_parts = []
        for condition in cr_conditions:
            if condition.get('type') == 'Ready' and condition.get('status') == 'False':
                reason = condition.get('reason', '')
                message = condition.get('message', '')
                if reason or message:
                    cr_error_parts.append(f"CertificateRequest '{request_name}': {reason} - {message}")
        
        # Try to get Order details if referenced
        order_name = None
        for condition in cr_conditions:
            msg = condition.get('message', '')
            # Look for order name in message (e.g., 'order resource "order-name-123"')
            if 'order resource' in msg.lower():
                import re
                match = re.search(r'order resource ["\']([^"\'\']+)["\']', msg, re.IGNORECASE)
                if match:
                    order_name = match.group(1)
                    break
        
        # Fetch Order details if we found a reference
        order_error = None
        if order_name:
            try:
                order = custom_api.get_namespaced_custom_object(
                    group="acme.cert-manager.io",
                    version="v1",
                    namespace=namespace,
                    plural="orders",
                    name=order_name
                )
                
                order_status = order.get('status', {})
                order_state = order_status.get('state', '')
                order_reason = order_status.get('reason', '')
                
                if order_state == 'errored' or order_reason:
                    order_error = f"Order '{order_name}' state: {order_state}, reason: {order_reason}"
                    
            except ApiException as e:
                if e.status != 404:
                    logger.warning(f"Could not fetch Order '{order_name}': {e.status}")
        
        # Combine all error information
        detailed_parts = [cert_message] if cert_message else []
        detailed_parts.extend(cr_error_parts)
        if order_error:
            detailed_parts.append(order_error)
        
        return " | ".join(detailed_parts) if detailed_parts else cert_message
        
    except ApiException as e:
        logger.warning(f"Could not fetch detailed error info for certificate '{cert_name}': {e.status}")
        return cert_message
    except Exception as e:
        logger.warning(f"Unexpected error fetching certificate details: {e}")
        return cert_message


def wait_for_certificate_ready(custom_api, cert_name, namespace, timeout=600, poll_interval=10):
    """
    Wait for a cert-manager Certificate to reach Ready status.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        cert_name: Name of the Certificate resource
        namespace: Namespace of the Certificate
        timeout: Maximum time to wait in seconds (default: 600)
        poll_interval: Time between checks in seconds (default: 10)
    
    Returns:
        tuple: (success: bool, status: dict)
    """
    start_time = time.time()
    elapsed = 0
    
    while elapsed < timeout:
        try:
            cert = custom_api.get_namespaced_custom_object(
                group="cert-manager.io",
                version="v1",
                namespace=namespace,
                plural="certificates",
                name=cert_name
            )
            
            conditions = cert.get('status', {}).get('conditions', [])
            
            # Build a map of conditions for easier lookup
            condition_map = {c.get('type'): c for c in conditions}
            
            # Check if certificate is Ready (success case)
            ready_condition = condition_map.get('Ready')
            if ready_condition and ready_condition.get('status') == 'True':
                logger.info(f"      ✓ Certificate Ready (took {int(elapsed)}s)")
                return True, cert.get('status', {})
            
            # Check Issuing condition for terminal failures
            # When Issuing is False with reason "Failed", cert-manager has given up
            issuing_condition = condition_map.get('Issuing')
            if issuing_condition:
                issuing_status = issuing_condition.get('status')
                issuing_reason = issuing_condition.get('reason', '')
                issuing_message = issuing_condition.get('message', 'No details')
                
                # Issuing condition with status False and reason Failed = terminal failure
                if issuing_status == 'False' and issuing_reason in ['Failed', 'InvalidConfiguration', 'Denied']:
                    detailed_error = _get_certificate_detailed_error(
                        custom_api,
                        cert_name,
                        namespace,
                        f"Issuing {issuing_reason}: {issuing_message}"
                    )
                    
                    # Always log detailed errors on failure
                    logger.info(f"      ✗ Certificate FAILED (Issuing condition): {issuing_reason}")
                    logger.info(f"      📋 Details: {detailed_error}")
                    
                    status_with_error = cert.get('status', {})
                    status_with_error['detailed_error'] = detailed_error
                    return False, status_with_error
            
            # Check Ready condition for other terminal failures
            # (e.g., configuration issues that prevent issuance from starting)
            if ready_condition:
                ready_reason = ready_condition.get('reason', 'Unknown')
                ready_message = ready_condition.get('message', 'No details')
                
                # Some reasons in Ready condition also indicate terminal failures
                if ready_reason in ['InvalidConfiguration', 'Denied']:
                    detailed_error = _get_certificate_detailed_error(
                        custom_api,
                        cert_name,
                        namespace,
                        f"Ready {ready_reason}: {ready_message}"
                    )
                    
                    logger.info(f"      ✗ Certificate FAILED (Ready condition): {ready_reason}")
                    logger.info(f"      📋 Details: {detailed_error}")
                    
                    status_with_error = cert.get('status', {})
                    status_with_error['detailed_error'] = detailed_error
                    return False, status_with_error
                
                # Not a terminal failure, log progress
                logger.info(f"      ⏳ Status: {ready_reason} - {ready_message}")
            
            if not any(c.get('type') == 'Ready' for c in conditions):
                logger.info(f"      ⏳ Waiting for Ready condition... ({int(elapsed)}s elapsed)")
            
        except ApiException as e:
            if e.status == 404:
                logger.info(f"      ⏳ Certificate not found yet... ({int(elapsed)}s elapsed)")
            else:
                logger.info(f"      ⚠ API error: {e}")
        
        time.sleep(poll_interval)
        elapsed = time.time() - start_time
    
    # Timeout reached - try to get detailed error
    detailed_error = f"Certificate not ready after {timeout}s"
    try:
        cert = custom_api.get_namespaced_custom_object(
            group="cert-manager.io",
            version="v1",
            namespace=namespace,
            plural="certificates",
            name=cert_name
        )
        conditions = cert.get('status', {}).get('conditions', [])
        for condition in conditions:
            if condition.get('type') == 'Ready' and condition.get('status') == 'False':
                reason = condition.get('reason', 'Unknown')
                message = condition.get('message', 'No details')
                detailed_error = _get_certificate_detailed_error(
                    custom_api,
                    cert_name,
                    namespace,
                    f"Timeout after {timeout}s - Last status: {reason}: {message}"
                )
                break
    except:
        pass  # Use the basic timeout message
    
    logger.info(f"      ✗ {detailed_error}")
    
    return False, {'detailed_error': detailed_error}


def validate_certificate_secret(core_v1, secret_name, namespace, expected_hostname=None):
    """
    Validate TLS secret contains valid certificate.
    
    Args:
        core_v1: Kubernetes CoreV1Api client
        secret_name: Name of the TLS secret
        namespace: Namespace of the secret
        expected_hostname: Expected hostname in certificate SAN (optional)
    
    Returns:
        tuple: (problems, cert_info_dict)
    """
    import base64
    
    problems = []
    cert_info = {}
    
    try:
        secret = core_v1.read_namespaced_secret(secret_name, namespace)
        
        if not secret.data or 'tls.crt' not in secret.data:
            problems.append(f"Secret {namespace}/{secret_name}: Missing tls.crt")
            return problems, cert_info
        
        # Decode and parse certificate
        cert_pem = base64.b64decode(secret.data['tls.crt'])
        cert = x509.load_pem_x509_certificate(cert_pem, default_backend())
        
        # Extract certificate info
        subject = cert.subject
        issuer = cert.issuer
        not_before = cert.not_valid_before_utc
        not_after = cert.not_valid_after_utc
        
        # Get common name
        cn_attr = subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        common_name = cn_attr[0].value if cn_attr else "N/A"
        
        # Get issuer organization
        issuer_org = issuer.get_attributes_for_oid(x509.oid.NameOID.ORGANIZATION_NAME)
        issuer_name = issuer_org[0].value if issuer_org else "Unknown"
        
        # Get SANs
        try:
            san_ext = cert.extensions.get_extension_for_oid(x509.oid.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
            san_names = [name.value for name in san_ext.value]
        except x509.ExtensionNotFound:
            san_names = []
        
        cert_info = {
            'common_name': common_name,
            'issuer': issuer_name,
            'not_before': not_before,
            'not_after': not_after,
            'sans': san_names
        }
        
        # Validate certificate is not expired
        now = datetime.now(timezone.utc)
        if now < not_before:
            problems.append(f"Certificate not yet valid (starts {not_before})")
        elif now > not_after:
            problems.append(f"Certificate expired (ended {not_after})")
        
        # Validate hostname if provided
        if expected_hostname:
            if expected_hostname not in san_names and expected_hostname != common_name:
                problems.append(f"Hostname '{expected_hostname}' not in certificate (CN: {common_name}, SANs: {san_names})")
        
        if not problems:
            logger.info(f"      CN: {common_name}")
            logger.info(f"      Issuer: {issuer_name}")
            logger.info(f"      Valid: {not_before} to {not_after}")
            if san_names:
                logger.info(f"      SANs: {', '.join(san_names)}")
        
    except Exception as e:
        problems.append(f"Failed to validate secret {namespace}/{secret_name}: {e}")
    
    return problems, cert_info


def validate_https_certificate(url, expected_hostname=None):
    """
    Validate HTTPS certificate via SSL connection.
    
    Args:
        url: HTTPS URL to test
        expected_hostname: Expected hostname in certificate (optional)
    
    Returns:
        tuple: (problems, response_info)
    """
    from urllib.parse import urlparse
    
    problems = []
    response_info = {}
    
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port or 443
        
        context = ssl.create_default_context()
        
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert_der = ssock.getpeercert(binary_form=True)
                cert = x509.load_der_x509_certificate(cert_der, default_backend())
                
                subject = cert.subject
                issuer = cert.issuer
                not_after = cert.not_valid_after_utc
                
                cn_attr = subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
                common_name = cn_attr[0].value if cn_attr else "N/A"
                
                issuer_org = issuer.get_attributes_for_oid(x509.oid.NameOID.ORGANIZATION_NAME)
                issuer_name = issuer_org[0].value if issuer_org else "Unknown"
                
                try:
                    san_ext = cert.extensions.get_extension_for_oid(x509.oid.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                    san_names = [name.value for name in san_ext.value]
                except x509.ExtensionNotFound:
                    san_names = []
                
                response_info = {
                    'common_name': common_name,
                    'issuer': issuer_name,
                    'not_after': not_after,
                    'sans': san_names
                }
                
                check_hostname = expected_hostname or hostname
                if check_hostname not in san_names and check_hostname != common_name:
                    problems.append(f"Hostname mismatch: expected '{check_hostname}', cert CN: {common_name}, SANs: {san_names}")
                
                if not problems:
                    logger.info(f"      CN: {common_name}")
                    logger.info(f"      Issuer: {issuer_name}")
                    logger.info(f"      Expires: {not_after}")
                
    except ssl.SSLError as e:
        problems.append(f"SSL error: {e}")
    except socket.timeout:
        problems.append(f"Connection timeout to {url}")
    except Exception as e:
        problems.append(f"HTTPS validation failed: {e}")
    
    return problems, response_info


# =============================================================================
# HTTP ENDPOINT VALIDATION
# =============================================================================

def validate_http_debug_app(url, expected_hostname, app_name=None, max_retries=3, retry_delays=None):
    """
    Validate mendhak/http-https-echo application response.
    
    Args:
        url: HTTPS URL to test
        expected_hostname: Expected hostname in response
        app_name: App name for error messages (defaults to hostname)
        max_retries: Number of retry attempts (default: 3)
        retry_delays: List of delay seconds between retries
    
    Returns:
        tuple: (problems, response_data)
    """
    problems = []
    response_data = {}
    retry_delays = retry_delays or [10, 30, 60]
    app_name = app_name or expected_hostname
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                logger.info(f"      Retry {attempt}/{max_retries - 1} after {retry_delays[attempt - 1]}s...")
            
            response = requests.get(url, timeout=30, verify=True)
            
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}"
                if attempt == max_retries - 1:
                    problems.append(f"{app_name} - {error_msg}")
                    logger.info(f"      ✗ {error_msg}")
                else:
                    logger.info(f"      ✗ {error_msg}, retrying in {retry_delays[attempt]}s...")
                    time.sleep(retry_delays[attempt])
                    continue
            
            try:
                json_data = response.json()
                response_data = json_data
            except ValueError:
                error_msg = "Response is not valid JSON"
                if attempt == max_retries - 1:
                    problems.append(f"{app_name} - {error_msg}")
                    logger.info(f"      ✗ {error_msg}")
                else:
                    logger.info(f"      ✗ {error_msg}, retrying in {retry_delays[attempt]}s...")
                    time.sleep(retry_delays[attempt])
                    continue
            
            # Validate expected fields
            validations = {
                'hostname': (None, 'hostname', expected_hostname),
                'x-scheme': ('headers', 'x-forwarded-port', '443'),
                'x-forwarded-proto': ('headers', 'x-forwarded-proto', 'https')
            }
            
            field_errors = []
            for field_name, (parent_key, json_key, expected_value) in validations.items():
                if parent_key:
                    actual_value = json_data.get(parent_key, {}).get(json_key)
                    display_key = f"{parent_key}.{json_key}"
                else:
                    actual_value = json_data.get(json_key)
                    display_key = json_key
                
                if actual_value == expected_value:
                    logger.info(f"      ✓ {display_key}: {actual_value}")
                else:
                    error_msg = f"{display_key}: expected '{expected_value}', got '{actual_value}'"
                    logger.info(f"      ✗ {error_msg}")
                    field_errors.append(f"{app_name} - {error_msg}")
            
            if field_errors:
                if attempt == max_retries - 1:
                    problems.extend(field_errors)
                else:
                    logger.info(f"      Validation failed, retrying in {retry_delays[attempt]}s...")
                    time.sleep(retry_delays[attempt])
                    continue
            
            # Success
            break
            
        except requests.exceptions.SSLError as e:
            error_msg = f"SSL error: {e}"
            if attempt == max_retries - 1:
                problems.append(f"{app_name} - {error_msg}")
                logger.info(f"      ✗ {error_msg}")
            else:
                logger.info(f"      ✗ {error_msg}, retrying in {retry_delays[attempt]}s...")
                time.sleep(retry_delays[attempt])
        except Exception as e:
            error_msg = f"Request failed: {e}"
            if attempt == max_retries - 1:
                problems.append(f"{app_name} - {error_msg}")
                logger.info(f"      ✗ {error_msg}")
            else:
                logger.info(f"      ✗ {error_msg}, retrying in {retry_delays[attempt]}s...")
                time.sleep(retry_delays[attempt])
    
    return problems, response_data


def validate_whoami_env_vars(url, expected_env_vars, app_name="app", max_retries=3, retry_delays=None):
    """
    Validate environment variables in traefik/whoami application response.
    
    Args:
        url: Application URL
        expected_env_vars: Dict of env var names to expected values
        app_name: Application name for logging
        max_retries: Maximum number of retry attempts
        retry_delays: List of delays between retries
    
    Returns:
        tuple: (problems_list, env_vars_dict)
    """
    if retry_delays is None:
        retry_delays = [10, 30, 60]
    
    problems = []
    
    while len(retry_delays) < max_retries - 1:
        retry_delays.append(retry_delays[-1] if retry_delays else 30)
    
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                logger.info(f"      Retry {attempt}/{max_retries}...")
            
            request_url = f"{url}?env=true"
            logger.info(f"      GET {request_url}")
            
            response = requests.get(request_url, timeout=30, verify=True)
            
            logger.info(f"      Status: {response.status_code}")
            
            if response.status_code != 200:
                if attempt < max_retries:
                    delay = retry_delays[attempt - 1]
                    logger.info(f"      ⏳ Waiting {delay}s before retry...")
                    time.sleep(delay)
                    continue
                else:
                    problems.append(f"{app_name}: HTTP {response.status_code}")
                    return problems, {}
            
            text = response.text
            logger.info(f"      ✓ Response received, parsing environment variables...")
            
            lines = text.split('\n')
            env_vars = {}
            
            found_env_section = False
            for line in lines:
                line = line.strip()
                if not line:
                    found_env_section = True
                    continue
                
                if found_env_section and '=' in line:
                    key, _, value = line.partition('=')
                    env_vars[key] = value
            
            logger.info(f"      ✓ Found {len(env_vars)} environment variables")
            
            missing_vars = []
            wrong_values = []
            
            for key, expected_value in expected_env_vars.items():
                if key not in env_vars:
                    missing_vars.append(key)
                elif env_vars[key] != expected_value:
                    wrong_values.append(f"{key} (expected: {expected_value}, got: {env_vars[key]})")
            
            if missing_vars:
                problems.append(f"{app_name}: Missing env vars: {', '.join(missing_vars)}")
            
            if wrong_values:
                problems.append(f"{app_name}: Wrong values: {', '.join(wrong_values)}")
            
            if not problems:
                logger.info(f"      ✓ All {len(expected_env_vars)} expected env vars validated")
            
            return problems, env_vars
        
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                delay = retry_delays[attempt - 1]
                logger.info(f"      ⚠ Request failed: {str(e)}")
                logger.info(f"      ⏳ Waiting {delay}s before retry...")
                time.sleep(delay)
            else:
                problems.append(f"{app_name}: Request failed after {max_retries} retries - {str(e)}")
                return problems, {}
    
    problems.append(f"{app_name}: Failed to validate after {max_retries} attempts")
    return problems, {}
