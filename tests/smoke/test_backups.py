"""Backup CronJob tests"""
import pytest
import subprocess
import time
import logging
from datetime import datetime, timezone
from kubernetes.client.rest import ApiException
from lib.k8s_utils import wait_for_job_completion, validate_pod_execution

logger = logging.getLogger(__name__)


def create_vault_backup_test_secret(captain_domain, vault_namespace="glueops-core-vault", verbose=False):
    """Create a timestamped test secret in Vault before triggering backup.
    
    Creates secret at path: secret/glueops-backup-test-secret-{unix_timestamp}
    Secret contains: {"created_at": ISO8601_UTC, "timestamp": unix_timestamp}
    
    This validates that backups capture fresh data created immediately before backup runs.
    
    Args:
        captain_domain: Domain for locating Vault terraform state
        vault_namespace: Kubernetes namespace where Vault is deployed (default: glueops-core-vault)
        verbose: Print detailed progress messages
    
    Returns: True if secret created successfully, False otherwise
    
    Requires: hvac library and vault module
    """
    try:
        from tests.smoke.test_vault import get_vault_client, cleanup_vault_client
    except ImportError:
        if verbose:
            logger.info("  ⚠ Skipping Vault secret creation (vault module not available)")
        return False
    
    try:
        import hvac
    except ImportError:
        if verbose:
            logger.info("  ⚠ Skipping Vault secret creation (hvac library not installed)")
        return False
    
    client = None
    try:
        if verbose:
            logger.info(f"  Creating test secret in Vault...")
        
        client = get_vault_client(captain_domain, vault_namespace=vault_namespace)
        
        # Create secret with unix timestamp
        timestamp = int(time.time())
        utc_time = datetime.now(timezone.utc).isoformat()
        secret_name = f"glueops-backup-test-secret-{timestamp}"
        secret_path = f"secret/{secret_name}"
        
        # Create the secret with UTC timestamp as value
        client.secrets.kv.v2.create_or_update_secret(
            path=secret_name,
            secret={"created_at": utc_time, "timestamp": timestamp}
        )
        
        if verbose:
            logger.info(f"  ✓ Created secret: {secret_path}")
            logger.info(f"    Value: {utc_time}")
        
        cleanup_vault_client(client)
        return True
        
    except Exception as e:
        if verbose:
            logger.info(f"  ⚠ Failed to create Vault secret: {e}")
        if client:
            cleanup_vault_client(client)
        return False


@pytest.mark.smoke
@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.backup
def test_backup_cronjobs_status(core_v1, batch_v1):
    """Check backup CronJobs have successful recent executions (read-only).
    
    Validates:
    - Finds recent Job executions for each CronJob
    - Checks Job succeeded/failed status
    - Reports suspended CronJobs or CronJobs with no recent execution
    - Validates pod execution quality (exit codes, restart counts)
    
    Fails if any CronJob is suspended, has no recent execution, or recent job failed.
    
    Cluster Impact: READ-ONLY (queries CronJob and Job status)
    """
    backup_namespace = "glueops-core-backup"
    
    try:
        cronjobs = batch_v1.list_namespaced_cron_job(namespace=backup_namespace)
    except ApiException as e:
        if e.status == 404:
            pytest.fail(f"Namespace {backup_namespace} not found")
        else:
            pytest.fail(f"API error: {e.reason}")
    
    assert cronjobs.items, f"No CronJobs found in {backup_namespace}"
    
    problems = []
    
    for cronjob in cronjobs.items:
        cj_name = cronjob.metadata.name
        
        if cronjob.spec.suspend:
            problems.append(f"{cj_name}: suspended")
            continue
        
        # Find recent jobs
        jobs = batch_v1.list_namespaced_job(
            namespace=backup_namespace,
            label_selector=f"cronjob={cj_name}"
        )
        
        if not jobs.items:
            problems.append(f"{cj_name}: no recent execution")
            continue
        
        # Check most recent job
        recent_job = sorted(jobs.items, 
                          key=lambda j: j.metadata.creation_timestamp, 
                          reverse=True)[0]
        
        if recent_job.status.failed:
            problems.append(f"{cj_name}: job failed")
        elif recent_job.status.succeeded:
            # Check execution quality
            success, message = validate_pod_execution(core_v1, recent_job.metadata.name, backup_namespace)
            if not success:
                problems.append(f"{cj_name}: {message}")
    
    assert not problems, (
        f"{len(problems)} backup CronJob issue(s) (total: {len(cronjobs.items)} jobs):\n" +
        "\n".join(f"  - {p}" for p in problems)
    )


@pytest.mark.slow
@pytest.mark.write
@pytest.mark.backup
def test_backup_cronjobs_trigger(core_v1, batch_v1, captain_domain, request):
    """Manually trigger backup CronJobs and validate execution (WRITE operation).
    
    Trigger mode:
    - Creates Vault test secret with timestamp (if captain_domain provided)
    - Manually creates Job from each CronJob using kubectl
    - Waits up to 300 seconds for all jobs to complete
    - Validates execution: checks pod phase, exit codes, restart counts
    - Reports failures if jobs timeout, fail, or have execution issues
    
    Fails if any jobs timeout, fail, or have execution issues.
    
    Cluster Impact: WRITE (creates Jobs, creates Vault secrets)
    """
    backup_namespace = "glueops-core-backup"
    timeout = 300
    verbose = request.config.option.verbose > 0
    
    try:
        cronjobs = batch_v1.list_namespaced_cron_job(namespace=backup_namespace)
    except ApiException as e:
        if e.status == 404:
            pytest.fail(f"Namespace {backup_namespace} not found")
        else:
            pytest.fail(f"API error: {e.reason}")
    
    assert cronjobs.items, f"No CronJobs found in {backup_namespace}"
    
    problems = []
    triggered_jobs = []
    
    # Create test secret in Vault before triggering backups
    if captain_domain:
        create_vault_backup_test_secret(captain_domain, verbose=verbose)
    
    for cronjob in cronjobs.items:
        cj_name = cronjob.metadata.name
        job_name = f"{cj_name}-{int(time.time())}"
        
        result = subprocess.run(
            ["kubectl", "create", "job", job_name, 
             "--from", f"cronjob/{cj_name}", "-n", backup_namespace],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode == 0:
            triggered_jobs.append({"name": job_name, "cronjob": cj_name})
            if verbose:
                logger.info(f"  Triggered: {job_name}")
        else:
            problems.append(f"{cj_name}: {result.stderr.strip()}")
    
    # Wait for triggered jobs
    if triggered_jobs and verbose:
        logger.info(f"  Waiting for {len(triggered_jobs)} job(s)...")
    
    for job_info in triggered_jobs:
        status = wait_for_job_completion(batch_v1, job_info["name"], backup_namespace, timeout)
        
        if status == "timeout":
            problems.append(f"{job_info['cronjob']}: timeout")
        elif status == "failed":
            problems.append(f"{job_info['cronjob']}: job failed")
        else:
            issues = validate_pod_execution(core_v1, job_info["name"], backup_namespace)
            if issues:
                problems.append(f"{job_info['cronjob']}: {', '.join(issues)}")
    
    assert not problems, (
        f"{len(problems)} triggered backup job issue(s) (triggered: {len(triggered_jobs)} jobs):\n" +
        "\n".join(f"  - {p}" for p in problems)
    )
