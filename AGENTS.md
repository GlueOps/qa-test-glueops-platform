# AI Agent Guide for GlueOps Testing Framework

Quick reference for AI agents working with this codebase.

## Repository Purpose

Automated testing suite for GlueOps Platform-as-a-Service Kubernetes deployments. Tests infrastructure components: ArgoCD, workloads, observability, backups, Vault, certificates, and GitOps workflows.

## Directory Structure

```
qa-test-glueops-platform/
├── tests/
│   ├── conftest.py               # Pytest fixtures (K8s clients, GitHub repo, config)
│   ├── helpers/                  # **NEW: Consolidated helper library**
│   │   ├── __init__.py           # Common re-exports for convenience
│   │   ├── k8s.py                # Kubernetes validators and utilities
│   │   ├── assertions.py         # pytest-specific assertion wrappers
│   │   ├── github.py             # GitHub repository operations
│   │   ├── vault.py              # Vault client and secret operations
│   │   ├── port_forward.py       # kubectl port-forward context manager
│   │   ├── browser.py            # Playwright browser automation helpers
│   │   └── utils.py              # Progress bars, formatting, logging
│   ├── smoke/                    # Read-only smoke tests
│   │   ├── test_argocd.py        # ArgoCD application health
│   │   ├── test_workloads.py     # Pods, jobs, ingress, DNS, OAuth2, alerts
│   │   ├── test_observability.py # Prometheus metrics baseline
│   │   ├── test_backups.py       # Backup CronJob validation
│   │   └── test_vault.py         # Vault secret operations
│   ├── gitops/                   # GitOps integration tests
│   │   ├── test_deployment_workflow.py  # http-debug app deployment
│   │   ├── test_externalsecrets.py      # Vault → K8s secrets via ESO
│   │   ├── test_preview_environment_pr.py # PR workflow validation
│   │   └── test_letsencrypt_http01.py   # cert-manager certificates
│   └── ui/                       # Browser automation tests (Playwright)
│       ├── conftest.py           # UI fixtures (browser, credentials)
│       ├── test_*_oauth.py       # OAuth redirect validation tests
│       └── test_*_login_example.py # Full login workflow tests
├── pytest.ini                    # Markers, test discovery, logging config
├── Makefile                      # Build and run automation
├── requirements.txt              # Python dependencies
└── AGENTS.md                     # This file
```

## Helper Library Architecture (tests/helpers/)

All helper modules are now consolidated in `tests/helpers/`. Import using:
```python
from tests.helpers.k8s import validate_pod_health, wait_for_job_completion
from tests.helpers.assertions import assert_argocd_healthy, assert_pods_healthy
from tests.helpers.github import create_github_file, delete_directory_contents
from tests.helpers.vault import get_vault_client, cleanup_vault_client
from tests.helpers.browser import ScreenshotManager, complete_github_oauth_flow
from tests.helpers.utils import display_progress_bar, print_section_header
```

### ⚠️ Important: Fixture Apps

The `captain_manifests` fixture automatically creates **3 fixture applications** (`fixture-http-debug-1/2/3`) that persist throughout the test session. When counting expected ArgoCD applications:

```python
# WRONG - Only counts test-specific apps
expected_count = num_apps

# CORRECT - Includes fixture apps
fixture_app_count = captain_manifests['fixture_app_count']  # Always 3
expected_count = fixture_app_count + num_apps
```

**Why:** Functions like `wait_for_appset_apps_created_and_healthy()` count ALL applications in the namespace, not just test-specific ones. See `test_deployment_workflow.py` for reference implementation.

### Module Organization

#### 1. **k8s.py** - Kubernetes Validators & Utilities
Low-level validation functions that return lists of problems. Never fail tests directly.

```python
# Validation functions (return problems list)
problems = validate_pod_health(core_v1, platform_namespaces)
problems, total = validate_ingress_configuration(networking_v1, platform_namespaces)
problems = validate_all_argocd_apps(custom_api, namespace_filter=None)

# Utility functions
lb_ip = get_ingress_load_balancer_ip(networking_v1, 'public', fail_on_none=True)
success, msg = wait_for_job_completion(batch_v1, job_name, namespace, timeout=300)
success, msg = validate_pod_execution(core_v1, job_name, namespace)
```

#### 2. **assertions.py** - pytest Assertion Wrappers
High-level wrappers that call validators and fail tests on errors using `pytest.fail()`.

```python
# Call these in tests - they handle logging and pytest.fail() internally
assert_argocd_healthy(custom_api, namespace_filter=None)
assert_pods_healthy(core_v1, platform_namespaces)
assert_ingress_valid(networking_v1, platform_namespaces)
assert_certificates_ready(custom_api, cert_info_list, namespace='nonprod')
assert_tls_secrets_valid(core_v1, secret_info_list, namespace='nonprod')
assert_https_endpoints_valid(endpoint_info_list, validate_cert=True)
```

#### 3. **github.py** - GitHub Operations
GitHub repository and file management for GitOps tests.

```python
client = get_github_client()  # Uses GITHUB_TOKEN from env
repo = create_repo(org, repo_name, private=False)
create_github_file(repo, file_path, content, commit_message, branch='main')
delete_directory_contents(repo, directory='apps/', branch='main')
```

#### 4. **vault.py** - Vault Integration
Vault client management and secret operations.

```python
with get_vault_client(captain_domain) as vault_client:
    # vault_client is hvac.Client instance
    vault_client.secrets.kv.v2.create_or_update_secret(path=..., secret=...)

create_multiple_vault_secrets(vault_client, base_path, secrets_dict)
verify_vault_secrets(vault_client, base_path, expected_secrets_dict)
delete_multiple_vault_secrets(vault_client, paths_list)
```

#### 5. **browser.py** - Playwright UI Automation
Browser connection, OAuth flows, and screenshot management.

```python
playwright, browser, session = get_browser_connection()  # BrowserBase or local Chrome
context = create_incognito_context(browser)
page = create_new_page(context)

# OAuth flow helper
complete_github_oauth_flow(page, github_credentials)

# Screenshot management
screenshot_mgr = ScreenshotManager(request, captain_domain)
screenshot_mgr.capture(page, description="Login page")
```

#### 6. **utils.py** - General Utilities
Progress bars, section headers, and formatting utilities.

```python
print_section_header("STEP 1: Creating Applications")
display_progress_bar(wait_time=300, interval=15, description="Waiting for sync...")
print_summary_list(items, title="Results")
```

## Key Fixtures (tests/conftest.py)

| Fixture | Description |
|---------|-------------|
| `core_v1` | Kubernetes CoreV1Api client |
| `batch_v1` | Kubernetes BatchV1Api client |
| `networking_v1` | Kubernetes NetworkingV1Api client |
| `custom_api` | Kubernetes CustomObjectsApi client |
| `platform_namespaces` | List of namespaces to test |
| `captain_domain` | Cluster domain (e.g., 'nonprod.example.com') |
| `ephemeral_github_repo` | Creates temp repo from template, clears apps/ by default |

## Pytest Markers (pytest.ini)

| Category | Markers |
|----------|---------|
| **Suites** | `smoke`, `gitops`, `ui` |
| **Speed** | `quick` (<5s), `slow` (>30s) |
| **Priority** | `critical`, `important`, `informational` |
| **Cluster Impact** | `readonly`, `write` |
| **Components** | `argocd`, `workloads`, `vault`, `backup`, `observability`, `ingress`, `dns`, `oauth2` |
| **GitOps** | `gitops_deployment`, `letsencrypt`, `externalsecrets` |
| **UI** | `oauth_redirect`, `authenticated` |

## Test Patterns

### Standard Smoke Test
```python
from tests.helpers.k8s import validate_pod_health
import pytest

@pytest.mark.smoke
@pytest.mark.quick
@pytest.mark.readonly
@pytest.mark.workloads
def test_something(core_v1, platform_namespaces):
    """What this test validates.
    
    Validates:
    - First thing checked
    - Second thing checked
    
    Fails if any validation fails.
    
    Cluster Impact: READ-ONLY (queries only)
    """
    problems = validate_pod_health(core_v1, platform_namespaces)
    
    if problems:
        pytest.fail(f"{len(problems)} issue(s) found:\n" + "\n".join(problems))
```

### Using Assertion Helpers (Recommended)
```python
from tests.helpers.assertions import assert_pods_healthy, assert_argocd_healthy

@pytest.mark.smoke
@pytest.mark.quick
def test_something_simple(core_v1, custom_api, platform_namespaces):
    """Simpler test using assertion helpers that handle logging and failure.
    
    Cluster Impact: READ-ONLY
    """
    # These call validators internally and pytest.fail() on errors
    assert_argocd_healthy(custom_api)
    assert_pods_healthy(core_v1, platform_namespaces)
```

### GitOps Integration Test
```python
from tests.helpers.assertions import assert_argocd_healthy, assert_pods_healthy
from tests.helpers.github import create_github_file
from tests.helpers.utils import print_section_header, display_progress_bar

@pytest.mark.gitops
@pytest.mark.externalsecrets
def test_gitops_workflow(ephemeral_github_repo, custom_api, core_v1, captain_domain):
    """What this GitOps test validates.
    
    Creates N applications and validates end-to-end deployment.
    
    Validates:
    - Repository operations
    - ArgoCD sync and health
    - Application-specific validations
    
    Applications use pattern: app-name-<guid>.apps.{captain_domain}
    """
    repo = ephemeral_github_repo  # apps/ already cleared by fixture
    
    # Step 1: Create resources
    print_section_header("STEP 1: Creating Applications")
    create_github_file(repo, "apps/app1.yaml", yaml_content, "Add app1")
    
    # Step 2: Wait for sync
    print_section_header("STEP 2: Waiting for GitOps Sync")
    display_progress_bar(wait_time=300, interval=15, description="Waiting...")
    
    # Step 3+: Validate using assertion functions
    print_section_header("STEP 3: Checking ArgoCD Status")
    assert_argocd_healthy(custom_api)
    
    print_section_header("STEP 4: Checking Pod Health")
    assert_pods_healthy(core_v1, platform_namespaces)
```

### UI Test with Browser Automation
```python
from tests.helpers.browser import ScreenshotManager, complete_github_oauth_flow
import pytest

@pytest.mark.ui
@pytest.mark.authenticated
def test_ui_workflow(page, github_credentials, captain_domain, request):
    """Test UI login workflow.
    
    Validates OAuth flow and authenticated access.
    """
    screenshot_mgr = ScreenshotManager(request, captain_domain)
    
    # Navigate to service
    service_url = f"https://argocd.{captain_domain}"
    page.goto(service_url, wait_until="load", timeout=30000)
    
    # Handle OAuth redirect
    if "github.com" in page.url:
        complete_github_oauth_flow(page, github_credentials)
    
    # Take screenshot
    screenshot_mgr.capture(page, description="After login")
```

## Static Analysis & Code Quality

**⚠️ ALWAYS run static analysis before committing or running tests:**

```bash
make ci                # Run all checks (lint + typecheck) - USE THIS
make lint              # Run pylint code analysis only
make typecheck         # Run mypy type checking only
```

**What these checks catch:**
- Type errors (wrong function signatures, incompatible types, missing `Optional[]`)
- Code quality issues (unused imports, undefined variables, too many arguments)
- Import errors (typos, missing modules)

**Configuration:**
- `mypy.ini` - Type checking config with **per-module** import ignores (better than `--ignore-missing-imports`)
- Only `kubernetes.*`, `hvac.*`, and `allure.*` are ignored (no type stubs available)
- All other imports are fully type-checked to catch bugs early

**Why not use `--ignore-missing-imports`?**
- Blanket flag silences ALL import errors (hides real bugs)
- Can't detect typos, wrong module names, or newly available type stubs
- Per-module config in `mypy.ini` is explicit and maintainable

**Best Practice:**
```bash
make ci && make test MARKER=quick  # Validate before running any tests
```

## Code Quality: DRY Principle (Don't Repeat Yourself)

**⚠️ AI Agents: Actively identify and eliminate code duplication**

### When to Extract Helper Functions

**Identify duplication when you see:**
- Same logic repeated in 2+ test files
- Similar calculation patterns (especially with 3+ lines)
- Repeated import + usage patterns
- Complex multi-step operations copy-pasted

**Where to place helpers:**

| Type | Location | Example |
|------|----------|----------|
| ArgoCD operations | `tests/helpers/argocd.py` | `calculate_expected_app_count()` |
| Kubernetes validation | `tests/helpers/k8s.py` | `validate_pod_health()` |
| GitHub operations | `tests/helpers/github.py` | `create_github_file()` |
| Vault operations | `tests/helpers/vault.py` | `create_multiple_vault_secrets()` |
| Browser automation | `tests/helpers/browser.py` | `complete_github_oauth_flow()` |
| General utilities | `tests/helpers/utils.py` | `print_section_header()` |

### DRY Workflow

1. **Spot the pattern** - Notice repeated code across files
2. **Extract to helper** - Create well-named function with docstring
3. **Update all usages** - Replace duplicated code with helper call
4. **Document in module** - Add to module docstring and this guide
5. **Run static analysis** - `make ci` to verify no breakage

### Example: Before & After

**Before (Repeated in 2+ tests):**
```python
# test_deployment_workflow.py
fixture_app_count = captain_manifests['fixture_app_count']
expected_total = fixture_app_count + num_apps

# test_externalsecrets.py
fixture_app_count = captain_manifests['fixture_app_count']
expected_total = fixture_app_count + num_apps
```

**After (DRY with helper):**
```python
# tests/helpers/argocd.py
def calculate_expected_app_count(captain_manifests: dict, test_app_count: int) -> int:
    """Calculate total expected app count including fixture apps."""
    return captain_manifests['fixture_app_count'] + test_app_count

# Both tests now use:
from tests.helpers.argocd import calculate_expected_app_count
expected_total = calculate_expected_app_count(captain_manifests, num_apps)
```

**Benefits:**
- ✅ Single source of truth
- ✅ Easier to update logic (one place)
- ✅ Self-documenting with clear function name
- ✅ Type hints catch errors at static analysis time

### AI Agent Checklist

When writing or modifying test code:

- [ ] Search for similar patterns in other test files
- [ ] If found 2+ times, extract to appropriate helper module
- [ ] Add type hints and comprehensive docstring
- [ ] Update all existing usages to use new helper
- [ ] Run `make ci` to verify type checking passes
- [ ] Document in AGENTS.md if it's a common pattern

### 🔍 How to Ensure Complete Refactoring

**Problem:** Easy to miss files when refactoring manually

**Solution: Always use grep_search to find ALL occurrences**

```python
# Step 1: Search for the pattern you're refactoring
grep_search(query="fixture_app_count = captain_manifests", isRegexp=False)

# Step 2: Review ALL matches (not just 1-2 files)
# Common mistake: Only fixing files you're currently looking at

# Step 3: Update EVERY occurrence with the DRY helper
# Use multi_replace_string_in_file for efficiency

# Step 4: Search again to verify none remain
grep_search(query="fixture_app_count = captain_manifests", isRegexp=False)
# Should return 0 matches after successful refactoring
```

**Example: Complete refactoring workflow**

1. **Identify duplication** - User points out repeated code
2. **Search codebase** - `grep_search` for ALL instances (found in 3 test files)
3. **Create helper** - Add `calculate_expected_app_count()` to `argocd.py`
4. **Update ALL files** - Replace pattern in test_deployment_workflow.py, test_externalsecrets.py, AND test_letsencrypt_http01.py
5. **Verify complete** - Search again to ensure 0 remaining instances
6. **Validate** - Run `make ci` to catch any errors

**Key insight:** grep_search shows you the FULL scope before you start

## Common Commands

```bash
# Docker (default - no local dependencies needed)
make test              # Smoke tests in Docker
make full              # Full tests (includes writes)
make quick             # Quick tests only (<5s)
make critical          # Critical tests only
make parallel          # Parallel execution (8 workers)
make ui                # UI tests
make ui-auth           # Authenticated UI tests (ArgoCD, Grafana, Vault)
make ui-oauth          # OAuth redirect tests

# Local development (requires Python dependencies)
make local-install     # Install dependencies
make local-test        # Smoke tests locally
make local-full        # Full tests locally
pytest tests/smoke/test_argocd.py -v  # Single test file

# Direct pytest usage
pytest -m smoke -v                      # Smoke tests
pytest -m "smoke and not slow" -v       # Fast smoke tests
pytest -m quick -v                      # Quick tests only
pytest -m critical -v                   # Critical tests only
pytest -n 8 -v                          # Parallel (8 workers)
pytest --collect-only -v                # List all tests
pytest --markers                        # Show all markers
pytest --fixtures                       # Show all fixtures

# Custom options
pytest --captain-domain=staging.example.com --namespace=glueops-core -v
```

## Configuration & Environment

### Environment Variables

| Variable | Description |
|----------|-------------|
| `CAPTAIN_DOMAIN` | Cluster domain (required for most tests) |
| `GITHUB_TOKEN` | GitHub PAT for GitOps tests |
| `GITHUB_USERNAME` | GitHub username for UI OAuth tests |
| `GITHUB_PASSWORD` | GitHub password for UI OAuth tests |
| `GITHUB_OTP_SECRET` | TOTP secret for GitHub 2FA |
| `TEMPLATE_REPO_URL` | Template repo URL for ephemeral repos |
| `DESTINATION_REPO_URL` | Target repo URL for test deployments |
| `WILDCARD_DNS_SERVICE` | DNS service for sslip.io-style domains |
| `USE_BROWSERBASE` | Use BrowserBase for UI tests (default: false) |

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

Default: Auto-detected from first namespace

### Vault Integration

Vault tests require terraform state at:
```
/workspaces/glueops/{captain_domain}/terraform/vault/configuration/terraform.tfstate
```

Root token extracted from `aws_s3_object.vault_access` resource.

### Service Access via Port Forwarding

Tests use `kubectl port-forward` to access cluster services:
- **Prometheus**: `glueops-core-kube-prometheus-stack/kps-prometheus:9090`
- **Alertmanager**: `glueops-core-kube-prometheus-stack/kps-alertmanager:9093`
- **Vault**: Dynamic based on service name

The `PortForward` context manager handles this automatically.

## Code Style Guidelines

1. **Import from tests.helpers/** - All helper imports use `from tests.helpers.{module} import ...`
2. **Validators return problems, assertions fail tests** - Keep separation clean:
   - Use validators (`tests.helpers.k8s`) when you need fine-grained control
   - Use assertions (`tests.helpers.assertions`) for simpler tests
3. **All assertion functions handle their own logging** - No duplicate logs in tests
4. **All helper functions log unconditionally** - No verbose parameters; functions always log their operations and results for debugging
5. **Docstrings document what, why, and cluster impact** - Every test has comprehensive docstring
6. **Section headers for multi-step tests** - Use `print_section_header("STEP N: Description")`
7. **Fixture handles setup** - `ephemeral_github_repo` clears apps/ automatically
8. **No sys.path manipulation** - Tests use proper Python package imports

## Adding New Tests

1. Choose appropriate test directory (`smoke/`, `gitops/`, `ui/`)
2. Import helpers from `tests.helpers.*` modules
3. Add pytest markers for categorization
4. Write comprehensive docstring with Validates/Fails/Cluster Impact sections
5. Use existing functions from `tests.helpers.assertions` when possible
6. For custom validation, use validators from `tests.helpers.k8s`
7. Follow the test patterns above

## Recent Refactoring (December 2025)

The test suite was refactored to consolidate all helper functions into `tests/helpers/`:

**What Changed:**
- Moved from scattered `lib/` modules to organized `tests/helpers/` package
- Separated pure validators from pytest-specific assertions
- Removed duplicate code across k8s_helpers, k8s_utils, k8s_validators
- Consolidated browser helpers into single module
- All tests now import from `tests.helpers.*`

**Migration:**
- Old: `from lib.k8s_validators import validate_pod_health`
- New: `from tests.helpers.k8s import validate_pod_health`
- Old: `from lib.k8s_assertions import assert_pods_healthy`
- New: `from tests.helpers.assertions import assert_pods_healthy`

## Debugging

```bash
# Verbose output
pytest tests/smoke/test_workloads.py -v -s

# Single test
pytest tests/smoke/test_workloads.py::test_pod_health -v

# With logging
pytest --log-cli-level=DEBUG -v

# Show print statements
pytest -v -s

# Stop on first failure
pytest -x -v
```

## Key Features & Patterns

### 1. Expected Alerts Whitelist

Some alerts are expected to always fire (e.g., Watchdog for pipeline validation):
```python
PASSABLE_ALERTS = [
    "Watchdog",  # Always-firing alert to verify alerting pipeline
    "InfoInhibitor" # Seems to occur intermittently. Added as passable by @venkatamutyala
]
```

### 2. Prometheus Metrics Baseline

**First run**: Creates baseline in `baselines/prometheus-metrics-baseline.json`  
**Subsequent runs**: Compares current vs baseline
- **FAIL**: If baseline metrics are missing (regression detection)
- **INFO**: If new metrics appear  
- **Query window**: 24 hours to capture intermittent metrics

### 3. DNS Validation

Uses `dnspython` to validate ingress hosts:
- Resolves A records using 1.1.1.1 (Cloudflare DNS)
- Compares resolved IPs to load balancer IPs
- Reports mismatches or DNS issues

### 4. Backup Validation

**Status test**: Checks CronJob status and recent execution  
**Trigger test** (`@pytest.mark.write`):
1. Creates test secret in Vault
2. Triggers all backup CronJobs  
3. Waits for completion
4. Validates job success

### 5. Unconditional Logging

All helper functions log their operations unconditionally for debugging:
```python
problems = validate_pod_health(core_v1, namespaces)
# Always logs:
#   Checking pod health across platform namespaces...
#   ✓ All 120 pods healthy
```

**Note:** The `verbose` parameter was removed in December 2025 - all functions now always log.

### 6. Progress Bars

Long operations show progress bars:
```python
display_progress_bar(wait_time=300, interval=15, description="Waiting for sync...")
# Shows: [04:41:30] ████████████░░░░░░░░  60.0% | Elapsed: 03:00 | Remaining: 02:00
```

## Dependencies

**Python packages** (requirements.txt):
- `pytest>=7.4.0` - Testing framework
- `pytest-xdist>=3.3.0` - Parallel test execution
- `pytest-html>=4.0.0` - HTML test reports
- `pytest-json-report>=1.5.0` - JSON test reports
- `pytest-timeout>=2.1.0` - Test timeout handling
- `pytest-rerunfailures>=16.0.0` - Retry flaky tests
- `kubernetes>=28.1.0` - K8s API client
- `hvac>=1.2.0` - Vault client
- `dnspython>=2.4.0` - DNS resolution
- `requests>=2.31.0` - HTTP client
- `playwright>=1.40.0` - Browser automation (UI tests)
- `pyotp>=2.9.0` - TOTP 2FA code generation (UI tests)
- `PyGithub>=2.0.0` - GitHub API client (GitOps tests)

**System** (included in Docker image):
- `kubectl` - Port forwarding to cluster services

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
          cd qa-test-glueops-platform
          make test
      
      - name: Upload test report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: test-report
          path: qa-test-glueops-platform/reports/
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
    - cd qa-test-glueops-platform
    - make test
  artifacts:
    when: always
    paths:
      - qa-test-glueops-platform/reports/
    reports:
      junit: qa-test-glueops-platform/reports/report.xml
```

### Exit Codes

- `0` - All tests passed
- `1` - One or more tests failed

## Common Issues & Troubleshooting

### Fixture Apps Count Mismatch

**Problem:** Test reports "Waiting for 3 apps" but actually sees 6 apps (or wrong count).

**Cause:** Forgot to include `fixture_app_count` in `expected_count` when using `wait_for_appset_apps_created_and_healthy()`.

**Solution:**
```python
# Add fixture apps to your expected count
fixture_app_count = captain_manifests['fixture_app_count']
expected_total = fixture_app_count + num_apps  # e.g., 3 + 3 = 6
```

### Port-Forward Failures

**Symptom**: Connection refused errors  
**Solution**: Ensure cluster is accessible and service exists in expected namespace

### Vault Tests Failing

**Symptom**: Authentication or permission errors  
**Solution**: Verify terraform state path exists at `/workspaces/glueops/{captain_domain}/terraform/vault/configuration/terraform.tfstate`

### DNS Resolution Timeouts

**Symptom**: DNS lookup timeout errors  
**Solution**: Check external-dns is configured, DNS records exist

### Import Errors After Refactoring

**Symptom**: `ModuleNotFoundError: No module named 'lib'`  
**Solution**: All imports should use `from tests.helpers.*` (not `from lib.*`)

### UI Tests Failing

**Symptom**: Browser connection errors  
**Solution**: 
- Ensure Chrome is running with `--remote-debugging-port=9222`
- For local: `google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug`
- Or set `USE_BROWSERBASE=true` to use BrowserBase cloud browser

## Best Practices

1. **Import from tests.helpers/** - All helper imports use `from tests.helpers.{module} import ...`
2. **Use assertion helpers for simple tests** - `assert_pods_healthy()` vs manual validation
3. **Use validators for complex logic** - When you need fine-grained control or custom error handling
4. **Always run smoke tests first** - Catch issues before write operations
5. **Use verbose mode for debugging** - See exactly what's being checked
6. **Test locally first** - Faster iteration than Docker rebuilds
7. **Review expected alerts** - Update PASSABLE_ALERTS when new monitoring rules added
8. **Proper markers** - Tag tests appropriately for selective execution
9. **Comprehensive docstrings** - Include Validates, Fails, and Cluster Impact sections
10. **No sys.path manipulation** - Use proper Python package imports

---

**Last Updated**: December 27, 2025  
**Major Refactor**: Consolidated `lib/` into `tests/helpers/` package with clean separation of validators and assertions.

## Documentation Structure

This repository has the following documentation:

- **[AGENTS.md](AGENTS.md)** (this file) - Comprehensive guide for AI agents and developers
- **[CLAUDE.md](CLAUDE.md)** - Redirect to AGENTS.md (consolidated)
- **[README.md](README.md)** - User-facing quick start guide
- **[tests/ui/CLAUDE.md](tests/ui/CLAUDE.md)** - Detailed UI testing guide with Playwright
- **[PLAN.md](PLAN.md)** - Roadmap and future enhancements
