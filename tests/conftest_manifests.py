"""
Captain manifests and GitOps deployment fixtures for GlueOps test suite.

This module provides fixtures for creating ArgoCD manifests, deploying
fixture applications, and managing test namespace lifecycle.

Fixtures:
    - captain_manifests: Creates dynamic ArgoCD manifests for test isolation
    - fixture_apps: Convenience wrapper for fixture app metadata
"""
import pytest
import time
import uuid
import logging
from typing import Optional, TypedDict, List

from tests.helpers.k8s import (
    wait_for_argocd_apps_deleted,
    ensure_argocd_app_allows_empty,
)
from tests.helpers.argocd import (
    wait_for_argocd_apps_by_project_deleted,
    wait_for_argocd_app_healthy,
    refresh_and_wait_for_argocd_app,
    wait_for_appset_apps_created_and_healthy,
)
from tests.helpers.github import (
    get_captain_repo,
    get_repo_latest_sha,
    create_or_update_file,
    delete_file_if_exists,
    create_github_file,
)
from tests.helpers.manifests import (
    extract_namespace_from_captain_domain,
    generate_namespace_yaml,
    generate_appproject_yaml,
    generate_appset_yaml,
    generate_pullrequest_appset_yaml,
)
from tests.templates import load_template
from tests.helpers.github import delete_repos_by_topic


logger = logging.getLogger(__name__)


# =============================================================================
# SESSION-SCOPED CLEANUP
# =============================================================================

@pytest.fixture(scope="session", autouse=True)
def cleanup_orphaned_test_resources_session(
    custom_api,
    captain_domain,
    captain_domain_repo_url,
    captain_domain_github_token,
    tenant_github_org
):
    """
    Clean up orphaned test resources from previous interrupted runs.
    
    Runs once at session start before any tests. Cleans in correct order:
    1. Manifests first (while repos still exist, can validate health)
    2. Then deployment-configurations repos
    
    This prevents the issue where:
    - Old repos get deleted first
    - Then manifests referencing deleted repos can't become healthy
    - Pre-cleanup gets stuck waiting for health
    
    Scope: session (runs once at start)
    Autouse: True (always runs)
    """
    logger.info("\n" + "="*70)
    logger.info("SESSION CLEANUP: Removing orphaned resources from previous runs")
    logger.info("="*70)
    
    # Extract namespace from captain domain
    namespace_name = extract_namespace_from_captain_domain(captain_domain)
    
    # Connect to captain repo
    g, captain_repo = get_captain_repo(
        token=captain_domain_github_token,
        repo_url=captain_domain_repo_url
    )
    
    # Define manifest paths
    manifest_paths = {
        'namespace': 'manifests/namespace.yaml',
        'appproject': 'manifests/appproject.yaml',
        'appset': 'manifests/appset.yaml',
        'pullrequest_appset': 'manifests/pullrequest-appset.yaml',
    }
    
    # Step 1: Clean up orphaned manifests FIRST (repos still exist)
    logger.info("\n1️⃣  Cleaning up orphaned captain manifests...")
    try:
        _cleanup_manifests(
            captain_repo=captain_repo,
            manifest_paths=manifest_paths,
            namespace_name=namespace_name,
            custom_api=custom_api
        )
        logger.info("   ✓ Orphaned manifests cleaned")
    except Exception as e:
        logger.warning(f"   ⚠ Error cleaning manifests (may not exist): {e}")
    
    # Step 2: NOW clean up orphaned repos (manifests already gone)
    logger.info("\n2️⃣  Cleaning up orphaned test repositories...")
    try:
        # Get GitHub client to access tenant org
        import os
        from github import Github, Auth
        github_token = os.environ.get("GITHUB_TOKEN")
        if github_token:
            g = Github(auth=Auth.Token(github_token))
            dest_owner = g.get_organization(tenant_github_org) if tenant_github_org else g.get_user()
            delete_repos_by_topic(dest_owner, 'createdby-automated-test-delete-me')
            logger.info("   ✓ Orphaned repositories cleaned")
        else:
            logger.warning("   ⚠ GITHUB_TOKEN not set, skipping repo cleanup")
    except Exception as e:
        logger.warning(f"   ⚠ Error cleaning repos (may not exist): {e}")
    
    logger.info("\n✓ Session cleanup complete")
    logger.info("="*70 + "\n")
    
    yield


# =============================================================================
# FIXTURE APP CONFIGURATION
# =============================================================================

class FixtureAppConfig(TypedDict, total=False):
    """Type definition for fixture app configuration."""
    name: str
    replicas: int
    type: str


# Fixture applications automatically deployed before tests run.
# These are shared test utilities available to all tests.
# Easy to add more by extending this list.
FIXTURE_APP_CONFIGS: List[FixtureAppConfig] = [
    {'name': 'fixture-http-debug-1', 'replicas': 2, 'type': 'http-debug'},
    {'name': 'fixture-http-debug-2', 'replicas': 2, 'type': 'http-debug'},
    {'name': 'fixture-http-debug-3', 'replicas': 2, 'type': 'http-debug'},
    {'name': 'container-registry', 'replicas': 1, 'type': 'registry'},
]


def _create_fixture_values_yaml(app_name: str, hostname: str, replicas: int, app_type: str = 'http-debug') -> str:
    """Generate values.yaml for fixture application.
    
    Args:
        app_name: Application name for deployment
        hostname: Full hostname for ingress (e.g., app.apps.example.com)
        replicas: Number of pod replicas to deploy
        app_type: Type of app ('http-debug' or 'registry')
        
    Returns:
        str: YAML content for values.yaml file
    """
    if app_type == 'registry':
        # Inline YAML for container registry
        return f"""#https://hub.docker.com/_/registry
image:
  registry: dockerhub.repo.gpkg.io
  repository: registry
  tag: 3.0.0
  port: 5000
service:
  enabled: true
deployment:
  replicas: {replicas}
  enabled: true
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
ingress:
  enabled: true
  ingressClassName: public
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "0"
  entries:
    - name: public
      hosts:
        - hostname: {hostname}
podDisruptionBudget:
  enabled: true
"""
    else:
        # Use existing http-debug template
        return load_template('http-debug-app-values.yaml',
                           hostname=hostname,
                           replicas=replicas,
                           cpu='100m',
                           memory='128Mi',
                           pdb_enabled='true')


def _deploy_fixture_apps(
    ephemeral_github_repo,
    captain_domain: str,
    fixture_app_configs: Optional[List[FixtureAppConfig]] = None
) -> tuple:
    """
    Deploy fixture applications to the ephemeral repository.
    
    Args:
        ephemeral_github_repo: GitHub repository object
        captain_domain: Captain domain for hostname generation
        fixture_app_configs: List of app configs (defaults to FIXTURE_APP_CONFIGS)
        
    Returns:
        tuple: (fixture_apps_metadata list, fixture_apps_by_friendly_name dict)
    """
    if fixture_app_configs is None:
        fixture_app_configs = FIXTURE_APP_CONFIGS
    
    fixture_apps_metadata = []
    fixture_apps_by_friendly_name = {}
    
    # Load env-values template
    env_values_yaml = load_template('env-values.yaml')
    
    # Deploy each fixture app
    for config in fixture_app_configs:
        app_name_base: str = config['name']
        replicas: int = config['replicas']
        app_type: str = config.get('type', 'http-debug')
        guid = str(uuid.uuid4())[:8]
        app_name = f"{app_name_base}-{guid}"
        hostname = f"{app_name}.apps.{captain_domain}"
        
        logger.info(f"\n📦 Creating fixture app: {app_name}")
        logger.info(f"   Friendly name: {app_name_base}")
        logger.info(f"   GUID: {guid}")
        logger.info(f"   Hostname: {hostname}")
        
        # Create directory structure
        values_yaml = _create_fixture_values_yaml(app_name, hostname, replicas, app_type)
        
        create_github_file(
            ephemeral_github_repo,
            f"apps/{app_name}/envs/prod/values.yaml",
            values_yaml,
            f"Add fixture app {app_name}"
        )
        
        create_github_file(
            ephemeral_github_repo,
            f"apps/{app_name}/envs/prod/env-values.yaml",
            env_values_yaml,
            f"Add env-values for fixture app {app_name}"
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
    
    return fixture_apps_metadata, fixture_apps_by_friendly_name


def _cleanup_manifests(
    captain_repo,
    manifest_paths: dict,
    namespace_name: str,
    custom_api
):
    """
    Clean up captain manifests in the correct order.
    
    Order: ApplicationSets → wait for apps deleted → AppProject → Namespace
    
    Args:
        captain_repo: GitHub repository object for captain domain
        manifest_paths: Dict of manifest type to file path
        namespace_name: Name of the namespace being cleaned up
        custom_api: Kubernetes CustomObjectsApi client
    """
    try:
        # Step 0: Ensure captain-manifests allows empty sync to prevent
        # "auto-sync will wipe out all resources" errors during cleanup
        logger.info("Ensuring captain-manifests allows empty sync...")
        ensure_argocd_app_allows_empty(custom_api, "captain-manifests", "glueops-core")
        
        # Step 1: Delete ApplicationSets first
        logger.info("\n🗑️  Step 1: Deleting ApplicationSets...")
        commit_sha = delete_file_if_exists(
            captain_repo,
            manifest_paths['appset'],
            f"Teardown: remove ApplicationSet for {namespace_name}"
        )
        if commit_sha:
            refresh_and_wait_for_argocd_app(
                custom_api, app_name="captain-manifests", 
                namespace="glueops-core", expected_sha=commit_sha
            )
        
        commit_sha = delete_file_if_exists(
            captain_repo,
            manifest_paths['pullrequest_appset'],
            f"Teardown: remove pull request ApplicationSet for {namespace_name}"
        )
        if commit_sha:
            refresh_and_wait_for_argocd_app(
                custom_api, app_name="captain-manifests",
                namespace="glueops-core", expected_sha=commit_sha
            )
        
        # Step 2: Wait for ArgoCD applications to be deleted
        logger.info("\n⏳ Step 2: Waiting for ArgoCD applications to be deleted...")
        apps_deleted = wait_for_argocd_apps_deleted(
            custom_api,
            namespace=namespace_name
        )
        
        if not apps_deleted:
            logger.warning(f"⚠ Some ArgoCD apps may still exist in '{namespace_name}'")
        
        # Step 2b: Wait for ALL Application CRs that reference this project
        logger.info("\n⏳ Step 2b: Waiting for Application CRs referencing project to be deleted...")
        project_apps_deleted = wait_for_argocd_apps_by_project_deleted(
            custom_api,
            project_name=namespace_name
        )
        
        if not project_apps_deleted:
            logger.warning(f"⚠ Some Application CRs may still reference project '{namespace_name}'")
        
        # Step 3: Delete AppProject
        logger.info("\n🗑️  Step 3: Deleting AppProject...")
        commit_sha = delete_file_if_exists(
            captain_repo,
            manifest_paths['appproject'],
            f"Teardown: remove AppProject for {namespace_name}"
        )
        if commit_sha:
            refresh_and_wait_for_argocd_app(
                custom_api, app_name="captain-manifests",
                namespace="glueops-core", expected_sha=commit_sha
            )
        
        # Step 4: Delete Namespace
        logger.info("\n🗑️  Step 4: Deleting Namespace...")
        commit_sha = delete_file_if_exists(
            captain_repo,
            manifest_paths['namespace'],
            f"Teardown: remove Namespace for {namespace_name}"
        )
        if commit_sha:
            refresh_and_wait_for_argocd_app(
                custom_api, app_name="captain-manifests",
                namespace="glueops-core", expected_sha=commit_sha
            )
        
        # Step 5: Final health check for captain-manifests
        logger.info("\n🔄 Step 5: Verifying captain-manifests is healthy...")
        latest_sha = get_repo_latest_sha(captain_repo)
        
        if latest_sha:
            # Verify sync to latest commit
            app_healthy = refresh_and_wait_for_argocd_app(
                custom_api,
                app_name="captain-manifests",
                namespace="glueops-core",
                expected_sha=latest_sha
            )
        else:
            # Fallback: just wait for healthy status without SHA validation
            logger.warning("Could not get latest SHA, falling back to health check only")
            app_healthy = wait_for_argocd_app_healthy(
                custom_api,
                app_name="captain-manifests",
                namespace="glueops-core",
            )
        
        if not app_healthy:
            logger.warning("⚠ captain-manifests app did not become healthy within timeout")
        
        logger.info("\n✓ Captain manifests cleanup complete")
        
    except Exception as e:
        logger.error(f"\n❌ Error during teardown: {e}")
        logger.error("Manual cleanup may be required")


# =============================================================================
# MAIN FIXTURES
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
    7. Teardown: Deletes AppSet → waits for apps deleted → deletes remaining manifests
    
    Scope: function (new manifests per test)
    
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
    
    Dependencies:
        - captain_domain: Captain domain configuration
        - captain_domain_repo_url: Captain repo URL
        - captain_domain_github_token: GitHub token
        - tenant_github_org: Tenant organization name
        - ephemeral_github_repo: Ephemeral deployment config repo
        - custom_api: Kubernetes CustomObjectsApi client
    
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
        repo_url=captain_domain_repo_url
    )
    
    # Define manifest paths
    manifest_paths = {
        'namespace': 'manifests/namespace.yaml',
        'appproject': 'manifests/appproject.yaml',
        'appset': 'manifests/appset.yaml',
        'pullrequest_appset': 'manifests/pullrequest-appset.yaml',
    }
    
    # Pre-cleanup: Delete existing manifests in reverse order of creation
    # CRITICAL: Must delete ApplicationSet first to avoid "appproject not found" errors
    logger.info("\n📋 Pre-cleanup: Removing existing manifests (reverse order of creation)...")
    
    # Ensure captain-manifests allows empty sync before cleanup
    logger.info("   Ensuring captain-manifests allows empty sync...")
    ensure_argocd_app_allows_empty(custom_api, "captain-manifests", "glueops-core")
    
    for i, (name, path) in enumerate(reversed(list(manifest_paths.items())), 1):
        logger.info(f"   {i}. Deleting {name}...")
        commit_sha = delete_file_if_exists(captain_repo, path, f"Pre-cleanup: remove {name}")
        
        if commit_sha:
            logger.info(f"      Waiting for captain-manifests to stabilize...")
            try:
                app_healthy = refresh_and_wait_for_argocd_app(
                    custom_api,
                    app_name="captain-manifests",
                    namespace="glueops-core",
                    expected_sha=commit_sha
                )
                if not app_healthy:
                    logger.error(f"      ❌ captain-manifests did not stabilize after deleting {name}")
                else:
                    logger.info(f"      ✓ captain-manifests stable")
            except Exception as e:
                logger.error(f"      ❌ Exception while waiting for captain-manifests: {e}")
    
    # Give GitHub API time to process deletions
    time.sleep(2)
    
    # Wait for ArgoCD to clean up old resources
    logger.info("\n⏳ Waiting for old ArgoCD resources to be deleted...")
    logger.info(f"   Checking for Application CRs referencing project '{namespace_name}'...")
    project_apps_deleted = wait_for_argocd_apps_by_project_deleted(
        custom_api,
        project_name=namespace_name
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
        deployment_config_repo=ephemeral_github_repo.name,
        captain_domain=captain_domain
    )
    pullrequest_appset_yaml = generate_pullrequest_appset_yaml(
        namespace_name=namespace_name,
        tenant_github_org=tenant_github_org,
        deployment_config_repo=ephemeral_github_repo.name,
        captain_domain=captain_domain
    )
    
    # Commit manifests to captain repo
    logger.info("\n📤 Committing manifests to captain repo...")
    
    namespace_result = create_or_update_file(
        captain_repo,
        manifest_paths['namespace'],
        namespace_yaml,
        f"Create namespace manifest for {namespace_name}"
    )
    
    appproject_result = create_or_update_file(
        captain_repo,
        manifest_paths['appproject'],
        appproject_yaml,
        f"Create AppProject manifest for {namespace_name}"
    )
    
    appset_result = create_or_update_file(
        captain_repo,
        manifest_paths['appset'],
        appset_yaml,
        f"Create ApplicationSet manifest for {namespace_name}"
    )
    
    pullrequest_appset_result = create_or_update_file(
        captain_repo,
        manifest_paths['pullrequest_appset'],
        pullrequest_appset_yaml,
        f"Create pull request ApplicationSet manifest for {namespace_name}"
    )
    
    logger.info(f"\n✓ All manifests committed successfully:")
    logger.info(f"  Namespace:        {namespace_result['commit'].sha[:8]}")
    logger.info(f"  AppProject:       {appproject_result['commit'].sha[:8]}")
    logger.info(f"  AppSet:           {appset_result['commit'].sha[:8]}")
    logger.info(f"  PR AppSet:        {pullrequest_appset_result['commit'].sha[:8]}")
    
    # Wait for captain-manifests ArgoCD Application to become healthy
    logger.info("")
    
    captain_app_healthy = wait_for_argocd_app_healthy(
        custom_api=custom_api,
        app_name='captain-manifests',
        namespace='glueops-core',
    )
    
    if not captain_app_healthy:
        pytest.fail("Captain manifests Application did not become healthy within timeout")
    
    logger.info("\n✓ Captain manifests verified successfully")
    logger.info("="*70 + "\n")
    
    # Deploy fixture applications
    logger.info("\n" + "="*70)
    logger.info("FIXTURE APPS: Deploying fixture applications")
    logger.info("="*70)
    
    fixture_apps_metadata, fixture_apps_by_friendly_name = _deploy_fixture_apps(
        ephemeral_github_repo=ephemeral_github_repo,
        captain_domain=captain_domain
    )
    
    # Wait for ApplicationSet to discover and deploy fixture apps
    logger.info(f"\n⏳ Waiting for {len(fixture_apps_metadata)} fixture apps to become healthy...")
    
    apps_ready = wait_for_appset_apps_created_and_healthy(
        custom_api,
        namespace=namespace_name,
        expected_count=len(fixture_apps_metadata),
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
    
    _cleanup_manifests(
        captain_repo=captain_repo,
        manifest_paths=manifest_paths,
        namespace_name=namespace_name,
        custom_api=custom_api
    )
    
    logger.info("="*70 + "\n")


@pytest.fixture
def fixture_apps(captain_manifests):
    """
    Convenience fixture that returns fixture app info from captain_manifests.
    
    Fixture apps are shared test applications automatically deployed before tests run.
    They provide common utilities that any test may need.
    
    Scope: function
    
    Dependencies:
        - captain_manifests: Main manifest fixture
    
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
