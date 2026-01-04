"""
Test helpers package for GlueOps PaaS tests.

This package contains all helper functions, utilities, and fixtures
used across the test suite. It replaces the old lib/ directory.

Submodules:
    - k8s: Kubernetes utilities and validators
    - github: GitHub API helpers
    - vault: HashiCorp Vault helpers
    - browser: Playwright/Selenium browser helpers for UI tests
    - utils: General test utilities (progress bars, formatting, etc.)
    - assertions: pytest-specific assertion helpers
"""

# Re-export commonly used items for convenience
from tests.helpers.k8s import (
    get_platform_namespaces,
    wait_for_job_completion,
    validate_pod_execution,
    validate_all_argocd_apps,
    validate_pod_health,
    validate_failed_jobs,
    validate_ingress_configuration,
    validate_ingress_dns,
    validate_certificate_secret,
    validate_https_certificate,
    validate_http_debug_app,
    wait_for_certificate_ready,
    get_ingress_load_balancer_ip,
)

from tests.helpers.assertions import (
    assert_argocd_healthy,
    assert_pods_healthy,
    assert_ingress_valid,
    assert_ingress_dns_valid,
    assert_certificates_ready,
    assert_tls_secrets_valid,
    assert_https_endpoints_valid,
)

from tests.helpers.utils import (
    display_progress_bar,
    print_section_header,
    print_summary_list,
)

__all__ = [
    # k8s validators
    'get_platform_namespaces',
    'wait_for_job_completion',
    'validate_pod_execution',
    'validate_all_argocd_apps',
    'validate_pod_health',
    'validate_failed_jobs',
    'validate_ingress_configuration',
    'validate_ingress_dns',
    'validate_certificate_secret',
    'validate_https_certificate',
    'validate_http_debug_app',
    'wait_for_certificate_ready',
    'get_ingress_load_balancer_ip',
    # assertions
    'assert_argocd_healthy',
    'assert_pods_healthy',
    'assert_ingress_valid',
    'assert_ingress_dns_valid',
    'assert_certificates_ready',
    'assert_tls_secrets_valid',
    'assert_https_endpoints_valid',
    # utils
    'display_progress_bar',
    'print_section_header',
    'print_summary_list',
]
