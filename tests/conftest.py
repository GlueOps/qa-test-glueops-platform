"""
Pytest fixtures for GlueOps test suite.

This is the main conftest.py that orchestrates fixture loading from
domain-specific conftest modules. It contains only:
- Configuration fixtures (captain_domain, namespace_filter, platform_namespaces)
- Pytest hooks and configuration
- Plugin imports via pytest_plugins

Fixture Organization:
    - conftest_k8s.py: Kubernetes client fixtures (core_v1, apps_v1, etc.)
    - conftest_github.py: GitHub/GitOps fixtures (ephemeral_github_repo, github_repo_factory)
    - conftest_browser.py: Browser/UI fixtures (page, authenticated_*_page, screenshots)
    - conftest_services.py: Service connection fixtures (vault_client, prometheus_url)
    - conftest_manifests.py: Captain manifests fixtures (captain_manifests, fixture_apps)
"""
import pytest
import os
import sys
import time
import logging
from pathlib import Path
import allure

from tests.helpers.k8s import get_platform_namespaces


logger = logging.getLogger(__name__)


# =============================================================================
# PYTEST PLUGINS - Import fixtures from domain-specific conftest modules
# =============================================================================

pytest_plugins = [
    "tests.conftest_k8s",
    "tests.conftest_github",
    "tests.conftest_browser",
    "tests.conftest_services",
    "tests.conftest_manifests",
]


# =============================================================================
# CONFIGURATION FIXTURES
# =============================================================================

@pytest.fixture(scope="session")
def captain_domain(request):
    """Captain domain from CLI, env var, or default.
    
    Priority order:
    1. CLI argument: --captain-domain
    2. Environment variable: CAPTAIN_DOMAIN
    3. Default: nonprod.foobar.onglueops.rocks
    
    Scope: session (shared across all tests)
    
    Returns:
        str: Captain domain (e.g., 'nonprod.jupiter.onglueops.rocks')
    """
    # Priority: CLI arg > env var > default
    cli_domain = request.config.getoption("--captain-domain", default=None)
    if cli_domain:
        return cli_domain
    
    env_domain = os.getenv("CAPTAIN_DOMAIN")
    if env_domain:
        return env_domain
    
    return "nonprod.foobar.onglueops.rocks"


@pytest.fixture(scope="session")
def namespace_filter(request):
    """Optional namespace filter from CLI.
    
    When provided, tests will only run against the specified namespace.
    
    Scope: session
    
    Returns:
        str | None: Namespace name to filter by, or None for all namespaces
    """
    return request.config.getoption("--namespace", default=None)


@pytest.fixture(scope="session")
def platform_namespaces(core_v1, namespace_filter):
    """Get platform namespaces, optionally filtered.
    
    Retrieves all platform namespaces from the cluster, optionally
    filtered to a single namespace if namespace_filter is provided.
    
    Scope: session
    
    Dependencies:
        - core_v1: Kubernetes CoreV1Api client
        - namespace_filter: Optional namespace filter
    
    Returns:
        list: List of namespace objects
    """
    return get_platform_namespaces(core_v1, namespace_filter)


# =============================================================================
# PYTEST HOOKS - Screenshot capture on test completion
# =============================================================================

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook to auto-capture final screenshot for UI tests and attach to Allure report.
    
    Captures a screenshot at the end of every UI test (pass, fail, or skip)
    and attaches it to the Allure report for visual debugging.
    """
    outcome = yield
    report = outcome.get_result()
    
    # Auto-capture screenshot for UI tests (always, regardless of pass/fail)
    if report.when == 'call' and hasattr(item, 'funcargs') and 'page' in item.funcargs:
        try:
            page = item.funcargs['page']
            # Generate screenshot filename
            test_name = item.nodeid.replace('::', '_').replace('/', '_')
            timestamp = time.strftime('%Y%m%d-%H%M%S')
            status = 'PASSED' if report.passed else 'FAILED' if report.failed else 'SKIPPED'
            
            # Get screenshots directory from config or use default
            screenshots_dir = Path('reports/screenshots')
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            
            screenshot_filename = f"{test_name}_FINAL_{status}_{timestamp}.png"
            screenshot_path = screenshots_dir / screenshot_filename
            
            # Capture screenshot and attach to Allure report
            screenshot_bytes = page.screenshot(path=str(screenshot_path))
            allure.attach(
                screenshot_bytes,
                name=f"Final Screenshot: {status}",
                attachment_type=allure.attachment_type.PNG
            )
        except Exception as e:
            # Silently ignore screenshot errors to not break tests
            pass


# =============================================================================
# PYTEST CONFIGURATION
# =============================================================================

def pytest_addoption(parser):
    """Add custom command-line options."""
    parser.addoption(
        "--environment",
        action="store",
        default=None,
        help="Test environment (e.g., prod, staging)",
    )
    parser.addoption(
        "--env",
        action="store",
        default=None,
        help="Test environment (shorthand)",
    )
    parser.addoption(
        "--captain-domain",
        action="store",
        default=None,
        help="Captain domain for the cluster (default: nonprod.foobar.onglueops.rocks)"
    )
    parser.addoption(
        "--namespace",
        action="store",
        default=None,
        help="Filter tests to specific namespace"
    )
    parser.addoption(
        "--update-baseline",
        action="store",
        default=None,
        help="Update baselines. Use 'all' to update all, 'prometheus' for metrics, or 'test_name' for specific visual tests"
    )


def pytest_configure(config):
    """Configure pytest with custom settings."""
    # Register custom markers
    config.addinivalue_line("markers", "gitops: GitOps integration tests")
    config.addinivalue_line("markers", "quick: Quick tests that run in <5 seconds")
    config.addinivalue_line("markers", "smoke: Smoke tests for basic functionality")
    config.addinivalue_line("markers", "write: Tests that modify cluster state")
    config.addinivalue_line("markers", "oauth_redirect: OAuth redirect flow tests")
    config.addinivalue_line("markers", "authenticated: Authenticated UI tests")
    config.addinivalue_line("markers", "captain_manifests: Tests requiring captain manifests fixture")
    
    # Allure report metadata (environment properties)
    allure_env_path = Path(config.option.allure_report_dir or "allure-results") / "environment.properties"
    allure_env_path.parent.mkdir(parents=True, exist_ok=True)
    with open(allure_env_path, "w") as f:
        f.write(f"Project=GlueOps Platform Test Suite\n")
        f.write(f"Environment={os.getenv('CAPTAIN_DOMAIN', 'QA Environment')}\n")
        f.write(f"Tester={os.getenv('USER', 'CI/CD Pipeline')}\n")
        f.write(f"Branch={os.getenv('GIT_BRANCH', 'N/A')}\n")
        f.write(f"Commit={os.getenv('GIT_COMMIT', 'N/A')}\n")
        f.write(f"Python.version={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n")
    
    # Terminal reporter customization
    config.option.verbose = max(config.option.verbose, 1)


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers dynamically."""
    # Add 'smoke' marker to all tests in tests/smoke/
    for item in items:
        if "tests/smoke" in str(item.fspath):
            item.add_marker(pytest.mark.smoke)


# =============================================================================
# DNS SERVICE SWITCHING FOR LETSENCRYPT TESTS
# =============================================================================

@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """
    Switch DNS service on test retries for letsencrypt tests.
    Allows testing multiple DNS services as fallbacks.
    """
    # Only apply to letsencrypt tests
    if 'letsencrypt' in item.nodeid:
        # Get list of DNS services to try
        dns_services_env = os.getenv('WILDCARD_DNS_SERVICES')
        if not dns_services_env:
            pytest.fail("WILDCARD_DNS_SERVICES environment variable is required but not set")
        dns_services = [s.strip() for s in dns_services_env.split(',')]
        
        # execution_count is set by pytest-rerunfailures
        # First run: execution_count = 1 → use index 0 (first DNS service)
        # First retry: execution_count = 2 → use index 1 (second DNS service)
        has_execution_count = hasattr(item, 'execution_count')
        if has_execution_count:
            retry_num = item.execution_count - 1  # Convert to 0-based index
        else:
            retry_num = 0  # Fallback
        
        # Debug: Log the actual execution_count value
        logger.info(f"DEBUG: has_execution_count={has_execution_count}, execution_count={item.execution_count if has_execution_count else 'N/A'}, retry_num={retry_num}, dns_services={dns_services}")
        
        if retry_num < len(dns_services):
            selected_service = dns_services[retry_num]
            os.environ['_WILDCARD_DNS_SERVICE_CURRENT'] = selected_service
            logger.info(f"\n{'='*80}")
            if retry_num == 0:
                logger.info(f"🌐 Attempt 1/{len(dns_services)}: Using DNS service '{selected_service}'")
            else:
                logger.info(f"🔄 Retry {retry_num}/{len(dns_services)-1}: Switching to DNS service '{selected_service}'")
            logger.info(f"{'='*80}\n")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item, nextitem):
    """
    Pause before teardown for manual inspection of test resources.
    
    When TEARDOWN_WAIT environment variable is set to a truthy value
    (TRUE, true, 1, yes, etc.), this hook will block and wait for user
    input before any fixture teardowns execute.
    
    Useful for debugging tests by inspecting ArgoCD apps, namespaces,
    GitHub repos, and other resources before cleanup.
    
    Usage:
        TEARDOWN_WAIT=1 pytest tests/test_deployment_workflow.py
    """
    teardown_wait = os.getenv('TEARDOWN_WAIT', '').strip().lower()
    
    # Check if truthy: any of these values enable the wait
    if teardown_wait in ('1', 'true', 'yes', 'y', 'on'):
        test_name = item.nodeid
        logger.info(f"\n{'='*80}")
        logger.info(f"⏸️  TEARDOWN PAUSED for test: {test_name}")
        logger.info(f"{'='*80}")
        logger.info("You can now inspect test resources:")
        logger.info("  - ArgoCD applications")
        logger.info("  - Kubernetes namespaces and resources")
        logger.info("  - GitHub repositories")
        logger.info("  - Browser state (if UI test)")
        logger.info("\n")
        logger.info("Press Enter to continue with teardown and cleanup.")
        logger.info("\n")
        logger.info(f"{'='*80}")
        
        try:
            # Use /dev/tty directly to read from terminal (works in Docker with -it)
            with open('/dev/tty', 'r') as tty:
                print("Press Enter to continue with teardown and cleanup...")
                tty.readline()
        except Exception as e:
            logger.warning(f"\nInput not available ({e}), continuing with teardown...")
        
        logger.info("Proceeding with teardown...\n")


# =============================================================================
# TERMINAL SUMMARY
# =============================================================================

class ColoredTerminalReporter:
    """Custom pytest reporter with colored output similar to old reporter."""
    
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREY = "\033[90m"
    DARK_RED = "\033[31m"
    ORANGE = "\033[38;5;208m"
    RESET = "\033[0m"
    
    def __init__(self):
        self.passed = []
        self.failed = []
    
    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        """Hook to capture test results."""
        outcome = yield
        report = outcome.get_result()
        
        if report.when == "call":
            if report.passed:
                self.passed.append(item.nodeid)
            elif report.failed:
                self.failed.append((item.nodeid, report.longreprtext))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Custom terminal summary with colors."""
    reporter = ColoredTerminalReporter()
    
    # Print summary
    terminalreporter.section("Summary", sep="=", bold=True)
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    
    terminalreporter.write_line(f"Passed: {passed}")
    terminalreporter.write_line(f"Failed: {failed}")
