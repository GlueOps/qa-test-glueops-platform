# AI Agent Guide for GlueOps Testing Framework

Quick reference for AI agents working with this codebase.

## Repository Purpose

Automated testing suite for GlueOps Platform-as-a-Service Kubernetes deployments. Tests infrastructure components: ArgoCD, workloads, observability, backups, Vault, certificates, and GitOps workflows.

## Directory Structure

```
qa-test-glueops-platform/
├── tests/
│   ├── conftest.py          # Pytest fixtures (K8s clients, GitHub repo, config)
│   ├── smoke/                # Read-only smoke tests
│   │   ├── test_argocd.py    # ArgoCD application health
│   │   ├── test_workloads.py # Pods, jobs, ingress, DNS, OAuth2, alerts
│   │   ├── test_observability.py # Prometheus metrics baseline
│   │   ├── test_backups.py   # Backup CronJob validation
│   │   └── test_vault.py     # Vault secret operations
│   ├── gitops/               # GitOps integration tests
│   │   ├── test_deployment_workflow.py  # http-debug app deployment
│   │   ├── test_externalsecrets.py      # Vault → K8s secrets via ESO
│   │   └── test_letsencrypt_http01.py   # cert-manager certificates
│   └── ui/                   # Browser automation tests (Playwright)
├── lib/                      # Shared helper libraries
│   ├── k8s_assertions.py     # High-level assertion functions (fail on error)
│   ├── k8s_validators.py     # Validation functions (return problems list)
│   ├── k8s_utils.py          # Kubernetes utility functions
│   ├── vault_helpers.py      # Vault client and secret operations
│   ├── github_helpers.py     # GitHub repository operations
│   ├── port_forward.py       # kubectl port-forward context manager
│   └── test_utils.py         # Progress bars, section headers, logging
├── pytest.ini                # Markers, test discovery, logging config
├── Makefile                  # Build and run automation
└── requirements.txt          # Python dependencies
```

## Library Architecture

### Layer 1: Validators (`lib/k8s_validators.py`)
Low-level validation functions that return a list of problems. Never fail tests directly.

```python
# Returns: (problems: list, count: int) or just problems: list
problems = validate_pod_health(core_v1, platform_namespaces, verbose=True)
problems, total = validate_ingress_configuration(networking_v1, platform_namespaces)
```

### Layer 2: Assertions (`lib/k8s_assertions.py`)
High-level wrappers that call validators and fail tests on errors. Handle logging internally.

```python
# Calls validator, logs results, calls pytest.fail() if problems found
assert_argocd_healthy(custom_api, namespace_filter=None, verbose=True)
assert_pods_healthy(core_v1, platform_namespaces, verbose=True)
assert_ingress_valid(networking_v1, platform_namespaces, verbose=True)
assert_certificates_ready(custom_api, cert_info_list, namespace='nonprod')
assert_tls_secrets_valid(core_v1, secret_info_list, namespace='nonprod')
assert_https_endpoints_valid(endpoint_info_list, validate_cert=True)
```

### Layer 3: Utils (`lib/k8s_utils.py`, `lib/test_utils.py`)
Utility functions for common operations.

```python
# K8s utils
lb_ip = get_ingress_load_balancer_ip(networking_v1, 'public', fail_on_none=True)
wait_for_certificate_ready(custom_api, cert_name, namespace, timeout=600)

# Test utils
print_section_header("STEP 1: Doing something")
display_progress_bar(wait_time=300, interval=15, description="Waiting...")
print_summary_list(items, title="Results")
```

### Layer 4: Domain Helpers
- **vault_helpers.py**: Vault client, secrets CRUD, context manager
- **github_helpers.py**: File creation, directory deletion for repos
- **port_forward.py**: Generic kubectl port-forward wrapper

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
    problems = validate_something(core_v1, platform_namespaces, verbose=True)
    
    if problems:
        pytest.fail(f"{len(problems)} issue(s) found:\n" + "\n".join(problems))
```

### GitOps Integration Test
```python
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
    # ... create apps in GitHub ...
    
    # Step 2: Wait for sync
    print_section_header("STEP 2: Waiting for GitOps Sync")
    display_progress_bar(wait_time=300, interval=15, description="Waiting...")
    
    # Step 3+: Validate using assertion functions
    print_section_header("STEP 3: Checking ArgoCD Status")
    assert_argocd_healthy(custom_api, verbose=True)
    
    print_section_header("STEP 4: Checking Pod Health")
    assert_pods_healthy(core_v1, platform_namespaces, verbose=True)
```

## Common Commands

```bash
# Run tests
make test              # Smoke tests in Docker
make gitops            # GitOps tests
make externalsecrets   # External Secrets test
make letsencrypt       # LetsEncrypt test
make ui                # UI tests

# Local development
make local-test        # Smoke tests locally
pytest tests/gitops/test_externalsecrets.py -v  # Single test

# Discovery
pytest --collect-only -v    # List all tests
pytest --markers            # Show all markers
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `CAPTAIN_DOMAIN` | Cluster domain (required for most tests) |
| `GITHUB_TOKEN` | GitHub PAT for GitOps tests |
| `TEMPLATE_REPO_URL` | Template repo URL for ephemeral repos |
| `DESTINATION_REPO_URL` | Target repo URL for test deployments |
| `WILDCARD_DNS_SERVICE` | DNS service for sslip.io-style domains |

## Vault Integration

Vault tests require terraform state at:
```
/workspaces/glueops/{captain_domain}/terraform/vault/configuration/terraform.tfstate
```

Root token extracted from `aws_s3_object.vault_access` resource.

## Code Style Guidelines

1. **Validators return problems, assertions fail tests** - Keep separation clean
2. **All assertion functions handle their own logging** - No duplicate logs in tests
3. **Use `verbose=True` parameter** - Functions log details when verbose
4. **Docstrings document what, why, and cluster impact** - Every test has comprehensive docstring
5. **Section headers for multi-step tests** - Use `print_section_header("STEP N: Description")`
6. **Fixture handles setup** - `ephemeral_github_repo` clears apps/ automatically

## Adding New Tests

1. Choose appropriate test directory (`smoke/`, `gitops/`, `ui/`)
2. Add pytest markers for categorization
3. Write comprehensive docstring with Validates/Fails/Cluster Impact sections
4. Use existing assertion functions from `lib/k8s_assertions.py`
5. Follow the test patterns above

## Debugging

```bash
# Verbose output
pytest tests/smoke/test_workloads.py -v -s

# Single test
pytest tests/smoke/test_workloads.py::test_pod_health -v

# With logging
pytest --log-cli-level=DEBUG -v
```

---

**Last Updated**: December 26, 2025
