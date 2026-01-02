# Contributing to GlueOps Test Suite

This guide walks you through adding new tests to the repository. For comprehensive documentation, see [AGENTS.md](AGENTS.md).

## Quick Start: Adding a New Test

### 1. Choose Your Test Type

| Type | Directory | When to Use |
|------|-----------|-------------|
| **Smoke** | `tests/smoke/` | Read-only validation of existing resources |
| **GitOps** | `tests/gitops/` | Tests that deploy apps via Git commits |
| **UI** | `tests/ui/` | Browser automation with Playwright |

**Decision Tree:**

```
Does your test modify cluster state?
├── No → Smoke Test
│   └── Does it deploy apps through GitOps?
│       ├── No → Smoke Test (tests/smoke/)
│       └── Yes → GitOps Test (tests/gitops/)
└── Yes (write operations)
    └── Does it need browser automation?
        ├── No → GitOps Test with @pytest.mark.write
        └── Yes → UI Test (tests/ui/)
```

### 2. Copy the Template

Templates are in `tests/templates/`. Copy the one matching your test type:

```bash
# Smoke test (read-only validation)
cp tests/templates/_test_smoke_template.py tests/smoke/test_my_feature.py

# GitOps test (deploys apps via Git)
cp tests/templates/_test_gitops_template.py tests/gitops/test_my_workflow.py

# UI test (browser automation)
cp tests/templates/_test_ui_template.py tests/ui/test_my_ui.py
```

### 3. Customize the Template

1. Update the module docstring with your test's purpose
2. Rename the test function to describe what it validates
3. Update the function docstring with:
   - What the test validates
   - What causes it to fail
   - Cluster Impact (READ-ONLY or WRITE)
4. Choose appropriate pytest markers (see [Markers Reference](#markers-reference))
5. Implement your validation logic

### 4. Run Static Analysis

**Always run before committing:**

```bash
make ci  # Runs lint + typecheck
```

This catches:
- Type errors (wrong function signatures, missing `Optional[]`)
- Import errors (typos, missing modules)
- Code quality issues (unused imports, undefined variables)

### 5. Test Your Changes

```bash
# Run your specific test
pytest tests/smoke/test_my_feature.py -v

# Run with verbose output
pytest tests/smoke/test_my_feature.py -v -s

# Run all quick smoke tests to ensure no regressions
pytest -m "smoke and quick" -v
```

---

## Environment Setup

### Prerequisites

1. **Clone and install dependencies:**
   ```bash
   cd qa-test-glueops-platform
   make local-install
   ```

2. **Create `.env` file from template:**
   ```bash
   cp .env.example .env
   # Edit .env with your values
   ```

3. **Required for different test types:**

   | Test Type | Required Environment Variables |
   |-----------|-------------------------------|
   | Smoke | `CAPTAIN_DOMAIN`, valid `kubeconfig` |
   | GitOps | Above + `GITHUB_TOKEN`, `TEMPLATE_REPO_URL`, `DESTINATION_REPO_URL` |
   | UI | Above + `GITHUB_USERNAME`, `GITHUB_PASSWORD`, `GITHUB_OTP_SECRET` |

4. **For UI tests, start Chrome:**
   ```bash
   ./start_chrome.sh
   # Or manually:
   google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug
   ```

---

## Markers Reference

### Required Markers (pick one from each category)

**Suite** (at least one):
- `@pytest.mark.smoke` - Read-only validation tests
- `@pytest.mark.gitops` - GitOps deployment tests
- `@pytest.mark.ui` - Browser automation tests

**Speed**:
- `@pytest.mark.quick` - Fast tests (<5 seconds)
- `@pytest.mark.slow` - Slow tests (>30 seconds)

**Priority**:
- `@pytest.mark.critical` - Must pass for release
- `@pytest.mark.important` - Should pass
- `@pytest.mark.informational` - Nice to have

**Cluster Impact**:
- `@pytest.mark.readonly` - No modifications
- `@pytest.mark.write` - Creates/modifies resources

### Component Markers

Add one or more based on what's tested:
- `@pytest.mark.argocd`
- `@pytest.mark.workloads`
- `@pytest.mark.vault`
- `@pytest.mark.backup`
- `@pytest.mark.observability`
- `@pytest.mark.ingress`
- `@pytest.mark.dns`
- `@pytest.mark.oauth2`

### Special Markers

- `@pytest.mark.authenticated` - Requires GitHub OAuth login
- `@pytest.mark.visual` - Has visual regression baseline
- `@pytest.mark.captain_manifests` - Uses `captain_manifests` fixture
- `@pytest.mark.flaky(reruns=1, reruns_delay=60)` - Retry on failure

---

## Fixtures Reference

### Kubernetes Clients

| Fixture | Type | Use For |
|---------|------|---------|
| `core_v1` | CoreV1Api | Pods, ConfigMaps, Secrets, Services |
| `batch_v1` | BatchV1Api | Jobs, CronJobs |
| `networking_v1` | NetworkingV1Api | Ingresses |
| `custom_api` | CustomObjectsApi | CRDs (ArgoCD Apps, Certificates) |

### Configuration

| Fixture | Type | Description |
|---------|------|-------------|
| `captain_domain` | str | Cluster domain (e.g., `nonprod.example.com`) |
| `platform_namespaces` | list[str] | Namespaces matching `glueops-core*` |
| `namespace_filter` | str or None | CLI filter (`--namespace=...`) |

### GitOps Testing

| Fixture | Type | Description |
|---------|------|-------------|
| `ephemeral_github_repo` | Repository | Temp repo from template (auto-cleanup) |
| `captain_manifests` | dict | Deploys fixture apps, returns `{'captain_domain', 'namespace', 'fixture_app_count'}` |

### UI Testing

| Fixture | Type | Description |
|---------|------|-------------|
| `page` | Page | Playwright browser page |
| `authenticated_argocd_page` | Page | Pre-authenticated ArgoCD page |
| `github_credentials` | dict | GitHub login credentials from env |
| `screenshots` | ScreenshotManager | Capture and compare screenshots |

---

## Helper Functions

Import helpers from `tests/helpers/`:

```python
# Kubernetes validators (return list of problems)
from tests.helpers.k8s import validate_pod_health, validate_all_argocd_apps

# Pytest assertions (call pytest.fail() on error)
from tests.helpers.assertions import assert_argocd_healthy, assert_pods_healthy

# GitHub operations
from tests.helpers.github import create_github_file, delete_directory_contents

# ArgoCD utilities
from tests.helpers.argocd import wait_for_appset_apps_created_and_healthy

# UI utilities
from tests.helpers.browser import complete_github_oauth_flow, ScreenshotManager

# General utilities
from tests.helpers.utils import print_section_header, display_progress_bar
```

---

## Test Patterns

### Pattern 1: Simple Validation (Smoke)

```python
@pytest.mark.smoke
@pytest.mark.quick
@pytest.mark.readonly
@pytest.mark.argocd
def test_argocd_healthy(custom_api, namespace_filter):
    """Verify all ArgoCD applications are healthy.
    
    Cluster Impact: READ-ONLY
    """
    from tests.helpers.assertions import assert_argocd_healthy
    assert_argocd_healthy(custom_api, namespace_filter)
```

### Pattern 2: Multi-Step GitOps

```python
@pytest.mark.gitops
@pytest.mark.captain_manifests
def test_deployment_workflow(captain_manifests, ephemeral_github_repo, custom_api):
    """Test end-to-end deployment through GitOps.
    
    Cluster Impact: WRITE (creates ArgoCD apps)
    """
    from tests.helpers.utils import print_section_header
    from tests.helpers.github import create_github_file
    from tests.helpers.argocd import wait_for_appset_apps_created_and_healthy
    
    print_section_header("STEP 1: Create Application")
    create_github_file(ephemeral_github_repo, "apps/my-app/values.yaml", content, "Add app")
    
    print_section_header("STEP 2: Wait for Sync")
    wait_for_appset_apps_created_and_healthy(custom_api, namespace, expected_count)
    
    print_section_header("STEP 3: Validate")
    # Your validation logic
```

### Pattern 3: UI with Screenshots

```python
@pytest.mark.ui
@pytest.mark.authenticated
@pytest.mark.visual
def test_dashboard_loads(authenticated_grafana_page, captain_domain, screenshots):
    """Verify Grafana dashboard loads correctly.
    
    Cluster Impact: READ-ONLY
    """
    page = authenticated_grafana_page
    
    # Capture with visual regression check
    screenshots.capture(
        page, page.url,
        description="Grafana Dashboard",
        baseline_key="grafana_dashboard",
        threshold=0.0
    )
    
    assert not screenshots.get_visual_failures()
```

---

## Common Mistakes

### ❌ Forgetting Fixture App Count

```python
# WRONG - Forgets the 3 fixture apps
expected_count = num_apps  # Only counts your test apps

# CORRECT - Include fixture apps
from tests.helpers.argocd import calculate_expected_app_count
expected_count = calculate_expected_app_count(captain_manifests, num_apps)
```

### ❌ Not Using Assertions Module

```python
# VERBOSE - Manual validation and failure
problems = validate_all_argocd_apps(custom_api)
if problems:
    pytest.fail(f"{len(problems)} issues:\n" + "\n".join(problems))

# CLEANER - Use assertion helper
from tests.helpers.assertions import assert_argocd_healthy
assert_argocd_healthy(custom_api)  # Handles logging and pytest.fail()
```

### ❌ Hardcoding Captain Domain

```python
# WRONG - Hardcoded domain
url = "https://argocd.nonprod.foobar.onglueops.rocks"

# CORRECT - Use fixture
url = f"https://argocd.{captain_domain}"
```

---

## PR Checklist

Before submitting a PR:

- [ ] Test follows appropriate template pattern
- [ ] All required markers are present (suite, speed, priority, cluster impact)
- [ ] Docstring includes Validates/Fails/Cluster Impact sections
- [ ] `make ci` passes (lint + typecheck)
- [ ] Test runs successfully locally
- [ ] No duplicate code (check if helper exists or should be created)
- [ ] Environment variables documented if new ones added

---

## Getting Help

- **[AGENTS.md](AGENTS.md)** - Comprehensive architecture and patterns
- **[tests/ui/CLAUDE.md](tests/ui/CLAUDE.md)** - Detailed UI testing guide
- **[README.md](README.md)** - Quick start commands
- **`make help`** - All available Makefile targets
- **`pytest --markers`** - All available markers
- **`pytest --fixtures`** - All available fixtures

---

**Last Updated**: January 2, 2026
