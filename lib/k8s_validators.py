"""Low-level Kubernetes validation functions that return problems lists."""
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


def validate_all_argocd_apps(custom_api, namespace_filter=None, verbose=True):
    """
    Check all ArgoCD applications for health and sync status.
    
    Returns list of problem descriptions (empty list if all healthy).
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


def validate_pod_health(core_v1, platform_namespaces, verbose=True):
    """
    Check pod health across platform namespaces.
    
    Returns list of problem descriptions (empty list if all healthy).
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
            elif verbose:
                healthy_pods += 1
    
    if verbose:
        if problems:
            logger.info(f"  {healthy_pods}/{total_pods} pods healthy")
        else:
            logger.info(f"  All {total_pods} pods healthy")
    
    return problems


def validate_failed_jobs(batch_v1, platform_namespaces, exclude_jobs=None, verbose=True):
    """
    Check for failed Jobs across platform namespaces.
    
    Returns tuple of (problems, warnings) where:
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
            
            # Check job conditions for actual status (more reliable than counts)
            # Jobs can have failed pod attempts but still succeed overall
            is_failed = False
            is_complete = False
            
            if job.status.conditions:
                for condition in job.status.conditions:
                    if condition.type == 'Failed' and condition.status == 'True':
                        is_failed = True
                    if condition.type == 'Complete' and condition.status == 'True':
                        is_complete = True
            
            # Only report jobs that are truly failed (not complete and marked as failed)
            # OR jobs with failures that haven't completed yet
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


def validate_ingress_configuration(networking_v1, platform_namespaces, verbose=True):
    """
    Validate Ingress resources have proper configuration.
    
    Returns tuple of (problems, total_ingresses).
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
    
    Returns tuple of (problems, checked_count).
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


def validate_certificate_secret(core_v1, secret_name, namespace, expected_hostname=None, verbose=True):
    """
    Validate TLS secret contains valid certificate.
    
    Returns tuple of (problems, cert_info_dict).
    """
    problems = []
    cert_info = {}
    
    try:
        secret = core_v1.read_namespaced_secret(secret_name, namespace)
        
        if not secret.data or 'tls.crt' not in secret.data:
            problems.append(f"Secret {namespace}/{secret_name}: Missing tls.crt")
            return problems, cert_info
        
        # Decode and parse certificate
        import base64
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
    
    Returns tuple of (problems, response_info).
    """
    problems = []
    response_info = {}
    
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port or 443
        
        # Create SSL context
        context = ssl.create_default_context()
        
        # Connect and get certificate
        with socket.create_connection((hostname, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=hostname) as ssock:
                cert_der = ssock.getpeercert(binary_form=True)
                cert = x509.load_der_x509_certificate(cert_der, default_backend())
                
                # Extract certificate info
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
                
                # Validate hostname
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


def validate_http_debug_app(url, expected_hostname, app_name=None, max_retries=3, retry_delays=None, verbose=True):
    """
    Validate mendhak/http-https-echo application response.
    
    Returns tuple of (problems, response_data).
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
            
            # Success - exit retry loop
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
    
    Makes GET request to {url}?env=true and validates that expected environment
    variables appear in the text response with correct values.
    
    Args:
        url: Application URL (e.g., "https://myapp.example.com")
        expected_env_vars: Dict of env var names to expected values
        app_name: Application name for logging
        max_retries: Maximum number of retry attempts
        retry_delays: List of delays (seconds) between retries
        verbose: Enable detailed logging
    
    Returns:
        Tuple of (problems_list, env_vars_dict)
        - problems_list: List of validation error strings (empty if all valid)
        - env_vars_dict: Dict of all environment variables found in response
    """
    if retry_delays is None:
        retry_delays = [10, 30, 60]
    
    problems = []
    
    # Ensure we have enough retry delays
    while len(retry_delays) < max_retries - 1:
        retry_delays.append(retry_delays[-1] if retry_delays else 30)
    
    for attempt in range(1, max_retries + 1):
        try:
            if verbose and attempt > 1:
                logger.info(f"      Retry {attempt}/{max_retries}...")
            
            # Make request with ?env=true parameter
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
            
            # Parse text response - env vars appear after blank line at the end
            text = response.text
            if verbose:
                logger.info(f"      ✓ Response received, parsing environment variables...")
            
            # Find environment variables section (after headers, separated by blank line)
            lines = text.split('\n')
            env_vars = {}
            
            # Skip to the environment variables section (after blank line)
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
            
            # Validate expected environment variables
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
