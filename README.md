# GlueOps Test Suite

Comprehensive test suite for validating GlueOps PaaS platform deployments using pytest.

## Quick Start

```bash
make help         # Show all available commands
make test         # Run smoke tests (Docker)
make full         # Run full tests (Docker)
make local-test   # Run smoke tests locally
make local-full   # Run full tests locally
```

## Test Types

**Smoke Tests (Read-Only)** - Tagged with `@pytest.mark.smoke`:
- ArgoCD Application health
- Pod health (CrashLoopBackOff, OOMKilled, etc.)
- Failed Jobs (with optional exclusion patterns)
- Ingress validity (hosts, load balancer addresses)
- Ingress DNS resolution (configurable DNS server, default: 1.1.1.1)
- Ingress OAuth2 redirect validation (HTTP request verification)
- Alertmanager firing alerts
- Prometheus metrics existence (baseline comparison)
- Backup CronJob status

**Full Tests (Includes Write Operations)** - Tagged with `@pytest.mark.write`:
- All smoke tests
- Backup CronJob triggering and validation
- Vault secret creation (10 test secrets)

## Test Tags

Tests are tagged with pytest markers for selective execution:

- **`smoke`** - Smoke test suite (read-only)
- **`quick`** - Quick tests (<5s each)
- **`slow`** - Slow tests (>30s each)
- **`critical`** - Critical tests that must pass
- **`important`** - Important tests
- **`readonly`** - Tests that don't modify cluster
- **`write`** - Tests that create/modify resources
- **Component tags**: `argocd`, `workloads`, `vault`, `backup`, `observability`, `ingress`, `dns`, `oauth2`

## Usage

### Docker Execution (Default)

No local dependencies needed except Docker:

```bash
# Smoke tests (read-only)
make test

# Full tests (includes writes)
make full

# Quick tests only (<5s)
make quick

# Critical tests only
make critical

# Parallel execution (8 workers)
make parallel

# Verbose output
make verbose

# Generate HTML report
make report-html
```

### Local Execution

Requires Python 3.10+ and dependencies:

```bash
# Install dependencies
make local-install

# Run tests
make local-test       # Smoke tests
make local-full       # Full tests
make local-quick      # Quick tests
make local-critical   # Critical tests
make local-parallel   # Parallel (8 workers)
make local-verbose    # Verbose output
```

Or use pytest directly:

```bash
pytest -m smoke -v                    # Smoke tests
pytest -m "smoke or write" -v         # Full tests
pytest -m quick -v                    # Quick tests
pytest -m critical -v                 # Critical tests
pytest -m smoke -n 8 -v               # Parallel (8 workers)
pytest -m "smoke and not slow" -v     # Quick smoke tests
pytest tests/smoke/test_argocd.py -v  # Single test file
```

### Docker Execution

No local dependencies needed (except Docker):

```bash
make docker-test  # Smoke tests in Docker
make docker-full  # Full tests in Docker
```

The Docker commands automatically:
- Build the image if needed
- Copy your kubeconfig to the workspace (always fresh)
- Mount it securely (read-only)
- Mount workspace directory (for Vault terraform state access)
- Run tests with proper network access

### Manual Docker

```bash
make docker-build  # Build image

# Smoke tests
docker run --rm --network host \
  -v $(pwd)/kubeconfig:/kubeconfig:ro \
  -e KUBECONFIG=/kubeconfig \
  glueops-tests

# Full tests (needs workspace access for Vault terraform state)
docker run --rm --network host \
  -v $(pwd)/kubeconfig:/kubeconfig:ro \
  -v /workspaces/glueops:/workspaces/glueops:ro \
  -e KUBECONFIG=/kubeconfig \
  glueops-tests --full
```

## Pytest Command-Line Options

Standard pytest options:
```bash
pytest -m smoke -v                  # Run smoke tests, verbose
pytest -m "quick and critical" -v   # Combine markers
pytest -m "not slow" -v             # Exclude slow tests
pytest -n 8                         # Parallel (8 workers)
pytest -k "argocd or vault"         # Filter by test name
pytest --maxfail=3                  # Stop after 3 failures
```

Custom options:
- `--captain-domain DOMAIN` - Specify captain domain (default: nonprod.foobar.onglueops.rocks)
- `--namespace NAMESPACE` - Filter to specific namespace

Example:
```bash
pytest -m smoke --captain-domain=staging.example.com --namespace=glueops-core -v
```

## Discovering Tests

Use make commands (works in both Docker and locally):

```bash
# Docker (default) - no dependencies needed
make discover       # List all tests with descriptions
make markers        # Show all available markers
make fixtures       # Show all fixtures with docstrings

# Local (requires: make local-install)
make local-discover # List all tests with descriptions locally
make local-markers  # Show all available markers locally
make local-fixtures # Show all fixtures locally
```

Or use pytest directly (local only):
```bash
pytest --collect-only -v              # All tests with descriptions
pytest --collect-only -m quick        # Quick tests only
pytest --markers                      # Available markers
pytest --fixtures                     # Available fixtures
```

## Test Organization

### Smoke Tests (`tests/smoke/`)

- [test_argocd.py](tests/smoke/test_argocd.py) - ArgoCD Application health validation
- [test_workloads.py](tests/smoke/test_workloads.py) - Pod, Job, Ingress validation (DNS, OAuth2, Alertmanager)
  - OAuth2 exceptions: `oauth2-proxy`, `glueops-dex`
  - Passable alerts: `Watchdog`
  - Jobs with retries are allowed (failed + succeeded = OK)
- [test_observability.py](tests/smoke/test_observability.py) - Prometheus metrics baseline (24hr window)
- [test_backups.py](tests/smoke/test_backups.py) - Backup CronJob validation and triggering
- [test_vault.py](tests/smoke/test_vault.py) - Vault secret creation tests

### Test Categories (Markers)

Run `pytest --markers` to see all available markers with descriptions:

- `smoke` - Core smoke test suite
- `quick` - Fast tests (<5 seconds)
- `slow` - Slower tests (>5 seconds)
- `critical` - Must-pass critical tests
- `important` - Important validations
- `informational` - Info-only tests
- `readonly` - No cluster modifications
- `write` - Creates/modifies cluster resources
- Component markers: `argocd`, `workloads`, `vault`, `backup`, `observability`, `ingress`, `dns`, `oauth2`

## Prometheus Metrics Baseline

The test suite validates Prometheus metrics against a baseline:

**First Run**: Creates baseline in `baselines/prometheus-metrics-baseline.json`
```bash
make test  # Automatically creates baseline if missing
```

**Subsequent Runs**: Compares current metrics vs baseline
- **FAIL**: If baseline metrics are missing (regression detection)
- **INFO**: If new metrics appear (shown in verbose mode)

**Query Window**: 24 hours of metrics history
- Captures intermittent metrics (e.g., vault_expire_* during lease expiration)
- Ensures periodic and activity-based metrics are not missed

**Baseline Format**: Metric signatures with label keys only
```json
{
  "metric_signatures": [
    "metric_name{label1,label2,label3}",
    ...
  ]
}
```

**Management**:
```bash
make clean-baselines  # Remove baseline files
rm baselines/*.json   # Manual cleanup
```

**Note**: Baseline files are gitignored. Recreate after platform upgrades or when metrics intentionally change.

## Requirements

- Kubernetes cluster access (k3d, EKS, GKE, etc.)
- Valid kubeconfig at `~/.kube/config` or `$KUBECONFIG`
- For Vault tests: Terraform state at `{captain_domain}/terraform/vault/configuration/terraform.tfstate`

## Notes

- **Smoke tests** are read-only and safe for production
- **Full tests** create temporary resources (cleaned up automatically)
- **Parallel execution** (`-n 8`) significantly speeds up test runs
- **Docker execution** uses `--network host` for local cluster access
- Works with k3d, EKS, GKE, and any Kubernetes cluster
- Test discovery follows pytest conventions (`test_*.py` files)
- Use pytest markers (`-m`) for selective test execution
