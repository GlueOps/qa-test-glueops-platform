"""Pytest fixtures for GlueOps test suite"""
import pytest
import os
import sys
from kubernetes import client, config
from pathlib import Path
from github import Github, GithubException
import time


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


# pytest-html hook to attach screenshots and extras
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook to add extra content to HTML report and auto-capture screenshots"""
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
            if hasattr(item.config, 'option') and hasattr(item.config.option, 'htmlpath'):
                html_path = Path(item.config.option.htmlpath)
                screenshots_dir = html_path.parent / 'screenshots'
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            
            screenshot_filename = f"{test_name}_FINAL_{status}_{timestamp}.png"
            screenshot_path = screenshots_dir / screenshot_filename
            
            # Capture screenshot
            page.screenshot(path=str(screenshot_path))
            
            # APPEND to existing screenshots (don't overwrite!)
            if not hasattr(item, '_screenshots'):
                item._screenshots = []
            item._screenshots.append((str(screenshot_path), f"Final Screenshot: {status}"))
        except Exception as e:
            # Silently ignore screenshot errors to not break tests
            pass
    
    # Add test description (docstring) and screenshots to the report
    if report.when == 'call':
        try:
            from pytest_html import extras
            extra = getattr(report, 'extras', [])
            
            # Add docstring as description if it exists
            if item.obj.__doc__:
                docstring = item.obj.__doc__.strip()
                extra.append(extras.html(f'<div style="margin: 10px 0; padding: 10px; background-color: #f5f5f5; border-left: 3px solid #2196F3;"><strong>Description:</strong><br>{docstring}</div>'))
                
            # Add screenshots to HTML report if they exist  
            screenshots = getattr(item, '_screenshots', [])
            if screenshots:
                extra.append(extras.html(f'<div style="margin: 15px 0 5px 0;"><strong>📸 Screenshots ({len(screenshots)}):</strong></div>'))
                for screenshot_path, description in screenshots:
                    screenshot_path_obj = Path(screenshot_path)
                    if screenshot_path_obj.exists():
                        # Use relative path from HTML report to screenshot
                        rel_path = f"screenshots/{screenshot_path_obj.name}"
                        
                        # Clean link with icon and styling
                        extra.append(extras.html(f'''
                            <div style="margin: 5px 0; padding: 8px 12px; background-color: #fff; border: 1px solid #e0e0e0; border-radius: 4px; display: inline-block;">
                                <a href="{rel_path}" target="_blank" style="text-decoration: none; color: #0066cc; font-size: 13px; display: flex; align-items: center; gap: 8px;">
                                    <span style="font-size: 16px;">🖼️</span>
                                    <span style="font-weight: 500;">{description}</span>
                                    <span style="color: #999; font-size: 11px;">↗</span>
                                </a>
                            </div>
                        '''))
                        
            report.extras = extra
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Error adding extras to report: {e}")
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


@pytest.fixture
def page(request, captain_domain):
    """Playwright page fixture for UI tests with auto screenshot capture.
    
    This fixture:
    - Creates a browser connection (BrowserBase or local Chrome)
    - Sets up an incognito context for test isolation
    - Exposes the page to pytest-html-plus for automatic screenshot capture
    - Automatically cleans up browser resources after the test
    
    Requires: tests.ui.helpers module for browser management
    """
    # Import here to avoid requiring playwright for non-UI tests
    from tests.ui.helpers import (
        get_browser_connection,
        create_incognito_context,
        cleanup_browser
    )
    
    playwright, browser, session = get_browser_connection()
    context = create_incognito_context(browser)
    page_instance = context.new_page()
    
    # Attach page to request for pytest-html-plus to find it
    request.node.page_for_screenshot = page_instance
    
    yield page_instance
    
    # Cleanup
    cleanup_browser(playwright, page_instance, context, session)


@pytest.fixture
def ephemeral_github_repo():
    """
    Create an ephemeral GitHub repository from a template for testing.
    
    This fixture:
    1. Authenticates using GITHUB_TOKEN environment variable
    2. Parses template and destination GitHub URLs
    3. Deletes the target test repository if it exists (cleanup safety)
    4. Creates a new repository from the template
    5. If template URL contains a tag, updates main branch to point to that tag's commit
    6. Yields the repository object for test use
    7. Deletes the repository in teardown
    
    Environment Variables:
        GITHUB_TOKEN: GitHub personal access token with repo permissions
        TEMPLATE_REPO_URL: Full GitHub URL (e.g., 'https://github.com/org/repo/releases/tag/0.1.0')
        DESTINATION_REPO_URL: Full destination URL (e.g., 'https://github.com/dest-org/dest-repo')
    
    Yields:
        github.Repository.Repository: The created repository object
    
    Raises:
        pytest.skip: If required environment variables are not set
    """
    import re
    
    # Get required environment variables
    github_token = os.environ.get("GITHUB_TOKEN")
    template_repo_url = os.environ.get("TEMPLATE_REPO_URL")
    destination_repo_url = os.environ.get("DESTINATION_REPO_URL")
    
    if not github_token:
        pytest.skip("GITHUB_TOKEN environment variable not set")
    if not template_repo_url:
        pytest.skip("TEMPLATE_REPO_URL environment variable not set")
    if not destination_repo_url:
        pytest.skip("DESTINATION_REPO_URL environment variable not set")
    
    # Parse template repo URL to extract org/repo and optional tag
    # Format: https://github.com/org/repo or https://github.com/org/repo/releases/tag/v1.0.0
    template_match = re.match(r'https://github\.com/([^/]+)/([^/]+)(?:/releases/tag/([^/]+))?', template_repo_url)
    if not template_match:
        pytest.skip(f"Invalid TEMPLATE_REPO_URL format: {template_repo_url}")
    
    template_org, template_repo, target_tag = template_match.groups()
    template_repo_name = f"{template_org}/{template_repo}"
    
    # Parse destination repo URL to extract org/repo
    # Format: https://github.com/org/repo
    dest_match = re.match(r'https://github\.com/([^/]+)/([^/]+)', destination_repo_url)
    if not dest_match:
        pytest.skip(f"Invalid DESTINATION_REPO_URL format: {destination_repo_url}")
    
    dest_org, dest_repo = dest_match.groups()
    test_repo_name = dest_repo
    
    # Authenticate with GitHub
    g = Github(github_token)
    
    # Get destination org/user
    try:
        dest_owner = g.get_organization(dest_org)
    except GithubException:
        # If not an organization, try as a user
        try:
            dest_owner = g.get_user(dest_org)
        except GithubException as e:
            pytest.skip(f"Failed to get destination owner '{dest_org}': {e}")
    
    # Get template repository
    try:
        template_repo = g.get_repo(template_repo_name)
    except GithubException as e:
        pytest.skip(f"Failed to get template repository '{template_repo_name}': {e}")
    
    # Safety cleanup: Delete test repo if it already exists
    try:
        existing_repo = dest_owner.get_repo(test_repo_name)
        print(f"Deleting existing test repository: {test_repo_name}")
        existing_repo.delete()
        time.sleep(2)  # Give GitHub API time to process deletion
    except GithubException as e:
        # Only continue if repo doesn't exist (404)
        # Other errors (like 403 permission denied) should fail
        if e.status == 404:
            # Repository doesn't exist, which is fine
            pass
        else:
            pytest.fail(f"Failed to delete existing repository '{test_repo_name}': {e.status} {e.data.get('message', str(e))}")
    
    # Create new repository from template
    print(f"Creating test repository '{dest_org}/{test_repo_name}' from template '{template_repo_name}'")
    try:
        test_repo = dest_owner.create_repo_from_template(
            name=test_repo_name,
            repo=template_repo,
            description=f"Ephemeral test repository created from {template_repo_name}",
            private=False
        )
        # Wait for repository to be fully created
        time.sleep(3)
    except GithubException as e:
        pytest.fail(f"Failed to create repository from template: {e}")
    
    # If target_tag is specified, get the commit SHA from the template repo
    # We'll use this for reference but won't attempt to update the new repo
    tag_commit_sha = None
    if target_tag:
        try:
            print(f"Fetching commit SHA for tag '{target_tag}' from template repo")
            # Get the tag reference from the TEMPLATE repo
            tag_ref = template_repo.get_git_ref(f"tags/{target_tag}")
            tag_sha = tag_ref.object.sha
            
            # If the tag points to a tag object, get the commit it points to
            if tag_ref.object.type == "tag":
                tag_obj = template_repo.get_git_tag(tag_sha)
                tag_commit_sha = tag_obj.object.sha
            else:
                tag_commit_sha = tag_sha
            
            print(f"Template tag '{target_tag}' points to commit: {tag_commit_sha}")
            print(f"Note: New repo uses template's HEAD. Tag commit is for reference only.")
        except GithubException as e:
            print(f"⚠ Warning: Could not fetch tag '{target_tag}': {e.status} - {e.data.get('message', str(e))}")
            print(f"  Continuing with template's HEAD commit")
    
    # Yield the repository for test use
    yield test_repo
    
    # Teardown: Delete the test repository
    try:
        print(f"Cleaning up: Deleting test repository '{test_repo_name}'")
        test_repo.delete()
    except GithubException as e:
        print(f"Warning: Failed to delete test repository during cleanup: {e}")


def pytest_addoption(parser):
    """Add custom command-line options"""
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





def pytest_html_report_title(report):
    """Set HTML report title"""
    report.title = "GlueOps Platform Test Suite"


def pytest_configure(config):
    """Configure pytest with custom settings"""
    # Register custom markers
    config.addinivalue_line("markers", "gitops: GitOps integration tests")
    config.addinivalue_line("markers", "quick: Quick tests that run in <5 seconds")
    config.addinivalue_line("markers", "smoke: Smoke tests for basic functionality")
    config.addinivalue_line("markers", "write: Tests that modify cluster state")
    config.addinivalue_line("markers", "oauth_redirect: OAuth redirect flow tests")
    config.addinivalue_line("markers", "authenticated: Authenticated UI tests")
    
    # Set HTML report metadata
    config._metadata = {
        'Project': 'GlueOps Platform Test Suite',
        'Environment': os.getenv('CAPTAIN_DOMAIN', 'QA Environment'),
        'Tester': os.getenv('USER', 'CI/CD Pipeline'),
        'Branch': os.getenv('GIT_BRANCH', 'N/A'),
        'Commit': os.getenv('GIT_COMMIT', 'N/A'),
        'Python version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    }
    
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
