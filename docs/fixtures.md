# Fixtures Reference

Complete catalog of pytest fixtures available in the test suite.

## Kubernetes Client Fixtures

These fixtures provide authenticated Kubernetes API clients.

### `core_v1`

**Type:** `kubernetes.client.CoreV1Api`  
**Scope:** Session  
**Source:** `tests/conftest_k8s.py`

Kubernetes CoreV1 API client for core resources.

**Use For:**
- Pods
- Services
- ConfigMaps
- Secrets
- Namespaces
- PersistentVolumeClaims

```python
def test_pod_health(core_v1, platform_namespaces):
    for ns in platform_namespaces:
        pods = core_v1.list_namespaced_pod(ns)
        # Check pod status...
```

---

### `batch_v1`

**Type:** `kubernetes.client.BatchV1Api`  
**Scope:** Session  
**Source:** `tests/conftest_k8s.py`

Kubernetes BatchV1 API client for batch workloads.

**Use For:**
- Jobs
- CronJobs

```python
def test_cronjob_status(batch_v1):
    cronjobs = batch_v1.list_namespaced_cron_job("glueops-core-backup")
    for cj in cronjobs.items:
        # Check last schedule time...
```

---

### `networking_v1`

**Type:** `kubernetes.client.NetworkingV1Api`  
**Scope:** Session  
**Source:** `tests/conftest_k8s.py`

Kubernetes NetworkingV1 API client for networking resources.

**Use For:**
- Ingresses
- NetworkPolicies
- IngressClasses

```python
def test_ingress_valid(networking_v1, platform_namespaces):
    for ns in platform_namespaces:
        ingresses = networking_v1.list_namespaced_ingress(ns)
        # Validate hosts, TLS, load balancer...
```

---

### `custom_api`

**Type:** `kubernetes.client.CustomObjectsApi`  
**Scope:** Session  
**Source:** `tests/conftest_k8s.py`

Kubernetes CustomObjectsApi for CRDs (Custom Resource Definitions).

**Use For:**
- ArgoCD Applications
- cert-manager Certificates
- ExternalSecrets
- Any CRD

```python
def test_argocd_apps(custom_api):
    apps = custom_api.list_cluster_custom_object(
        group="argoproj.io",
        version="v1alpha1",
        plural="applications"
    )
    for app in apps['items']:
        # Check health, sync status...
```

---

## Configuration Fixtures

### `captain_domain`

**Type:** `str`  
**Scope:** Session  
**Source:** `tests/conftest.py`

The captain domain for the cluster being tested (e.g., `nonprod.example.onglueops.rocks`).

**Set via:**
1. `--captain-domain` CLI option
2. `CAPTAIN_DOMAIN` environment variable
3. Auto-detected from namespace labels

```python
def test_service_url(captain_domain):
    argocd_url = f"https://argocd.{captain_domain}"
    grafana_url = f"https://grafana.{captain_domain}"
```

---

### `platform_namespaces`

**Type:** `list[str]`  
**Scope:** Session  
**Source:** `tests/conftest_k8s.py`

List of platform namespaces matching `glueops-core*` pattern.

**Typical values:**
- `glueops-core`
- `glueops-core-backup`
- `glueops-core-kube-prometheus-stack`
- `glueops-core-vault`

```python
def test_pods_across_namespaces(core_v1, platform_namespaces):
    for ns in platform_namespaces:
        pods = core_v1.list_namespaced_pod(ns)
        # Validate each pod...
```

---

### `namespace_filter`

**Type:** `str | None`  
**Scope:** Session  
**Source:** `tests/conftest.py`

Optional namespace filter from `--namespace` CLI option.

```python
def test_filtered(custom_api, namespace_filter):
    if namespace_filter:
        # Test only specified namespace
    else:
        # Test all namespaces
```

---

## GitOps Fixtures

### `ephemeral_github_repo`

**Type:** `github.Repository.Repository`  
**Scope:** Function  
**Source:** `tests/conftest_github.py`

Creates a temporary GitHub repository from a template. Automatically cleans up after test.

**Features:**
- Cloned from `TEMPLATE_REPO_URL`
- `apps/` directory cleared by default
- Deleted after test completes
- Returns PyGithub Repository object

**Required Environment Variables:**
- `GITHUB_TOKEN` - GitHub PAT with repo permissions
- `TEMPLATE_REPO_URL` - Template repo URL
- `DESTINATION_REPO_URL` - Target org/repo pattern

```python
def test_deployment(ephemeral_github_repo):
    repo = ephemeral_github_repo
    
    # Create app configuration
    from tests.helpers.github import create_github_file
    create_github_file(
        repo=repo,
        file_path="apps/my-app/values.yaml",
        content=yaml_content,
        commit_message="Add my-app"
    )
```

---

### `captain_manifests`

**Type:** `dict`  
**Scope:** Session  
**Source:** `tests/conftest_manifests.py`  
**Marker Required:** `@pytest.mark.captain_manifests`

Deploys 3 fixture applications that persist throughout the test session.

**Returns:**
```python
{
    'captain_domain': str,      # e.g., 'nonprod.example.com'
    'namespace': str,           # e.g., 'deployment-configurations'
    'fixture_app_count': int,   # Always 3
}
```

**⚠️ Important:** When counting expected applications:

```python
# WRONG - forgets fixture apps
expected_count = num_test_apps

# CORRECT - include fixture apps
from tests.helpers.argocd import calculate_expected_app_count
expected_count = calculate_expected_app_count(captain_manifests, num_test_apps)
```

---

## UI/Browser Fixtures

### `page`

**Type:** `playwright.sync_api.Page`  
**Scope:** Function  
**Source:** `tests/conftest_browser.py`

Fresh Playwright browser page (unauthenticated).

**Features:**
- Incognito context (no cookies persisted)
- Connected via CDP to Chrome at `localhost:9222`
- Or BrowserBase if `USE_BROWSERBASE=true`

```python
def test_oauth_redirect(page, captain_domain):
    page.goto(f"https://argocd.{captain_domain}")
    assert "github.com" in page.url  # Should redirect
```

---

### `authenticated_argocd_page`

**Type:** `playwright.sync_api.Page`  
**Scope:** Function  
**Source:** `tests/conftest_browser.py`

Browser page pre-authenticated to ArgoCD via GitHub OAuth.

```python
def test_argocd_apps(authenticated_argocd_page):
    page = authenticated_argocd_page
    assert "/applications" in page.url
    # Already logged in, interact with ArgoCD...
```

---

### `authenticated_grafana_page`

**Type:** `playwright.sync_api.Page`  
**Scope:** Function  
**Source:** `tests/conftest_browser.py`

Browser page pre-authenticated to Grafana via GitHub OAuth.

---

### `authenticated_vault_page`

**Type:** `playwright.sync_api.Page`  
**Scope:** Function  
**Source:** `tests/conftest_browser.py`

Browser page pre-authenticated to Vault via GitHub OAuth.

---

### `github_credentials`

**Type:** `dict`  
**Scope:** Session  
**Source:** `tests/conftest_browser.py`

GitHub login credentials from environment.

**Returns:**
```python
{
    'username': str,     # GITHUB_USERNAME
    'password': str,     # GITHUB_PASSWORD
    'otp_secret': str,   # GITHUB_OTP_SECRET
}
```

```python
def test_manual_login(page, github_credentials):
    from tests.helpers.browser import complete_github_oauth_flow
    complete_github_oauth_flow(page, github_credentials)
```

---

### `screenshots`

**Type:** `ScreenshotManager`  
**Scope:** Function  
**Source:** `tests/conftest_browser.py`

Screenshot capture and visual regression manager.

**Methods:**
- `capture(page, url, description, baseline_key=None, threshold=0.0)`
- `get_visual_failures()` → `list[str]`

```python
def test_dashboard(authenticated_grafana_page, screenshots):
    screenshots.capture(
        authenticated_grafana_page,
        authenticated_grafana_page.url,
        description="Grafana Dashboard",
        baseline_key="grafana_main",
        threshold=0.01  # 1% difference allowed
    )
    assert not screenshots.get_visual_failures()
```

---

## Service Access Fixtures

### `vault_client`

**Type:** `hvac.Client`  
**Scope:** Function  
**Source:** `tests/conftest_services.py`

Authenticated Vault client via port-forward.

```python
def test_vault_secret(vault_client):
    vault_client.secrets.kv.v2.create_or_update_secret(
        path="test/secret",
        secret={"key": "value"}
    )
```

---

## Pytest Standard Fixtures

These are built-in pytest fixtures commonly used in tests:

### `capsys`

Capture stdout/stderr output.

```python
def test_logging(capsys):
    print("Debug message")
    captured = capsys.readouterr()
    assert "Debug" in captured.out
```

### `request`

Access test metadata (name, markers, etc.).

```python
def test_with_metadata(request):
    test_name = request.node.name
    # Useful for dynamic file naming
```

### `tmp_path`

Temporary directory for test artifacts.

```python
def test_file_generation(tmp_path):
    output_file = tmp_path / "output.json"
    # Write test artifacts...
```

---

**Last Updated**: January 2, 2026
