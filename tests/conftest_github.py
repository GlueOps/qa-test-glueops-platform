"""
GitHub and GitOps fixtures for GlueOps test suite.

This module provides fixtures for GitHub repository operations, credentials,
and ephemeral repository management for GitOps testing.

Fixtures:
    - tenant_github_org: Tenant GitHub organization name
    - deployment_config_template_repo: Template repository URL for deployment configs
    - captain_domain_repo_url: Captain domain GitHub repository URL
    - captain_domain_github_token: GitHub token for captain domain repo access
    - github_credentials: GitHub credentials for UI tests (username, password, OTP)
    - ephemeral_github_repo: Creates ephemeral GitHub repo from template
    - github_repo_factory: Factory for creating multiple ephemeral repos
"""
import pytest
import os
import re
import uuid
import logging
from typing import Optional
from github import Github, GithubException, Auth
from github.Organization import Organization
from github.NamedUser import NamedUser
from github.AuthenticatedUser import AuthenticatedUser

from tests.helpers.github import (
    delete_directory_contents,
    delete_repos_by_topic,
    set_repo_topics,
    clone_repo_contents,
)


logger = logging.getLogger(__name__)


# =============================================================================
# TENANT CONFIGURATION FIXTURES
# =============================================================================

@pytest.fixture(scope="session")
def tenant_github_org():
    """
    Tenant GitHub organization name.
    
    Reads from TENANT_GITHUB_ORGANIZATION_NAME environment variable.
    
    Scope: session
    
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
    
    Reads from DEPLOYMENT_CONFIGURATIONS_TEMPLATE_REPO environment variable.
    
    Scope: session
    
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
    
    Scope: session
    
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
    
    Scope: session
    
    Returns:
        str: GitHub personal access token
        
    Raises:
        pytest.skip: If not configured
    """
    token = os.environ.get("CAPTAIN_DOMAIN_GITHUB_TOKEN")
    if not token:
        pytest.skip("CAPTAIN_DOMAIN_GITHUB_TOKEN environment variable not set")
    return token


@pytest.fixture(scope="session")
def github_credentials():
    """
    GitHub credentials for UI tests.
    
    Reads from environment variables:
    - GITHUB_USERNAME: GitHub username or email
    - GITHUB_PASSWORD: GitHub password
    - GITHUB_OTP_SECRET: TOTP secret for 2FA
    
    Scope: session (credentials reused across all UI tests)
    
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


# =============================================================================
# EPHEMERAL GITHUB REPOSITORY FIXTURES
# =============================================================================

def _get_github_client_and_owner(github_token: str, org_name: str):
    """
    Get authenticated GitHub client and destination owner (org or user).
    
    Args:
        github_token: GitHub personal access token
        org_name: Organization or user name
        
    Returns:
        tuple: (Github client, owner object)
        
    Raises:
        pytest.skip: If owner cannot be resolved
    """
    auth = Auth.Token(github_token)
    g = Github(auth=auth)
    
    dest_owner: Organization | NamedUser | AuthenticatedUser
    try:
        dest_owner = g.get_organization(org_name)
    except GithubException:
        try:
            dest_owner = g.get_user(org_name)
        except GithubException as e:
            pytest.skip(f"Failed to get destination owner '{org_name}': {e}")
    
    return g, dest_owner


def _create_ephemeral_repo(
    g: Github,
    dest_owner,
    template_repo,
    clone_ref: str,
    repo_name: str,
    clear_apps: bool = True
):
    """
    Create an ephemeral repository from a template.
    
    Args:
        g: Authenticated GitHub client
        dest_owner: Destination organization/user
        template_repo: Template repository object
        clone_ref: Git ref to clone (tag or branch)
        repo_name: Name for the new repository
        clear_apps: Whether to clear apps/ directory after cloning
        
    Returns:
        Repository: Created repository object
        
    Raises:
        pytest.fail: If creation fails
    """
    logger.info(f"\n📦 Creating ephemeral repository: {repo_name}")
    
    # Create empty repository
    try:
        test_repo = dest_owner.create_repo(
            name=repo_name,
            description="Ephemeral test repository for GitOps testing",
            private=False,
            auto_init=True
        )
        logger.info(f"✓ Repository created: {test_repo.html_url}")
    except GithubException as e:
        pytest.fail(f"Failed to create repository: {e.status} {e.data.get('message', str(e))}")
    
    # Set topics IMMEDIATELY for cleanup
    logger.info("🏷️  Setting repository topics...")
    set_repo_topics(g, test_repo, ['createdby-automated-test-delete-me'])
    
    # Validate topics were persisted
    logger.info("Validating topics were persisted...")
    try:
        validated_repo = g.get_repo(test_repo.full_name)
        actual_topics = validated_repo.get_topics()
        expected_topic = 'createdby-automated-test-delete-me'
        
        if expected_topic not in actual_topics:
            error_msg = (
                f"❌ TOPIC VALIDATION FAILED!\n"
                f"   Repository: {test_repo.full_name}\n"
                f"   Expected topic: '{expected_topic}'\n"
                f"   Actual topics: {actual_topics if actual_topics else '(none)'}\n"
                f"   This repo will NOT be auto-cleaned up!"
            )
            logger.error(error_msg)
            pytest.fail(error_msg)
        
        logger.info(f"✓ Topic validated: '{expected_topic}' found on {test_repo.full_name}")
        
    except GithubException as e:
        error_msg = f"❌ Failed to validate topics: {e.status} - {e.data.get('message', str(e))}"
        logger.error(error_msg)
        pytest.fail(error_msg)
    
    # Clone contents from template repo
    logger.info(f"📋 Cloning template repository contents (ref: {clone_ref})...")
    try:
        file_count = clone_repo_contents(
            source_repo=template_repo,
            dest_repo=test_repo,
            ref=clone_ref,
            skip_ci=True
        )
        logger.info(f"✓ Cloned {file_count} files from template")
    except GithubException as e:
        pytest.fail(f"Failed to clone template repository: {e.status} {e.data.get('message', str(e))}")
    
    # Clear apps directory if requested
    if clear_apps:
        logger.info("🧹 Clearing apps/ directory...")
        try:
            delete_directory_contents(test_repo, "apps", skip_ci=True)
            logger.info("✓ Apps folder cleared - ready for test to add apps")
        except GithubException as e:
            if e.status == 403:
                pytest.fail(f"❌ Failed to clear apps folder - permission denied (403). Check GITHUB_TOKEN has write access to {test_repo.full_name}")
            else:
                pytest.fail(f"❌ Failed to clear apps folder: {e.status} {e.data.get('message', str(e))}")
        except Exception as e:
            pytest.fail(f"❌ Failed to clear apps folder: {e}")
    
    return test_repo


@pytest.fixture
def ephemeral_github_repo(request, deployment_config_template_repo, tenant_github_org):
    """
    Create an ephemeral GitHub repository from a template for testing.
    
    This fixture:
    1. Creates a repository with unique name from template
    2. Sets 'createdby-automated-test-delete-me' topic for automated cleanup
    3. Clears apps/ directory
    4. Yields the repository object for test use
    5. Deletes all test repos by topic in teardown
    
    Note: Orphaned repos from previous runs are cleaned by session-scoped fixture.
    
    Scope: function (new repo per test)
    
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
    # Get required environment variables
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        pytest.skip("GITHUB_TOKEN environment variable not set")
    
    # Parse template repo URL
    template_repo_url = deployment_config_template_repo
    template_match = re.match(r'https://github\.com/([^/]+)/([^/]+)(?:/releases/tag/([^/]+))?', template_repo_url)
    if not template_match:
        pytest.skip(f"Invalid DEPLOYMENT_CONFIGURATIONS_TEMPLATE_REPO format: {template_repo_url}")
    
    template_org, template_repo_name, target_tag = template_match.groups()
    template_repo_full_name = f"{template_org}/{template_repo_name}"
    
    # Get GitHub client and destination owner
    g, dest_owner = _get_github_client_and_owner(github_token, tenant_github_org)
    
    # Get template repository
    try:
        template_repo = g.get_repo(template_repo_full_name)
    except GithubException as e:
        pytest.skip(f"Failed to get template repository '{template_repo_full_name}': {e}")
    
    # Generate unique repository name
    test_repo_name = f"deployment-configurations-{str(uuid.uuid4())[:8]}"
    logger.info(f"\n" + "="*70)
    logger.info("SETUP: Creating deployment-configurations repository")
    logger.info("="*70)
    logger.info(f"Repository name: {test_repo_name}")
    
    # Determine ref to use
    clone_ref = target_tag if target_tag else template_repo.default_branch
    logger.info(f"Template ref: {clone_ref}")
    
    # Create the repository
    test_repo = _create_ephemeral_repo(
        g=g,
        dest_owner=dest_owner,
        template_repo=template_repo,
        clone_ref=clone_ref,
        repo_name=test_repo_name,
        clear_apps=True
    )
    
    logger.info("="*70 + "\n")
    logger.info(f"✓ Repository ready: {test_repo.full_name}")
    logger.info(f"✓ Repository URL: {test_repo.html_url}\n")
    
    yield test_repo
    
    # Teardown: Delete all test repositories by topic
    logger.info("\n" + "="*70)
    logger.info("TEARDOWN: Deleting test repositories")
    logger.info("="*70)
    delete_repos_by_topic(dest_owner, 'createdby-automated-test-delete-me')
    logger.info("="*70 + "\n")


@pytest.fixture
def github_repo_factory(deployment_config_template_repo, tenant_github_org):
    """
    Factory fixture for creating multiple ephemeral GitHub repositories.
    
    Returns a callable that creates new ephemeral repositories on demand.
    All created repositories are tracked and cleaned up on teardown.
    
    Scope: function
    
    Usage:
        def test_multiple_repos(github_repo_factory):
            repo1 = github_repo_factory("my-test-1")
            repo2 = github_repo_factory("my-test-2")
            
            # Both repos are automatically cleaned up after test
    
    Returns:
        callable: Factory function that accepts optional name suffix
    
    Factory Arguments:
        name_suffix (str, optional): Custom suffix for repo name. 
            Defaults to random UUID if not provided.
        clear_apps (bool, optional): Whether to clear apps/ directory. 
            Defaults to True.
    
    Raises:
        pytest.skip: If required environment variables are not set
    """
    # Get required environment variables
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        pytest.skip("GITHUB_TOKEN environment variable not set")
    
    # Parse template repo URL
    template_repo_url = deployment_config_template_repo
    template_match = re.match(r'https://github\.com/([^/]+)/([^/]+)(?:/releases/tag/([^/]+))?', template_repo_url)
    if not template_match:
        pytest.skip(f"Invalid DEPLOYMENT_CONFIGURATIONS_TEMPLATE_REPO format: {template_repo_url}")
    
    template_org, template_repo_name, target_tag = template_match.groups()
    template_repo_full_name = f"{template_org}/{template_repo_name}"
    
    # Get GitHub client and destination owner
    g, dest_owner = _get_github_client_and_owner(github_token, tenant_github_org)
    
    # Get template repository
    try:
        template_repo = g.get_repo(template_repo_full_name)
    except GithubException as e:
        pytest.skip(f"Failed to get template repository '{template_repo_full_name}': {e}")
    
    # Determine ref to use
    clone_ref = target_tag if target_tag else template_repo.default_branch
    
    # Track created repos for cleanup
    created_repos = []
    
    def create_repo(name_suffix: Optional[str] = None, clear_apps: bool = True):
        """
        Create a new ephemeral repository.
        
        Args:
            name_suffix: Optional suffix for the repo name. Random UUID if not provided.
            clear_apps: Whether to clear apps/ directory after cloning.
            
        Returns:
            Repository: The created repository object
        """
        suffix = name_suffix if name_suffix else str(uuid.uuid4())[:8]
        repo_name = f"deployment-configurations-{suffix}"
        
        repo = _create_ephemeral_repo(
            g=g,
            dest_owner=dest_owner,
            template_repo=template_repo,
            clone_ref=clone_ref,
            repo_name=repo_name,
            clear_apps=clear_apps
        )
        
        created_repos.append(repo)
        logger.info(f"✓ Factory created repository: {repo.full_name}")
        return repo
    
    yield create_repo
    
    # Teardown: Delete all created repos by topic
    logger.info("\n" + "="*70)
    logger.info(f"TEARDOWN: Cleaning up {len(created_repos)} factory-created repositories")
    logger.info("="*70)
    delete_repos_by_topic(dest_owner, 'createdby-automated-test-delete-me')
    logger.info("="*70 + "\n")
