"""Observability and metrics tests"""
import pytest
import json
import os
import time
from pathlib import Path
import requests
import logging

logger = logging.getLogger(__name__)

# Percentage of baseline metrics allowed to be missing before test fails.
# If the fraction of unexpected missing metrics is below this threshold,
# they are logged as warnings instead of causing a failure.
MISSING_METRICS_TOLERANCE_PCT = 10.0

# Whitelist of metrics that are expected to be missing intermittently
IGNORABLE_MISSING_METRICS = [
    "vault_identity_entity_creation",
    "vault_identity_upsert_entity_txn",
    "vault_identity_upsert_entity_txn_count",
    "vault_identity_upsert_entity_txn_sum",
    "vault_storage_packer_put_bucket",
    "vault_storage_packer_put_bucket_count",
    "vault_storage_packer_put_bucket_sum",
    "vault_storage_packer_put_item",
    "vault_storage_packer_put_item_count",
    "vault_storage_packer_put_item_sum"
]


def query_all_metrics(prometheus_url):
    """Query Prometheus and return set of metric names (deduplicated)
    
    Queries last 24 hours of metrics using series endpoint to capture
    metrics that may not be present at exact instant of query.
    Returns deduplicated set of metric names only (ignoring labels).
    """
    # Query all time series from last 24 hours (86400 seconds)
    # Longer window captures intermittent metrics (e.g., vault_expire_* only appears during lease expiration)
    end_time = time.time()
    start_time = end_time - (24 * 60 * 60)  # 24 hours ago
    
    response = requests.get(
        f"{prometheus_url}/api/v1/series",
        params={
            "match[]": "{__name__=~\".+\"}",
            "start": start_time,
            "end": end_time
        },
        timeout=30
    )
    
    if response.status_code != 200:
        raise Exception(f"Prometheus API returned status {response.status_code}")
    
    data = response.json()
    if data.get('status') != 'success':
        raise Exception(f"Prometheus query failed: {data.get('error', 'unknown error')}")
    
    # Use set for automatic deduplication of metric names
    metrics = set()
    for series in data['data']:
        metric_name = series.get('__name__', '')
        if metric_name:
            metrics.add(metric_name)
    
    return metrics


def create_baseline(metrics, baseline_file, captain_domain, prometheus_url):
    """Create baseline file with metric names (local file operation only)"""
    from datetime import datetime, timezone
    
    baseline_dir = Path(baseline_file).parent
    baseline_dir.mkdir(parents=True, exist_ok=True)
    
    baseline_data = {
        "metadata": {
            "captain_domain": captain_domain,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "prometheus_url": prometheus_url,
            "total_metrics": len(metrics)
        },
        "metric_names": sorted(metrics)
    }
    
    with open(baseline_file, 'w') as f:
        json.dump(baseline_data, f, indent=2)


def load_baseline(baseline_file):
    """Load baseline metric names from file"""
    with open(baseline_file, 'r') as f:
        data = json.load(f)
        # Support both old format (metric_signatures) and new format (metric_names)
        if 'metric_names' in data:
            return data
        elif 'metric_signatures' in data:
            # Convert old format: extract just the metric name before '{'
            metric_names = set()
            for sig in data['metric_signatures']:
                # Extract metric name (everything before '{' or the whole string)
                metric_name = sig.split('{')[0]
                metric_names.add(metric_name)
            data['metric_names'] = sorted(metric_names)
            data['metadata']['total_metrics'] = len(metric_names)
            return data
        else:
            raise ValueError("Invalid baseline file format")


@pytest.mark.smoke
@pytest.mark.quick
@pytest.mark.important
@pytest.mark.readonly
@pytest.mark.observability
def test_prometheus_metrics_existence(core_v1, captain_domain, prometheus_url, request):
    """Verify all baseline Prometheus metrics still exist (READ-ONLY cluster operation).
    
    This is a READ-ONLY test with respect to the Kubernetes cluster:
    - Only queries Prometheus (read-only API calls)
    - Does NOT modify cluster resources
    - File writes are LOCAL ONLY (baseline file to disk)
    
    First run: Creates baseline at baselines/prometheus-metrics-baseline.json
    Subsequent runs: Compares current metrics against baseline
    
    Validates metric name existence:
    - Checks metric names exist (ignoring labels/signatures)
    - Tolerates up to 10% missing metrics (logs WARNING instead of failure)
    - FAILS if missing metrics exceed the tolerance threshold
    - Reports new metrics as INFO (not a failure)
    
    Fails if unexpected missing metric names exceed MISSING_METRICS_TOLERANCE_PCT
    of total baseline metrics (indicates significant metric loss/regression).
    
    Note: To recreate baseline, delete the baseline file and rerun, or use --update-baseline=all
    
    Cluster Impact: READ-ONLY (queries only, no modifications)
    """
    baseline_dir = "baselines"
    baseline_file = f"{baseline_dir}/prometheus-metrics-baseline.json"
    
    # Check if we should force update the baseline
    update_baseline = request.config.getoption("--update-baseline")
    force_update = update_baseline in ("all", "prometheus", request.node.name)
    
    # Use prometheus_url fixture (port-forward already established)
    logger.info(f"Querying Prometheus at {prometheus_url} (read-only)")
    current_metrics = query_all_metrics(prometheus_url)
    logger.info(f"Found {len(current_metrics)} unique metric names")
    
    # First run or force update - create/recreate baseline (writes to LOCAL filesystem only)
    if not os.path.exists(baseline_file) or force_update:
        action = "updated" if force_update else "created"
        create_baseline(current_metrics, baseline_file, captain_domain, prometheus_url)
        logger.info(f"✓ Baseline {action}: {len(current_metrics)} metrics")
        logger.info(f"  Baseline saved to {baseline_file}")
        if force_update:
            logger.info(f"  Baseline force-updated due to --update-baseline={update_baseline}")
        pytest.skip(f"Baseline {action} with {len(current_metrics)} metrics (rerun to compare)")
    
    # Comparison run
    baseline = load_baseline(baseline_file)
    baseline_set = set(baseline['metric_names'])
    current_set = current_metrics
    
    logger.info(f"Baseline contains {len(baseline_set)} metric names")
    
    missing = baseline_set - current_set
    new = current_set - baseline_set
    
    # Separate whitelisted missing metrics from unexpected missing metrics
    whitelisted_missing = missing & set(IGNORABLE_MISSING_METRICS)
    unexpected_missing = missing - set(IGNORABLE_MISSING_METRICS)
    
    # Report new metrics (informational)
    if new:
        logger.info(f"\nNew metrics detected ({len(new)} total):")
        # Show first 10 new metrics
        for metric in sorted(new):
            logger.info(f"  + {metric}")

    
    # Log whitelisted missing metrics as warning (not a failure)
    if whitelisted_missing:
        logger.warning(f"\nWhitelisted missing metrics ({len(whitelisted_missing)} total):")
        for metric in sorted(whitelisted_missing):
            logger.warning(f"  - {metric}")
    
    # Assert no unexpected missing metrics (with tolerance)
    if unexpected_missing:
        missing_pct = (len(unexpected_missing) / len(baseline_set)) * 100
        missing_list = sorted(unexpected_missing)

        if missing_pct < MISSING_METRICS_TOLERANCE_PCT:
            # Under tolerance — warn but pass
            logger.warning(
                f"\n{len(unexpected_missing)} metric name(s) missing "
                f"({missing_pct:.1f}% of {len(baseline_set)} baseline metrics, "
                f"within {MISSING_METRICS_TOLERANCE_PCT}% tolerance):"
            )
            for m in missing_list:
                logger.warning(f"  - {m}")
        else:
            # Over tolerance — fail
            error_msg = (
                f"{len(unexpected_missing)} metric name(s) missing from baseline "
                f"({missing_pct:.1f}% of {len(baseline_set)} — "
                f"exceeds {MISSING_METRICS_TOLERANCE_PCT}% tolerance):\n"
            )
            for m in missing_list:
                error_msg += f"  - {m}\n"
            pytest.fail(error_msg)

    # Summary
    summary = f"✓ All {len(baseline_set)} baseline metrics verified"
    if unexpected_missing:
        summary += (
            f" ({len(unexpected_missing)} missing — {missing_pct:.1f}%, "
            f"within {MISSING_METRICS_TOLERANCE_PCT}% tolerance)"
        )
    if new:
        summary += f" ({len(new)} new metrics detected)"
    logger.info(summary)
