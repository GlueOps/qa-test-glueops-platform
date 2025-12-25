"""Observability and metrics tests"""
import pytest
import json
import os
import time
from pathlib import Path
import requests
from lib.port_forward import PortForward


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
def test_prometheus_metrics_existence(core_v1, captain_domain):
    """Verify all baseline Prometheus metrics still exist (READ-ONLY cluster operation).
    
    This is a READ-ONLY test with respect to the Kubernetes cluster:
    - Only queries Prometheus (read-only API calls)
    - Does NOT modify cluster resources
    - File writes are LOCAL ONLY (baseline file to disk)
    
    First run: Creates baseline at baselines/prometheus-metrics-baseline.json
    Subsequent runs: Compares current metrics against baseline
    
    Validates metric name existence:
    - Checks metric names exist (ignoring labels/signatures)
    - FAILS if baseline metrics are missing (regression detection)
    - Reports new metrics as INFO (not a failure)
    
    Fails if any baseline metric names are missing (indicates metric loss/regression).
    
    Note: To recreate baseline, delete the baseline file and rerun.
    
    Cluster Impact: READ-ONLY (queries only, no modifications)
    """
    baseline_dir = "baselines"
    baseline_file = f"{baseline_dir}/prometheus-metrics-baseline.json"
    
    # Port-forward to Prometheus (read-only connection)
    with PortForward("glueops-core-kube-prometheus-stack", "kps-prometheus", 9090) as pf:
        prometheus_url = f"http://127.0.0.1:{pf.local_port}"
        
        print(f"Querying Prometheus at {prometheus_url} (read-only)")
        current_metrics = query_all_metrics(prometheus_url)
        print(f"Found {len(current_metrics)} unique metric names")
        
        # First run - create baseline (writes to LOCAL filesystem only)
        if not os.path.exists(baseline_file):
            create_baseline(current_metrics, baseline_file, captain_domain, prometheus_url)
            print(f"✓ Baseline created: {len(current_metrics)} metrics")
            print(f"  Baseline saved to {baseline_file}")
            pytest.skip(f"Baseline created with {len(current_metrics)} metrics (rerun to compare)")
        
        # Comparison run
        baseline = load_baseline(baseline_file)
        baseline_set = set(baseline['metric_names'])
        current_set = current_metrics
        
        print(f"Baseline contains {len(baseline_set)} metric names")
        
        missing = baseline_set - current_set
        new = current_set - baseline_set
        
        # Report new metrics (informational)
        if new:
            print(f"\nNew metrics detected ({len(new)} total):")
            # Show first 10 new metrics
            for metric in sorted(new)[:10]:
                print(f"  + {metric}")
            if len(new) > 10:
                print(f"  ... and {len(new) - 10} more")
        
        # Assert no missing metrics
        if missing:
            # Show all missing metrics
            missing_list = sorted(missing)
            error_msg = f"{len(missing)} metric name(s) missing from baseline:\n"
            for m in missing_list:
                error_msg += f"  - {m}\n"
            
            pytest.fail(error_msg)
        
        print(f"✓ All {len(baseline_set)} baseline metrics verified" + 
              (f" ({len(new)} new metrics detected)" if new else ""))
