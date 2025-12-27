"""
Preview Environment PR Workflow Tests

Tests the complete PR lifecycle for preview environments by:
1. Creating a new repository with various name formats
2. Creating branches with various name formats
3. Creating, closing, and merging pull requests
4. Validating PR creation via browser screenshot

Tests valid GitHub name transformations (e.g., spaces become dashes).
"""
import pytest
import os
import time
import uuid
import logging
from pathlib import Path

from tests.helpers.github import (
    get_github_client,
    create_repo,
    delete_repo,
    delete_repo_if_exists,
    create_branch,
    create_dummy_commit,
    create_pull_request,
    close_pull_request,
    merge_pull_request,
)
from tests.helpers.utils import display_progress_bar, print_section_header
from tests.helpers.browser import ScreenshotManager

logger = logging.getLogger(__name__)


# ============================================================================
# EASILY EDITABLE: Valid GitHub name formats to test
# Each tuple is (repo_name, branch_name) - 5 tests total, each name tested once
# These are all VALID formats that GitHub accepts (no API errors expected)
# NOTE: Avoid reserved prefixes like 'dependabot/' which are restricted by GitHub
# ============================================================================
NAME_VARIATIONS = [
    # (repo_name, branch_name) - Test different valid GitHub name formats
    ("preview-env-test", "feature/preview-test"),      # kebab-case + slash hierarchy
    ("preview_env_test", "preview_branch"),            # underscores
    ("Preview Env Test", "feature-v1.0.0"),            # spaces→dashes + periods in version
    ("preview.env.test", "updates/npm/lodash"),        # periods + deep slash path (not dependabot/)
    ("PreviewEnvTest123", "hotfix-123"),               # camelCase with numbers
]
# ============================================================================


@pytest.mark.gitops
@pytest.mark.preview_environments
@pytest.mark.ui
@pytest.mark.parametrize("repo_name,branch_name", NAME_VARIATIONS, ids=[
    "kebab-case",
    "underscores", 
    "spaces-to-dashes",
    "periods",
    "camelCase-numbers",
])
@pytest.mark.skip(reason="Temporarily disabled - reason here")
def test_preview_environment_pr_workflow(
    repo_name,
    branch_name,
    page,
    request,
):
    """
    Test preview environment workflow via PR lifecycle with name variations.
    
    Creates a public repository, simulates the full PR lifecycle:
    1. Creates repo with parametrized name (tests GitHub name transformations)
    2. Creates branch with parametrized name
    3. Creates first PR with dummy commit
    4. Navigates to PR in browser and takes screenshot
    5. Waits 30 seconds and closes the PR
    6. Creates second branch with another dummy commit
    7. Creates second PR
    8. Merges the PR
    9. Cleans up by deleting the test repository
    
    Validates:
    - Repository creation with various valid name formats
    - Branch creation with various valid name formats  
    - PR creation, closing, and merging
    - PR visibility in GitHub WebUI (screenshot)
    
    Cluster Impact: WRITE (creates GitHub resources)
    """
    # Get GitHub credentials from environment
    github_token = os.environ.get("GITHUB_TOKEN")
    if not github_token:
        pytest.skip("GITHUB_TOKEN environment variable not set")
    
    # Get the organization from DESTINATION_REPO_URL
    destination_repo_url = os.environ.get("DESTINATION_REPO_URL")
    if not destination_repo_url:
        pytest.skip("DESTINATION_REPO_URL environment variable not set")
    
    import re
    dest_match = re.match(r'https://github\.com/([^/]+)/([^/]+)', destination_repo_url)
    if not dest_match:
        pytest.skip(f"Invalid DESTINATION_REPO_URL format: {destination_repo_url}")
    
    org_name = dest_match.group(1)
    
    # Add unique suffix to avoid conflicts between parallel test runs
    unique_suffix = str(uuid.uuid4())[:8]
    test_repo_name = f"{repo_name}-{unique_suffix}"
    
    # Initialize GitHub client
    g = get_github_client(github_token)
    
    # Get organization
    try:
        org = g.get_organization(org_name)
    except Exception:
        try:
            org = g.get_user(org_name)
        except Exception as e:
            pytest.fail(f"Failed to get GitHub org/user '{org_name}': {e}")
    
    test_repo = None
    screenshot_manager = None
    step_counter = 0
    
    def next_step(title):
        """Print next step header with auto-incrementing counter."""
        nonlocal step_counter
        step_counter += 1
        print_section_header(f"STEP {step_counter}: {title}")
    
    # Helper function to capture screenshots (DRY)
    def capture_screenshot(url, description):
        """Capture a screenshot and attach to Allure report."""
        nonlocal screenshot_manager
        if screenshot_manager is None:
            screenshot_manager = ScreenshotManager(
                test_name=f"preview_pr_{repo_name.replace(' ', '_')}",
                request=request
            )
        
        logger.info(f"Taking screenshot: {description}")
        page.goto(url, wait_until="load", timeout=30000)
        page.wait_for_timeout(3000)
        
        screenshot_manager.capture(
            page=page,
            url=url,
            description=description,
            full_page=True
        )
    
    try:
        # ================================================================
        # Cleanup - Delete repo if exists from prior failed run
        # ================================================================
        next_step("Pre-test Cleanup")
        delete_repo_if_exists(org, test_repo_name, verbose=True)
        
        # ================================================================
        # Create public test repository
        # ================================================================
        next_step("Creating Test Repository")
        logger.info(f"Repository name: {test_repo_name}")
        logger.info(f"Original name format: {repo_name}")
        
        test_repo = create_repo(
            org=org,
            repo_name=test_repo_name,
            description=f"Preview environment test - {repo_name}",
            private=False,  # Public repo for screenshot without auth
            verbose=True
        )
        
        # Log actual repo name (GitHub may have transformed it)
        logger.info(f"GitHub created repo as: {test_repo.name}")
        if test_repo.name != test_repo_name:
            logger.info(f"  Name was transformed: '{test_repo_name}' -> '{test_repo.name}'")
        
        # Take screenshot of newly created repo
        capture_screenshot(test_repo.html_url, f"Repository Created - {test_repo.name}")
        
        # ================================================================
        # Create first branch with dummy commit
        # ================================================================
        next_step("Creating First Branch")
        first_branch = f"{branch_name}-first"
        logger.info(f"Branch name: {first_branch}")
        
        create_branch(
            repo=test_repo,
            branch_name=first_branch,
            source_branch="main",
            verbose=True
        )
        
        # Create dummy commit on the branch
        create_dummy_commit(
            repo=test_repo,
            branch_name=first_branch,
            file_path="preview-test-1.md",
            content=f"# Preview Environment Test\n\nCreated at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
            commit_message="creating PR for preview environments",
            verbose=True
        )
        
        # ================================================================
        # Create first PR
        # ================================================================
        next_step("Creating First Pull Request")
        
        first_pr = create_pull_request(
            repo=test_repo,
            title="creating PR for preview environments",
            body="This PR tests the preview environment workflow.\n\nThis is the first PR that will be closed after 30 seconds.",
            head_branch=first_branch,
            base_branch="main",
            verbose=True
        )
        
        logger.info(f"PR URL: {first_pr.html_url}")
        
        # ================================================================
        # Take screenshot of PR in browser
        # ================================================================
        next_step("Taking Screenshot of First PR")
        capture_screenshot(first_pr.html_url, f"First PR - {test_repo.name}")
        
        # Verify we're on the PR page
        assert "/pull/" in page.url, f"Not on PR page. URL: {page.url}"
        
        if screenshot_manager:
            screenshot_manager.log_summary()
        
        # ================================================================
        # Wait and close first PR
        # ================================================================
        next_step("Waiting Before Closing PR")
        display_progress_bar(wait_time=5, interval=5, description="Waiting before closing PR")
        
        logger.info("Closing first PR...")
        close_pull_request(first_pr, verbose=True)
        
        # ================================================================
        # Create second branch with another dummy commit
        # ================================================================
        next_step("Creating Second Branch")
        second_branch = f"{branch_name}-second"
        logger.info(f"Branch name: {second_branch}")
        
        create_branch(
            repo=test_repo,
            branch_name=second_branch,
            source_branch="main",
            verbose=True
        )
        
        create_dummy_commit(
            repo=test_repo,
            branch_name=second_branch,
            file_path="preview-test-2.md",
            content=f"# Preview Environment Test - Second PR\n\nCreated at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
            commit_message="Second commit for preview environment test",
            verbose=True
        )
        
        # ================================================================
        # Create second PR
        # ================================================================
        next_step("Creating Second Pull Request")
        
        second_pr = create_pull_request(
            repo=test_repo,
            title="Second PR for preview environment test",
            body="This is the second PR that will be merged.",
            head_branch=second_branch,
            base_branch="main",
            verbose=True
        )
        
        logger.info(f"Second PR URL: {second_pr.html_url}")
        
        # Take screenshot of second PR
        capture_screenshot(second_pr.html_url, f"Second PR - {test_repo.name}")
        
        if screenshot_manager:
            screenshot_manager.log_summary()
        
        # ================================================================
        # Merge second PR
        # ================================================================
        next_step("Merging Second Pull Request")
        
        merge_pull_request(
            pr=second_pr,
            merge_method="merge",
            verbose=True
        )
        
        # ================================================================
        # FINAL SUMMARY
        # ================================================================
        print_section_header("FINAL SUMMARY")
        logger.info(f"✅ SUCCESS: Preview environment PR workflow completed")
        logger.info(f"   Repository: {test_repo.full_name}")
        logger.info(f"   Repo name format tested: {repo_name}")
        logger.info(f"   Branch name format tested: {branch_name}")
        logger.info(f"   First PR: #{first_pr.number} (closed)")
        logger.info(f"   Second PR: #{second_pr.number} (merged)")
        
    finally:
        # ================================================================
        # WAIT: Hold resources for inspection before cleanup
        # ================================================================
        if test_repo:
            print_section_header("INSPECTION: Waiting 10 Minutes Before Cleanup")
            logger.info(f"Repository URL: {test_repo.html_url}")
            logger.info(f"Waiting 10 minutes to allow manual inspection...")
            display_progress_bar(wait_time=10, interval=30, description="Holding repository for inspection")
        
        # ================================================================
        # CLEANUP: Delete test repository
        # ================================================================
        print_section_header("CLEANUP: Deleting Test Repository")
        if test_repo:
            try:
                delete_repo(test_repo, verbose=True)
            except Exception as e:
                logger.warning(f"⚠️  Failed to delete test repository: {e}")
        else:
            logger.info("No repository to clean up")
