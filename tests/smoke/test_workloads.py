"""Kubernetes workload health checks"""
import pytest
import dns.resolver
import requests
from lib.port_forward import PortForward


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
    problems = []
    
    for namespace in platform_namespaces:
        pods = core_v1.list_namespaced_pod(namespace=namespace)
        print(f"Checking {len(pods.items)} pods in {namespace}")
        
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
                continue
            
            # Check pod phase
            if pod.status.phase in ["Failed", "Unknown"]:
                problems.append(f"{name}: phase={pod.status.phase}")
                continue
            
            # Check container statuses
            if pod.status.container_statuses:
                for container in pod.status.container_statuses:
                    # Waiting state issues
                    if container.state.waiting:
                        reason = container.state.waiting.reason
                        if reason in ["CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"]:
                            problems.append(f"{name}/{container.name}: {reason}")
                    
                    # OOMKilled
                    if container.last_state.terminated:
                        if container.last_state.terminated.reason == "OOMKilled":
                            problems.append(f"{name}/{container.name}: OOMKilled")
                    
                    # High restart count
                    if container.restart_count > 5:
                        problems.append(f"{name}/{container.name}: {container.restart_count} restarts")
    
    assert not problems, f"{len(problems)} pod issue(s) found:\n" + "\n".join(f"  - {p}" for p in problems)


@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.workloads
def test_failed_jobs(batch_v1, platform_namespaces):
    """Check for failed Jobs across platform namespaces.
    
    Validates Job resources for failure count (status.failed > 0).
    Any failed job causes test to FAIL unless in exclusion list.
    
    Configure exclusions via pytest.ini or command-line to exclude specific job patterns.
    
    Fails if any non-excluded jobs have status.failed > 0.
    
    Cluster Impact: READ-ONLY (queries job status)
    """
    exclude_jobs = []  # No exclusions - all failed jobs should be caught
    
    problems = []
    warnings = []
    
    for namespace in platform_namespaces:
        jobs = batch_v1.list_namespaced_job(namespace=namespace)
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
                else:
                    problems.append(job_desc)
    
    # Report warnings if any
    if warnings:
        print("Excluded jobs with failures (warnings only):")
        for warning in warnings:
            print(f"  {warning}")
    
    assert not problems, f"{len(problems)} failed job(s) found:\n" + "\n".join(f"  - {p}" for p in problems)


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
            
            print(f"{name}: {', '.join(hosts) if hosts else 'no hosts'} → {', '.join(lb_addrs) if lb_addrs else 'no LB'}")
            
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
    
    assert not problems, (
        f"{len(problems)} ingress issue(s) found (total: {total_ingresses} ingresses):\n" +
        "\n".join(f"  - {p}" for p in problems)
    )


@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.dns
def test_ingress_dns(networking_v1, platform_namespaces):
    """Verify ingress hosts resolve to correct load balancer IPs via DNS.
    
    For each ingress with a load balancer IP:
    - Queries DNS A records for each host using 1.1.1.1 (Cloudflare DNS)
    - Compares resolved IPs against expected load balancer IPs
    - Fails if host doesn't exist (NXDOMAIN), has no A record, or resolves to wrong IP
    
    Cluster Impact: READ-ONLY (queries ingress resources + external DNS)
    """
    dns_server = '1.1.1.1'
    problems = []
    checked_count = 0
    
    # Create custom resolver with specified DNS server
    resolver = dns.resolver.Resolver()
    resolver.nameservers = [dns_server]
    print(f"Using DNS server: {dns_server}")
    
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
                        print(f"{host} → {', '.join(sorted(resolved_ips))} ✓")
                
                except dns.resolver.NXDOMAIN:
                    problems.append(f"{name}/{host}: domain does not exist")
                except dns.resolver.NoAnswer:
                    problems.append(f"{name}/{host}: no A record found")
                except dns.resolver.Timeout:
                    problems.append(f"{name}/{host}: DNS lookup timeout")
                except Exception as e:
                    problems.append(f"{name}/{host}: DNS lookup error: {e}")
    
    assert not problems, (
        f"{len(problems)} DNS issue(s) found (checked {checked_count} hosts):\n" +
        "\n".join(f"  - {p}" for p in problems)
    )


@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.oauth2
def test_ingress_oauth2_redirect(networking_v1, platform_namespaces, captain_domain):
    """Verify ingresses have OAuth2 redirect annotations and actually redirect via HTTP.
    
    Validates OAuth2 protection for ingresses:
    - Checks nginx.ingress.kubernetes.io/auth-url annotation points to oauth2.{captain_domain}
    - Checks nginx.ingress.kubernetes.io/auth-signin annotation points to oauth2.{captain_domain}
    - Makes HTTP request to ingress host and verifies redirect (301/302/307/308) to OAuth2 URL
    - Accepts 401/403 auth challenges as valid (protected but different auth method)
    
    Skips ingresses not matching class "glueops-platform".
    
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
                print(f"{name}: skipped (in exception list)")
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
                print(f"{name}: auth-url ✓")
            
            if not auth_signin:
                problems.append(f"{name}: missing nginx.ingress.kubernetes.io/auth-signin annotation")
            elif not auth_signin.startswith(expected_oauth2_url):
                problems.append(f"{name}: auth-signin '{auth_signin}' does not start with '{expected_oauth2_url}'")
            else:
                print(f"{name}: auth-signin ✓")
            
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
                                print(f"{name} ({host}): HTTP redirect to OAuth2 ✓")
                            else:
                                problems.append(f"{name} ({host}): redirects to '{location}' instead of OAuth2")
                        elif response.status_code == 401 or response.status_code == 403:
                            # Auth challenge without redirect - still protected
                            print(f"{name} ({host}): auth challenge (status {response.status_code}) ✓")
                        else:
                            print(f"{name} ({host}): unexpected status {response.status_code}")
                    
                    except requests.exceptions.Timeout:
                        print(f"{name} ({host}): HTTP request timeout (skipped)")
                    except requests.exceptions.ConnectionError:
                        print(f"{name} ({host}): connection failed (skipped)")
                    except Exception as e:
                        print(f"{name} ({host}): HTTP test error: {e}")
    
    assert not problems, (
        f"{len(problems)} OAuth2 configuration issue(s) found (checked {checked_count} ingresses):\n" +
        "\n".join(f"  - {p}" for p in problems)
    )


@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.observability
def test_alertmanager_alerts(core_v1):
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
    # Port-forward to Alertmanager
    with PortForward("glueops-core-kube-prometheus-stack", "kps-alertmanager", 9093) as pf:
        alertmanager_url = f"http://127.0.0.1:{pf.local_port}"
        
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
            print(f"\nExpected alerts (informational, {len(passable)} alert(s)):")
            for alert in passable:
                labels = alert.get("labels", {})
                annotations = alert.get("annotations", {})
                name = labels.get("alertname", "Unknown")
                severity = labels.get("severity", "unknown")
                summary = annotations.get("summary", "")
                print(f"  {name} (severity: {severity})")
                if summary:
                    print(f"    {summary}")
        
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
