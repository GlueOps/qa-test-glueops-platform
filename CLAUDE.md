# GlueOps PaaS Testing Framework

**AI Context Document** - See [AGENTS.md](AGENTS.md) for quick reference guide.

## Project Overview

Automated testing suite for validating GlueOps Platform-as-a-Service deployments on Kubernetes. Tests critical infrastructure components including ArgoCD, workload health, observability stack, backups, and Vault secrets management.

**Technology Stack:**
- Python 3.11+
- Pytest testing framework with plugins (xdist, html, json-report, timeout)
- Kubernetes client library
- Docker containerization
- Make for build automation

## Architecture

### Directory Structure

```
qa-test-glueops-platform/
├── pytest.ini                    # Pytest configuration and markers
├── CLAUDE.md                     # Main AI context document (this file)
├── README.md                     # User-facing documentation
├── tests/
│   ├── conftest.py              # Pytest fixtures (K8s clients, config)
│   ├── smoke/                   # Smoke test suite
│   │   ├── test_argocd.py       # ArgoCD application health
│   │   ├── test_workloads.py    # Pod health, jobs, ingress, DNS, OAuth2, alerts
│   │   ├── test_observability.py # Prometheus metrics, Alertmanager
│   │   ├── test_backups.py      # Backup CronJob validation
│   │   └── test_vault.py        # Vault secret creation tests
│   ├── integration/             # Integration tests (future)
│   └── ui/                      # UI tests (Playwright browser automation)
│       ├── CLAUDE.md            # Detailed UI testing guide
│       ├── conftest.py          # UI test fixtures (github_credentials, captain_domain)
│       ├── helpers.py           # Browser connection, OAuth flow, screenshots
│       ├── test_argocd_login_example.py   # ArgoCD applications page test
│       ├── test_grafana_login_example.py  # Grafana dashboard test
│       └── test_vault_login_example.py    # Vault secrets page test
├── lib/                          # Shared utilities
│   ├── k8s_helpers.py           # Kubernetes helper functions
│   └── port_forward.py          # Generic kubectl port-forward wrapper
├── baselines/                    # Prometheus metrics baselines (gitignored)
├── reports/                      # Test reports (gitignored)
│   └── screenshots/             # UI test screenshots (gitignored)
├── Makefile                      # Build and run automation
├── Dockerfile                    # Container for CI/CD
└── requirements.txt              # Python dependencies

### Core Components

#### 1. Pytest Framework

Test execution using pytest with custom markers and fixtures:

**Markers** (defined in `pytest.ini`):
- `smoke` - Core smoke test suite
- `quick` / `slow` - Test duration categories
- `critical` / `important` / `informational` - Test priority levels
- `readonly` / `write` - Cluster modification indicators
- `ui` - UI tests (browser automation)
- `authenticated` - Tests requiring GitHub OAuth authentication
- `oauth_redirect` - Tests involving OAuth redirects
- Component markers: `argocd`, `workloads`, `vault`, `backup`, `observability`, `ingress`, `dns`, `oauth2`

**Fixtures** (defined in `tests/conftest.py`):
- `k8s_config` - Loads kubeconfig
- `core_v1`, `batch_v1`, `networking_v1`, `custom_api` - Kubernetes API clients
- `captain_domain` - Cluster domain from command line or namespace
- `platform_namespaces` - List of namespaces to test (filters applied)
- `namespace_filter` - Optional namespace filter from command line

**Configuration** (`pytest.ini`):
- Color output enabled (`--color=yes`)
- Verbose mode (`-v`)
- Short traceback format (`--tb=short`)
- Strict marker validation (`--strict-markers`)

#### 2. Port Forwarding (`lib/port_forward.py`)

Generic context manager for `kubectl port-forward`:
```python
with PortForward("namespace", "service", 8200) as pf:
    url = f"http://127.0.0.1:{pf.local_port}"
    # Use service locally
```

Used by observability tests to access Prometheus, Alertmanager, and Vault locally.

#### 3. Test Modules

All test functions use pytest conventions:
```python
@pytest.mark.quick
@pytest.mark.critical
@pytest.mark.readonly
def test_something(core_v1, platform_namespaces):
    """Test description in docstring."""
    problems = []
    # ... collect problems ...
    assert not problems, f"{len(problems)} issue(s) found:\n" + "\n".join(problems)
```

**Test Suites:**

- **ArgoCD** (`tests/smoke/test_argocd.py`): Validates all Applications are Healthy/Synced
- **Workloads** (`tests/smoke/test_workloads.py`):
  - Pod health (CrashLoopBackOff, OOMKilled, high restarts)
  - Failed Jobs detection (allows jobs with retries if eventually succeeded)
  - Ingress validity (hosts, load balancer addresses)
  - Ingress DNS resolution (validates hosts resolve to LB IPs)
  - Ingress OAuth2 redirect (validates OAuth2 annotations and HTTP redirects)
  - Alertmanager firing alerts (whitelists: Watchdog)
- **Observability** (`tests/smoke/test_observability.py`):
  - Prometheus metrics baseline comparison (24-hour query window)
  - Alertmanager status
- **Backups** (`tests/smoke/test_backups.py`): 
  - CronJob status validation
  - Trigger backup jobs on-demand
- **Vault** (`tests/smoke/test_vault.py`): 
  - Creates test secrets (validates Vault access)
  - Extracts root token from terraform state
- **UI Tests** (`tests/ui/`): Browser automation with Playwright
  - ArgoCD login and applications page (`test_argocd_login_example.py`)
  - Grafana login and dashboards (`test_grafana_login_example.py`)
  - Vault login and secrets page (`test_vault_login_example.py`)
  - **See [tests/ui/CLAUDE.md](tests/ui/CLAUDE.md) for detailed UI testing guide**
  - Ingress OAuth2 redirect (validates OAuth2 annotations and HTTP redirects)
  - Alertmanager firing alerts (whitelists: Watchdog)
- **Observability** (`tests/smoke/test_observability.py`):
  - Prometheus metrics baseline comparison (24-hour query window)
  - Alertmanager status
- **Backups** (`tests/smoke/test_backups.py`): 
  - CronJob status validation
  - Trigger backup jobs on-demand
- **Vault** (`tests/smoke/test_vault.py`): 
  - Creates test secrets (validates Vault access)
  - Extracts root token from terraform state

## Usage

### Docker (Default)

```bash
make test      # Smoke tests in Docker
make full      # Full tests (includes write operations)
make quick     # Quick tests only (<5s)
make critical  # Critical tests only
make parallel  # Parallel execution (8 workers)
make verbose   # Verbose output
make build     # Build Docker image

# UI tests (requires Chrome at localhost:9222)
make ui        # All UI tests
make ui-auth   # Authenticated UI tests (ArgoCD, Grafana, Vault)
make ui-oauth  # OAuth redirect tests
```

### Local Execution

```bash
make local-install  # Install dependencies
make local-test     # Smoke tests locally
make local-full     # Full tests locally
make local-quick    # Quick tests locally
make local-parallel # Parallel execution locally

# UI tests (requires Chrome at localhost:9222)
pytest tests/ui/ -m authenticated -v  # Authenticated UI tests
pytest tests/ui/ -m oauth_redirect -v # OAuth redirect tests
```

### Direct Pytest Usage

```bash
# Basic test runs
pytest -m smoke -v                    # Smoke tests
pytest -m "smoke or write" -v         # Full tests
pytest -m quick -v                    # Quick tests only
pytest -m critical -v                 # Critical tests only

# Marker combinations
pytest -m "smoke and not slow" -v     # Fast smoke tests
pytest -m "quick and critical" -v     # Quick + critical

# Specific tests
pytest tests/smoke/test_argocd.py -v  # Single file
pytest -k "pod_health" -v             # By test name pattern

# Parallel execution
pytest -m smoke -n 8 -v               # 8 workers

# Custom options
pytest -m smoke --captain-domain=staging.example.com --namespace=glueops-core -v
```

### Test Discovery

```bash
# Docker (default) - portable, no local dependencies
make discover      # List all tests with descriptions
make markers       # Show all markers
make fixtures      # Show all fixtures

# Local (requires Python dependencies installed)
make local-discover # List all tests
make local-markers  # Show markers
make local-fixtures # Show fixtures

# Direct pytest (local only)
pytest --collect-only -v
pytest --markers
pytest --fixtures
```

## Test Modes

### Smoke Tests (Default)

Read-only validation with `@pytest.mark.smoke` and `@pytest.mark.readonly`:
- ArgoCD application health
- Pod health across platform namespaces
- Failed Jobs detection
- Ingress validity and DNS resolution
- Alertmanager firing alerts
- Backup CronJob history

### Full Tests (`--full`)

Includes write operations:
- **Trigger backup CronJobs**: Creates test secret in Vault, triggers backups, waits for completion
- **Vault stress test**: Creates 10 secrets, verifies creation, waits 30s, cleans up

## Key Features

### 1. Verbose Mode (`-v`)

Shows detailed execution flow with pytest output:
```
============================= test session starts ==============================
platform linux -- Python 3.11.14, pytest-9.0.2
collected 11 items / 3 deselected / 8 selected

tests/smoke/test_argocd.py::test_argocd_applications PASSED              [ 12%]
Checking 38 ArgoCD applications
  ✓ glueops-core/argocd-servicemonitors: Healthy/Synced
  ✓ glueops-core/captain-manifests: Healthy/Synced
  ...

tests/smoke/test_workloads.py::test_pod_health PASSED                    [ 37%]
Checking 18 pods in glueops-core
Checking 27 pods in glueops-core-backup
...

=========================== 8 passed in 4.28s ===================================
```

### 2. Expected Alerts (PASSABLE_ALERTS)

Whitelist for alerts that should always fire:
```python
PASSABLE_ALERTS = [
    "Watchdog",  # Always-firing alert to verify alerting pipeline
]
```

Displayed as informational in test output, not counted as failures.

### 3. DNS Validation

Uses `dnspython` library to validate ingress hosts:
- Resolves A records for each ingress host (using 1.1.1.1 Cloudflare DNS)
- Compares resolved IPs to load balancer IPs from ingress status
- Reports mismatches or DNS issues

### 4. Prometheus Metrics Baseline

**First run**: Creates baseline in `baselines/prometheus-metrics-baseline.json`
**Subsequent runs**: Compares current metrics vs baseline
- **FAIL**: If baseline metrics are missing (regression detection)
- **INFO**: If new metrics appear (shown in verbose mode)
- **Query window**: 24 hours to capture intermittent metrics

### 5. Backup Validation

**Status test** (`@pytest.mark.slow`): Checks CronJob status and recent execution
**Trigger test** (`@pytest.mark.write`): 
1. Triggers all backup CronJobs
2. Waits for completion (timeout configured)
3. Validates job completion

### 6. Docker Integration

- Mounts `kubeconfig` for cluster access
- Uses `--network host` for local service access via port-forward
- Mounts `/workspaces/glueops` (read-only) for Vault terraform state access
- Copies kubeconfig to avoid directory mount issues

## Dependencies

**Python packages** (requirements.txt):
- `pytest>=7.4.0` - Testing framework
- `pytest-xdist>=3.3.0` - Parallel test execution
- `pytest-html>=4.0.0` - HTML test reports
- `pytest-json-report>=1.5.0` - JSON test reports
- `pytest-timeout>=2.1.0` - Test timeout handling
- `kubernetes>=28.1.0` - K8s API client
- `hvac>=1.2.0` - Vault client
- `dnspython>=2.4.0` - DNS resolution
- `requests>=2.31.0` - HTTP client

**System:**
- `kubectl` - Port forwarding to cluster services (included in Docker image)

## Configuration

### Platform Namespaces

Tests scan all `glueops-core*` namespaces by default. Filter with `--namespace`:
```bash
pytest -m smoke --namespace=glueops-core-backup -v
```

### Captain Domain

Specify cluster domain with `--captain-domain`:
```bash
pytest -m smoke --captain-domain=staging.example.com -v
```

Default: Auto-detected from first namespace or `nonprod.foobar.onglueops.rocks`

### Vault Configuration

Vault tests require terraform state at:
```
/workspaces/glueops/{captain_domain}/terraform/vault/configuration/terraform.tfstate
```

Extracts root token from `aws_s3_object.vault_access` resource.

### Service Access

Tests use port-forwarding to access cluster services:
- **Prometheus**: `glueops-core-kube-prometheus-stack/kps-prometheus:9090`
- **Alertmanager**: `glueops-core-kube-prometheus-stack/kps-alertmanager:9093`
- **Vault**: Dynamic based on service name

## Development Patterns

### Adding a New Test

1. Create test function in appropriate module (e.g., `tests/smoke/test_workloads.py`):
```python
@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.workloads
def test_my_feature(core_v1, platform_namespaces):
    """Brief description of what this test validates.
    
    Detailed explanation of:
    - What is being checked
    - How failures are detected
    - Any exclusions or special cases
    
    Cluster Impact: READ-ONLY (queries resource status)
    """
    problems = []
    
    for namespace in platform_namespaces:
        # ... validation logic ...
        if issue_detected:
            problems.append(f"{namespace}: issue description")
    
    assert not problems, (
        f"{len(problems)} issue(s) found:\n" +
        "\n".join(f"  - {p}" for p in problems)
    )
```

2. Choose appropriate markers:
   - `@pytest.mark.smoke` - Include in smoke test suite
   - `@pytest.mark.quick` or `@pytest.mark.slow` - Duration category
   - `@pytest.mark.critical`, `@pytest.mark.important`, or `@pytest.mark.informational` - Priority
   - `@pytest.mark.readonly` or `@pytest.mark.write` - Cluster modification
   - Component marker: `@pytest.mark.workloads`, `@pytest.mark.vault`, etc.

3. Use fixtures for dependencies:
   - `core_v1` - CoreV1Api client
   - `batch_v1` - BatchV1Api client
   - `networking_v1` - NetworkingV1Api client
   - `custom_api` - CustomObjectsApi client
   - `platform_namespaces` - List of namespaces to check
   - `captain_domain` - Cluster domain

4. Test it:
```bash
pytest tests/smoke/test_workloads.py::test_my_feature -v
```

### Test Documentation

Tests are self-documenting through:

1. **Docstrings**: Each test function has a comprehensive docstring
2. **Pytest discovery**: Use `pytest --collect-only -v` to browse all tests
3. **README.md**: High-level overview and usage examples

To view all tests:
```bash
pytest --collect-only -v              # All tests with descriptions
pytest --collect-only -m quick        # Quick tests only
pytest --markers                      # Available markers
pytest --fixtures                     # Available fixtures
```

### Exception Handling

Pytest handles test failures through assertions:
- `assert not problems` - Test fails if problems list is not empty
- `pytest.fail()` - Explicit test failure with custom message
- Exceptions are automatically caught and reported by pytest

Failed tests show:
- Test name and location
- Assertion error message
- Short traceback (configured via `--tb=short`)

### Parallel Execution

Use pytest-xdist for parallel test execution:
```bash
pytest -m smoke -n 8 -v  # 8 parallel workers
pytest -m smoke -n auto  # Auto-detect CPU count
```

**Note**: Some tests use port-forwarding and may conflict when run in parallel. Mark tests with potential conflicts as `@pytest.mark.slow` to run them sequentially.

## CI/CD Integration

### GitHub Actions Example

```yaml
jobs:
  smoke-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Configure kubectl
        uses: azure/k8s-set-context@v3
        with:
          kubeconfig: ${{ secrets.KUBECONFIG }}
      
      - name: Run smoke tests
        run: |
          cd test-fun
          make test
      
      - name: Upload test report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: test-report
          path: test-fun/reports/
```

### GitLab CI Example

```yaml
smoke-tests:
  stage: test
  image: docker:latest
  services:
    - docker:dind
  before_script:
    - echo "$KUBECONFIG" > kubeconfig
  script:
    - cd test-fun
    - make test
  artifacts:
    when: always
    paths:
      - test-fun/reports/
    reports:
      junit: test-fun/reports/report.xml
```

### JSON Report for CI/CD

Generate JSON reports for programmatic parsing:
```bash
make report-json  # Creates reports/report.json
          echo "${{ secrets.KUBECONFIG }}" > kubeconfig
          make test
```

### Exit Codes

- `0` - All tests passed
- `1` - One or more tests failed

## Common Issues

### Port-Forward Failures

**Symptom**: Connection refused errors
**Solution**: Ensure cluster is accessible and service exists in expected namespace

### Vault Tests Failing

**Symptom**: `NameError: name 'time' is not defined`
**Solution**: Ensure `import time` in `tests/vault.py`

### DNS Resolution Timeouts

**Symptom**: DNS lookup timeout errors
**Solution**: Check external DNS is configured, Route53 records exist

### Alertmanager Connection Issues

**Symptom**: Alertmanager API returned status 000 or timeout
**Solution**: Verify `kps-alertmanager` service exists in `glueops-core-kube-prometheus-stack`

## Best Practices

1. **Always run smoke tests before full tests** - Catch issues early without write operations
2. **Use verbose mode for debugging** - See exactly what's being checked
3. **Review expected alerts** - Update PASSABLE_ALERTS when new monitoring rules added
4. **Test locally first** - Faster iteration than Docker rebuilds
5. **Check terraform state paths** - Vault tests require correct captain_domain

## Recent Improvements

- **UI Testing Framework** - Playwright browser automation for ArgoCD, Grafana, and Vault
- **OAuth Double-Click Pattern** - Discovered and implemented pattern for dex-based OAuth services
- **Websocket Wait Strategy** - Proper handling of websocket-based apps (ArgoCD) with `wait_until="load"`
- **Screenshot Volume Mounting** - Persistent screenshot storage via Docker volume mounts
- **Centralized GitHub OAuth** - Reusable OAuth flow handler with OTP/2FA/passkeys support
- **Decorator pattern** - Eliminated 30+ lines of boilerplate across tests
- **Unified problem reporting** - Consistent error formatting
- **Verbose logging** - Optional detailed output for debugging
- **Color enhancements** - Better visual distinction (dark red errors, orange messages, yellow warnings)
- **DNS validation** - Validates ingress hosts resolve to correct IPs
- **Alertmanager integration** - Checks for firing alerts with whitelisting
- **Backup test secret** - Creates Vault secret before backup to validate fresh data capture
- **Generic port-forward** - Reusable PortForward class for all services
- **Makefile standardization** - Docker as default, local targets prefixed with `local-*`

## Future Enhancements

See [PLAN.md](PLAN.md) for comprehensive roadmap including:
- Performance tests (ingress throughput, API latency)
- Chaos engineering (pod kills, network partitions)
- Security scanning (Trivy, Falco)
- Multi-cluster testing
- SLO validation

---

**Last Updated**: December 26, 2025
**Version**: 1.2.0
**Maintainer**: GlueOps Platform Team

## Documentation Structure

This codebase uses category-specific AI context documents:

- **[AGENTS.md](AGENTS.md)** - Quick reference for AI agents (library architecture, patterns, commands)
- **[CLAUDE.md](CLAUDE.md)** (this file) - Comprehensive testing framework overview
- **[tests/ui/CLAUDE.md](tests/ui/CLAUDE.md)** - Detailed UI testing guide with Playwright
- **[README.md](README.md)** - User-facing quick start and usage guide

**Why separate files?**
- AGENTS.md provides concise patterns and commands for AI agents
- CLAUDE.md contains full details for deep understanding
- UI tests have fundamentally different patterns than API/K8s tests
- Focused documentation makes it easier to find relevant information
