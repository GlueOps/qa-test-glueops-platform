# GlueOps PaaS Testing Plan

Complete roadmap for platform testing and validation.

**Date:** December 24, 2025  
**Status:** Step 1 (Smoke Tests) - ✅ Implemented

---

## Overview

This plan outlines a comprehensive testing strategy for the GlueOps PaaS platform, covering:
- ArgoCD applications and GitOps workflows
- Kubernetes workload health
- Observability stack (Prometheus, Grafana, Loki)
- Networking and ingress
- Security and secrets management
- Backup and disaster recovery

---

## Step 1: Smoke Tests ✅ COMPLETED

**Priority:** Critical  
**Status:** Implemented with pytest in `tests/smoke/`

### Scope
Quick validation of critical platform components to ensure basic functionality.

### Tests Implemented
1. ✅ ArgoCD Applications - Check all Applications are Healthy and Synced
2. ✅ Pod Health - Scan for CrashLoopBackOff, ImagePullBackOff, OOMKilled, high restarts
3. ✅ Failed Jobs - Check Jobs status (allows retries if eventually succeeded)
4. ✅ Ingress Validation - Verify ingress hosts, load balancers, DNS resolution
5. ✅ OAuth2 Protection - Validate OAuth2 annotations and HTTP redirects
6. ✅ Alertmanager Alerts - Check for unexpected firing alerts
7. ✅ Prometheus Metrics - Baseline comparison (24-hour query window)
8. ✅ Backup CronJobs - Validate CronJob status and execution
9. ✅ Vault Secrets - Test secret creation and access

### Usage
```bash
# Docker (default)
make test          # Smoke tests
make quick         # Quick tests only
make full          # Full tests (includes writes)

# Local
make local-test    # Smoke tests locally
pytest -m smoke -v # Direct pytest

# Discovery
make discover      # List all tests
make markers       # Show markers
```

### Rationale
ArgoCD Applications provide the primary health indicator - if all apps are Healthy/Synced, most platform components are working. Additional checks catch edge cases ArgoCD might miss (pod crashes, job failures, PVC issues).

---

## Step 2: ArgoCD-Specific Validation

**Priority:** High  
**Status:** Planned

### Scope
Deep validation of ArgoCD configurations and GitOps workflows beyond basic health checks.

### Tests to Implement
1. **Application Sync Windows** - Verify sync windows configured correctly
2. **App-of-Apps Pattern** - Validate platform app generates all expected child apps
3. **Sync Hooks** - Test PreSync/Sync/PostSync/SyncFail hooks execute
4. **Resource Tracking** - Verify application owns all expected resources
5. **AppProject RBAC** - Validate tenant isolation (nonprod project restrictions)
6. **Repository Access** - Confirm ArgoCD can access all configured Git repos
7. **Helm Values Overrides** - Check custom values applied correctly
8. **ApplicationSet Generation** - Verify ApplicationSet generates apps from Git discovery
9. **Notification Integration** - Test ArgoCD notifications (if configured)
10. **SSO/OIDC Login** - Validate Dex integration for authentication

### Implementation Notes
- Query ArgoCD API directly via REST or CLI
- Test tenant namespace isolation (can't deploy to glueops-core)
- Validate sync waves and resource ordering
- Check for orphaned resources not tracked by ArgoCD

---

## Step 3: Kubernetes Workload Health

**Priority:** High  
**Status:** Partially implemented (basic pod checks in smoke tests)

### Scope
Comprehensive validation of Kubernetes resources beyond pod status.

### Tests to Implement
1. **Resource Quotas** - Check namespaces not hitting quotas
2. **Node Health** - Verify nodes Ready, no pressure (disk, memory, PID)
3. **Service Endpoints** - Confirm services have healthy endpoints
4. **StatefulSet Rollout** - Validate StatefulSets fully rolled out
5. **DaemonSet Coverage** - Verify DaemonSets running on expected nodes
6. **HPA Status** - Check HorizontalPodAutoscalers within bounds
7. **NetworkPolicy** - Validate network policies applied (if used)
8. **PodDisruptionBudgets** - Confirm PDBs configured for HA components
9. **Init Container Failures** - Catch init container crashes
10. **Container Resource Limits** - Warn on containers without limits

### Implementation Notes
- Extend smoke tests with more detailed resource checks
- Add node-level validation (disk space, kubelet health)
- Check for overcommitted nodes
- Validate anti-affinity rules for HA components

---

## Step 4: Observability Stack Validation

**Priority:** High  
**Status:** Planned

### Scope
Validate monitoring, logging, and alerting infrastructure is functional.

### Tests to Implement

#### Prometheus
1. **Targets Up** - Query Prometheus API for target health
2. **Scrape Errors** - Check for persistent scrape failures
3. **Alert Rules Loaded** - Verify PrometheusRule CRDs loaded
4. **Alertmanager Integration** - Test alert routing (if configured)
5. **Remote Write** - Validate remote write to external systems (if used)
6. **TSDB Health** - Check database size, compaction status
7. **Query Performance** - Run sample queries, check latency

#### Grafana
1. **Datasource Health** - Verify Prometheus/Loki datasources connected
2. **Dashboard Load** - Test loading key dashboards
3. **OAuth Integration** - Validate GitHub OAuth login
4. **Provisioning** - Confirm dashboards/datasources auto-provisioned

#### Loki
1. **Ingester Health** - Check all ingesters ready
2. **Log Ingestion** - Query recent logs from all namespaces
3. **S3 Backend** - Verify logs persisting to S3
4. **Compactor Status** - Check log compaction running
5. **Query Performance** - Test log queries return timely

#### Network Exporter
1. **Connectivity Tests** - Verify network-exporter probes passing
2. **DNS Resolution** - Check internal/external DNS working
3. **Egress Connectivity** - Validate outbound connections

### Implementation Notes
- Query Prometheus API: `GET /api/v1/targets`, `/api/v1/rules`
- Use LogQL for Loki queries
- Test actual log ingestion by creating test pod
- Validate alert rules syntax

---

## Step 5: Backup & Disaster Recovery

**Priority:** Medium  
**Status:** Planned

### Scope
Validate backup infrastructure and test restore procedures.

### Tests to Implement

#### Vault Backups
1. **Backup Job Success** - Check vault-backup CronJob recent runs succeeded
2. **S3 Backup Exists** - Verify backup files in S3 bucket
3. **Backup Validator** - Confirm vault-backup-validator job passed
4. **Restore Test** - Perform vault restore in test namespace
5. **Backup Encryption** - Validate backups are encrypted
6. **Retention Policy** - Check old backups cleaned up per policy

#### Certificate Backups
1. **Cert Backup Job** - Verify cert-backup CronJob running every 6 hours
2. **S3 Cert Backup** - Confirm cert backups in S3
3. **Restore Test** - Test restoring certificates
4. **Secret Backup** - Verify TLS secrets backed up

#### ArgoCD GitOps
1. **Git Repository Backup** - Validate all ArgoCD repos have backups/mirrors
2. **Declarative Restore** - Test re-deploying platform from Git

### Implementation Notes
- Test restore in isolated namespace
- Validate backup encryption keys accessible
- Check S3 bucket versioning enabled
- Test disaster recovery runbook

---

## Step 6: Networking & Security

**Priority:** Medium  
**Status:** Planned

### Scope
Validate networking infrastructure and security configurations.

### Tests to Implement

#### Ingress & DNS
1. **Ingress Controllers** - Verify NGINX ingress pods ready (2 replicas HA)
2. **External DNS** - Check Route53 records created for ingresses
3. **DNS Propagation** - Validate DNS resolves correctly
4. **TLS Termination** - Confirm HTTPS working on all ingresses
5. **Certificate Renewal** - Test cert-manager auto-renewal
6. **Ingress Rules** - Validate routing rules applied correctly

#### Authentication & Authorization
1. **OAuth2 Proxy** - Verify authentication proxy working
2. **Dex OIDC** - Test SSO login flow
3. **Vault OIDC** - Validate Vault authentication methods
4. **GitHub OAuth** - Test GitHub integration (Grafana, ArgoCD)
5. **Kubernetes RBAC** - Verify service account permissions
6. **Vault Policies** - Test policy enforcement (super_admin, admin, editor, reader)

#### Security
1. **Pod Security Standards** - Check PSS/PSA enforcement (if enabled)
2. **Network Policies** - Validate traffic isolation (if used)
3. **Secret Encryption** - Verify etcd encryption at rest (if configured)
4. **Image Pull Secrets** - Check private registry access
5. **Vulnerability Scanning** - Run container image scans (future)

### Implementation Notes
- Test DNS resolution from within cluster and externally
- Validate OAuth flows without manual interaction
- Check Vault audit logs enabled
- Test least-privilege service accounts

---

## Implementation Priorities

### Phase 1 (Immediate)
- [x] Step 1: Smoke Tests

### Phase 2 (Next Sprint)
- [ ] Step 2: ArgoCD-Specific Validation
- [ ] Step 3: Extended Kubernetes Workload Health

### Phase 3 (Following Sprint)
- [ ] Step 4: Observability Stack Validation
- [ ] Step 5: Backup & Disaster Recovery

### Phase 4 (Future)
- [ ] Step 6: Networking & Security
- [ ] Performance Tests
- [ ] Chaos Engineering

---

## Testing Framework Recommendations

### Technology Stack
1. **Python + pytest** - Current choice, integrates well with tools-api
   - Pros: Flexible, good Kubernetes library, easy CI/CD integration
   - Cons: Requires Python runtime

2. **Bash + kubectl** - Simple scripts
   - Pros: No dependencies, fast
   - Cons: Limited error handling, harder to maintain

3. **Chainsaw** - Kubernetes-native testing framework
   - Pros: Declarative, designed for K8s
   - Cons: New tool, learning curve

4. **Sonobuoy** - Kubernetes conformance testing
   - Pros: Standard tool, comprehensive
   - Cons: Heavy, more suited for cluster validation

### Recommended Approach
Continue with **Python + pytest** for:
- Consistency with existing tools-api codebase
- Flexibility for complex validation logic
- Easy JSON output for CI/CD integration
- Kubernetes client library feature-rich

---

## CI/CD Integration Strategy

### GitHub Actions Workflow (Recommended)
```yaml
name: Platform Smoke Tests
on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:  # Manual trigger

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
      
      - name: Upload HTML report
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: test-report
          path: test-fun/reports/
      
      - name: Upload JSON report  
        if: always()
        run: |
          cd test-fun
          make report-json
        
      - name: Upload JSON results
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: test-results-json
          path: test-fun/reports/report.json
```

### ArgoCD Hooks (Alternative)
- Add PreSync/PostSync hooks to platform Application
- Run smoke tests after sync completes
- Block deployment if tests fail

---

## Metrics & Monitoring

### Test Metrics to Track
1. **Test Success Rate** - % of test runs passing
2. **Test Duration** - Time to complete full suite
3. **Failure Frequency** - Which tests fail most often
4. **MTTR** - Mean time to resolve test failures
5. **Coverage** - % of platform components tested

### Alerting
- Alert on smoke test failures (via Opsgenie integration)
- Dashboard showing test history in Grafana
- Trend analysis for flaky tests

---

## Future Enhancements

1. **Performance Tests** - Ingress throughput, Prometheus query latency, API response times
2. **Chaos Engineering** - Pod kills, node failures, network partitions (Chaos Mesh/Litmus)
3. **Load Tests** - Application workload stress testing
4. **Upgrade Tests** - Platform component upgrade validation with rollback
5. **Multi-Cluster** - Test across multiple environments (nonprod, prod)
6. **Security Scanning** - Trivy, Falco runtime security
7. **Cost Validation** - Resource usage vs budget
8. **SLO Validation** - Test against defined SLOs/SLAs

---

## References

- **Platform Config:** `nonprod.foobar.onglueops.rocks/platform.yaml`
- **ArgoCD Manifests:** `nonprod.foobar.onglueops.rocks/manifests/`
- **Tools API:** `tools-api/`
- **Versions:** `VERSIONS/glueops.yaml`, `VERSIONS/aws.yaml`
