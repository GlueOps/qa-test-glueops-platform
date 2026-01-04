"""
Generic port-forwarding utility for kubectl.

This module provides a context manager for establishing kubectl port-forward
connections to Kubernetes services.
"""
import subprocess
import time


class PortForward:
    """Context manager for kubectl port-forward to any service."""
    
    def __init__(self, namespace, service, port, local_port=None):
        """
        Initialize port-forward configuration.
        
        Args:
            namespace: Kubernetes namespace containing the service
            service: Service name to port-forward to
            port: Remote port on the service
            local_port: Local port to bind to (defaults to same as remote port)
        """
        self.namespace = namespace
        self.service = service
        self.port = port
        self.local_port = local_port or port
        self.process = None
    
    def __enter__(self):
        """Start port-forward."""
        cmd = [
            "kubectl", "port-forward",
            f"svc/{self.service}",
            f"{self.local_port}:{self.port}",
            "-n", self.namespace
        ]
        
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        # Wait for port-forward to be ready
        time.sleep(10)
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop port-forward."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
