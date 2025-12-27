"""Kubernetes utility functions for common operations."""
import time
import logging
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)


def get_platform_namespaces(core_v1, namespace_filter=None):
    """Get list of platform namespaces to check."""
    if namespace_filter:
        return [namespace_filter]
    all_ns = core_v1.list_namespace()
    return [ns.metadata.name for ns in all_ns.items 
            if ns.metadata.name.startswith("glueops-") or ns.metadata.name == "nonprod"]


def wait_for_job_completion(batch_v1, job_name, namespace, timeout=300):
    """Wait for a job to complete and return its status."""
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
    """Wait for a job to complete and return its status."""
    pods = core_v1.list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}")
    
    if not pods.items:
        return False, "No pods found for job"
    
    pod = pods.items[0]
    pod_status = pod.status.phase
    
    if pod_status == "Succeeded":
        return True, "Pod completed successfully"
    elif pod_status == "Failed":
        return False, "Pod failed"
    else:
        return False, f"Pod in unexpected phase: {pod_status}"


def get_ingress_load_balancer_ip(networking_v1, ingress_class_name, namespace=None, verbose=True, fail_on_none=False):
    """
    Get the load balancer IP from ingresses matching the specified class.
    
    Args:
        networking_v1: Kubernetes NetworkingV1Api client
        ingress_class_name: Ingress class name to filter by (e.g., 'public', 'glueops-platform')
        namespace: Specific namespace to check (optional, checks all if None)
        verbose: Whether to log details (default: True)
        fail_on_none: Whether to fail test if IP not found (default: False)
    
    Returns:
        str: Load balancer IP or None if not found (raises pytest.fail if fail_on_none=True and IP not found)
    """
    if verbose:
        logger.info(f"Searching for load balancer IP (ingressClassName: {ingress_class_name})...")
    
    try:
        if namespace:
            ingresses = networking_v1.list_namespaced_ingress(namespace=namespace)
        else:
            ingresses = networking_v1.list_ingress_for_all_namespaces()
        
        for ingress in ingresses.items:
            # Filter by ingress class
            if ingress.spec.ingress_class_name != ingress_class_name:
                continue
            
            if (ingress.status and 
                ingress.status.load_balancer and 
                ingress.status.load_balancer.ingress):
                
                for lb in ingress.status.load_balancer.ingress:
                    if lb.ip:
                        if verbose:
                            logger.info(f"✓ Found load balancer IP: {lb.ip}")
                            logger.info(f"  Source: {ingress.metadata.namespace}/{ingress.metadata.name}")
                            logger.info(f"  Ingress Class: {ingress.spec.ingress_class_name}")
                        return lb.ip
        
        logger.warning(f"No load balancer IP found for ingressClassName: {ingress_class_name}")
        
        if fail_on_none:
            import pytest
            pytest.fail(f"Could not find load balancer IP for ingressClassName '{ingress_class_name}'")
        
        return None
        
    except Exception as e:
        logger.error(f"Failed to get load balancer IP: {e}")
        
        if fail_on_none:
            import pytest
            pytest.fail(f"Failed to get load balancer IP: {e}")
        
        return None


def wait_for_certificate_ready(custom_api, cert_name, namespace, timeout=600, poll_interval=10, verbose=True):
    """
    Wait for a cert-manager Certificate to reach Ready status.
    
    Args:
        custom_api: Kubernetes CustomObjectsApi client
        cert_name: Name of the Certificate resource
        namespace: Namespace of the Certificate
        timeout: Maximum time to wait in seconds (default: 600)
        poll_interval: Time between checks in seconds (default: 10)
        verbose: Whether to print progress updates (default: True)
    
    Returns:
        tuple: (success: bool, status: dict)
    """
    start_time = time.time()
    elapsed = 0
    
    while elapsed < timeout:
        try:
            cert = custom_api.get_namespaced_custom_object(
                group="cert-manager.io",
                version="v1",
                namespace=namespace,
                plural="certificates",
                name=cert_name
            )
            
            conditions = cert.get('status', {}).get('conditions', [])
            
            # Check for Ready condition
            for condition in conditions:
                if condition.get('type') == 'Ready':
                    if condition.get('status') == 'True':
                        if verbose:
                            logger.info(f"      ✓ Certificate Ready (took {int(elapsed)}s)")
                        return True, cert.get('status', {})
                    else:
                        reason = condition.get('reason', 'Unknown')
                        message = condition.get('message', 'No details')
                        if verbose:
                            logger.info(f"      ⏳ Status: {reason} - {message[:80]}")
            
            # If no Ready condition found, show current state
            if verbose and not any(c.get('type') == 'Ready' for c in conditions):
                logger.info(f"      ⏳ Waiting for Ready condition... ({int(elapsed)}s elapsed)")
            
        except ApiException as e:
            if e.status == 404:
                if verbose:
                    logger.info(f"      ⏳ Certificate not found yet... ({int(elapsed)}s elapsed)")
            else:
                if verbose:
                    logger.info(f"      ⚠ API error: {e}")
        
        time.sleep(poll_interval)
        elapsed = time.time() - start_time
    
    # Timeout reached
    if verbose:
        logger.info(f"      ✗ Certificate not ready after {timeout}s")
    
    return False, {}
