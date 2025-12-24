"""Pytest fixtures for GlueOps test suite"""
import pytest
import os
from kubernetes import client, config


@pytest.fixture(scope="session")
def k8s_config():
    """Load Kubernetes configuration once per test session"""
    config.load_kube_config()


@pytest.fixture(scope="session")
def core_v1(k8s_config):
    """Kubernetes CoreV1Api client"""
    return client.CoreV1Api()


@pytest.fixture(scope="session")
def apps_v1(k8s_config):
    """Kubernetes AppsV1Api client"""
    return client.AppsV1Api()


@pytest.fixture(scope="session")
def batch_v1(k8s_config):
    """Kubernetes BatchV1Api client"""
    return client.BatchV1Api()


@pytest.fixture(scope="session")
def networking_v1(k8s_config):
    """Kubernetes NetworkingV1Api client"""
    return client.NetworkingV1Api()


@pytest.fixture(scope="session")
def custom_api(k8s_config):
    """Kubernetes CustomObjectsApi client"""
    return client.CustomObjectsApi()


@pytest.fixture(scope="session")
def captain_domain(request):
    """Captain domain from CLI, env var, or default"""
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
    """Optional namespace filter from CLI"""
    return request.config.getoption("--namespace", default=None)


@pytest.fixture(scope="session")
def platform_namespaces(core_v1, namespace_filter):
    """Get platform namespaces, optionally filtered"""
    from lib.k8s_helpers import get_platform_namespaces
    return get_platform_namespaces(core_v1, namespace_filter)


def pytest_addoption(parser):
    """Add custom command-line options"""
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


def pytest_configure(config):
    """Configure pytest with custom settings"""
    # Terminal reporter customization
    config.option.verbose = max(config.option.verbose, 1)


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers dynamically"""
    # Add 'smoke' marker to all tests in tests/smoke/
    for item in items:
        if "tests/smoke" in str(item.fspath):
            item.add_marker(pytest.mark.smoke)


# Custom terminal reporter for colored output
class ColoredTerminalReporter:
    """Custom pytest reporter with colored output similar to old reporter"""
    
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
        """Hook to capture test results"""
        outcome = yield
        report = outcome.get_result()
        
        if report.when == "call":
            if report.passed:
                self.passed.append(item.nodeid)
            elif report.failed:
                self.failed.append((item.nodeid, report.longreprtext))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Custom terminal summary with colors"""
    reporter = ColoredTerminalReporter()
    
    # Print summary
    terminalreporter.section("Summary", sep="=", bold=True)
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    
    terminalreporter.write_line(f"Passed: {passed}")
    terminalreporter.write_line(f"Failed: {failed}")
