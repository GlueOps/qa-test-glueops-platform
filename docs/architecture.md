# Architecture

Overview of the test suite architecture, design decisions, and component relationships.

## Directory Structure

```
qa-test-glueops-platform/
├── tests/
│   ├── conftest.py               # Main fixtures orchestrator
│   ├── conftest_k8s.py           # Kubernetes client fixtures
│   ├── conftest_github.py        # GitHub/GitOps fixtures
│   ├── conftest_browser.py       # Browser/UI fixtures
│   ├── conftest_services.py      # Service connection fixtures
│   ├── conftest_manifests.py     # Captain manifests fixtures
│   │
│   ├── helpers/                  # Consolidated helper library
│   │   ├── __init__.py           # Re-exports common utilities
│   │   ├── argocd.py             # ArgoCD-specific operations
│   │   ├── assertions.py         # pytest assertion wrappers
│   │   ├── browser.py            # Playwright browser helpers
│   │   ├── github.py             # GitHub API operations
│   │   ├── k8s.py                # Kubernetes validators
│   │   ├── manifests.py          # Manifest generation
│   │   ├── port_forward.py       # kubectl port-forward wrapper
│   │   ├── utils.py              # Progress bars, formatting
│   │   └── vault.py              # Vault client operations
│   │
│   ├── templates/                # YAML templates for test apps
│   │   ├── __init__.py           # load_template() function
│   │   ├── http-debug-app-values.yaml
│   │   ├── externalsecrets-app-values.yaml
│   │   ├── letsencrypt-app-values.yaml
│   │   ├── _test_smoke_template.py
│   │   ├── _test_gitops_template.py
│   │   └── _test_ui_template.py
│   │
│   ├── smoke/                    # Read-only smoke tests
│   ├── gitops/                   # GitOps integration tests
│   ├── ui/                       # Browser automation tests
│   └── integration/              # Integration tests (future)
│
├── baselines/                    # Visual regression baselines
├── reports/                      # Test output (gitignored)
├── docs/                         # Reference documentation
│
├── pytest.ini                    # Pytest configuration
├── Makefile                      # Build automation
├── requirements.txt              # Python dependencies
└── Dockerfile                    # CI/CD container
```

## Design Principles

### 1. Separation of Validators and Assertions

**Validators** (`tests/helpers/k8s.py`, etc.):
- Return lists of problems found
- Never call `pytest.fail()`
- Can be used for fine-grained control
- Reusable across different contexts

```python
# Validator returns problems
problems = validate_pod_health(core_v1, namespaces)
# Returns: ["pod-x: CrashLoopBackOff", "pod-y: OOMKilled"]
```

**Assertions** (`tests/helpers/assertions.py`):
- Wrap validators with logging
- Call `pytest.fail()` on errors
- Simpler API for tests
- Handle all error formatting

```python
# Assertion handles everything
assert_pods_healthy(core_v1, namespaces)
# Logs progress, fails if problems found
```

### 2. Fixture Composition

Fixtures are split across multiple `conftest_*.py` files by domain:

| File | Domain | Fixtures |
|------|--------|----------|
| `conftest.py` | Orchestration | Imports all, CLI options |
| `conftest_k8s.py` | Kubernetes | `core_v1`, `batch_v1`, etc. |
| `conftest_github.py` | GitHub | `ephemeral_github_repo` |
| `conftest_browser.py` | Browser | `page`, `authenticated_*_page` |
| `conftest_services.py` | Services | `vault_client` |
| `conftest_manifests.py` | Manifests | `captain_manifests` |

### 3. Template-Based Test Creation

Test templates in `tests/templates/` provide:
- Copy-paste ready boilerplate
- Correct marker combinations
- Docstring patterns
- Common import statements

Users copy and customize rather than writing from scratch.

### 4. Unconditional Logging

All helper functions log their operations unconditionally:
- No `verbose=True` parameters
- Always shows what's being checked
- Easier debugging in CI/CD
- Consistent output format

### 5. Environment-Based Configuration

Configuration via environment variables (`.env` file):
- `CAPTAIN_DOMAIN` - Target cluster
- `GITHUB_TOKEN` - GitHub API access
- `GITHUB_USERNAME/PASSWORD/OTP_SECRET` - OAuth credentials
- `TEMPLATE_REPO_URL` - GitOps template source

CLI options (`--captain-domain`, `--namespace`) override env vars.

## Test Flow

### Smoke Test Flow

```
1. Load kubeconfig
2. Create K8s API clients (fixtures)
3. Discover platform namespaces
4. For each test:
   a. Call validator function
   b. Collect problems
   c. Assert no problems (or report failures)
```

### GitOps Test Flow

```
1. Create ephemeral GitHub repo from template
2. Clear apps/ directory
3. Deploy captain_manifests fixture apps (3 apps)
4. For each test:
   a. Create app YAML in repo
   b. Wait for ArgoCD sync
   c. Validate deployed resources
5. Cleanup: Delete ephemeral repo
```

### UI Test Flow

```
1. Connect to Chrome via CDP (localhost:9222)
2. Create incognito browser context
3. For each test:
   a. Navigate to service URL
   b. Handle GitHub OAuth if needed
   c. Interact with page
   d. Capture screenshots
   e. Compare to baselines
4. Cleanup: Close context
```

## Component Dependencies

```
┌─────────────────────────────────────────────────────────────┐
│                        Test Files                           │
│  tests/smoke/    tests/gitops/    tests/ui/                │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    tests/helpers/                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │assertions│ │   k8s    │ │  github  │ │ browser  │ ...   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘       │
└───────┼────────────┼────────────┼────────────┼──────────────┘
        │            │            │            │
        ▼            ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────┐
│                      Fixtures                               │
│  conftest_k8s.py  conftest_github.py  conftest_browser.py  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  External Services                          │
│  Kubernetes API    GitHub API    Chrome CDP    Vault API   │
└─────────────────────────────────────────────────────────────┘
```

## Marker Categories

| Category | Purpose | Examples |
|----------|---------|----------|
| **Suite** | Which test suite | `smoke`, `gitops`, `ui` |
| **Speed** | Execution time | `quick` (<5s), `slow` (>30s) |
| **Priority** | Importance | `critical`, `important`, `informational` |
| **Impact** | Cluster modification | `readonly`, `write` |
| **Component** | What's tested | `argocd`, `vault`, `ingress` |
| **Special** | Behavior flags | `authenticated`, `visual`, `flaky` |

## Static Analysis

Two tools ensure code quality:

**mypy** (Type Checking):
- Configured in `mypy.ini`
- Per-module import ignores (not blanket `--ignore-missing-imports`)
- Catches type mismatches, wrong signatures

**pylint** (Code Analysis):
- Catches unused imports, undefined variables
- Style consistency
- Potential bugs

Run both with:
```bash
make ci  # Equivalent to: make lint && make typecheck
```

## ADR: Why Consolidated helpers/

**Decision**: Consolidate all helper modules into `tests/helpers/`.

**Context**: Previously, helpers were scattered across:
- `lib/k8s_helpers.py`
- `lib/k8s_validators.py`
- `lib/k8s_utils.py`
- `tests/ui/helpers.py`

**Rationale**:
1. Single import location: `from tests.helpers.X import Y`
2. Clear separation: validators vs assertions
3. Proper Python package structure
4. No `sys.path` manipulation needed

**Status**: Implemented December 2025

---

**Last Updated**: January 2, 2026
