"""Pytest fixtures for GlueOps test suite"""
import pytest
import os
import sys
from kubernetes import client, config
from pathlib import Path
from github import Github, GithubException
import time
import logging
import allure

from tests.helpers.k8s import (
    get_platform_namespaces,
    wait_for_argocd_apps_deleted,
    force_sync_argocd_app,
    wait_for_argocd_app_healthy,
)
from tests.helpers.argocd import (
    wait_for_argocd_apps_by_project_deleted,
)
from tests.helpers.github import (
    delete_directory_contents,
    get_captain_repo,
    create_or_update_file,
    delete_file_if_exists,
    delete_repos_by_topic,
    set_repo_topics,
)
from tests.helpers.manifests import (
    extract_namespace_from_captain_domain,
    generate_namespace_yaml,
    generate_appproject_yaml,
    generate_appset_yaml,
)


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


logger = logging.getLogger(__name__)


@pytest.fixture(scope="session", autouse=True)
def configure_safe_logging():
    """Configure logging to handle surrogate characters safely.
    
    This fixture runs automatically at session start and installs a filter
    that prevents UnicodeEncodeError when logging contains invalid UTF-8
    surrogate characters. This is especially important for Python 3.14+
    which has stricter UTF-8 validation.
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


# Auto-capture final screenshot for UI tests using Allure
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook to auto-capture final screenshot for UI tests and attach to Allure report"""
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
    return get_platform_namespaces(core_v1, namespace_filter)


# =============================================================================
# TENANT CONFIGURATION FIXTURES
# =============================================================================

@pytest.fixture(scope="session")
def tenant_github_org():
    """
    Tenant GitHub organization name.
    
    Returns:
        str: GitHub organization name (e.g., 'development-tenant-jupiter')
        
    Raises:
        pytest.skip: If TENANT_GITHUB_ORGANIZATION_NAME not set
    """
    org = os.environ.get("TENANT_GITHUB_ORGANIZATION_NAME")
    if not org:
        pytest.skip("TENANT_GITHUB_ORGANIZATION_NAME environment variable not set")
    return org


@pytest.fixture(scope="session")
def deployment_config_template_repo():
    """
    Template repository URL for deployment configurations.
    
    Returns:
        str: Template repo URL (e.g., 'https://github.com/GlueOps/deployment-configurations/releases/tag/0.1.0')
        
    Raises:
        pytest.skip: If DEPLOYMENT_CONFIGURATIONS_TEMPLATE_REPO not set
    """
    template_url = os.environ.get("DEPLOYMENT_CONFIGURATIONS_TEMPLATE_REPO")
    if not template_url:
        pytest.skip("DEPLOYMENT_CONFIGURATIONS_TEMPLATE_REPO environment variable not set")
    return template_url


@pytest.fixture(scope="session")
def captain_domain_repo_url():
    """
    Captain domain GitHub repository URL.
    
    Reads from CAPTAIN_DOMAIN_REPO_URL environment variable.
    
    Returns:
        str: Captain domain repo URL (e.g., 'https://github.com/development-captains/nonprod.jupiter.onglueops.rocks')
        
    Raises:
        pytest.skip: If not configured
    """
    repo_url = os.environ.get("CAPTAIN_DOMAIN_REPO_URL")
    if not repo_url:
        pytest.skip("CAPTAIN_DOMAIN_REPO_URL environment variable not set")
    return repo_url


@pytest.fixture(scope="session")
def captain_domain_github_token():
    """
    GitHub token for captain domain repository access.
    
    Reads from CAPTAIN_DOMAIN_GITHUB_TOKEN environment variable.
    This is separate from GITHUB_TOKEN to allow different access scopes.
    
    Returns:
        str: GitHub personal access token
        
    Raises:
        pytest.skip: If not configured
    """
    token = os.environ.get("CAPTAIN_DOMAIN_GITHUB_TOKEN")
    if not token:
        pytest.skip("CAPTAIN_DOMAIN_GITHUB_TOKEN environment variable not set")
    return token


# =============================================================================
# CAPTAIN MANIFESTS FIXTURE
# =============================================================================

@pytest.fixture
def captain_manifests(
    request,
    captain_domain,
    captain_domain_repo_url,
    captain_domain_github_token,
    tenant_github_org,
    ephemeral_github_repo,
    custom_api
):
    """
    Create dynamic ArgoCD manifests for test isolation.
    
    This fixture:
    1. Pre-cleanup: Deletes existing manifests if present
    2. Generates namespace, AppProject, and ApplicationSet manifests
    3. Commits them to the captain domain repository
    4. Deploys fixture apps (shared test applications available to all tests)
    5. Waits for ArgoCD to sync (configurable)
    6. Yields test context with namespace, captain_domain, and fixture app metadata
    7. Teardown: Deletes AppSet → waits for apps to be deleted → deletes remaining manifests
    
    Usage:
        @pytest.mark.captain_manifests
        def test_something(captain_manifests):
            namespace = captain_manifests['namespace']
            captain_domain = captain_manifests['captain_domain']
            # ... test code ...
    
    Marker Options:
        @pytest.mark.captain_manifests(sync_wait=60)  # Wait 60s for ArgoCD sync (default: 30)
    
    Environment Variables Required:
        - CAPTAIN_DOMAIN: The captain domain (e.g., 'nonprod.jupiter.onglueops.rocks')
        - CAPTAIN_DOMAIN_REPO_URL: GitHub URL for captain repo
        - CAPTAIN_DOMAIN_GITHUB_TOKEN: GitHub token for captain repo access
        - TENANT_GITHUB_ORGANIZATION_NAME: Tenant GitHub org
        - DEPLOYMENT_CONFIGURATIONS_TEMPLATE_REPO: Template repo URL
    
    Yields:
        dict: {
            'namespace': str,
            'captain_domain': str,
            'deployment_config_repo': str,
            'fixture_apps': list of dicts with app metadata,
            'fixture_app_count': int,
            'fixture_apps_by_friendly_name': dict mapping friendly names to metadata
        }
    
    Fixture Apps:
        Fixture apps are shared test applications automatically deployed before tests run.
        They provide common utilities that any test may need (e.g., http-debug endpoints).
        
        Metadata includes:
            - name: Full unique name with GUID (e.g., 'fixture-http-debug-1-a1b2c3d4')
            - friendly_name: Base name without GUID (e.g., 'fixture-http-debug-1')
            - guid: 8-character unique identifier
            - hostname: Full FQDN for ingress
            - replicas: Number of pod replicas
        
        Access patterns:
            # Get count for assertions
            count = captain_manifests['fixture_app_count']
            
            # Iterate all fixture apps
            for app in captain_manifests['fixture_apps']:
                print(app['name'], app['hostname'])
            
            # Look up by friendly name
            app = captain_manifests['fixture_apps_by_friendly_name']['fixture-http-debug-1']
            unique_name = app['name']  # Gets the full name with GUID
    """
    # Get marker options
    marker = request.node.get_closest_marker("captain_manifests")
    sync_wait = 30  # Default wait time
    if marker and marker.kwargs.get("sync_wait"):
        sync_wait = marker.kwargs["sync_wait"]
    
    # Extract namespace from captain domain
    namespace_name = extract_namespace_from_captain_domain(captain_domain)
    
    logger.info("\n" + "="*70)
    logger.info("SETUP: Creating captain manifests")
    logger.info("="*70)
    logger.info(f"  Captain domain: {captain_domain}")
    logger.info(f"  Namespace: {namespace_name}")
    logger.info(f"  Tenant org: {tenant_github_org}")
    logger.info(f"  Deployment config repo: {ephemeral_github_repo.name}")
    
    # Connect to captain repo
    g, captain_repo = get_captain_repo(
        token=captain_domain_github_token,
        repo_url=captain_domain_repo_url,
        verbose=True
    )
    
    # Define manifest paths
    manifest_paths = {
        'namespace': 'manifests/namespace.yaml',
        'appproject': 'manifests/appproject.yaml',
        'appset': 'manifests/appset.yaml',
    }
    
    # Pre-cleanup: Delete existing manifests in reverse order of creation
    # CRITICAL: Must delete ApplicationSet first to avoid "appproject not found" errors
    # When ApplicationSet still exists but AppProject is deleted, ArgoCD reconciliation fails
    logger.info("\n📋 Pre-cleanup: Removing existing manifests (reverse order of creation)...")
    
    # Delete in reverse order of creation
    for i, (name, path) in enumerate(reversed(list(manifest_paths.items())), 1):
        logger.info(f"   {i}. Deleting {name}...")
        delete_file_if_exists(captain_repo, path, f"Pre-cleanup: remove {name}", verbose=True)
        
        # Wait for captain-manifests to stabilize after each deletion
        logger.info(f"      Waiting for captain-manifests to stabilize...")
        app_healthy = wait_for_argocd_app_healthy(
            custom_api,
            app_name="captain-manifests",
            namespace="glueops-core",
            verbose=False
        )
        if not app_healthy:
            logger.warning(f"      ⚠ captain-manifests did not stabilize, continuing anyway")
        else:
            logger.info(f"      ✓ captain-manifests stable")
    
    # Give GitHub API time to process deletions
    time.sleep(2)
    
    # Wait for ArgoCD to clean up old resources before creating new ones
    logger.info("\n⏳ Waiting for old ArgoCD resources to be deleted...")
    
    # Wait for any existing Application CRs for this project to be deleted
    logger.info(f"   Checking for Application CRs referencing project '{namespace_name}'...")
    project_apps_deleted = wait_for_argocd_apps_by_project_deleted(
        custom_api,
        project_name=namespace_name,
        verbose=True
    )
    
    if project_apps_deleted:
        logger.info(f"✓ No Application CRs found - ready to create new manifests")
    else:
        logger.warning(f"⚠ Some Application CRs may still exist, proceeding anyway")
    
    # Generate manifests
    logger.info("\n📝 Generating manifests...")
    
    namespace_yaml = generate_namespace_yaml(namespace_name)
    appproject_yaml = generate_appproject_yaml(namespace_name, tenant_github_org)
    appset_yaml = generate_appset_yaml(
        namespace_name=namespace_name,
        tenant_github_org=tenant_github_org,
        deployment_config_repo=ephemeral_github_repo.name,  # Use dynamic repo name
        captain_domain=captain_domain
    )
    
    # Commit manifests to captain repo
    logger.info("\n📤 Committing manifests to captain repo...")
    
    # Create/update all manifest files (function validates and raises exceptions on failure)
    namespace_result = create_or_update_file(
        captain_repo,
        manifest_paths['namespace'],
        namespace_yaml,
        f"Create namespace manifest for {namespace_name}",
        verbose=True
    )
    
    appproject_result = create_or_update_file(
        captain_repo,
        manifest_paths['appproject'],
        appproject_yaml,
        f"Create AppProject manifest for {namespace_name}",
        verbose=True
    )
    
    appset_result = create_or_update_file(
        captain_repo,
        manifest_paths['appset'],
        appset_yaml,
        f"Create ApplicationSet manifest for {namespace_name}",
        verbose=True
    )
    
    # Log commit SHAs for verification
    logger.info(f"\n✓ All manifests committed successfully:")
    logger.info(f"  Namespace:   {namespace_result['commit'].sha[:8]}")
    logger.info(f"  AppProject:  {appproject_result['commit'].sha[:8]}")
    logger.info(f"  AppSet:      {appset_result['commit'].sha[:8]}")
    
    # Wait for ArgoCD to sync
    if sync_wait > 0:
        logger.info(f"\n⏳ Waiting {sync_wait}s for ArgoCD to sync manifests...")
        time.sleep(sync_wait)
    
    logger.info("\n✓ Captain manifests created successfully")
    logger.info("="*70 + "\n")
    
    # Deploy fixture applications
    logger.info("\n" + "="*70)
    logger.info("FIXTURE APPS: Deploying fixture applications")
    logger.info("="*70)
    
    import uuid
    from tests.helpers.github import create_github_file
    from tests.helpers.argocd import wait_for_appset_apps_created_and_healthy
    
    # Define fixture applications (easy to add more)
    # These are shared test utilities automatically deployed before tests run
    fixture_app_configs = [
        {'name': 'fixture-http-debug-1', 'replicas': 2},
        {'name': 'fixture-http-debug-2', 'replicas': 2},
        {'name': 'fixture-http-debug-3', 'replicas': 2},
    ]
    
    fixture_apps_metadata = []
    fixture_apps_by_friendly_name = {}
    
    from tests.templates import load_template
    
    def create_fixture_values_yaml(app_name, hostname, replicas):
        """Generate values.yaml for fixture http-debug application.
        
        Args:
            app_name: Application name for deployment
            hostname: Full hostname for ingress (e.g., app.apps.example.com)
            replicas: Number of pod replicas to deploy
            
        Returns:
            str: YAML content for values.yaml file
        """
        return load_template('http-debug-app-values.yaml',
                           hostname=hostname,
                           replicas=replicas,
                           cpu='100m',
                           memory='128Mi',
                           pdb_enabled='true')
    
    # Load env-values template
    env_values_yaml = load_template('env-values.yaml')
    
    # Deploy each fixture app
    for config in fixture_app_configs:
        app_name_base = config['name']
        replicas = config['replicas']
        guid = str(uuid.uuid4())[:8]
        app_name = f"{app_name_base}-{guid}"
        hostname = f"{app_name}.apps.{captain_domain}"
        
        logger.info(f"\n📦 Creating fixture app: {app_name}")
        logger.info(f"   Friendly name: {app_name_base}")
        logger.info(f"   GUID: {guid}")
        logger.info(f"   Hostname: {hostname}")
        
        # Create directory structure
        values_yaml = create_fixture_values_yaml(app_name, hostname, replicas)
        
        create_github_file(
            ephemeral_github_repo,
            f"apps/{app_name}/envs/prod/values.yaml",
            values_yaml,
            f"Add fixture app {app_name}",
            verbose=False
        )
        
        create_github_file(
            ephemeral_github_repo,
            f"apps/{app_name}/envs/prod/env-values.yaml",
            env_values_yaml,
            f"Add env-values for fixture app {app_name}",
            verbose=False
        )
        
        # Store metadata with friendly name and GUID for lookups
        app_metadata = {
            'name': app_name,
            'friendly_name': app_name_base,
            'guid': guid,
            'hostname': hostname,
            'replicas': replicas
        }
        
        fixture_apps_metadata.append(app_metadata)
        fixture_apps_by_friendly_name[app_name_base] = app_metadata
        
        logger.info(f"   ✓ Created manifests for {app_name}")
    
    # Wait for ApplicationSet to discover and deploy fixture apps
    logger.info(f"\n⏳ Waiting for {len(fixture_apps_metadata)} fixture apps to become healthy...")
    
    apps_ready = wait_for_appset_apps_created_and_healthy(
        custom_api,
        namespace=namespace_name,
        expected_count=len(fixture_apps_metadata),
        verbose=True
    )
    
    if not apps_ready:
        pytest.fail(f"Fixture apps did not become healthy within timeout")
    
    logger.info("\n✓ All fixture applications are healthy")
    logger.info("   Note: Tests should add fixture_app_count to their expected app totals")
    logger.info("="*70 + "\n")
    
    # Yield test context with fixture app info
    yield {
        'namespace': namespace_name,
        'captain_domain': captain_domain,
        'tenant_github_org': tenant_github_org,
        'deployment_config_repo': ephemeral_github_repo.name,
        'fixture_apps': fixture_apps_metadata,
        'fixture_app_count': len(fixture_apps_metadata),
        'fixture_apps_by_friendly_name': fixture_apps_by_friendly_name,
    }
    
    # Teardown
    logger.info("\n" + "="*70)
    logger.info("TEARDOWN: Cleaning up captain manifests")
    logger.info("="*70)
    
    try:
        # Step 1: Delete ApplicationSet first (this will trigger app deletion)
        logger.info("\n🗑️  Step 1: Deleting ApplicationSet...")
        delete_file_if_exists(
            captain_repo,
            manifest_paths['appset'],
            f"Teardown: remove ApplicationSet for {namespace_name}",
            verbose=True
        )
        
        # Step 2: Wait for ArgoCD applications to be deleted
        logger.info("\n⏳ Step 2: Waiting for ArgoCD applications to be deleted...")
        apps_deleted = wait_for_argocd_apps_deleted(
            custom_api,
            namespace=namespace_name,
            verbose=True
        )
        
        if not apps_deleted:
            logger.warning(f"⚠ Some ArgoCD apps may still exist in '{namespace_name}'")
        
        # Step 2b: Wait for ALL Application CRs that reference this project
        logger.info("\n⏳ Step 2b: Waiting for Application CRs referencing project to be deleted...")
        project_apps_deleted = wait_for_argocd_apps_by_project_deleted(
            custom_api,
            project_name=namespace_name,
            verbose=True
        )
        
        if not project_apps_deleted:
            logger.warning(f"⚠ Some Application CRs may still reference project '{namespace_name}'")
        
        # Step 3: Delete AppProject
        logger.info("\n🗑️  Step 3: Deleting AppProject...")
        delete_file_if_exists(
            captain_repo,
            manifest_paths['appproject'],
            f"Teardown: remove AppProject for {namespace_name}",
            verbose=True
        )
        
        # Step 4: Delete Namespace
        logger.info("\n🗑️  Step 4: Deleting Namespace...")
        delete_file_if_exists(
            captain_repo,
            manifest_paths['namespace'],
            f"Teardown: remove Namespace for {namespace_name}",
            verbose=True
        )
        
        # Step 5: Force sync captain-manifests app to clear the "auto-sync will wipe out all resources" state
        logger.info("\n🔄 Step 5: Force syncing captain-manifests app...")
        force_sync_argocd_app(
            custom_api,
            app_name="captain-manifests",
            namespace="glueops-core",
            verbose=True
        )
        
        # Give ArgoCD time to process the sync
        logger.info("\n⏱️  Waiting 30s for sync to stabilize...")
        time.sleep(30)
        
        # Step 6: Wait for captain-manifests app to become healthy/synced
        logger.info("\n⏳ Step 6: Waiting for captain-manifests to stabilize...")
        app_healthy = wait_for_argocd_app_healthy(
            custom_api,
            app_name="captain-manifests",
            namespace="glueops-core",

            verbose=True
        )
        
        if not app_healthy:
            logger.warning("⚠ captain-manifests app did not become healthy within timeout")
        
        logger.info("\n✓ Captain manifests cleanup complete")
        
    except Exception as e:
        logger.error(f"\n❌ Error during teardown: {e}")
        logger.error("Manual cleanup may be required")
    
    logger.info("="*70 + "\n")


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
    
    Requires: tests.helpers.browser module for browser management
    """
    from tests.helpers.browser import (
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
def ephemeral_github_repo(request, deployment_config_template_repo, tenant_github_org):
    """
    Create an ephemeral GitHub repository from a template for testing.
    
    This fixture:
    1. Cleans up orphaned test repos from previous runs (by topic)
    2. Creates a repository with unique name from template
    3. Sets 'createdby-automated-test-delete-me' topic for automated cleanup
    4. Clears apps/ directory
    5. Yields the repository object for test use
    6. Deletes all test repos by topic in teardown
    
    Environment Variables:
        GITHUB_TOKEN: GitHub personal access token with repo permissions
        DEPLOYMENT_CONFIGURATIONS_TEMPLATE_REPO: Template URL (e.g., 'https://github.com/org/repo/releases/tag/0.1.0')
        TENANT_GITHUB_ORGANIZATION_NAME: Destination org name
    
    Yields:
        github.Repository.Repository: The created repository object with unique name
    
    Raises:
        pytest.skip: If required environment variables are not set
        pytest.fail: If repo creation or apps/ clearing fails
    """
    import re
    
    # Get required environment variables
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        pytest.skip("GITHUB_TOKEN environment variable not set")
    
    # Parse template repo URL to extract org/repo and optional tag
    template_repo_url = deployment_config_template_repo
    template_match = re.match(r'https://github\.com/([^/]+)/([^/]+)(?:/releases/tag/([^/]+))?', template_repo_url)
    if not template_match:
        pytest.skip(f"Invalid DEPLOYMENT_CONFIGURATIONS_TEMPLATE_REPO format: {template_repo_url}")
    
    template_org, template_repo_name, target_tag = template_match.groups()
    template_repo_full_name = f"{template_org}/{template_repo_name}"
    
    # Get tenant org for destination
    dest_org = tenant_github_org
    
    # Authenticate with GitHub
    from github import Auth
    auth = Auth.Token(github_token)
    g = Github(auth=auth)
    
    # Get destination org/user
    try:
        dest_owner = g.get_organization(dest_org)
    except GithubException:
        # If not an organization, try as a user
        try:
            dest_owner = g.get_user(dest_org)
        except GithubException as e:
            pytest.skip(f"Failed to get destination owner '{dest_org}': {e}")
    
    # Clean up any orphaned test repositories from previous runs
    logger.info("\n" + "="*70)
    logger.info("SETUP: Cleaning up orphaned test repositories")
    logger.info("="*70)
    delete_repos_by_topic(dest_owner, 'createdby-automated-test-delete-me', verbose=True)
    
    # Get template repository
    try:
        template_repo = g.get_repo(template_repo_full_name)
    except GithubException as e:
        pytest.skip(f"Failed to get template repository '{template_repo_full_name}': {e}")
    
    # Generate unique repository name with GUID
    import uuid
    test_repo_name = f"deployment-configurations-{str(uuid.uuid4())[:8]}"
    logger.info(f"\n" + "="*70)
    logger.info("SETUP: Creating deployment-configurations repository")
    logger.info("="*70)
    logger.info(f"Repository name: {test_repo_name}")
    
    # Create repository from template
    try:
        test_repo = dest_owner.create_repo_from_template(
            name=test_repo_name,
            repo=template_repo,
            description="Ephemeral test repository for GitOps testing",
            private=False
        )
        time.sleep(3)  # Wait for repository to be fully created
        logger.info(f"✓ Repository created: {test_repo.html_url}")
    except GithubException as e:
        pytest.fail(f"Failed to create repository from template: {e.status} {e.data.get('message', str(e))}")
    
    # Set topics for automated cleanup and verify they are set
    logger.info("\n🏷️  Setting repository topics...")
    set_repo_topics(test_repo, ['createdby-automated-test-delete-me'], verbose=True)
    
    # Clear apps directory immediately after repo creation
    # This is CRITICAL - if it fails, the test cannot proceed
    logger.info("\n🧹 Clearing apps/ directory in new repository...")
    try:
        delete_directory_contents(test_repo, "apps", verbose=True)
        logger.info("✓ Apps folder cleared - ready for test to add apps")
    except GithubException as e:
        if e.status == 403:
            pytest.fail(f"❌ Failed to clear apps folder - permission denied (403). Check GITHUB_TOKEN has write access to {test_repo.full_name}")
        else:
            pytest.fail(f"❌ Failed to clear apps folder: {e.status} {e.data.get('message', str(e))}")
    except Exception as e:
        pytest.fail(f"❌ Failed to clear apps folder: {e}")
    
    logger.info("="*70 + "\n")
    
    # If target_tag is specified, get the commit SHA from the template repo
    # We'll use this for reference but won't attempt to update the new repo
    tag_commit_sha = None
    if target_tag:
        try:
            logger.info(f"Fetching commit SHA for tag '{target_tag}' from template repo")
            # Get the tag reference from the TEMPLATE repo
            tag_ref = template_repo.get_git_ref(f"tags/{target_tag}")
            tag_sha = tag_ref.object.sha
            
            # If the tag points to a tag object, get the commit it points to
            if tag_ref.object.type == "tag":
                tag_obj = template_repo.get_git_tag(tag_sha)
                tag_commit_sha = tag_obj.object.sha
            else:
                tag_commit_sha = tag_sha
            
            logger.info(f"Template tag '{target_tag}' points to commit: {tag_commit_sha}")
            logger.info(f"Note: New repo uses template's HEAD. Tag commit is for reference only.")
        except GithubException as e:
            logger.info(f"⚠ Warning: Could not fetch tag '{target_tag}': {e.status} - {e.data.get('message', str(e))}")
            logger.info(f"  Continuing with template's HEAD commit")
    
    # Give GitHub a moment to propagate deletions and ensure repo is ready
    logger.info("⏱️  Waiting 2s for GitHub to propagate changes...")
    time.sleep(2)
    
    # Verify repo is actually accessible (refresh to get latest state)
    try:
        # Force a fresh API call to verify repo exists and is accessible
        test_repo_refreshed = g.get_repo(test_repo.full_name)
        logger.info(f"✓ Repository verified accessible: {test_repo_refreshed.full_name}")
        test_repo = test_repo_refreshed  # Use the refreshed object
    except GithubException as e:
        pytest.fail(f"❌ Repository exists but is not accessible: {e.status} - {e.data.get('message', str(e))}")
    
    # Log repository information for test visibility
    logger.info(f"✓ Repository ready: {test_repo.full_name}")
    logger.info(f"✓ Repository URL: {test_repo.html_url}\n")
    
    # Yield the repository for test use
    yield test_repo
    
    # Teardown: Delete all test repositories by topic
    logger.info("\n" + "="*70)
    logger.info("TEARDOWN: Deleting test repositories")
    logger.info("="*70)
    delete_repos_by_topic(dest_owner, 'createdby-automated-test-delete-me', verbose=True)
    logger.info("="*70 + "\n")


@pytest.fixture
def fixture_apps(captain_manifests):
    """
    Convenience fixture that returns fixture app info from captain_manifests.
    
    Fixture apps are shared test applications automatically deployed before tests run.
    They provide common utilities that any test may need.
    
    Returns:
        dict: {
            'apps': list of app metadata dicts,
            'count': int number of fixture apps,
            'by_friendly_name': dict mapping friendly names to full metadata
        }
    
    Usage:
        def test_something(fixture_apps):
            # Get count
            count = fixture_apps['count']
            
            # Iterate all apps
            for app in fixture_apps['apps']:
                print(app['name'], app['hostname'])
            
            # Look up by friendly name
            app = fixture_apps['by_friendly_name']['fixture-http-debug-1']
            unique_name = app['name']  # Full name with GUID
    """
    return {
        'apps': captain_manifests['fixture_apps'],
        'count': captain_manifests['fixture_app_count'],
        'by_friendly_name': captain_manifests['fixture_apps_by_friendly_name']
    }


# =============================================================================
# PORT-FORWARD AND SERVICE CONNECTION FIXTURES
# =============================================================================

@pytest.fixture
def prometheus_url():
    """
    Port-forward to Prometheus and yield local URL.
    
    Automatically establishes kubectl port-forward to Prometheus service
    and cleans up the connection after the test completes.
    
    Returns:
        str: Local Prometheus URL (e.g., 'http://127.0.0.1:9090')
    
    Usage:
        def test_prometheus_metrics(prometheus_url):
            response = requests.get(f"{prometheus_url}/api/v1/query?query=up")
            assert response.status_code == 200
    """
    from tests.helpers.port_forward import PortForward
    
    with PortForward("glueops-core-kube-prometheus-stack", "kps-prometheus", 9090) as pf:
        yield f"http://127.0.0.1:{pf.local_port}"


@pytest.fixture
def alertmanager_url():
    """
    Port-forward to Alertmanager and yield local URL.
    
    Automatically establishes kubectl port-forward to Alertmanager service
    and cleans up the connection after the test completes.
    
    Returns:
        str: Local Alertmanager URL (e.g., 'http://127.0.0.1:9093')
    
    Usage:
        def test_alertmanager(alertmanager_url):
            response = requests.get(f"{alertmanager_url}/api/v2/status")
            assert response.status_code == 200
    """
    from tests.helpers.port_forward import PortForward
    
    with PortForward("glueops-core-kube-prometheus-stack", "kps-alertmanager", 9093) as pf:
        yield f"http://127.0.0.1:{pf.local_port}"


@pytest.fixture
def vault_client(captain_domain, request):
    """
    Vault client with automatic port-forward and cleanup.
    
    Establishes kubectl port-forward to Vault, authenticates, and yields
    an authenticated hvac.Client. Automatically cleans up port-forward
    on test completion.
    
    Args:
        captain_domain: Captain domain fixture (injected automatically)
        request: Pytest request fixture (injected automatically)
    
    Returns:
        hvac.Client: Authenticated Vault client
    
    Raises:
        ImportError: If hvac library not installed
        pytest.skip: If required environment variables not set
    
    Usage:
        def test_vault_secrets(vault_client):
            # Create secret
            vault_client.secrets.kv.v2.create_or_update_secret(
                path="test/path",
                secret={"key": "value"}
            )
            
            # Read secret
            result = vault_client.secrets.kv.v2.read_secret_version(path="test/path")
            assert result['data']['data']['key'] == 'value'
    """
    from tests.helpers.vault import get_vault_client, cleanup_vault_client
    
    verbose = request.config.option.verbose > 0
    vault_namespace = "glueops-core-vault"
    
    client = get_vault_client(
        captain_domain, 
        vault_namespace=vault_namespace, 
        verbose=verbose
    )
    
    yield client
    
    cleanup_vault_client(client, verbose=verbose)


# =============================================================================
# SCREENSHOT MANAGER FIXTURE
# =============================================================================

@pytest.fixture
def screenshots(request):
    """
    Screenshot manager with automatic summary logging.
    
    Creates a ScreenshotManager configured for the current test and
    automatically logs a summary of all captured screenshots on teardown.
    
    Args:
        request: Pytest request fixture (injected automatically)
    
    Returns:
        ScreenshotManager: Manager instance for capturing screenshots
    
    Usage:
        def test_ui_flow(page, screenshots):
            page.goto("https://example.com")
            screenshots.capture(page, "https://example.com", "Homepage")
            
            page.click("button[name='login']")
            screenshots.capture(page, page.url, "After clicking login")
            
            # Summary automatically logged at test end
    """
    from tests.helpers.browser import ScreenshotManager
    
    # Extract clean test name
    test_name = request.node.name.replace('test_', '')
    manager = ScreenshotManager(test_name=test_name, request=request)
    
    yield manager
    
    manager.log_summary()


# =============================================================================
# AUTHENTICATED BROWSER PAGE FIXTURES
# =============================================================================

@pytest.fixture
def authenticated_argocd_page(page, github_credentials, captain_domain):
    """
    Browser page authenticated to ArgoCD via GitHub OAuth.
    
    Handles the complete OAuth flow including:
    - Navigating to ArgoCD
    - Detecting and completing GitHub OAuth login
    - Handling SSO button clicks
    - Managing redirects
    
    Args:
        page: Playwright page fixture (injected automatically)
        github_credentials: GitHub credentials fixture (injected automatically)
        captain_domain: Captain domain fixture (injected automatically)
    
    Returns:
        Page: Playwright page object authenticated to ArgoCD
    
    Usage:
        def test_argocd_apps(authenticated_argocd_page):
            # Page is already authenticated and on ArgoCD
            authenticated_argocd_page.goto(f"https://argocd.{captain_domain}/applications")
            # ... perform test actions ...
    """
    from tests.helpers.browser import complete_github_oauth_flow
    
    argocd_url = f"https://argocd.{captain_domain}/applications"
    
    # Navigate to ArgoCD
    page.goto(argocd_url, wait_until="load", timeout=30000)
    
    # Handle GitHub OAuth if redirected
    if "github.com" in page.url:
        complete_github_oauth_flow(page, github_credentials)
        page.wait_for_timeout(3000)
    
    # If on login page, click SSO button
    if "/login" in page.url:
        page.get_by_role("button", name="Log in via GitHub SSO").click()
        page.wait_for_timeout(5000)
        
        if "github.com" in page.url:
            complete_github_oauth_flow(page, github_credentials)
            page.wait_for_timeout(3000)
    
    # Navigate to ArgoCD one final time to ensure we're there
    page.goto(argocd_url, wait_until="load", timeout=30000)
    page.wait_for_timeout(3000)
    
    yield page


@pytest.fixture
def authenticated_grafana_page(page, github_credentials, captain_domain):
    """
    Browser page authenticated to Grafana via GitHub OAuth.
    
    Handles the complete OAuth flow including:
    - Navigating to Grafana
    - Detecting and completing GitHub OAuth login
    - Handling SSO button clicks
    - Managing redirects
    
    Args:
        page: Playwright page fixture (injected automatically)
        github_credentials: GitHub credentials fixture (injected automatically)
        captain_domain: Captain domain fixture (injected automatically)
    
    Returns:
        Page: Playwright page object authenticated to Grafana
    
    Usage:
        def test_grafana_dashboards(authenticated_grafana_page):
            # Page is already authenticated and on Grafana
            authenticated_grafana_page.goto(f"https://grafana.{captain_domain}/dashboards")
            # ... perform test actions ...
    """
    from tests.helpers.browser import complete_github_oauth_flow
    
    grafana_url = f"https://grafana.{captain_domain}"
    
    # Navigate to Grafana
    page.goto(grafana_url, wait_until="load", timeout=30000)
    
    # Handle GitHub OAuth if redirected
    if "github.com" in page.url:
        complete_github_oauth_flow(page, github_credentials)
        page.wait_for_timeout(3000)
    
    # If on login page, click SSO button
    if "/login" in page.url:
        page.get_by_role("button", name="Log in via GitHub SSO").click()
        page.wait_for_timeout(5000)
        
        if "github.com" in page.url:
            complete_github_oauth_flow(page, github_credentials)
            page.wait_for_timeout(3000)
    
    # Navigate to Grafana one final time to ensure we're there
    page.goto(grafana_url, wait_until="load", timeout=30000)
    page.wait_for_timeout(3000)
    
    yield page


@pytest.fixture
def authenticated_vault_page(page, github_credentials, captain_domain):
    """
    Browser page authenticated to Vault via GitHub OAuth.
    
    Handles the complete OAuth flow including:
    - Navigating to Vault
    - Detecting and completing GitHub OAuth login
    - Handling SSO button clicks
    - Managing redirects
    
    Args:
        page: Playwright page fixture (injected automatically)
        github_credentials: GitHub credentials fixture (injected automatically)
        captain_domain: Captain domain fixture (injected automatically)
    
    Returns:
        Page: Playwright page object authenticated to Vault
    
    Usage:
        def test_vault_ui(authenticated_vault_page):
            # Page is already authenticated and on Vault
            authenticated_vault_page.goto(f"https://vault.{captain_domain}/ui/vault/secrets")
            # ... perform test actions ...
    """
    from tests.helpers.browser import complete_github_oauth_flow
    
    vault_url = f"https://vault.{captain_domain}/ui/"
    
    # Navigate to Vault
    page.goto(vault_url, wait_until="load", timeout=30000)
    
    # Handle GitHub OAuth if redirected
    if "github.com" in page.url:
        complete_github_oauth_flow(page, github_credentials)
        page.wait_for_timeout(3000)
    
    # If on login page, click SSO button
    if "/login" in page.url or "method=oidc" not in page.url:
        try:
            page.get_by_role("button", name="Sign in with OIDC Provider").click()
            page.wait_for_timeout(5000)
            
            if "github.com" in page.url:
                complete_github_oauth_flow(page, github_credentials)
                page.wait_for_timeout(3000)
        except Exception:
            # Button might not be present if already authenticated
            pass
    
    # Navigate to Vault one final time to ensure we're there
    page.goto(vault_url, wait_until="load", timeout=30000)
    page.wait_for_timeout(3000)
    
    yield page


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




def pytest_configure(config):
    """Configure pytest with custom settings"""
    # Register custom markers
    config.addinivalue_line("markers", "gitops: GitOps integration tests")
    config.addinivalue_line("markers", "quick: Quick tests that run in <5 seconds")
    config.addinivalue_line("markers", "smoke: Smoke tests for basic functionality")
    config.addinivalue_line("markers", "write: Tests that modify cluster state")
    config.addinivalue_line("markers", "oauth_redirect: OAuth redirect flow tests")
    config.addinivalue_line("markers", "authenticated: Authenticated UI tests")
    
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
