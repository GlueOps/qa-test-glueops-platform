# Troubleshooting Guide

Common issues and solutions when working with the GlueOps test suite.

## Quick Fixes

| Issue | Quick Fix |
|-------|-----------|
| Import errors | Use `from tests.helpers.X import Y` (not `from lib.*`) |
| Type errors | Run `make ci` before testing |
| Missing fixtures | Check you have required env vars in `.env` |
| Browser tests fail | Run `./start_chrome.sh` first |
| GitOps tests timeout | Check `GITHUB_TOKEN` has repo permissions |

---

## Static Analysis Issues

### ModuleNotFoundError: No module named 'lib'

**Symptom:**
```
ModuleNotFoundError: No module named 'lib'
```

**Cause:** Old import path from before December 2025 refactoring.

**Solution:** Update imports:
```python
# OLD (broken)
from lib.k8s_validators import validate_pod_health

# NEW (correct)
from tests.helpers.k8s import validate_pod_health
```

---

### Type errors in mypy

**Symptom:**
```
error: Argument "timeout" has incompatible type "str"; expected "int"
```

**Solution:** Run `make ci` before testing to catch type issues early.

Common fixes:
- Add `Optional[]` for nullable parameters
- Use correct types from function signatures
- Import types from `typing` module

---

### Pylint: unused-import

**Symptom:**
```
W0611: Unused import X from Y
```

**Solution:** Remove unused imports or use them. If import is needed for side effects:
```python
from tests.helpers import assertions  # pylint: disable=unused-import
```

---

## Kubernetes Connection Issues

### Connection refused / No route to host

**Symptom:**
```
kubernetes.client.exceptions.ApiException: (None)
```

**Causes:**
1. Kubeconfig not set or invalid
2. Cluster not accessible from test environment
3. VPN not connected (for remote clusters)

**Solutions:**
```bash
# Check kubeconfig is set
echo $KUBECONFIG
kubectl cluster-info

# Verify connectivity
kubectl get namespaces

# For Docker tests, ensure host network
docker run --network host ...
```

---

### Namespace not found

**Symptom:**
```
No namespaces found matching 'glueops-core*'
```

**Cause:** Either wrong cluster or platform not deployed.

**Solution:**
```bash
# List available namespaces
kubectl get ns | grep glueops

# Specify exact namespace
pytest -m smoke --namespace=glueops-core -v
```

---

## Port Forwarding Issues

### Address already in use

**Symptom:**
```
error: unable to listen on any of the requested ports: [{8200 8200}]
```

**Cause:** Previous port-forward still running.

**Solution:**
```bash
# Find and kill existing port-forwards
pkill -f "kubectl port-forward"

# Or use a different port (helpers will find available port)
```

---

### Port forward connection refused

**Symptom:**
```
ConnectionRefusedError: [Errno 111] Connection refused
```

**Causes:**
1. Service doesn't exist in expected namespace
2. Pod not ready
3. Port number mismatch

**Solution:**
```bash
# Verify service exists
kubectl get svc -n glueops-core-vault

# Check pod is running
kubectl get pods -n glueops-core-vault

# Manual port-forward to debug
kubectl port-forward -n glueops-core-vault svc/vault 8200:8200
```

---

## GitHub/GitOps Issues

### Repository creation failed

**Symptom:**
```
github.GithubException.UnknownObjectException: 404 {"message": "Not Found"}
```

**Causes:**
1. `GITHUB_TOKEN` doesn't have repo permissions
2. Organization doesn't exist
3. Template repo doesn't exist

**Solution:**
1. Create new token at https://github.com/settings/tokens
2. Include `repo` scope (full control of private repos)
3. Verify `TEMPLATE_REPO_URL` exists and is accessible

---

### ApplicationSet not syncing

**Symptom:**
```
ApplicationSet did not create/sync N apps within timeout
```

**Causes:**
1. ArgoCD ApplicationSet controller not running
2. Repository not added to ArgoCD
3. YAML syntax errors in committed files

**Solutions:**
```bash
# Check ApplicationSet controller
kubectl get pods -n argocd | grep applicationset

# Check ArgoCD repos
kubectl get applications -n argocd

# Check git commit was successful
# (look for create_github_file output in test logs)
```

---

### Fixture app count mismatch

**Symptom:**
```
Waiting for 3 apps but found 6
```

**Cause:** Forgot to include `fixture_app_count` in expected count.

**Solution:**
```python
# WRONG
expected_count = num_apps

# CORRECT
from tests.helpers.argocd import calculate_expected_app_count
expected_count = calculate_expected_app_count(captain_manifests, num_apps)
```

---

## UI/Browser Issues

### Browser connection failed

**Symptom:**
```
playwright._impl._errors.Error: connect ECONNREFUSED 127.0.0.1:9222
```

**Cause:** Chrome not running with remote debugging enabled.

**Solution:**
```bash
# Start Chrome with debugging
./start_chrome.sh

# Or manually:
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug
```

---

### OAuth flow fails

**Symptom:**
```
TimeoutError: Waiting for selector "#login_field" timed out
```

**Causes:**
1. Already logged into GitHub (cookies persisted)
2. GitHub changed their login page
3. Network timeout

**Solutions:**
```bash
# Clear Chrome data
rm -rf /tmp/chrome-debug
./start_chrome.sh

# Or use BrowserBase (fresh browser each time)
export USE_BROWSERBASE=true
```

---

### 2FA/OTP code rejected

**Symptom:**
```
Incorrect verification code
```

**Causes:**
1. `GITHUB_OTP_SECRET` is wrong
2. System clock is off (TOTP is time-based)
3. Secret is not base32 encoded

**Solutions:**
```bash
# Verify time is synced
timedatectl

# Generate code manually to test
python -c "import pyotp; print(pyotp.TOTP('YOUR_SECRET').now())"

# Secret should be 16+ chars, all caps A-Z and 2-7
echo $GITHUB_OTP_SECRET
```

---

### Visual regression false positives

**Symptom:**
```
Visual regression detected in dashboard
```

**Causes:**
1. Dynamic content (timestamps, counts)
2. Different screen resolution
3. Legitimate UI changes

**Solutions:**
```bash
# Update baselines if change is intentional
make update-baselines

# Check the diff in reports/visual-diffs/
ls -la reports/visual-diffs/

# Adjust threshold if needed
screenshots.capture(..., threshold=0.05)  # 5% difference allowed
```

---

## Vault Issues

### Vault authentication failed

**Symptom:**
```
hvac.exceptions.Forbidden: Permission denied
```

**Cause:** Root token from terraform state is invalid or expired.

**Solution:**
```bash
# Verify terraform state exists
ls /workspaces/glueops/*/terraform/vault/configuration/terraform.tfstate

# Check token in state (look for vault_access)
cat terraform.tfstate | jq '.resources[] | select(.name=="vault_access")'
```

---

### Terraform state not found

**Symptom:**
```
FileNotFoundError: terraform.tfstate
```

**Cause:** `CAPTAIN_DOMAIN` doesn't match directory structure.

**Solution:**
```bash
# List available captain domains
ls -d /workspaces/glueops/*/terraform/vault/

# Set correct domain
export CAPTAIN_DOMAIN=nonprod.example.onglueops.rocks
```

---

## DNS Issues

### DNS resolution timeout

**Symptom:**
```
dns.exception.Timeout: The DNS query timed out
```

**Cause:** DNS server (1.1.1.1) not reachable or slow.

**Solution:**
```bash
# Test DNS manually
dig @1.1.1.1 argocd.nonprod.example.com

# Check external-dns is running
kubectl get pods -n glueops-core | grep external-dns
```

---

### DNS mismatch with load balancer

**Symptom:**
```
DNS resolves to 1.2.3.4 but ingress LB is 5.6.7.8
```

**Causes:**
1. DNS record not updated yet (TTL)
2. Wrong hosted zone
3. external-dns not running

**Solutions:**
```bash
# Wait for DNS propagation (up to TTL, often 300s)
sleep 300

# Check external-dns logs
kubectl logs -n glueops-core deployment/external-dns

# Verify ingress has correct LB
kubectl get ingress -A -o wide
```

---

## Docker Issues

### Permission denied on kubeconfig

**Symptom:**
```
PermissionError: [Errno 13] Permission denied: '/kubeconfig'
```

**Solution:**
```bash
# Copy kubeconfig to project directory
cp ~/.kube/config ./kubeconfig
chmod 644 ./kubeconfig

# Or use Makefile (handles this automatically)
make test
```

---

### Network host not working

**Symptom:**
```
Cluster connection works locally but not in Docker
```

**Solution:**
Docker must use host networking for local cluster access:
```bash
docker run --network host ...
```

For remote clusters, ensure kubeconfig has correct external URL.

---

## Still Stuck?

1. **Check the logs:**
   ```bash
   pytest -v -s --log-cli-level=DEBUG
   ```

2. **Run a minimal test:**
   ```bash
   pytest tests/smoke/test_argocd.py -v
   ```

3. **Verify environment:**
   ```bash
   cat .env
   kubectl cluster-info
   echo $CAPTAIN_DOMAIN
   ```

4. **Check AGENTS.md** for comprehensive patterns and examples.

---

**Last Updated**: January 2, 2026
