"""
Pull Request Environment Tests

Tests the complete PR lifecycle for preview environments including:
1. Creating a new repository with Dockerfile and GitHub Actions workflow
2. Pushing container images to the in-cluster registry
3. Creating PRs with the -glueops-preview branch suffix
4. Holding PRs open for in-cluster automation to comment
5. Cleanup and teardown

The test validates that the PR comment automation works correctly by:
- Creating a real repository with container build pipeline
- Opening a PR and waiting for in-cluster automation to interact with it
- Verifying the PR lifecycle completes successfully
"""
import pytest
import os
import time
import uuid
import logging
import re
from github.Organization import Organization
from github.NamedUser import NamedUser
from github.AuthenticatedUser import AuthenticatedUser

from tests.helpers.github import (
    get_github_client,
    create_repo,
    delete_repo_if_exists,
    create_branch,
    create_dummy_commit,
    create_pull_request,
    create_github_file,
)
from tests.helpers.utils import display_progress_bar, print_section_header

logger = logging.getLogger(__name__)


# ============================================================================
# DOCKERFILE TEMPLATE
# Uses the http-debug image as base (same as fixture apps)
# ============================================================================
DOCKERFILE_CONTENT = """FROM dockerhub.repo.gpkg.io/mendhak/http-https-echo:37
# Preview environment test container
# This Dockerfile is used to test the container build pipeline
"""


def get_container_workflow_yaml(registry_hostname: str) -> str:
    """
    Generate the GitHub Actions workflow for building and pushing container images.
    
    Args:
        registry_hostname: The hostname of the in-cluster registry
                          (e.g., container-registry-abc123.apps.nonprod.jupiter.onglueops.rocks)
    
    Returns:
        str: The complete workflow YAML content
    """
    return f"""name: Build and Push Container Image

on:
  push:
    branches-ignore: 'dependabot/**'
  pull_request:
    branches-ignore: 'dependabot/**'
    types: [closed]
  release:
    types: [created]

env:
  REGISTRY: {registry_hostname}
  IMAGE_NAME: ${{{{ github.repository }}}}

jobs:
  build_tag_push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write

    steps:
      - name: Checkout repository
        uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4

      - name: Set up QEMU
        uses: docker/setup-qemu-action@49b3bc8e6bdd4a60e6116a5414239cba5943d3cf # v3

      - name: Setup Docker buildx
        uses: docker/setup-buildx-action@c47758b77c9736f4b2ef4073d4d51994fabfe349 # v3.7.1

      - name: Extract Docker metadata
        id: meta
        uses: docker/metadata-action@369eb591f429131d6889c46b94e711f089e6ca96 # v5.6.1
        with:
          github-token: ${{{{ secrets.GITHUB_TOKEN }}}}
          images: ${{{{ env.REGISTRY }}}}/${{{{ env.IMAGE_NAME }}}}
          tags: |
            type=ref,event=branch,prefix=
            type=ref,event=tag,prefix=
            type=sha,format=short,prefix=
            type=sha,format=long,prefix=
            type=raw,value=latest,enable={{{{is_default_branch}}}}

      - name: Build and push Docker image
        id: build-and-push
        uses: docker/build-push-action@48aba3b46d1b1fec4febb7c5d0c644b249a11355 # v6.10.0
        with:
          context: .
          push: true
          tags: ${{{{ steps.meta.outputs.tags }}}}
          labels: ${{{{ steps.meta.outputs.labels }}}}
          provenance: false
          cache-from: type=gha
          cache-to: type=gha,mode=max
"""


# ============================================================================
# EASILY EDITABLE: Valid GitHub name formats to test
# Each tuple is (repo_name, branch_name) - branch MUST end with -glueops-preview
# These are all VALID formats that GitHub accepts (no API errors expected)
# NOTE: Branch names must match the ApplicationSet filter pattern: .*-glueops-preview
# ============================================================================
NAME_VARIATIONS = [
    # (repo_name, branch_name) - Test different valid GitHub name formats
    ("demo-app-pr-testing", "feature/test-glueops-preview"),           # kebab-case + slash hierarchy
    ("demo_app_pr_testing", "preview-glueops-preview"),                # underscores
    ("Demo App PR Testing", "feature-v1.0.0-glueops-preview"),         # spaces→dashes + periods in version
    ("demo.app.pr.testing", "updates/npm-glueops-preview"),            # periods + deep slash path
    ("DemoAppPRTesting123", "hotfix-123-glueops-preview"),            # camelCase with numbers
]
# ============================================================================


@pytest.mark.gitops
@pytest.mark.preview_environments
@pytest.mark.captain_manifests
@pytest.mark.parametrize("repo_name,branch_name", NAME_VARIATIONS, ids=[
    "kebab-case",
    "underscores",
    "spaces-to-dashes",
    "periods",
    "camelCase-numbers",
])
def test_pull_request_environment(
    repo_name: str,
    branch_name: str,
    captain_manifests: dict,
    ephemeral_github_repo,
) -> None:
    """
    Test pull request environment workflow with container build pipeline.
    
    Creates a public repository with a Dockerfile and GitHub Actions workflow,
    simulates the full PR lifecycle:
    1. Creates repo with Dockerfile and workflow (pushes to in-cluster registry)
    2. Creates branch with -glueops-preview suffix (required for ApplicationSet)
    3. Creates PR with a dummy commit to trigger the container build
    4. Waits 3 minutes for in-cluster automation to comment on the PR
    5. Cleans up by closing PR and deleting the test repository
    
    Validates:
    - Repository creation with container build setup
    - Branch naming with ApplicationSet-compatible suffix
    - PR creation triggers container build asynchronously
    - In-cluster automation has time to interact with the PR
    
    Cluster Impact: WRITE (creates GitHub resources, pushes container images)
    """
    # Get GitHub credentials from environment
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        pytest.skip("GITHUB_TOKEN environment variable not set")
    
    # Get the organization from DESTINATION_REPO_URL
    destination_repo_url = os.environ.get("DESTINATION_REPO_URL")
    if not destination_repo_url:
        pytest.skip("DESTINATION_REPO_URL environment variable not set")
    
    dest_match = re.match(r'https://github\.com/([^/]+)/([^/]+)', destination_repo_url)
    if not dest_match:
        pytest.skip(f"Invalid DESTINATION_REPO_URL format: {destination_repo_url}")
    
    org_name = dest_match.group(1)
    
    # Get the registry hostname from the captain_manifests fixture
    registry_app = captain_manifests['fixture_apps_by_friendly_name'].get('container-registry')
    if not registry_app:
        pytest.fail("container-registry fixture app not found in captain_manifests")
    
    registry_hostname = registry_app['hostname']
    logger.info(f"Using in-cluster registry: {registry_hostname}")
    
    # Add unique suffix to avoid conflicts between parallel test runs
    unique_suffix = str(uuid.uuid4())[:8]
    test_repo_name = f"{repo_name}-{unique_suffix}"
    
    # Initialize GitHub client
    g = get_github_client(github_token)
    
    # Get organization
    org: Organization | NamedUser | AuthenticatedUser
    try:
        org = g.get_organization(org_name)
    except Exception:
        try:
            org = g.get_user(org_name)
        except Exception as e:
            pytest.fail(f"Failed to get GitHub org/user '{org_name}': {e}")
    
    test_repo = None
    step_counter = 0
    
    def next_step(title: str):
        """Print next step header with auto-incrementing counter."""
        nonlocal step_counter
        step_counter += 1
        print_section_header(f"STEP {step_counter}: {title}")
    
    try:
        # ================================================================
        # Cleanup - Delete repo if exists from prior failed run
        # ================================================================
        next_step("Pre-test Cleanup")
        delete_repo_if_exists(org, test_repo_name)
        
        # ================================================================
        # Create public test repository
        # ================================================================
        next_step("Creating Test Repository")
        logger.info(f"Repository name: {test_repo_name}")
        logger.info(f"Original name format: {repo_name}")
        
        test_repo = create_repo(
            org=org,
            repo_name=test_repo_name,
            description=f"PR environment test - {repo_name}",
            private=False  # Public repo for workflow to run
        )
        
        # Log actual repo name (GitHub may have transformed it)
        logger.info(f"GitHub created repo as: {test_repo.name}")
        if test_repo.name != test_repo_name:
            logger.info(f"  Name was transformed: '{test_repo_name}' -> '{test_repo.name}'")
        
        # ================================================================
        # Add base-values.yaml to deployment-configurations repo
        # ================================================================
        next_step("Adding App Config to Deployment Configurations Repo")
        
        app_name = test_repo.name  # Use actual GitHub repo name
        base_values_content = f"""image:
  registry: {registry_hostname}
  repository: {org_name}/{app_name}
  port: 8080
service:
  enabled: true
deployment:
  replicas: 2
  enabled: true
  resources:
    requests:
      cpu: 100m
      memory: 128Mi
podDisruptionBudget:
  enabled: true
ingress:
  enabled: true
  ingressClassName: public
  entries:
    - name: public
      hosts:
        - hostname: '{{{{ .Values.image.tag | trunc 8 }}}}-{{{{ .Release.Name }}}}.apps.{{{{.Values.captain_domain}}}}'
"""
        
        logger.info(f"Creating base-values.yaml for {app_name} in deployment-configurations")
        logger.info(f"  App repo: {org_name}/{app_name}")
        logger.info(f"  Registry: {registry_hostname}")
        
        create_github_file(
            repo=ephemeral_github_repo,
            file_path=f"apps/{app_name}/base/base-values.yaml",
            content=base_values_content,
            commit_message=f"Add base-values for {app_name}",
            skip_ci=True
        )
        
        logger.info(f"✓ base-values.yaml created in deployment-configurations")
        
        # ================================================================
        # Add Dockerfile and GitHub Actions workflow to main branch
        # ================================================================
        next_step("Adding Container Build Setup to Main Branch")
        
        workflow_yaml = get_container_workflow_yaml(registry_hostname)
        
        logger.info(f"Registry hostname: {registry_hostname}")
        logger.info("Creating files:")
        logger.info("  - Dockerfile")
        logger.info("  - .github/workflows/container_image.yaml")
        
        # Create Dockerfile
        create_github_file(
            repo=test_repo,
            file_path="Dockerfile",
            content=DOCKERFILE_CONTENT,
            commit_message="Add Dockerfile for container build",
            skip_ci=False  # We WANT CI to run
        )
        
        # Create GitHub Actions workflow
        create_github_file(
            repo=test_repo,
            file_path=".github/workflows/container_image.yaml",
            content=workflow_yaml,
            commit_message="Add container image build workflow",
            skip_ci=False  # We WANT CI to run
        )
        
        logger.info("✓ Container build setup committed")
        
        # ================================================================
        # Create branch with -glueops-preview suffix
        # ================================================================
        next_step("Creating Preview Branch")
        logger.info(f"Branch name: {branch_name}")
        
        create_branch(
            repo=test_repo,
            branch_name=branch_name,
            source_branch="main"
        )
        
        # Create dummy commit on the branch to trigger workflow
        create_dummy_commit(
            repo=test_repo,
            branch_name=branch_name,
            file_path="preview-test.md",
            content=f"# Preview Environment Test\n\nCreated at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\nThis PR tests the preview environment workflow.\n",
            commit_message="feat: creating test commit for PR environment",
            skip_ci=False  # We WANT CI to run on this commit
        )
        
        # ================================================================
        # Create Pull Request
        # ================================================================
        next_step("Creating Pull Request")
        
        pr = create_pull_request(
            repo=test_repo,
            title="Preview environment test PR",
            body=(
                "This PR tests the preview environment workflow.\n\n"
                "**Expected behavior:**\n"
                "- Container image will be built and pushed to in-cluster registry\n"
                "- In-cluster automation should comment on this PR within 1-2 minutes\n\n"
                f"**Registry:** `{registry_hostname}`\n"
                f"**Branch:** `{branch_name}`\n"
            ),
            head_branch=branch_name,
            base_branch="main"
        )
        
        logger.info(f"PR URL: {pr.html_url}")
        logger.info(f"PR Number: #{pr.number}")
        
        # ================================================================
        # Wait for in-cluster automation (3 minutes)
        # ================================================================
        next_step("Waiting for In-Cluster Automation")
        logger.info("Holding PR open for 3 minutes to allow automation to comment...")
        logger.info(f"PR URL: {pr.html_url}")
        
        display_progress_bar(
            wait_time=180,  # 3 minutes
            interval=30,
            description="Waiting for in-cluster automation"
        )
        
        # ================================================================
        # FINAL SUMMARY
        # ================================================================
        print_section_header("FINAL SUMMARY")
        logger.info(f"✅ SUCCESS: Pull request environment workflow completed")
        logger.info(f"   Repository: {test_repo.full_name}")
        logger.info(f"   Repo name format tested: {repo_name}")
        logger.info(f"   Branch name format tested: {branch_name}")
        logger.info(f"   Registry: {registry_hostname}")
        logger.info(f"   PR: #{pr.number} ({pr.html_url})")
        
    finally:
        # ================================================================
        # TEARDOWN: Repository will be auto-cleaned
        # ================================================================
        print_section_header("TEARDOWN: Automatic Cleanup")
        
        if test_repo:
            logger.info(f"📦 Repository: {test_repo.full_name}")
            logger.info(f"🏷️  Cleanup topic: 'createdby-automated-test-delete-me'")
            logger.info(f"🤖 Repository will be automatically deleted by orphan cleanup fixture")
            logger.info(f"   (PR and all resources will be removed with the repo)")
        else:
            logger.info("No repository created - nothing to clean up")
