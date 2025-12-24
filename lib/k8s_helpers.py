"""Kubernetes helper functions"""
import time
from kubernetes import client
from kubernetes.client.rest import ApiException


def get_platform_namespaces(core_v1, namespace_filter=None):
    """Get list of platform namespaces to check"""
    if namespace_filter:
        return [namespace_filter]
    all_ns = core_v1.list_namespace()
    return [ns.metadata.name for ns in all_ns.items 
            if ns.metadata.name.startswith("glueops-") or ns.metadata.name == "nonprod"]


def wait_for_job_completion(batch_v1, job_name, namespace, timeout=300):
    """Wait for a job to complete and return its status"""
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            job = batch_v1.read_namespaced_job(name=job_name, namespace=namespace)
            if job.status.succeeded and job.status.succeeded > 0:
                return "succeeded"
            elif job.status.failed and job.status.failed > 0:
                return "failed"
        except ApiException:
            pass
        time.sleep(5)
    
    return "timeout"


def validate_pod_execution(core_v1, job_name, namespace):
    """Check pods for a job to validate clean execution (no restarts, exit code 0)"""
    issues = []
    
    try:
        pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}")
        
        for pod in pods.items:
            if pod.status.container_statuses:
                for container in pod.status.container_statuses:
                    if container.restart_count > 0:
                        issues.append(f"container restarted {container.restart_count}x")
                    
                    if container.last_state.terminated:
                        if container.last_state.terminated.exit_code != 0:
                            issues.append(f"exit code {container.last_state.terminated.exit_code}")
            
            if pod.status.phase not in ["Succeeded", "Running"]:
                issues.append(f"pod {pod.status.phase}")
    except ApiException as e:
        issues.append(f"failed to check pods: {e.reason}")
    
    return issues
