"""Pytest fixtures for GlueOps test suite"""
import pytest
import os
from kubernetes import client, config
from pathlib import Path


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


# pytest-html hook to attach screenshots
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook to add extra content to HTML report"""
    outcome = yield
    report = outcome.get_result()
    
    # Add screenshots to HTML report if they exist  
    if report.when == 'call':
        # Get screenshots from test if they were stored
        screenshots = getattr(item, '_screenshots', [])
        if screenshots:
            try:
                from pytest_html import extras
                extra = getattr(report, 'extras', [])
                for screenshot_path, description in screenshots:
                    if Path(screenshot_path).exists():
                        # Add as clickable link to the screenshot file
                        rel_path = Path(screenshot_path).name
                        extra.append(extras.html(f'<div><a href="screenshots/{rel_path}" target="_blank">{description}</a></div>'))
                report.extras = extra
            except Exception:
                pass


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


@pytest.fixture(scope="session")
def github_credentials():
    """
    GitHub credentials for UI tests.
    
    Reads from environment variables:
    - GITHUB_USERNAME: GitHub username or email
    - GITHUB_PASSWORD: GitHub password
    - GITHUB_OTP_SECRET: TOTP secret for 2FA
    
    Returns:
        dict: Credentials dictionary with keys: username, password, otp_secret
    
    Raises:
        pytest.skip: If credentials are not configured
    """
    username = os.environ.get("GITHUB_USERNAME")
    password = os.environ.get("GITHUB_PASSWORD")
    otp_secret = os.environ.get("GITHUB_OTP_SECRET")
    
    if not username or not password or not otp_secret:
        pytest.skip(
            "GitHub credentials not configured. Set GITHUB_USERNAME, "
            "GITHUB_PASSWORD, and GITHUB_OTP_SECRET environment variables."
        )
    
    return {
        "username": username,
        "password": password,
        "otp_secret": otp_secret
    }


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
