"""Observability and metrics tests"""
import pytest
import json
import os
import time
from pathlib import Path
import requests
from lib.port_forward import PortForward


def query_all_metrics(prometheus_url):
    """Query Prometheus and return set of metric signatures (name + label keys)
    
    Queries last 24 hours of metrics using series endpoint to capture
    metrics that may not be present at exact instant of query.
    Returns deduplicated set of metric signatures.
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
    
    # Use set for automatic deduplication
    metrics = set()
    for series in data['data']:
        metric_name = series.get('__name__', '')
        if not metric_name:
            continue
        
        # Get label keys (excluding __name__)
        label_keys = sorted([k for k in series.keys() if k != '__name__'])
        
        # Create signature: metric_name{label1,label2,label3}
        if label_keys:
            label_str = ','.join(label_keys)
            signature = f"{metric_name}{{{label_str}}}"
        else:
            signature = metric_name
        
        metrics.add(signature)
    
    return metrics


def create_baseline(metrics, baseline_file, captain_domain, prometheus_url):
    """Create baseline file with metric signatures (local file operation only)"""
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
        "metric_signatures": sorted(metrics)
    }
    
    with open(baseline_file, 'w') as f:
        json.dump(baseline_data, f, indent=2)


def load_baseline(baseline_file):
    """Load baseline metric signatures from file"""
    with open(baseline_file, 'r') as f:
        return json.load(f)


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
    
    Validates metric schema existence (metric name + label keys):
    - Checks metric_name{label1,label2,label3} patterns exist
    - Does NOT compare label values (survives pod restarts, IP changes)
    - FAILS if baseline metrics are missing (regression detection)
    - Reports new metrics as INFO (not a failure)
    
    Fails if any baseline metric signatures are missing (indicates metric loss/regression).
    
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
        print(f"Found {len(current_metrics)} unique metric signatures")
        
        # First run - create baseline (writes to LOCAL filesystem only)
        if not os.path.exists(baseline_file):
            create_baseline(current_metrics, baseline_file, captain_domain, prometheus_url)
            print(f"✓ Baseline created: {len(current_metrics)} metrics")
            print(f"  Baseline saved to {baseline_file}")
            pytest.skip(f"Baseline created with {len(current_metrics)} metrics (rerun to compare)")
        
        # Comparison run
        baseline = load_baseline(baseline_file)
        baseline_set = set(baseline['metric_signatures'])
        current_set = current_metrics
        
        print(f"Baseline contains {len(baseline_set)} metric signatures")
        
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
            error_msg = f"{len(missing)} metric signature(s) missing from baseline:\n"
            for m in missing_list:
                error_msg += f"  - {m}\n"
            
            pytest.fail(error_msg)
        
        print(f"✓ All {len(baseline_set)} baseline metrics verified" + 
              (f" ({len(new)} new metrics detected)" if new else ""))
