"""
Pytest-specific assertion helpers.

These functions wrap validation functions and call pytest.fail() on errors.
This separation keeps the validation logic pure (no pytest dependency) while
providing convenient test assertions.
"""
import pytest
import logging

from tests.helpers.k8s import (
    validate_all_argocd_apps,
    validate_pod_health,
    validate_ingress_configuration,
    validate_ingress_dns,
    validate_certificate_secret,
    validate_https_certificate,
    validate_http_debug_app,
    wait_for_certificate_ready,
)

logger = logging.getLogger(__name__)


def _log_validation_failure(failure_title, problems, max_display=10):
    """
    Helper to log validation failures with consistent formatting.
    
    Args:
        failure_title: Title for the failure section
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


def assert_argocd_healthy(custom_api, namespace_filter=None):
    """
    Validate ArgoCD apps and fail test if unhealthy.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        namespace_filter: Optional namespace filter
    
    Raises:
        pytest.fail: If any ArgoCD application is unhealthy
    """
    logger.info(f"\n🔍 Validating ArgoCD applications...\n")
    
    problems = validate_all_argocd_apps(custom_api, namespace_filter)
    
    if problems:
        _log_validation_failure("ARGOCD VALIDATION FAILED", problems)
        pytest.fail(f"\n❌ ArgoCD validation failed with {len(problems)} error(s)")
    
    logger.info(f"\n✓ All ArgoCD applications are Healthy and Synced")


def assert_pods_healthy(core_v1, platform_namespaces):
    """
    Validate pod health and fail test if unhealthy.
    
    Args:
        core_v1: Kubernetes CoreV1Api client
        platform_namespaces: List of namespaces to check
    
    Raises:
        pytest.fail: If any pod is unhealthy
    """
    logger.info(f"\n🔍 Validating pod health across platform namespaces...\n")
    
    problems = validate_pod_health(core_v1, platform_namespaces)
    
    if problems:
        _log_validation_failure("POD HEALTH VALIDATION FAILED", problems)
        pytest.fail(f"\n❌ Pod health validation failed with {len(problems)} error(s)")
    
    logger.info(f"\n✓ All pods are healthy")


def assert_ingress_valid(networking_v1, platform_namespaces):
    """
    Validate ingress configuration and fail test if invalid.
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        platform_namespaces: List of namespaces to check
    
    Returns:
        int: Total number of ingresses checked
    
    Raises:
        pytest.fail: If any ingress is invalid
    """
    logger.info(f"\n🔍 Checking Ingress resources across platform...\n")
    
    problems, total_ingresses = validate_ingress_configuration(networking_v1, platform_namespaces)
    
    if problems:
        _log_validation_failure("INGRESS CONFIGURATION VALIDATION FAILED", problems)
        pytest.fail(f"\n❌ Ingress configuration validation failed with {len(problems)} error(s)")
    
    logger.info(f"\n✓ All {total_ingresses} Ingress resources are properly configured")
    
    return total_ingresses


def assert_ingress_dns_valid(networking_v1, platform_namespaces, dns_server='1.1.1.1'):
    """
    Validate ingress DNS resolution and fail test if invalid.
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        platform_namespaces: List of namespaces to check
        dns_server: DNS server to query (default: '1.1.1.1')
    
    Returns:
        int: Number of hosts checked
    
    Raises:
        pytest.fail: If any DNS resolution fails
    """
    logger.info(f"\n🔍 Checking DNS resolution for all Ingress hosts...\n")
    
    problems, checked_count = validate_ingress_dns(networking_v1, platform_namespaces, dns_server)
    
    if problems:
        _log_validation_failure("DNS RESOLUTION VALIDATION FAILED", problems)
        pytest.fail(f"\n❌ DNS validation failed with {len(problems)} error(s)")
    
    logger.info(f"\n✓ All {checked_count} Ingress hosts resolve correctly via DNS")
    
    return checked_count


def assert_certificates_ready(custom_api, cert_info_list, namespace='nonprod'):
    """
    Wait for multiple certificates to be ready and fail test if any fail.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        cert_info_list: List of dicts with 'name' and 'cert_name' keys
        namespace: Namespace of certificates (default: 'nonprod')
    
    Returns:
        list: List of certificate statuses
    
    Raises:
        pytest.fail: If any certificate fails to become ready
    """
    logger.info(f"\n🔍 Waiting for {len(cert_info_list)} certificate(s) to be issued...\n")
    
    problems = []
    statuses = []
    
    for idx, app in enumerate(cert_info_list, 1):
        logger.info(f"[{idx}/{len(cert_info_list)}] Waiting for certificate: {app['name']}")
        logger.info(f"      Hostname: {app.get('hostname', 'N/A')}")
        logger.info(f"      Namespace: {namespace}")
        
        success, status = wait_for_certificate_ready(
            custom_api,
            cert_name=app['cert_name'],
            namespace=namespace
        )
        
        statuses.append(status)
        
        if not success:
            # Use detailed_error from status if available
            detailed = status.get('detailed_error', 'Certificate not ready after timeout')
            error_msg = f"{app['name']}: {detailed}"
            logger.info(f"      ✗ Failed\n")
            problems.append(error_msg)
        else:
            logger.info(f"      ✓ Certificate is Ready!\n")
    
    if problems:
        _log_validation_failure("CERTIFICATE ISSUANCE FAILED", problems)
        pytest.fail(f"\n❌ Certificate validation failed with {len(problems)} error(s)")
    
    logger.info(f"\n✓ All {len(cert_info_list)} certificates issued successfully")
    
    return statuses


def assert_tls_secrets_valid(core_v1, secret_info_list, namespace='nonprod'):
    """
    Validate multiple TLS secrets and fail test if any are invalid.
    
    Args:
        core_v1: Kubernetes CoreV1Api client
        secret_info_list: List of dicts with 'name', 'secret_name', and 'hostname' keys
        namespace: Namespace of secrets (default: 'nonprod')
    
    Returns:
        list: List of certificate info dicts
    
    Raises:
        pytest.fail: If any TLS secret is invalid
    """
    logger.info(f"\n🔍 Validating {len(secret_info_list)} TLS secret(s)...\n")
    
    all_problems = []
    cert_infos = []
    
    for idx, app in enumerate(secret_info_list, 1):
        logger.info(f"[{idx}/{len(secret_info_list)}] Validating TLS secret: {app['secret_name']}")
        logger.info(f"      Hostname: {app['hostname']}")
        
        problems, cert_info = validate_certificate_secret(
            core_v1,
            secret_name=app['secret_name'],
            namespace=namespace,
            expected_hostname=app['hostname']
        )
        
        if problems:
            logger.info(f"      ✗ Secret validation failed")
            all_problems.extend(problems)
        else:
            logger.info(f"      ✓ TLS secret is valid")
            cert_infos.append(cert_info)
        
        logger.info("")
    
    if all_problems:
        _log_validation_failure("TLS SECRET VALIDATION FAILED", all_problems)
        pytest.fail(f"\n❌ TLS secret validation failed with {len(all_problems)} error(s)")
    
    logger.info(f"\n✓ All {len(secret_info_list)} TLS secrets are valid")
    
    return cert_infos


def assert_https_endpoints_valid(endpoint_info_list, validate_cert=True, validate_app=False):
    """
    Validate multiple HTTPS endpoints and fail test if any are invalid.
    
    Args:
        endpoint_info_list: List of dicts with 'name', 'hostname', and 'url' keys
        validate_cert: Whether to validate HTTPS certificate (default: True)
        validate_app: Whether to validate http-debug app response (default: False)
    
    Raises:
        pytest.fail: If any HTTPS endpoint validation fails
    """
    import requests
    
    logger.info(f"\n🔍 Testing {len(endpoint_info_list)} HTTPS endpoint(s)...\n")
    
    all_problems = []
    
    for idx, app in enumerate(endpoint_info_list, 1):
        app_name = app['name']
        hostname = app['hostname']
        url = app['url']
        
        logger.info(f"[{idx}/{len(endpoint_info_list)}] {app_name}")
        logger.info(f"      URL: {url}")
        
        # Validate HTTPS certificate if requested
        if validate_cert:
            logger.info(f"      Testing HTTPS certificate...")
            
            cert_problems, response_info = validate_https_certificate(
                url=url,
                expected_hostname=hostname
            )
            
            if cert_problems:
                logger.info(f"      ✗ HTTPS certificate validation failed")
                all_problems.extend([f"{app_name}: {p}" for p in cert_problems])
            else:
                logger.info(f"      ✓ HTTPS certificate is valid")
        
        # Validate http-debug app if requested
        if validate_app:
            app_problems, response_data = validate_http_debug_app(
                url=url,
                expected_hostname=hostname,
                app_name=app_name
            )
            
            if app_problems:
                all_problems.extend(app_problems)
        else:
            # Just make a basic HTTP request to verify endpoint works
            logger.info(f"      Making HTTPS request...")
            try:
                response = requests.get(url, timeout=30, verify=True)
                if response.status_code == 200:
                    logger.info(f"      ✓ HTTP {response.status_code} - Application responding")
                else:
                    error_msg = f"Unexpected status code: HTTP {response.status_code}"
                    logger.info(f"      ✗ {error_msg}")
                    all_problems.append(f"{app_name}: {error_msg}")
            except requests.exceptions.SSLError as e:
                error_msg = f"SSL error: {e}"
                logger.info(f"      ✗ {error_msg}")
                all_problems.append(f"{app_name}: {error_msg}")
            except Exception as e:
                error_msg = f"Request failed: {e}"
                logger.info(f"      ✗ {error_msg}")
                all_problems.append(f"{app_name}: {error_msg}")
        
        logger.info("")
    
    logger.info(f"\n✓ All {len(endpoint_info_list)} HTTPS endpoints are working")
    
    if all_problems:
        _log_validation_failure("HTTPS VALIDATION FAILED", all_problems)
        pytest.fail(f"\n❌ HTTPS validation failed with {len(all_problems)} error(s)")
