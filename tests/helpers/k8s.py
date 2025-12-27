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
from kubernetes import client
from kubernetes.client.rest import ApiException
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


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

def wait_for_job_completion(batch_v1, job_name, namespace, timeout=300):
    """
    Wait for a job to complete and return its status.
    
    Args:
        batch_v1: Kubernetes BatchV1Api client
        job_name: Name of the Job resource
        namespace: Namespace of the Job
        timeout: Maximum wait time in seconds (default: 300)
    
    Returns:
        str: 'succeeded', 'failed', or 'timeout'
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
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

def validate_all_argocd_apps(custom_api, namespace_filter=None, verbose=True):
    """
    Check all ArgoCD applications for health and sync status.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        namespace_filter: Optional namespace filter for ArgoCD apps
        verbose: Print detailed status for each app (default: True)
    
    Returns:
        list: List of problem descriptions (empty if all healthy)
    """
    if verbose:
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
        if verbose:
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
        
        if verbose:
            status_icon = "✓" if (health == 'Healthy' and sync == 'Synced') else "✗"
            logger.info(f"  {status_icon} {namespace}/{name}: Health={health}, Sync={sync}")
    
    if verbose and not problems:
        logger.info(f"  All {total_apps} applications healthy and synced")
    
    return problems


# =============================================================================
# POD HEALTH VALIDATION
# =============================================================================

def validate_pod_health(core_v1, platform_namespaces, verbose=True):
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
        verbose: Print detailed status (default: True)
    
    Returns:
        list: List of problem descriptions (empty if all healthy)
    """
    if verbose:
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
                if verbose:
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
            
            if verbose and pod_has_issues:
                logger.info(f"  ✗ {namespace}/{pod_name}: Issues found")
            elif not pod_has_issues:
                healthy_pods += 1
    
    if verbose:
        if problems:
            logger.info(f"  {healthy_pods}/{total_pods} pods healthy")
        else:
            logger.info(f"  All {total_pods} pods healthy")
    
    return problems


# =============================================================================
# JOB VALIDATION
# =============================================================================

def validate_failed_jobs(batch_v1, platform_namespaces, exclude_jobs=None, verbose=True):
    """
    Check for failed Jobs across platform namespaces.
    
    Args:
        batch_v1: Kubernetes BatchV1Api client
        platform_namespaces: List of namespaces to check
        exclude_jobs: Optional list of job name patterns to exclude from errors
        verbose: Print detailed status (default: True)
    
    Returns:
        tuple: (problems, warnings) where:
            - problems: list of non-excluded failed jobs
            - warnings: list of excluded failed jobs
    """
    if verbose:
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
                    if verbose:
                        logger.info(f"  ⚠ {namespace}/{job_name}: Failed (attempts: {failed_count}) [EXCLUDED]")
                else:
                    problems.append(f"{namespace}/{job_name}: Failed (attempts: {failed_count})")
                    if verbose:
                        logger.info(f"  ✗ {namespace}/{job_name}: Failed (attempts: {failed_count})")
    
    if verbose:
        logger.info(f"  Checked {total_jobs} jobs, {failed_jobs} with failures, {len(problems)} requiring attention")
    
    return problems, warnings


# =============================================================================
# INGRESS VALIDATION
# =============================================================================

def validate_ingress_configuration(networking_v1, platform_namespaces, verbose=True):
    """
    Validate Ingress resources have proper configuration.
    
    Validates:
    - Ingress spec exists and has rules defined
    - All rules have non-empty host values
    - Load balancer status exists with IP or hostname populated
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        platform_namespaces: List of namespaces to check
        verbose: Print detailed status (default: True)
    
    Returns:
        tuple: (problems, total_ingresses)
    """
    if verbose:
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
                if verbose:
                    logger.info(f"  ✗ {name}: Missing spec")
                continue
            
            # Check if rules exist
            if not ingress.spec.rules:
                problems.append(f"{name}: No rules defined")
                if verbose:
                    logger.info(f"  ✗ {name}: No rules defined")
                continue
            
            # Check each rule for host
            for i, rule in enumerate(ingress.spec.rules):
                if not rule.host or rule.host.strip() == "":
                    problems.append(f"{name}: Rule {i} has empty host")
                    if verbose:
                        logger.info(f"  ✗ {name}: Rule {i} has empty host")
            
            # Check load balancer status
            if not ingress.status or not ingress.status.load_balancer:
                problems.append(f"{name}: No load balancer status")
                if verbose:
                    logger.info(f"  ✗ {name}: No load balancer status")
                continue
            
            lb_ingress = ingress.status.load_balancer.ingress
            if not lb_ingress:
                problems.append(f"{name}: Load balancer has no ingress")
                if verbose:
                    logger.info(f"  ✗ {name}: Load balancer has no ingress")
                continue
            
            # Check if at least one LB ingress has IP or hostname
            has_address = any(lb.ip or lb.hostname for lb in lb_ingress)
            if not has_address:
                problems.append(f"{name}: Load balancer has no IP or hostname")
                if verbose:
                    logger.info(f"  ✗ {name}: Load balancer has no IP or hostname")
            elif verbose:
                logger.info(f"  ✓ {name}: Valid configuration")
    
    if verbose and not problems:
        logger.info(f"  All {total_ingresses} ingresses properly configured")
    
    return problems, total_ingresses


def validate_ingress_dns(networking_v1, platform_namespaces, dns_server='1.1.1.1', verbose=True):
    """
    Validate DNS resolution for Ingress hosts.
    
    For each ingress with a load balancer IP:
    - Queries DNS A records for each host using specified DNS server
    - Compares resolved IPs against expected load balancer IPs
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        platform_namespaces: List of namespaces to check
        dns_server: DNS server to query (default: '1.1.1.1')
        verbose: Print detailed status (default: True)
    
    Returns:
        tuple: (problems, checked_count)
    """
    if verbose:
        logger.info(f"Validating DNS resolution (using {dns_server})...")
    
    problems = []
    checked_count = 0
    resolver = dns.resolver.Resolver()
    resolver.nameservers = [dns_server]
    
    for namespace in platform_namespaces:
        ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
        
        for ingress in ingresses.items:
            name = f"{namespace}/{ingress.metadata.name}"
            
            # Get expected IPs from load balancer
            if not ingress.status or not ingress.status.load_balancer or not ingress.status.load_balancer.ingress:
                continue
            
            expected_ips = []
            for lb in ingress.status.load_balancer.ingress:
                if lb.ip:
                    expected_ips.append(lb.ip)
            
            if not expected_ips:
                continue
            
            # Check each host
            if not ingress.spec or not ingress.spec.rules:
                continue
            
            for rule in ingress.spec.rules:
                if not rule.host:
                    continue
                
                checked_count += 1
                host = rule.host
                
                try:
                    answers = resolver.resolve(host, 'A')
                    resolved_ips = [str(rdata) for rdata in answers]
                    
                    # Check if any resolved IP matches expected
                    if not any(ip in expected_ips for ip in resolved_ips):
                        problems.append(f"{name} ({host}): Resolves to {resolved_ips}, expected {expected_ips}")
                        if verbose:
                            logger.info(f"  ✗ {host}: {resolved_ips} (expected {expected_ips})")
                    elif verbose:
                        logger.info(f"  ✓ {host}: {resolved_ips[0]}")
                        
                except dns.resolver.NXDOMAIN:
                    problems.append(f"{name} ({host}): NXDOMAIN (does not exist)")
                    if verbose:
                        logger.info(f"  ✗ {host}: NXDOMAIN")
                except dns.resolver.NoAnswer:
                    problems.append(f"{name} ({host}): No A records")
                    if verbose:
                        logger.info(f"  ✗ {host}: No A records")
                except Exception as e:
                    problems.append(f"{name} ({host}): DNS error - {e}")
                    if verbose:
                        logger.info(f"  ✗ {host}: {e}")
    
    if verbose and not problems:
        logger.info(f"  All {checked_count} hosts resolve correctly")
    
    return problems, checked_count


def get_ingress_load_balancer_ip(networking_v1, ingress_class_name, namespace=None, verbose=True, fail_on_none=False):
    """
    Get the load balancer IP from ingresses matching the specified class.
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        ingress_class_name: Ingress class name to filter by
        namespace: Specific namespace to check (optional)
        verbose: Whether to log details (default: True)
        fail_on_none: Whether to fail test if IP not found (default: False)
    
    Returns:
        str: Load balancer IP or None
    """
    if verbose:
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
                    if lb.ip:
                        if verbose:
                            logger.info(f"✓ Found load balancer IP: {lb.ip}")
                        return lb.ip
        
        logger.warning(f"No load balancer IP found for ingressClassName: {ingress_class_name}")
        
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

def wait_for_certificate_ready(custom_api, cert_name, namespace, timeout=600, poll_interval=10, verbose=True):
    """
    Wait for a cert-manager Certificate to reach Ready status.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        cert_name: Name of the Certificate resource
        namespace: Namespace of the Certificate
        timeout: Maximum time to wait in seconds (default: 600)
        poll_interval: Time between checks in seconds (default: 10)
        verbose: Whether to print progress updates (default: True)
    
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
            
            for condition in conditions:
                if condition.get('type') == 'Ready':
                    if condition.get('status') == 'True':
                        if verbose:
                            logger.info(f"      ✓ Certificate Ready (took {int(elapsed)}s)")
                        return True, cert.get('status', {})
                    else:
                        reason = condition.get('reason', 'Unknown')
                        message = condition.get('message', 'No details')
                        if verbose:
                            logger.info(f"      ⏳ Status: {reason} - {message[:80]}")
            
            if verbose and not any(c.get('type') == 'Ready' for c in conditions):
                logger.info(f"      ⏳ Waiting for Ready condition... ({int(elapsed)}s elapsed)")
            
        except ApiException as e:
            if e.status == 404:
                if verbose:
                    logger.info(f"      ⏳ Certificate not found yet... ({int(elapsed)}s elapsed)")
            else:
                if verbose:
                    logger.info(f"      ⚠ API error: {e}")
        
        time.sleep(poll_interval)
        elapsed = time.time() - start_time
    
    if verbose:
        logger.info(f"      ✗ Certificate not ready after {timeout}s")
    
    return False, {}


def validate_certificate_secret(core_v1, secret_name, namespace, expected_hostname=None, verbose=True):
    """
    Validate TLS secret contains valid certificate.
    
    Args:
        core_v1: Kubernetes CoreV1Api client
        secret_name: Name of the TLS secret
        namespace: Namespace of the secret
        expected_hostname: Expected hostname in certificate SAN (optional)
        verbose: Print detailed status (default: True)
    
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
        
        if verbose and not problems:
            logger.info(f"      CN: {common_name}")
            logger.info(f"      Issuer: {issuer_name}")
            logger.info(f"      Valid: {not_before} to {not_after}")
            if san_names:
                logger.info(f"      SANs: {', '.join(san_names)}")
        
    except Exception as e:
        problems.append(f"Failed to validate secret {namespace}/{secret_name}: {e}")
    
    return problems, cert_info


def validate_https_certificate(url, expected_hostname=None, verbose=True):
    """
    Validate HTTPS certificate via SSL connection.
    
    Args:
        url: HTTPS URL to test
        expected_hostname: Expected hostname in certificate (optional)
        verbose: Print detailed status (default: True)
    
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
                
                if verbose and not problems:
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

def validate_http_debug_app(url, expected_hostname, app_name=None, max_retries=3, retry_delays=None, verbose=True):
    """
    Validate mendhak/http-https-echo application response.
    
    Args:
        url: HTTPS URL to test
        expected_hostname: Expected hostname in response
        app_name: App name for error messages (defaults to hostname)
        max_retries: Number of retry attempts (default: 3)
        retry_delays: List of delay seconds between retries
        verbose: Print detailed status (default: True)
    
    Returns:
        tuple: (problems, response_data)
    """
    problems = []
    response_data = {}
    retry_delays = retry_delays or [10, 30, 60]
    app_name = app_name or expected_hostname
    
    for attempt in range(max_retries):
        try:
            if verbose and attempt > 0:
                logger.info(f"      Retry {attempt}/{max_retries - 1} after {retry_delays[attempt - 1]}s...")
            
            response = requests.get(url, timeout=30, verify=True)
            
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}"
                if attempt == max_retries - 1:
                    problems.append(f"{app_name} - {error_msg}")
                    if verbose:
                        logger.info(f"      ✗ {error_msg}")
                else:
                    if verbose:
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
                    if verbose:
                        logger.info(f"      ✗ {error_msg}")
                else:
                    if verbose:
                        logger.info(f"      ✗ {error_msg}, retrying in {retry_delays[attempt]}s...")
                    time.sleep(retry_delays[attempt])
                    continue
            
            # Validate expected fields
            validations = {
                'hostname': (None, 'hostname', expected_hostname),
                'x-scheme': ('headers', 'x-scheme', 'https'),
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
                    if verbose:
                        logger.info(f"      ✓ {display_key}: {actual_value}")
                else:
                    error_msg = f"{display_key}: expected '{expected_value}', got '{actual_value}'"
                    if verbose:
                        logger.info(f"      ✗ {error_msg}")
                    field_errors.append(f"{app_name} - {error_msg}")
            
            if field_errors:
                if attempt == max_retries - 1:
                    problems.extend(field_errors)
                else:
                    if verbose:
                        logger.info(f"      Validation failed, retrying in {retry_delays[attempt]}s...")
                    time.sleep(retry_delays[attempt])
                    continue
            
            # Success
            break
            
        except requests.exceptions.SSLError as e:
            error_msg = f"SSL error: {e}"
            if attempt == max_retries - 1:
                problems.append(f"{app_name} - {error_msg}")
                if verbose:
                    logger.info(f"      ✗ {error_msg}")
            else:
                if verbose:
                    logger.info(f"      ✗ {error_msg}, retrying in {retry_delays[attempt]}s...")
                time.sleep(retry_delays[attempt])
        except Exception as e:
            error_msg = f"Request failed: {e}"
            if attempt == max_retries - 1:
                problems.append(f"{app_name} - {error_msg}")
                if verbose:
                    logger.info(f"      ✗ {error_msg}")
            else:
                if verbose:
                    logger.info(f"      ✗ {error_msg}, retrying in {retry_delays[attempt]}s...")
                time.sleep(retry_delays[attempt])
    
    return problems, response_data


def validate_whoami_env_vars(url, expected_env_vars, app_name="app", max_retries=3, retry_delays=None, verbose=True):
    """
    Validate environment variables in traefik/whoami application response.
    
    Args:
        url: Application URL
        expected_env_vars: Dict of env var names to expected values
        app_name: Application name for logging
        max_retries: Maximum number of retry attempts
        retry_delays: List of delays between retries
        verbose: Enable detailed logging
    
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
            if verbose and attempt > 1:
                logger.info(f"      Retry {attempt}/{max_retries}...")
            
            request_url = f"{url}?env=true"
            if verbose:
                logger.info(f"      GET {request_url}")
            
            response = requests.get(request_url, timeout=30, verify=True)
            
            if verbose:
                logger.info(f"      Status: {response.status_code}")
            
            if response.status_code != 200:
                if attempt < max_retries:
                    delay = retry_delays[attempt - 1]
                    if verbose:
                        logger.info(f"      ⏳ Waiting {delay}s before retry...")
                    time.sleep(delay)
                    continue
                else:
                    problems.append(f"{app_name}: HTTP {response.status_code}")
                    return problems, {}
            
            text = response.text
            if verbose:
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
            
            if verbose:
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
            
            if verbose and not problems:
                logger.info(f"      ✓ All {len(expected_env_vars)} expected env vars validated")
            
            return problems, env_vars
        
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                delay = retry_delays[attempt - 1]
                if verbose:
                    logger.info(f"      ⚠ Request failed: {str(e)}")
                    logger.info(f"      ⏳ Waiting {delay}s before retry...")
                time.sleep(delay)
            else:
                problems.append(f"{app_name}: Request failed after {max_retries} retries - {str(e)}")
                return problems, {}
    
    problems.append(f"{app_name}: Failed to validate after {max_retries} attempts")
    return problems, {}
