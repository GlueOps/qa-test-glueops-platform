"""
Kubernetes client fixtures for GlueOps test suite.

This module provides session-scoped Kubernetes API clients and logging configuration.

Fixtures:
    - configure_safe_logging: Auto-configures logging to handle surrogate characters
    - k8s_config: Loads Kubernetes configuration once per session
    - core_v1: Kubernetes CoreV1Api client (pods, namespaces, secrets, configmaps)
    - apps_v1: Kubernetes AppsV1Api client (deployments, statefulsets, daemonsets)
    - batch_v1: Kubernetes BatchV1Api client (jobs, cronjobs)
    - networking_v1: Kubernetes NetworkingV1Api client (ingresses, network policies)
    - custom_api: Kubernetes CustomObjectsApi client (ArgoCD CRDs, certificates)
"""
import pytest
import logging
from kubernetes import client, config


class SafeUnicodeFilter(logging.Filter):
    """Filter to sanitize log messages containing surrogate characters.
    
    This prevents UnicodeEncodeError when Allure tries to attach captured logs
    that contain surrogate characters (U+D800 to U+DFFF) which are invalid in UTF-8.
    Common sources: binary data in exceptions, improperly decoded responses, etc.
    """
    
    def filter(self, record):
        """Sanitize the log message to handle surrogate characters."""
        if isinstance(record.msg, str):
            # Check if message contains surrogates
            try:
                record.msg.encode('utf-8')
            except UnicodeEncodeError:
                # Message contains surrogates, sanitize it
                record.msg = record.msg.encode('utf-8', errors='replace').decode('utf-8')
        
        # Also sanitize args if they contain strings with surrogates
        if record.args:
            safe_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    try:
                        arg.encode('utf-8')
                        safe_args.append(arg)
                    except UnicodeEncodeError:
                        safe_args.append(arg.encode('utf-8', errors='replace').decode('utf-8'))
                else:
                    safe_args.append(arg)
            record.args = tuple(safe_args)
        
        return True


@pytest.fixture(scope="session", autouse=True)
def configure_safe_logging():
    """Configure logging to handle surrogate characters safely.
    
    This fixture runs automatically at session start and installs a filter
    that prevents UnicodeEncodeError when logging contains invalid UTF-8
    surrogate characters. This is especially important for Python 3.14+
    which has stricter UTF-8 validation.
    
    Scope: session (runs once per test session)
    """
    safe_filter = SafeUnicodeFilter()
    
    # Add filter to root logger
    logging.root.addFilter(safe_filter)
    
    # Also add to all existing loggers
    for logger_name in logging.Logger.manager.loggerDict:
        logger_obj = logging.getLogger(logger_name)
        if isinstance(logger_obj, logging.Logger):
            logger_obj.addFilter(safe_filter)
    
    yield


@pytest.fixture(scope="session")
def k8s_config():
    """Load Kubernetes configuration once per test session.
    
    Loads kubeconfig from the default location (~/.kube/config) or
    from the KUBECONFIG environment variable.
    
    Scope: session (configuration loaded once, shared across all tests)
    """
    config.load_kube_config()


@pytest.fixture(scope="session")
def core_v1(k8s_config):
    """Kubernetes CoreV1Api client.
    
    Provides access to core Kubernetes resources:
    - Pods, Services, Endpoints
    - Namespaces
    - Secrets, ConfigMaps
    - PersistentVolumes, PersistentVolumeClaims
    - ServiceAccounts
    
    Scope: session (client reused across all tests)
    
    Dependencies:
        - k8s_config: Ensures kubeconfig is loaded
    """
    return client.CoreV1Api()


@pytest.fixture(scope="session")
def apps_v1(k8s_config):
    """Kubernetes AppsV1Api client.
    
    Provides access to workload resources:
    - Deployments
    - StatefulSets
    - DaemonSets
    - ReplicaSets
    
    Scope: session (client reused across all tests)
    
    Dependencies:
        - k8s_config: Ensures kubeconfig is loaded
    """
    return client.AppsV1Api()


@pytest.fixture(scope="session")
def batch_v1(k8s_config):
    """Kubernetes BatchV1Api client.
    
    Provides access to batch resources:
    - Jobs
    - CronJobs
    
    Scope: session (client reused across all tests)
    
    Dependencies:
        - k8s_config: Ensures kubeconfig is loaded
    """
    return client.BatchV1Api()


@pytest.fixture(scope="session")
def networking_v1(k8s_config):
    """Kubernetes NetworkingV1Api client.
    
    Provides access to networking resources:
    - Ingresses
    - IngressClasses
    - NetworkPolicies
    
    Scope: session (client reused across all tests)
    
    Dependencies:
        - k8s_config: Ensures kubeconfig is loaded
    """
    return client.NetworkingV1Api()


@pytest.fixture(scope="session")
def custom_api(k8s_config):
    """Kubernetes CustomObjectsApi client.
    
    Provides access to custom resources (CRDs):
    - ArgoCD Applications, ApplicationSets, AppProjects
    - cert-manager Certificates, ClusterIssuers
    - Any other custom resources
    
    Scope: session (client reused across all tests)
    
    Dependencies:
        - k8s_config: Ensures kubeconfig is loaded
    """
    return client.CustomObjectsApi()
