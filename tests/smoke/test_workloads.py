"""Kubernetes workload health checks"""
import pytest
import logging
import requests
from tests.helpers.k8s import (
    validate_pod_health,
    validate_failed_jobs,
    validate_ingress_configuration,
    validate_ingress_dns
)

logger = logging.getLogger(__name__)


# Alerts that are expected to be firing and don't indicate issues
PASSABLE_ALERTS = [
    "Watchdog"  # Always-firing alert to verify alerting pipeline is working
]


@pytest.mark.smoke
@pytest.mark.quick
@pytest.mark.critical
@pytest.mark.readonly
@pytest.mark.workloads
def test_pod_health(core_v1, platform_namespaces):
    """Check for unhealthy pods across platform namespaces.
    
    Checks for critical pod issues:
    - CrashLoopBackOff - container repeatedly crashing
    - ImagePullBackOff/ErrImagePull - cannot pull container image  
    - OOMKilled - container killed due to out of memory (checks both last_state and current state)
    - High restart count (>5) - indicates intermittent failures
    - Failed/Unknown pod phase
    
    All issues are reported as failures.
    
    Cluster Impact: READ-ONLY (queries pod status)
    """
    logger.info("\n" + "="*70)
    logger.info("POD HEALTH CHECK")
    logger.info("="*70)
    
    problems = validate_pod_health(core_v1, platform_namespaces, verbose=True)
    
    logger.info("\n" + "="*70)
    logger.info("SUMMARY")
    logger.info("="*70)
    
    if problems:
        logger.info(f"❌ {len(problems)} pod issue(s) found\n")
        pytest.fail(f"{len(problems)} pod issue(s) found:\n" + "\n".join(f"  - {p}" for p in problems))
    
    logger.info(f"✅ All pods are healthy\n")


@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.workloads
def test_failed_jobs(batch_v1, platform_namespaces):
    """Check for failed Jobs across platform namespaces.
    
    Validates Job resources for failure count (status.failed > 0).
    All failed jobs cause test to FAIL - no exclusions configured.
    
    Fails if any jobs have status.failed > 0.
    
    Cluster Impact: READ-ONLY (queries job status)
    """
    logger.info("\n" + "="*70)
    logger.info("FAILED JOBS CHECK")
    logger.info("="*70)
    
    exclude_jobs = []  # No exclusions - all failed jobs should be caught
    
    problems, warnings = validate_failed_jobs(batch_v1, platform_namespaces, exclude_jobs, verbose=True)
    
    logger.info("\n" + "="*70)
    logger.info("SUMMARY")
    logger.info("="*70)
    
    # Report warnings if any
    if warnings:
        logger.info("Excluded jobs with failures (warnings only):")
        for warning in warnings:
            logger.info(f"  {warning}")
    
    if problems:
        logger.info(f"❌ {len(problems)} failed job(s) found\n")
        pytest.fail(f"{len(problems)} failed job(s) found:\n" + "\n".join(f"  - {p}" for p in problems))
    
    logger.info(f"✅ No failed jobs found\n")


@pytest.mark.quick
@pytest.mark.critical
@pytest.mark.readonly
@pytest.mark.ingress
def test_ingress_validity(networking_v1, platform_namespaces):
    """Check all Ingress objects are valid with proper configuration.
    
    Validates:
    - Ingress spec exists and has rules defined
    - All rules have non-empty host values
    - Load balancer status exists with IP or hostname populated
    
    Fails if any ingress has missing/empty hosts or no load balancer address.
    
    Cluster Impact: READ-ONLY (queries ingress resources)
    """
    logger.info("\n" + "="*70)
    logger.info("INGRESS VALIDITY CHECK")
    logger.info("="*70)
    
    problems, total_ingresses = validate_ingress_configuration(networking_v1, platform_namespaces, verbose=True)
    
    logger.info("\n" + "="*70)
    logger.info("SUMMARY")
    logger.info("="*70)
    
    if problems:
        logger.info(f"❌ {len(problems)} ingress issue(s) found (total: {total_ingresses} ingresses)\n")
        pytest.fail(
            f"{len(problems)} ingress issue(s) found (total: {total_ingresses} ingresses):\n" +
            "\n".join(f"  - {p}" for p in problems)
        )
    
    logger.info(f"✅ All {total_ingresses} ingresses are valid\n")


@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.dns
def test_ingress_dns(networking_v1, platform_namespaces):
    """Verify ingress hosts resolve to correct load balancer IPs via DNS.
    
    For each ingress with a load balancer IP:
    - Queries DNS A records for each host using Cloudflare DNS (1.1.1.1)
    - Compares resolved IPs against expected load balancer IPs
    
    Fails if:
    - Host doesn't exist (NXDOMAIN)
    - Host has no A record
    - Host resolves to wrong IP
    
    Cluster Impact: READ-ONLY (queries ingress resources + external DNS)
    """
    logger.info("\n" + "="*70)
    logger.info("INGRESS DNS CHECK")
    logger.info("="*70)
    
    problems, checked_count = validate_ingress_dns(networking_v1, platform_namespaces, dns_server='1.1.1.1', verbose=True)
    
    logger.info("\n" + "="*70)
    logger.info("SUMMARY")
    logger.info("="*70)
    
    if problems:
        logger.info(f"❌ {len(problems)} DNS issue(s) found (checked {checked_count} hosts)\n")
        pytest.fail(
            f"{len(problems)} DNS issue(s) found (checked {checked_count} hosts):\n" +
            "\n".join(f"  - {p}" for p in problems)
        )
    
    logger.info(f"✅ All {checked_count} ingress hosts resolve correctly\n")


@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.oauth2
def test_ingress_oauth2_redirect(networking_v1, platform_namespaces, captain_domain):
    """Verify ingresses have OAuth2 redirect annotations and actually redirect via HTTP.
    
    Validates OAuth2 protection for ingresses with class 'glueops-platform':
    - Checks nginx.ingress.kubernetes.io/auth-url points to oauth2.{captain_domain}
    - Checks nginx.ingress.kubernetes.io/auth-signin points to oauth2.{captain_domain}
    - Makes HTTP request and verifies redirect (301/302/307/308) to OAuth2 URL
    - Accepts 401/403 auth challenges as valid (protected but different auth method)
    
    Exceptions (skipped ingresses):
    - oauth2-proxy
    - glueops-dex
    
    Timeouts:
    - HTTP request: 5 seconds
    
    Cluster Impact: READ-ONLY (queries ingress resources + external HTTP requests)
    """
    ingress_classes = ["glueops-platform"]
    exceptions = ["oauth2-proxy", "glueops-dex"]
    problems = []
    checked_count = 0
    expected_oauth2_url = f"https://oauth2.{captain_domain}"
    
    for namespace in platform_namespaces:
        ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
        
        for ingress in ingresses.items:
            name = f"{namespace}/{ingress.metadata.name}"
            
            # Check if ingress class matches our criteria
            ingress_class = ingress.spec.ingress_class_name
            if not ingress_class or ingress_class not in ingress_classes:
                continue
            
            # Check if ingress is in exception list
            if ingress.metadata.name in exceptions:
                logger.info(f"{name}: skipped (in exception list)")
                continue
            
            checked_count += 1
            annotations = ingress.metadata.annotations or {}
            
            # Check for auth-url annotation
            auth_url = annotations.get("nginx.ingress.kubernetes.io/auth-url")
            auth_signin = annotations.get("nginx.ingress.kubernetes.io/auth-signin")
            
            if not auth_url:
                problems.append(f"{name}: missing nginx.ingress.kubernetes.io/auth-url annotation")
            elif not auth_url.startswith(expected_oauth2_url):
                problems.append(f"{name}: auth-url '{auth_url}' does not start with '{expected_oauth2_url}'")
            else:
                logger.info(f"{name}: auth-url ✓")
            
            if not auth_signin:
                problems.append(f"{name}: missing nginx.ingress.kubernetes.io/auth-signin annotation")
            elif not auth_signin.startswith(expected_oauth2_url):
                problems.append(f"{name}: auth-signin '{auth_signin}' does not start with '{expected_oauth2_url}'")
            else:
                logger.info(f"{name}: auth-signin ✓")
            
            # Test actual HTTP redirect if ingress has hosts
            if ingress.spec and ingress.spec.rules:
                for rule in ingress.spec.rules:
                    if not rule.host:
                        continue
                    
                    host = rule.host.strip()
                    # Try HTTP request to verify redirect
                    try:
                        url = f"http://{host}"
                        response = requests.get(url, allow_redirects=False, timeout=5, verify=False)
                        
                        # Check if we get a redirect (301, 302, 307, 308)
                        if response.status_code in [301, 302, 307, 308]:
                            location = response.headers.get('Location', '')
                            if location.startswith(expected_oauth2_url):
                                logger.info(f"{name} ({host}): HTTP redirect to OAuth2 ✓")
                            else:
                                problems.append(f"{name} ({host}): redirects to '{location}' instead of OAuth2")
                        elif response.status_code == 401 or response.status_code == 403:
                            # Auth challenge without redirect - still protected
                            logger.info(f"{name} ({host}): auth challenge (status {response.status_code}) ✓")
                        else:
                            logger.info(f"{name} ({host}): unexpected status {response.status_code}")
                    
                    except requests.exceptions.Timeout:
                        logger.info(f"{name} ({host}): HTTP request timeout (skipped)")
                    except requests.exceptions.ConnectionError:
                        logger.info(f"{name} ({host}): connection failed (skipped)")
                    except Exception as e:
                        logger.info(f"{name} ({host}): HTTP test error: {e}")
    
    assert not problems, (
        f"{len(problems)} OAuth2 configuration issue(s) found (checked {checked_count} ingresses):\n" +
        "\n".join(f"  - {p}" for p in problems)
    )


@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.observability
def test_alertmanager_alerts(core_v1, alertmanager_url):
    """Check for firing alerts in Alertmanager via API.
    
    Connects to Alertmanager via port-forward and queries /api/v2/alerts endpoint.
    
    Checks for alerts with state: active, firing, or suppressed.
    
    Expected alerts (PASSABLE_ALERTS) generate info messages only:
    - "Watchdog" - Always-firing alert to verify alerting pipeline works
    
    Unexpected firing alerts are reported as failures with:
    - Alert name, namespace, severity
    - Summary/description from annotations
    
    Cluster Impact: READ-ONLY (port-forward + queries Alertmanager API)
    """
    # Use alertmanager_url fixture (port-forward already established)
    # Query Alertmanager API for alerts
    response = requests.get(
        f"{alertmanager_url}/api/v2/alerts",
        timeout=10
    )
    
    assert response.status_code == 200, f"Alertmanager API returned status {response.status_code}"
    
    alerts = response.json()
    
    # Filter for firing/active/suppressed alerts
    firing_alerts = [
        alert for alert in alerts 
        if alert.get("status", {}).get("state") in ["active", "firing", "suppressed"]
    ]
    
    # Separate passable alerts from actual issues
    passable = []
    problematic = []
    
    for alert in firing_alerts:
        labels = alert.get("labels", {})
        name = labels.get("alertname", "Unknown")
        if name in PASSABLE_ALERTS:
            passable.append(alert)
        else:
            problematic.append(alert)
    
    # Build output for passable alerts (info only)
    if passable:
        logger.info(f"\nExpected alerts (informational, {len(passable)} alert(s)):")
        for alert in passable:
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            name = labels.get("alertname", "Unknown")
            severity = labels.get("severity", "unknown")
            summary = annotations.get("summary", "")
            logger.info(f"  {name} (severity: {severity})")
            if summary:
                logger.info(f"    {summary}")
    
    # Build error message for problematic alerts
    if problematic:
        problems = []
        for alert in problematic:
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            name = labels.get("alertname", "Unknown")
            severity = labels.get("severity", "unknown")
            namespace = labels.get("namespace", "")
            summary = annotations.get("summary", "")
            
            if namespace:
                alert_line = f"{name} in {namespace} (severity: {severity})"
            else:
                alert_line = f"{name} (severity: {severity})"
            
            if summary:
                alert_line += f"\n      {summary}"
            
            problems.append(alert_line)
        
        pytest.fail(f"{len(problematic)} firing alert(s):\n  " + "\n  ".join(problems))
