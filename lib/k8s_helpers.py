"""Kubernetes helper functions"""
import time
import logging
from kubernetes import client
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


def _log_validation_failure(failure_title, problems, max_display=10):
    """
    Helper to log validation failures with consistent formatting.
    
    Args:
        failure_title: Title for the failure section (e.g., "POD HEALTH VALIDATION FAILED")
        problems: List of problem descriptions
        max_display: Maximum number of problems to display (default: 10)
    """
    logger.info("\n" + "="*70)
    logger.info(failure_title)
    logger.info("="*70)
    logger.info(f"\n❌ {len(problems)} issue(s) found:\n")
    
    for error in problems[:max_display]:
        logger.info(f"   • {error}")
    
    if len(problems) > max_display:
        logger.info(f"   ... and {len(problems) - max_display} more")


def get_platform_namespaces(core_v1, namespace_filter=None):
    """Get list of platform namespaces to check"""
    if namespace_filter:
        return [namespace_filter]
    all_ns = core_v1.list_namespace()
    return [ns.metadata.name for ns in all_ns.items 
            if ns.metadata.name.startswith("glueops-") or ns.metadata.name == "nonprod"]


def wait_for_job_completion(batch_v1, job_name, namespace, timeout=300):
    """Wait for a job to complete and return its status"""
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
    """Check pods for a job to validate clean execution (no restarts, exit code 0)"""
    issues = []
    
    try:
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}")
        
        for pod in pods.items:
            if pod.status.container_statuses:
                for container in pod.status.container_statuses:
                    if container.restart_count > 0:
                        issues.append(f"container restarted {container.restart_count}x")
                    
                    if container.last_state.terminated:
                        if container.last_state.terminated.exit_code != 0:
                            issues.append(f"exit code {container.last_state.terminated.exit_code}")
            
            if pod.status.phase not in ["Succeeded", "Running"]:
                issues.append(f"pod {pod.status.phase}")
    except ApiException as e:
        issues.append(f"failed to check pods: {e.reason}")
    
    return issues


def validate_all_argocd_apps(custom_api, namespace_filter=None, verbose=True):
    """
    Validate all ArgoCD applications are Healthy and Synced.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        namespace_filter: Optional namespace filter for ArgoCD apps
        verbose: Print detailed status for each app (default: True)
    
    Returns:
        list: List of problem descriptions for apps that failed validation
    
    Raises:
        AssertionError: If no ArgoCD applications found
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
    
    if verbose:
        logger.info(f"  Checking {len(apps['items'])} ArgoCD applications...")
    
    problems = []
    healthy_count = 0
    
    for app in apps['items']:
        name = app['metadata']['name']
        namespace = app['metadata'].get('namespace', 'default')
        health = app.get('status', {}).get('health', {}).get('status', 'Unknown')
        sync = app.get('status', {}).get('sync', {}).get('status', 'Unknown')
        
        if health != 'Healthy' or sync != 'Synced':
            problems.append(f"{namespace}/{name} (health: {health}, sync: {sync})")
            if verbose:
                logger.info(f"    ✗ {namespace}/{name}: {health}/{sync}")
        else:
            healthy_count += 1
            if verbose:
                logger.info(f"    ✓ {namespace}/{name}: {health}/{sync}")
    
    if verbose:
        logger.info(f"  Summary: {healthy_count} healthy, {len(problems)} unhealthy")
    
    return problems


def validate_pod_health(core_v1, platform_namespaces, verbose=True):
    """
    Check for unhealthy pods across platform namespaces.
    
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
        list: List of problem descriptions for pods with issues
    """
    problems = []
    total_pods = 0
    healthy_pods = 0
    
    for namespace in platform_namespaces:
        pods = core_v1.list_namespaced_pod(namespace=namespace)
        total_pods += len(pods.items)
        
        if verbose:
            logger.info(f"  Checking {len(pods.items)} pods in {namespace}...")
        
        for pod in pods.items:
            name = f"{namespace}/{pod.metadata.name}"
            
            # Skip pods from completed Jobs (they're expected to be Failed/Succeeded)
            is_job_pod = False
            if pod.metadata.owner_references:
                for owner in pod.metadata.owner_references:
                    if owner.kind == "Job":
                        is_job_pod = True
                        break
            
            if is_job_pod:
                total_pods -= 1  # Don't count job pods in totals
                continue
            
            pod_healthy = True
            
            # Check pod phase
            if pod.status.phase in ["Failed", "Unknown"]:
                problem = f"{name}: phase={pod.status.phase}"
                problems.append(problem)
                pod_healthy = False
                if verbose:
                    logger.info(f"    ✗ {problem}")
                continue
            
            # Check container statuses
            if pod.status.container_statuses:
                for container in pod.status.container_statuses:
                    # Waiting state issues
                    if container.state.waiting:
                        reason = container.state.waiting.reason
                        if reason in ["CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"]:
                            problem = f"{name}/{container.name}: {reason}"
                            problems.append(problem)
                            pod_healthy = False
                            if verbose:
                                logger.info(f"    ✗ {problem}")
                    
                    # OOMKilled
                    if container.last_state.terminated:
                        if container.last_state.terminated.reason == "OOMKilled":
                            problem = f"{name}/{container.name}: OOMKilled"
                            problems.append(problem)
                            pod_healthy = False
                            if verbose:
                                logger.info(f"    ✗ {problem}")
                    
                    # High restart count
                    if container.restart_count > 5:
                        problem = f"{name}/{container.name}: {container.restart_count} restarts"
                        problems.append(problem)
                        pod_healthy = False
                        if verbose:
                            logger.info(f"    ✗ {problem}")
            
            if pod_healthy:
                healthy_pods += 1
    
    if verbose:
        logger.info(f"  Summary: {healthy_pods}/{total_pods} pods healthy, {len(problems)} issues found")
    
    return problems


def validate_failed_jobs(batch_v1, platform_namespaces, exclude_jobs=None, verbose=True):
    """
    Check for failed Jobs across platform namespaces.
    
    Validates Job resources for failure count (status.failed > 0).
    Jobs that eventually succeeded (after retries) are not reported.
    
    Args:
        batch_v1: Kubernetes BatchV1Api client
        platform_namespaces: List of namespaces to check
        exclude_jobs: Optional list of job name patterns to exclude from errors
        verbose: Print detailed status (default: True)
    
    Returns:
        tuple: (problems, warnings) - problems cause test failure, warnings are informational
    """
    if exclude_jobs is None:
        exclude_jobs = []
    
    problems = []
    warnings = []
    total_jobs = 0
    
    for namespace in platform_namespaces:
        jobs = batch_v1.list_namespaced_job(namespace=namespace)
        total_jobs += len(jobs.items)
        
        for job in jobs.items:
            if job.status.failed and job.status.failed > 0:
                # If job eventually succeeded, it's fine (retries are expected)
                if job.status.succeeded and job.status.succeeded > 0:
                    continue
                
                job_full_name = f"{namespace}/{job.metadata.name}"
                job_desc = f"{job_full_name} ({job.status.failed}x failed)"
                
                # Check if job matches exclusion pattern
                excluded = False
                for pattern in exclude_jobs:
                    if '*' in pattern:
                        # Simple wildcard matching
                        prefix = pattern.split('*')[0]
                        if job.metadata.name.startswith(prefix):
                            excluded = True
                            break
                    elif pattern == job.metadata.name or pattern == job_full_name:
                        excluded = True
                        break
                
                if excluded:
                    warnings.append(job_desc)
                    if verbose:
                        logger.info(f"    ⚠ {job_desc} (excluded)")
                else:
                    problems.append(job_desc)
                    if verbose:
                        logger.info(f"    ✗ {job_desc}")
    
    if verbose:
        failed_count = len(problems) + len(warnings)
        logger.info(f"  Summary: {total_jobs} jobs checked, {failed_count} failed")
    
    return problems, warnings


def validate_ingress_configuration(networking_v1, platform_namespaces, verbose=True):
    """
    Check all Ingress objects are valid with proper configuration.
    
    Validates:
    - Ingress spec exists and has rules defined
    - All rules have non-empty host values
    - Load balancer status exists with IP or hostname populated
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        platform_namespaces: List of namespaces to check
        verbose: Print detailed status (default: True)
    
    Returns:
        tuple: (problems, total_ingresses) - problems cause test failure
    """
    problems = []
    total_ingresses = 0
    
    for namespace in platform_namespaces:
        ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
        
        for ingress in ingresses.items:
            total_ingresses += 1
            name = f"{namespace}/{ingress.metadata.name}"
            
            # Get hosts and LB for verbose logging
            hosts = []
            lb_addrs = []
            if ingress.spec and ingress.spec.rules:
                hosts = [r.host for r in ingress.spec.rules if r.host]
            if ingress.status and ingress.status.load_balancer and ingress.status.load_balancer.ingress:
                for lb in ingress.status.load_balancer.ingress:
                    if lb.ip:
                        lb_addrs.append(lb.ip)
                    elif lb.hostname:
                        lb_addrs.append(lb.hostname)
            
            if verbose:
                logger.info(f"  {name}: {', '.join(hosts) if hosts else 'no hosts'} → {', '.join(lb_addrs) if lb_addrs else 'no LB'}")
            
            # Check if spec exists
            if not ingress.spec:
                problems.append(f"{name}: missing spec")
                continue
            
            # Check if rules exist
            if not ingress.spec.rules:
                problems.append(f"{name}: no rules defined")
                continue
            
            # Check each rule has a host
            empty_hosts = []
            for i, rule in enumerate(ingress.spec.rules):
                if not rule.host or rule.host.strip() == "":
                    empty_hosts.append(f"rule[{i}]")
            
            if empty_hosts:
                problems.append(f"{name}: empty hosts in {', '.join(empty_hosts)}")
            
            # Check if ingress has a load balancer address
            if ingress.status and ingress.status.load_balancer:
                lb_ingress = ingress.status.load_balancer.ingress
                if not lb_ingress or len(lb_ingress) == 0:
                    problems.append(f"{name}: no load balancer address")
                else:
                    # Check if address/IP is populated
                    has_address = False
                    for lb in lb_ingress:
                        if (lb.ip and lb.ip.strip()) or (lb.hostname and lb.hostname.strip()):
                            has_address = True
                            break
                    if not has_address:
                        problems.append(f"{name}: load balancer address is empty")
            else:
                problems.append(f"{name}: no load balancer status")
    
    if verbose:
        logger.info(f"  Summary: {len(problems)} issues found across {total_ingresses} ingresses")
    
    return problems, total_ingresses


def validate_ingress_dns(networking_v1, platform_namespaces, dns_server='1.1.1.1', verbose=True):
    """
    Verify ingress hosts resolve to correct load balancer IPs via DNS.
    
    For each ingress with a load balancer IP:
    - Queries DNS A records for each host using specified DNS server
    - Compares resolved IPs against expected load balancer IPs
    - Fails if host doesn't exist (NXDOMAIN), has no A record, or resolves to wrong IP
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        platform_namespaces: List of namespaces to check
        dns_server: DNS server to query (default: '1.1.1.1' - Cloudflare)
        verbose: Print detailed status (default: True)
    
    Returns:
        tuple: (problems, checked_count) - problems cause test failure
    """
    import dns.resolver
    
    problems = []
    checked_count = 0
    
    # Create custom resolver with specified DNS server
    resolver = dns.resolver.Resolver()
    resolver.nameservers = [dns_server]
    
    if verbose:
        logger.info(f"  Using DNS server: {dns_server}")
    
    for namespace in platform_namespaces:
        ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
        
        for ingress in ingresses.items:
            name = f"{namespace}/{ingress.metadata.name}"
            
            # Skip if no rules or status
            if not ingress.spec or not ingress.spec.rules:
                continue
            if not ingress.status or not ingress.status.load_balancer:
                continue
            
            # Get expected LB IP(s)
            expected_ips = set()
            lb_ingress = ingress.status.load_balancer.ingress
            if lb_ingress:
                for lb in lb_ingress:
                    if lb.ip and lb.ip.strip():
                        expected_ips.add(lb.ip.strip())
            
            if not expected_ips:
                continue
            
            # Check each host's DNS resolution
            for rule in ingress.spec.rules:
                if not rule.host or not rule.host.strip():
                    continue
                
                host = rule.host.strip()
                checked_count += 1
                
                # Query DNS using dnspython
                try:
                    # Resolve A records for the host using custom resolver
                    answers = resolver.resolve(host, 'A')
                    resolved_ips = set()
                    for rdata in answers:
                        resolved_ips.add(rdata.address)
                    
                    # Check if resolved IP matches expected LB IP
                    if not resolved_ips:
                        problems.append(f"{name}/{host}: no A record found")
                    elif not resolved_ips.intersection(expected_ips):
                        problems.append(
                            f"{name}/{host}: resolves to {', '.join(sorted(resolved_ips))} "
                            f"but expected {', '.join(sorted(expected_ips))}"
                        )
                    else:
                        # DNS resolves correctly
                        if verbose:
                            logger.info(f"    ✓ {host} → {', '.join(sorted(resolved_ips))}")
                
                except dns.resolver.NXDOMAIN:
                    problems.append(f"{name}/{host}: domain does not exist")
                except dns.resolver.NoAnswer:
                    problems.append(f"{name}/{host}: no A record found")
                except dns.resolver.Timeout:
                    problems.append(f"{name}/{host}: DNS lookup timeout")
                except Exception as e:
                    problems.append(f"{name}/{host}: DNS lookup error: {e}")
    
    if verbose:
        logger.info(f"  Summary: {len(problems)} DNS issues found (checked {checked_count} hosts)")
    
    return problems, checked_count


def get_ingress_load_balancer_ip(networking_v1, namespace=None):
    """
    Get the first available load balancer IP from ingress resources.
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        namespace: Optional namespace to search (searches all if None)
    
    Returns:
        str: Load balancer IP address or None if not found
    """
    if namespace:
        namespaces = [namespace]
    else:
        # Get all namespaces
        core_v1 = client.CoreV1Api()
        all_ns = core_v1.list_namespace()
        namespaces = [ns.metadata.name for ns in all_ns.items]
    
    for ns in namespaces:
        try:
            ingresses = networking_v1.list_namespaced_ingress(namespace=ns)
            for ingress in ingresses.items:
                if ingress.status and ingress.status.load_balancer:
                    lb_ingress = ingress.status.load_balancer.ingress
                    if lb_ingress:
                        for lb in lb_ingress:
                            if lb.ip and lb.ip.strip():
                                return lb.ip.strip()
        except ApiException:
            continue
    
    return None


def wait_for_certificate_ready(custom_api, cert_name, namespace, timeout=600, poll_interval=10, verbose=True):
    """
    Wait for a cert-manager Certificate resource to become ready.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        cert_name: Name of the Certificate resource
        namespace: Namespace of the Certificate
        timeout: Maximum time to wait in seconds (default: 600 = 10 minutes)
        poll_interval: Time between checks in seconds (default: 10)
        verbose: Print status updates (default: True)
    
    Returns:
        tuple: (success: bool, status: dict) - success indicates if cert is ready
    """
    import time
    
    start_time = time.time()
    last_status = None
    
    while time.time() - start_time < timeout:
        try:
            cert = custom_api.get_namespaced_custom_object(
                group="cert-manager.io",
                version="v1",
                namespace=namespace,
                plural="certificates",
                name=cert_name
            )
            
            status = cert.get('status', {})
            conditions = status.get('conditions', [])
            
            # Check if Ready condition is True
            for condition in conditions:
                if condition.get('type') == 'Ready':
                    last_status = condition
                    if condition.get('status') == 'True':
                        if verbose:
                            logger.info(f"  ✓ Certificate {namespace}/{cert_name} is Ready")
                        return True, status
                    else:
                        if verbose:
                            reason = condition.get('reason', 'Unknown')
                            message = condition.get('message', 'No message')
                            logger.info(f"  ⏳ Certificate {namespace}/{cert_name}: {reason} - {message}")
            
            time.sleep(poll_interval)
            
        except ApiException as e:
            if e.status == 404:
                if verbose:
                    logger.info(f"  ⏳ Certificate {namespace}/{cert_name} not found yet...")
                time.sleep(poll_interval)
            else:
                raise
    
    # Timeout reached
    if verbose:
        if last_status:
            reason = last_status.get('reason', 'Unknown')
            message = last_status.get('message', 'No message')
            logger.info(f"  ✗ Timeout waiting for certificate: {reason} - {message}")
        else:
            logger.info(f"  ✗ Timeout waiting for certificate (no status available)")
    
    return False, last_status or {}


def validate_certificate_secret(core_v1, secret_name, namespace, expected_hostname=None, verbose=True):
    """
    Validate a TLS secret created by cert-manager.
    
    Checks:
    - Secret exists
    - Contains tls.crt and tls.key
    - Certificate is valid X.509
    - Certificate matches expected hostname (if provided)
    - Certificate is not expired
    
    Args:
        core_v1: Kubernetes CoreV1Api client
        secret_name: Name of the TLS secret
        namespace: Namespace of the secret
        expected_hostname: Expected hostname in certificate SAN (optional)
        verbose: Print detailed status (default: True)
    
    Returns:
        tuple: (problems: list, cert_info: dict) - problems list is empty if valid
    """
    import base64
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    from datetime import datetime, timezone
    
    problems = []
    cert_info = {}
    
    try:
        # Get the secret
        secret = core_v1.read_namespaced_secret(name=secret_name, namespace=namespace)
        
        # Check required fields
        if not secret.data:
            problems.append(f"{namespace}/{secret_name}: secret has no data")
            return problems, cert_info
        
        if 'tls.crt' not in secret.data:
            problems.append(f"{namespace}/{secret_name}: missing tls.crt")
        if 'tls.key' not in secret.data:
            problems.append(f"{namespace}/{secret_name}: missing tls.key")
        
        if problems:
            return problems, cert_info
        
        # Decode and parse certificate
        cert_data = base64.b64decode(secret.data['tls.crt'])
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())
        
        # Extract certificate information
        cert_info['subject'] = cert.subject.rfc4514_string()
        cert_info['issuer'] = cert.issuer.rfc4514_string()
        cert_info['not_before'] = cert.not_valid_before_utc
        cert_info['not_after'] = cert.not_valid_after_utc
        cert_info['serial_number'] = str(cert.serial_number)
        
        # Extract SANs (Subject Alternative Names)
        try:
            san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            cert_info['sans'] = [name.value for name in san_ext.value]
        except x509.ExtensionNotFound:
            cert_info['sans'] = []
        
        if verbose:
            logger.info(f"  Certificate info for {namespace}/{secret_name}:")
            logger.info(f"    Issuer: {cert_info['issuer']}")
            logger.info(f"    Valid from: {cert_info['not_before']}")
            logger.info(f"    Valid until: {cert_info['not_after']}")
            logger.info(f"    SANs: {', '.join(cert_info['sans'])}")
        
        # Validation checks
        now = datetime.now(timezone.utc)
        
        # Check expiration
        if cert.not_valid_after_utc < now:
            problems.append(f"{namespace}/{secret_name}: certificate expired on {cert_info['not_after']}")
        elif cert.not_valid_before_utc > now:
            problems.append(f"{namespace}/{secret_name}: certificate not yet valid (starts {cert_info['not_before']})")
        else:
            if verbose:
                logger.info(f"    ✓ Certificate is currently valid")
        
        # Check if Let's Encrypt issued
        if 'Let\'s Encrypt' in cert_info['issuer'] or 'letsencrypt' in cert_info['issuer'].lower():
            cert_info['is_letsencrypt'] = True
            if verbose:
                logger.info(f"    ✓ Issued by Let's Encrypt")
        else:
            cert_info['is_letsencrypt'] = False
            if verbose:
                logger.info(f"    ⚠ Not issued by Let's Encrypt")
        
        # Check hostname if provided
        if expected_hostname:
            if expected_hostname in cert_info['sans']:
                if verbose:
                    logger.info(f"    ✓ Hostname '{expected_hostname}' in SANs")
            else:
                problems.append(
                    f"{namespace}/{secret_name}: expected hostname '{expected_hostname}' "
                    f"not in SANs: {cert_info['sans']}"
                )
        
    except ApiException as e:
        if e.status == 404:
            problems.append(f"{namespace}/{secret_name}: secret not found")
        else:
            problems.append(f"{namespace}/{secret_name}: API error: {e.reason}")
    except Exception as e:
        problems.append(f"{namespace}/{secret_name}: failed to parse certificate: {e}")
    
    return problems, cert_info


def validate_https_certificate(url, expected_hostname=None, verbose=True):
    """
    Validate HTTPS certificate by making a request and inspecting the certificate.
    
    Args:
        url: HTTPS URL to test
        expected_hostname: Expected hostname in certificate (optional)
        verbose: Print detailed status (default: True)
    
    Returns:
        tuple: (problems: list, response_info: dict)
    """
    import ssl
    import socket
    from urllib.parse import urlparse
    
    problems = []
    response_info = {}
    
    parsed = urlparse(url)
    hostname = parsed.hostname
    port = parsed.port or 443
    
    try:
        # Create SSL context that verifies certificates
        context = ssl.create_default_context()
        
        # Connect and get certificate
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert = ssock.getpeercert()
                
                response_info['subject'] = dict(x[0] for x in cert.get('subject', []))
                response_info['issuer'] = dict(x[0] for x in cert.get('issuer', []))
                response_info['version'] = cert.get('version')
                response_info['notBefore'] = cert.get('notBefore')
                response_info['notAfter'] = cert.get('notAfter')
                response_info['subjectAltName'] = [name[1] for name in cert.get('subjectAltName', [])]
                
                if verbose:
                    logger.info(f"  HTTPS certificate for {hostname}:")
                    logger.info(f"    Issuer: {response_info['issuer'].get('organizationName', 'Unknown')}")
                    logger.info(f"    Valid until: {response_info['notAfter']}")
                    logger.info(f"    SANs: {', '.join(response_info['subjectAltName'])}")
                
                # Check if Let's Encrypt
                issuer_org = response_info['issuer'].get('organizationName', '')
                if 'Let\'s Encrypt' in issuer_org:
                    response_info['is_letsencrypt'] = True
                    if verbose:
                        logger.info(f"    ✓ Issued by Let's Encrypt")
                else:
                    response_info['is_letsencrypt'] = False
                
                # Check hostname
                if expected_hostname:
                    if expected_hostname in response_info['subjectAltName']:
                        if verbose:
                            logger.info(f"    ✓ Hostname '{expected_hostname}' in SANs")
                    else:
                        problems.append(
                            f"{hostname}: expected hostname '{expected_hostname}' "
                            f"not in SANs: {response_info['subjectAltName']}"
                        )
        
    except ssl.SSLError as e:
        problems.append(f"{hostname}: SSL error: {e}")
    except socket.timeout:
        problems.append(f"{hostname}: connection timeout")
    except Exception as e:
        problems.append(f"{hostname}: {type(e).__name__}: {e}")
    
    return problems, response_info


def validate_http_debug_app(url, expected_hostname, app_name=None, max_retries=3, retry_delays=None, verbose=True):
    """
    Validate http-https-echo application JSON response.
    
    Tests the mendhak/http-https-echo application that echoes request details as JSON.
    
    Args:
        url: HTTPS URL to test
        expected_hostname: Expected hostname in response
        app_name: App name for error messages (defaults to hostname)
        max_retries: Number of retry attempts (default: 3)
        retry_delays: List of delay seconds between retries (default: [10, 30, 60])
        verbose: Print detailed status (default: True)
    
    Returns:
        tuple: (problems: list, response_data: dict) - problems list is empty if valid
    """
    import requests
    import time
    
    if retry_delays is None:
        retry_delays = [10, 30, 60]
    
    if app_name is None:
        app_name = expected_hostname
    
    problems = []
    response_data = {}
    
    if verbose:
        logger.info(f"  Testing {app_name}")
        logger.info(f"    URL: {url}")
        logger.info(f"    Making HTTPS request (will retry up to {max_retries} times with backoff)...")
    
    # Retry logic with exponential backoff
    response = None
    last_error = None
    
    for attempt in range(max_retries):
        try:
            if verbose:
                logger.info(f"    Attempt {attempt + 1}/{max_retries}...")
            response = requests.get(url, timeout=30, verify=True)
            if verbose:
                logger.info(f"    ✓ HTTP {response.status_code}")
            last_error = None
            break  # Success, exit retry loop
        except requests.exceptions.RequestException as e:
            last_error = e
            if verbose:
                logger.info(f"    ✗ {type(e).__name__}: {str(e)[:100]}")
            if attempt < max_retries - 1:
                wait_time = retry_delays[attempt]
                if verbose:
                    logger.info(f"    Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
    
    # If all retries failed, record error and return
    if last_error:
        error_msg = f"Request failed after {max_retries} attempts: {last_error}"
        if verbose:
            logger.info(f"    ✗ {error_msg}")
        problems.append(f"{app_name}: {error_msg}")
        return problems, response_data
    
    # Check for successful response
    if response.status_code != 200:
        error_msg = f"Unexpected status code: HTTP {response.status_code}"
        if verbose:
            logger.info(f"    ✗ {error_msg}")
        problems.append(f"{app_name}: {error_msg}")
        return problems, response_data
    
    # Parse JSON response
    try:
        json_data = response.json()
        response_data = json_data
        if verbose:
            logger.info(f"    ✓ JSON parsed successfully")
    except ValueError as e:
        error_msg = f"Invalid JSON response: {e}"
        if verbose:
            logger.info(f"    ✗ {error_msg}")
        problems.append(f"{app_name}: {error_msg}")
        return problems, response_data
    
    # Validate required fields
    if verbose:
        logger.info(f"    Validating fields:")
    
    validations = {
        'x-scheme': ('headers', 'x-scheme', 'https'),
        'hostname': (None, 'hostname', expected_hostname),
        'method': (None, 'method', 'GET')
    }
    
    for field_name, (parent_key, json_key, expected_value) in validations.items():
        if parent_key:
            # Field is nested (e.g., headers.x-scheme)
            actual_value = json_data.get(parent_key, {}).get(json_key)
            display_key = f"{parent_key}.{json_key}"
        else:
            # Field is at root level
            actual_value = json_data.get(json_key)
            display_key = json_key
        
        if actual_value == expected_value:
            if verbose:
                logger.info(f"      ✓ {display_key}: {actual_value}")
        else:
            error_msg = f"{display_key}: expected '{expected_value}', got '{actual_value}'"
            if verbose:
                logger.info(f"      ✗ {error_msg}")
            problems.append(f"{app_name} - {error_msg}")
    
    if not problems and verbose:
        logger.info(f"    ✓ All validations passed")
    
    return problems, response_data


# High-level assertion helpers that combine validation + logging + test failure

def assert_argocd_healthy(custom_api, namespace_filter=None, verbose=True):
    """
    Validate ArgoCD apps and fail test if unhealthy.
    
    Wrapper around validate_all_argocd_apps that handles logging and test failure.
    """
    import pytest
    
    problems = validate_all_argocd_apps(custom_api, namespace_filter, verbose)
    
    if problems:
        _log_validation_failure("ARGOCD VALIDATION FAILED", problems)
        pytest.fail(f"\n❌ ArgoCD validation failed with {len(problems)} error(s)")


def assert_pods_healthy(core_v1, platform_namespaces, verbose=True):
    """
    Validate pod health and fail test if unhealthy.
    
    Wrapper around validate_pod_health that handles logging and test failure.
    """
    import pytest
    
    problems = validate_pod_health(core_v1, platform_namespaces, verbose)
    
    if problems:
        _log_validation_failure("POD HEALTH VALIDATION FAILED", problems)
        pytest.fail(f"\n❌ Pod health validation failed with {len(problems)} error(s)")


def assert_ingress_valid(networking_v1, platform_namespaces, verbose=True):
    """
    Validate ingress configuration and fail test if invalid.
    
    Wrapper around validate_ingress_configuration that handles logging and test failure.
    
    Returns:
        int: Total number of ingresses checked
    """
    import pytest
    
    problems, total_ingresses = validate_ingress_configuration(networking_v1, platform_namespaces, verbose)
    
    if problems:
        _log_validation_failure("INGRESS CONFIGURATION VALIDATION FAILED", problems)
        pytest.fail(f"\n❌ Ingress configuration validation failed with {len(problems)} error(s)")
    
    return total_ingresses


def assert_ingress_dns_valid(networking_v1, platform_namespaces, dns_server='1.1.1.1', verbose=True):
    """
    Validate ingress DNS resolution and fail test if invalid.
    
    Wrapper around validate_ingress_dns that handles logging and test failure.
    
    Returns:
        int: Number of hosts checked
    """
    import pytest
    
    problems, checked_count = validate_ingress_dns(networking_v1, platform_namespaces, dns_server, verbose)
    
    if problems:
        _log_validation_failure("DNS RESOLUTION VALIDATION FAILED", problems)
        pytest.fail(f"\n❌ DNS validation failed with {len(problems)} error(s)")
    
    return checked_count


def assert_certificates_ready(custom_api, cert_info_list, namespace='nonprod', timeout=600, poll_interval=10, verbose=True):
    """
    Wait for multiple certificates to be ready and fail test if any fail.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        cert_info_list: List of dicts with 'name' and 'cert_name' keys
        namespace: Namespace of certificates (default: 'nonprod')
        timeout: Max wait time per certificate (default: 600s)
        poll_interval: Time between checks (default: 10s)
        verbose: Print status updates (default: True)
    
    Returns:
        list: List of certificate statuses
    """
    import pytest
    
    problems = []
    statuses = []
    
    for idx, app in enumerate(cert_info_list, 1):
        if verbose:
            logger.info(f"[{idx}/{len(cert_info_list)}] Waiting for certificate: {app['name']}")
            logger.info(f"      Hostname: {app.get('hostname', 'N/A')}")
            logger.info(f"      Namespace: {namespace}")
        
        success, status = wait_for_certificate_ready(
            custom_api,
            cert_name=app['cert_name'],
            namespace=namespace,
            timeout=timeout,
            poll_interval=poll_interval,
            verbose=verbose
        )
        
        statuses.append(status)
        
        if not success:
            error_msg = f"{app['name']}: Certificate not ready after {timeout}s"
            if verbose:
                logger.info(f"      ✗ {error_msg}\n")
            problems.append(error_msg)
        else:
            if verbose:
                logger.info(f"      ✓ Certificate is Ready!\n")
    
    if problems:
        _log_validation_failure("CERTIFICATE ISSUANCE FAILED", problems)
        pytest.fail(f"\n❌ Certificate validation failed with {len(problems)} error(s)")
    
    return statuses


def assert_tls_secrets_valid(core_v1, secret_info_list, namespace='nonprod', verbose=True):
    """
    Validate multiple TLS secrets and fail test if any are invalid.
    
    Args:
        core_v1: Kubernetes CoreV1Api client
        secret_info_list: List of dicts with 'name', 'secret_name', and 'hostname' keys
        namespace: Namespace of secrets (default: 'nonprod')
        verbose: Print status updates (default: True)
    
    Returns:
        list: List of certificate info dicts
    """
    import pytest
    
    all_problems = []
    cert_infos = []
    
    for idx, app in enumerate(secret_info_list, 1):
        if verbose:
            logger.info(f"[{idx}/{len(secret_info_list)}] Validating TLS secret: {app['secret_name']}")
            logger.info(f"      Hostname: {app['hostname']}")
        
        problems, cert_info = validate_certificate_secret(
            core_v1,
            secret_name=app['secret_name'],
            namespace=namespace,
            expected_hostname=app['hostname'],
            verbose=verbose
        )
        
        if problems:
            if verbose:
                logger.info(f"      ✗ Secret validation failed")
            all_problems.extend(problems)
        else:
            if verbose:
                logger.info(f"      ✓ TLS secret is valid")
            cert_infos.append(cert_info)
        
        if verbose:
            logger.info("")
    
    if all_problems:
        _log_validation_failure("TLS SECRET VALIDATION FAILED", all_problems)
        pytest.fail(f"\n❌ TLS secret validation failed with {len(all_problems)} error(s)")
    
    return cert_infos


def assert_https_endpoints_valid(endpoint_info_list, validate_cert=True, validate_app=False, verbose=True):
    """
    Validate multiple HTTPS endpoints and fail test if any are invalid.
    
    Args:
        endpoint_info_list: List of dicts with 'name', 'hostname', and 'url' keys
        validate_cert: Whether to validate HTTPS certificate (default: True)
        validate_app: Whether to validate http-debug app response (default: False)
        verbose: Print status updates (default: True)
    """
    import pytest
    import requests
    
    all_problems = []
    
    for idx, app in enumerate(endpoint_info_list, 1):
        app_name = app['name']
        hostname = app['hostname']
        url = app['url']
        
        if verbose:
            logger.info(f"[{idx}/{len(endpoint_info_list)}] {app_name}")
            logger.info(f"      URL: {url}")
        
        # Validate HTTPS certificate if requested
        if validate_cert:
            if verbose:
                logger.info(f"      Testing HTTPS certificate...")
            
            cert_problems, response_info = validate_https_certificate(
                url=url,
                expected_hostname=hostname,
                verbose=verbose
            )
            
            if cert_problems:
                if verbose:
                    logger.info(f"      ✗ HTTPS certificate validation failed")
                all_problems.extend([f"{app_name}: {p}" for p in cert_problems])
            else:
                if verbose:
                    logger.info(f"      ✓ HTTPS certificate is valid")
        
        # Validate http-debug app if requested
        if validate_app:
            app_problems, response_data = validate_http_debug_app(
                url=url,
                expected_hostname=hostname,
                app_name=app_name,
                verbose=verbose
            )
            
            if app_problems:
                all_problems.extend(app_problems)
        else:
            # Just make a basic HTTP request to verify endpoint works
            if verbose:
                logger.info(f"      Making HTTPS request...")
            try:
                response = requests.get(url, timeout=30, verify=True)
                if response.status_code == 200:
                    if verbose:
                        logger.info(f"      ✓ HTTP {response.status_code} - Application responding")
                else:
                    error_msg = f"Unexpected status code: HTTP {response.status_code}"
                    if verbose:
                        logger.info(f"      ✗ {error_msg}")
                    all_problems.append(f"{app_name}: {error_msg}")
            except requests.exceptions.SSLError as e:
                error_msg = f"SSL error: {e}"
                if verbose:
                    logger.info(f"      ✗ {error_msg}")
                all_problems.append(f"{app_name}: {error_msg}")
            except Exception as e:
                error_msg = f"Request failed: {e}"
                if verbose:
                    logger.info(f"      ✗ {error_msg}")
                all_problems.append(f"{app_name}: {error_msg}")
        
        if verbose:
            logger.info("")
    
    if all_problems:
        _log_validation_failure("HTTPS VALIDATION FAILED", all_problems)
        pytest.fail(f"\n❌ HTTPS validation failed with {len(all_problems)} error(s)")
