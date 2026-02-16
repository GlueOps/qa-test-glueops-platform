"""
Pull Request Environment Tests

Tests the complete PR lifecycle for preview environments including:
1. Creating a new repository with Dockerfile and GitHub Actions workflow
2. Pushing container images to the in-cluster registry
3. Creating PRs with the -glueops-preview branch suffix
4. Waiting for in-cluster automation to comment with deployment details
5. Validating all URLs from the bot comment (ArgoCD, Grafana, Loki, Preview)
6. Taking screenshots of each service
7. Cleanup and teardown

The test validates that the PR comment automation works correctly by:
- Creating a real repository with container build pipeline
- Opening a PR and waiting for in-cluster automation to interact with it
- Parsing the bot comment and validating commit SHA matches
- Loading each URL with authenticated browser sessions
- Capturing screenshots for test evidence
"""
import pytest
import os
import time
import uuid
import logging
import re
import requests
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
    wait_for_bot_comment,
)
from tests.helpers.browser import (
    get_browser_connection,
    create_authenticated_page,
    ScreenshotManager,
)
from tests.helpers.utils import display_progress_bar, print_section_header
from tests.helpers.constants import INGRESS_CLASS_NAMES

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
@pytest.mark.visual
@pytest.mark.parametrize("repo_name,branch_name", NAME_VARIATIONS, ids=[
    "kebab-case",
    "underscores",
    "spaces-to-dashes",
    "periods",
    "camelCase-numbers",
])
@pytest.mark.parametrize("ingress_class_name", INGRESS_CLASS_NAMES)
@pytest.mark.flaky(reruns=0, reruns_delay=300)
def test_pull_request_environment(
    ingress_class_name: str,
    repo_name: str,
    branch_name: str,
    captain_manifests: dict,
    ephemeral_github_repo,
    captain_domain: str,
    github_credentials: dict,
    request,
) -> None:
    """
    Test pull request environment workflow with container build pipeline.
    
    Creates a public repository with a Dockerfile and GitHub Actions workflow,
    simulates the full PR lifecycle:
    1. Creates repo with Dockerfile and workflow (pushes to in-cluster registry)
    2. Creates branch with -glueops-preview suffix (required for ApplicationSet)
    3. Creates PR with a dummy commit to trigger the container build
    4. Waits for automation bot to comment with deployment details (5 min timeout)
    5. Validates commit SHA in comment matches PR head
    6. Screenshots all URLs: GitHub PR, ArgoCD, Deployment Preview, Grafana, Loki
    7. Cleans up - repository auto-deleted by cleanup fixture
    
    Validates:
    - Repository creation with container build setup
    - Branch naming with ApplicationSet-compatible suffix
    - PR creation triggers container build asynchronously
    - Bot comment appears with correct deployment URLs
    - All deployment URLs are accessible and functional
    
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
    registry_app = captain_manifests['fixture_apps_by_friendly_name'].get(f'container-registry:{ingress_class_name}')
    if not registry_app:
        pytest.fail(f"container-registry:{ingress_class_name} fixture app not found in captain_manifests")
    
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
  registry: {registry_hostname.lower()}
  repository: {org_name.lower()}/{app_name.lower()}
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
  ingressClassName: {ingress_class_name}
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
        # Wait for bot comment (5 minute timeout)
        # ================================================================
        next_step("Waiting for Bot Comment")
        logger.info("Polling for automation bot comment (5 minute timeout)...")
        logger.info(f"PR URL: {pr.html_url}")
        
        comment_data = wait_for_bot_comment(pr, timeout=300, poll_interval=15)
        
        # ================================================================
        # Validate commit SHA matches
        # ================================================================
        next_step("Validating Comment Data")
        
        pr.update()  # Refresh PR to get latest head SHA
        expected_sha = pr.head.sha
        comment_sha = comment_data['latest_commit']
        
        if comment_sha != expected_sha:
            pytest.fail(
                f"Commit SHA mismatch!\n"
                f"  Expected (PR head): {expected_sha}\n"
                f"  Got (from comment): {comment_sha}"
            )
        logger.info(f"✓ Commit SHA matches: {expected_sha[:8]}")
        
        # Validate all URLs were parsed
        required_urls = ['argocd_url', 'deployment_preview_url', 'grafana_metrics_url', 'loki_logs_url']
        missing = [k for k in required_urls if not comment_data.get(k)]
        if missing:
            pytest.fail(f"Missing URLs in comment: {missing}\n\nRaw comment:\n{comment_data['raw_body']}")
        logger.info("✓ All required URLs parsed from comment")
        
        # ================================================================
        # Validate QR Code URL
        # ================================================================
        next_step("Validating QR Code")
        
        qr_code_url = comment_data.get('qr_code_url')
        preview_url = comment_data['deployment_preview_url']
        
        if qr_code_url:
            logger.info(f"🔍 Validating QR code encodes correct URL...")
            logger.info(f"   QR Code URL: {qr_code_url}")
            logger.info(f"   Expected encoded URL: {preview_url}")
            
            # Download the QR code image
            qr_response = requests.get(qr_code_url, timeout=30)
            if qr_response.status_code != 200:
                pytest.fail(f"Failed to download QR code: HTTP {qr_response.status_code}")
            
            # Decode the QR code
            try:
                from PIL import Image
                from pyzbar.pyzbar import decode
                import io
                
                img = Image.open(io.BytesIO(qr_response.content))
                decoded_objects = decode(img)
                
                if not decoded_objects:
                    pytest.fail("Could not decode QR code - no data found")
                
                qr_data = decoded_objects[0].data.decode('utf-8')
                logger.info(f"   QR code decoded: {qr_data}")
                
                # Validate QR code contains the deployment preview URL
                if qr_data.rstrip('/') != preview_url.rstrip('/'):
                    pytest.fail(
                        f"QR code URL mismatch!\n"
                        f"  Expected: {preview_url}\n"
                        f"  Got: {qr_data}"
                    )
                logger.info(f"   ✓ QR code correctly encodes deployment preview URL")
                
            except ImportError:
                logger.warning("   ⚠ pyzbar/PIL not installed - skipping QR decode validation")
                # Fallback: check that the QR URL contains the preview URL as a parameter
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(qr_code_url)
                query_params = parse_qs(parsed.query)
                qr_target_url = query_params.get('url', [''])[0]
                
                if qr_target_url.rstrip('/') != preview_url.rstrip('/'):
                    pytest.fail(
                        f"QR code URL parameter mismatch!\n"
                        f"  Expected: {preview_url}\n"
                        f"  Got: {qr_target_url}"
                    )
                logger.info(f"   ✓ QR code URL parameter matches deployment preview URL")
        else:
            logger.warning("   ⚠ No QR code URL found in comment")
        
        # ================================================================
        # Setup browser and screenshot manager
        # ================================================================
        next_step("Capturing Screenshots")
        
        playwright, browser, session = get_browser_connection()
        screenshot_manager = ScreenshotManager(
            test_name=f"pr_env_{repo_name.replace(' ', '_').lower()}",
            request=request
        )
        
        # Enable baseline update mode if flag set
        update_baseline = request.config.getoption("--update-baseline")
        if update_baseline and (update_baseline == "all" or update_baseline in request.node.name):
            screenshot_manager.update_baseline_mode = True
            logger.info(f"📝 Baseline update mode enabled for {request.node.name}")
        
        # Track contexts for cleanup
        contexts_to_close = []
        
        try:
            # ================================================================
            # Screenshot GitHub PR with bot comment
            # ================================================================
            logger.info("📸 1/5: Capturing GitHub PR page with bot comment...")
            github_page, github_ctx = create_authenticated_page(
                browser, 'github', github_credentials
            )
            contexts_to_close.append(github_ctx)
            
            github_page.goto(pr.html_url, wait_until="load", timeout=30000)
            github_page.wait_for_timeout(3000)
            screenshot_manager.capture(
                github_page, pr.html_url,
                description="GitHub PR with bot comment",
                baseline_key="pr_github_bot_comment",
                threshold=1.0
            )
            logger.info(f"   ✓ GitHub PR screenshot captured")
            
            # ================================================================
            # Screenshot ArgoCD application
            # ================================================================
            logger.info(f"📸 2/5: Capturing ArgoCD: {comment_data['argocd_url']}")
            argocd_page, argocd_ctx = create_authenticated_page(
                browser, 'argocd', github_credentials, captain_domain
            )
            contexts_to_close.append(argocd_ctx)
            
            argocd_page.goto(comment_data['argocd_url'], wait_until="load", timeout=30000)
            argocd_page.wait_for_timeout(5000)  # ArgoCD can be slow to render
            screenshot_manager.capture(
                argocd_page, comment_data['argocd_url'],
                description="ArgoCD Application",
                baseline_key="pr_argocd_application",
                threshold=1.0
            )
            logger.info(f"   ✓ ArgoCD screenshot captured")
            
            # ================================================================
            # Validate and screenshot deployment preview
            # ================================================================
            logger.info(f"📸 3/5: Validating deployment preview: {preview_url}")
            
            response = requests.get(preview_url, timeout=30, verify=True)
            
            if response.status_code != 200:
                pytest.fail(f"Deployment preview returned HTTP {response.status_code}")
            
            # Parse JSON and validate host header matches the URL hostname
            json_data = response.json()
            host_header = json_data.get('headers', {}).get('host', '')
            expected_host = preview_url.replace('http://', '').replace('https://', '').rstrip('/')
            
            if host_header != expected_host:
                pytest.fail(
                    f"Host header mismatch!\n"
                    f"  Expected: {expected_host}\n"
                    f"  Got: {host_header}"
                )
            logger.info(f"   ✓ Deployment preview responding correctly (host: {host_header})")
            
            # Use existing github page for unauthenticated preview screenshot
            github_page.goto(preview_url, wait_until="load", timeout=30000)
            github_page.wait_for_timeout(2000)
            screenshot_manager.capture(
                github_page, preview_url,
                description="Deployment Preview (HTTP Debug)",
                baseline_key="pr_deployment_preview",
                threshold=1.0
            )
            logger.info(f"   ✓ Deployment preview screenshot captured")
            
            # ================================================================
            # Screenshot Loki logs first (before metrics wait)
            # ================================================================
            logger.info(f"📸 4/5: Capturing Loki logs: {comment_data['loki_logs_url']}")
            grafana_page, grafana_ctx = create_authenticated_page(
                browser, 'grafana', github_credentials, captain_domain
            )
            contexts_to_close.append(grafana_ctx)
            
            grafana_page.goto(comment_data['loki_logs_url'], wait_until="load", timeout=30000)
            grafana_page.wait_for_timeout(5000)
            screenshot_manager.capture(
                grafana_page, comment_data['loki_logs_url'],
                description="Loki Logs Dashboard",
                baseline_key="pr_loki_logs_dashboard",
                threshold=1.0
            )
            logger.info(f"   ✓ Loki logs screenshot captured")
            
            # ================================================================
            # Wait for metrics to populate, then screenshot Grafana
            # ================================================================
            logger.info(f"📸 5/5: Waiting for metrics to populate...")
            display_progress_bar(
                wait_time=120,  # 2 minutes
                interval=15,
                description="Waiting for Grafana metrics to populate"
            )
            
            logger.info(f"   Capturing Grafana metrics: {comment_data['grafana_metrics_url']}")
            grafana_page.goto(comment_data['grafana_metrics_url'], wait_until="load", timeout=30000)
            grafana_page.wait_for_timeout(5000)  # Grafana needs time to load panels
            screenshot_manager.capture(
                grafana_page, comment_data['grafana_metrics_url'],
                description="Grafana Metrics Dashboard",
                baseline_key="pr_grafana_metrics_dashboard",
                threshold=2.0
            )
            logger.info(f"   ✓ Grafana metrics screenshot captured")
            
            # Assert no visual regressions
            failures = screenshot_manager.get_visual_failures()
            if failures:
                failure_msgs = [f"{f.baseline_key}: {f.diff_percent:.4f}%" for f in failures]
                pytest.fail(f"Visual regression detected: {', '.join(failure_msgs)}")
            
            # Log screenshot summary
            screenshot_manager.log_summary()
            
        finally:
            # Close all browser contexts
            for ctx in contexts_to_close:
                try:
                    ctx.close()
                except Exception:
                    pass
            
            # Cleanup browser connection
            try:
                playwright.stop()
            except Exception:
                pass
        
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
        logger.info(f"   Bot: {comment_data['bot_name']}")
        logger.info(f"   Screenshots captured: {screenshot_manager.get_screenshot_count()}")
        
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
