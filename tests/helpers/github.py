"""
GitHub helper functions for GitOps testing.

This module provides utilities for interacting with GitHub repositories
during test automation, including repo creation, file manipulation, and PR management.
"""
import logging
import time
from typing import Optional
from github import GithubException, Github
from github.GithubException import UnknownObjectException

logger = logging.getLogger(__name__)

# Polling configuration constants (10 minutes timeout, 15 second intervals)
DEFAULT_POLL_INTERVAL = 15
DEFAULT_TIMEOUT = 600


def clone_repo_contents(source_repo, dest_repo, ref, skip_ci=True):
    """
    Clone all contents from source repository to destination repository.
    
    This is a generic utility that copies the entire file structure from one
    GitHub repository to another. Useful for creating test repositories from
    template repositories without using GitHub's template API.
    
    Args:
        source_repo: GitHub Repository object (source)
        dest_repo: GitHub Repository object (destination, should be empty or just initialized)
        ref: Git reference to copy from (branch name, tag, or commit SHA - e.g., 'main', 'v1.0.0', 'abc123')
        skip_ci: Whether to add [skip ci] to commit messages (default: True)
        
    Returns:
        int: Number of files copied
        
    Example:
        # Clone from a specific tag with CI skipped
        count = clone_repo_contents(template_repo, new_repo, ref='v1.0.0')
        
        # Clone without skipping CI
        count = clone_repo_contents(template_repo, new_repo, ref='main', skip_ci=False)
    """
    copied_count = 0
    ci_suffix = " [skip ci]" if skip_ci else ""
    
    def copy_contents_recursive(path=""):
        """Recursively copy all files and directories."""
        nonlocal copied_count
        
        try:
            contents = source_repo.get_contents(path, ref=ref)
            
            if not isinstance(contents, list):
                contents = [contents]
            
            for item in contents:
                if item.type == "dir":
                    logger.info(f"  📁 {item.path}/")
                    # Recurse into directory
                    copy_contents_recursive(item.path)
                else:
                    # Copy file
                    logger.info(f"  📄 {item.path}")
                    
                    try:
                        # Get file content from source
                        file_content = item.decoded_content
                        
                        # Create file in destination (always on default branch)
                        dest_repo.create_file(
                            path=item.path,
                            message=f"Clone: {item.path}{ci_suffix}",
                            content=file_content
                        )
                        copied_count += 1
                        
                    except GithubException as e:
                        if e.status == 422:
                            # File already exists - update it instead
                            logger.info(f"    ⚠ Updating existing {item.path}")
                            existing_file = dest_repo.get_contents(item.path)
                            dest_repo.update_file(
                                path=item.path,
                                message=f"Clone: Update {item.path}{ci_suffix}",
                                content=file_content,
                                sha=existing_file.sha
                            )
                            copied_count += 1
                        else:
                            raise
                            
        except GithubException as e:
            if e.status == 404:
                pass  # Path doesn't exist, skip
            else:
                raise
    
    logger.info(f"Cloning contents from {source_repo.full_name} (ref: {ref}) to {dest_repo.full_name}...")
    if skip_ci:
        logger.info("  CI/CD workflows will be skipped for all commits")
    
    copy_contents_recursive()
    
    logger.info(f"✓ Cloned {copied_count} file(s)")
    
    return copied_count


def get_github_client(token: str) -> Github:
    """
    Create and return a GitHub client.
    
    Args:
        token: GitHub personal access token
        
    Returns:
        Github: Authenticated GitHub client
    """
    from github import Auth
    auth = Auth.Token(token)
    return Github(auth=auth)


def get_repo_latest_sha(repo, branch: str = "main") -> Optional[str]:
    """
    Get the latest commit SHA from a repository branch.
    
    Args:
        repo: GitHub Repository object
        branch: Branch name to get the latest commit from (default: main)
        
    Returns:
        str: The latest commit SHA, or None if error
        
    Example:
        sha = get_repo_latest_sha(captain_repo)
        # Use this SHA for ArgoCD sync validation
    """
    try:
        branch_ref = repo.get_branch(branch)
        sha = branch_ref.commit.sha
        logger.info(f"✓ Latest commit on {repo.full_name}/{branch}: {sha[:8]}")
        return sha
    except GithubException as e:
        logger.error(f"❌ Failed to get latest SHA from {repo.full_name}/{branch}: {e}")
        return None


def create_repo(org, repo_name: str, description: str = "Test repository", private: bool = False):
    """
    Create a new GitHub repository in an organization with automatic cleanup topic.
    
    This function automatically sets the 'createdby-automated-test-delete-me' topic
    on ALL created repositories to ensure they are cleaned up by orphan cleanup fixtures.
    
    Args:
        org: GitHub Organization object
        repo_name: Name for the new repository
        description: Repository description
        private: Whether the repo should be private (default: False)
        
    Returns:
        github.Repository.Repository: The created repository with cleanup topic set
        
    Note:
        ALL repositories created with this function will be tagged for automatic cleanup.
        The 'createdby-automated-test-delete-me' topic is MANDATORY and hardcoded.
    """
    logger.info(f"Creating repository: {repo_name} (private={private})")
    
    new_repo = org.create_repo(
        name=repo_name,
        description=description,
        private=private,
        auto_init=True
    )
    
    time.sleep(2)
    
    logger.info(f"✓ Repository created: {new_repo.html_url}")
    
    # MANDATORY: Set cleanup topic on ALL repos created by tests
    logger.info("🏷️  Setting mandatory cleanup topic...")
    try:
        # Get GitHub client from the org object
        from github import Github, Auth
        # The org object has a _requester which has the auth token
        g = Github(auth=Auth.Token(org._requester.auth.token if hasattr(org._requester.auth, 'token') else org._requester._Requester__authorizationHeader.split()[-1]))
        set_repo_topics(g, new_repo, ['createdby-automated-test-delete-me'])
        logger.info("✓ Cleanup topic set successfully")
    except Exception as e:
        logger.warning(f"⚠️  Failed to set cleanup topic (repo will need manual cleanup): {e}")
        # Don't fail the test - just warn
    
    return new_repo


def delete_repo(repo):
    """
    Delete a GitHub repository.
    
    Args:
        repo: GitHub Repository object to delete
    """
    repo_name = repo.full_name
    logger.info(f"Deleting repository: {repo_name}")
    
    repo.delete()
    
    logger.info(f"✓ Repository deleted: {repo_name}")


def delete_repo_if_exists(org, repo_name: str) -> bool:
    """
    Delete a repository if it exists (for cleanup before/after tests).
    
    Args:
        org: GitHub Organization object
        repo_name: Name of the repository to delete
        
    Returns:
        bool: True if repo was deleted, False if it didn't exist
    """
    try:
        existing_repo = org.get_repo(repo_name)
        logger.info(f"Found existing repository: {repo_name} - deleting...")
        existing_repo.delete()
        time.sleep(2)
        logger.info(f"✓ Repository deleted: {repo_name}")
        return True
    except UnknownObjectException:
        logger.info(f"Repository {repo_name} does not exist (nothing to delete)")
        return False
    except GithubException as e:
        if e.status == 404:
            logger.info(f"Repository {repo_name} does not exist (nothing to delete)")
            return False
        raise


def delete_repos_by_topic(org, topic: str) -> int:
    """
    Delete all repositories in an organization that have a specific topic.
    
    This is used for cleanup of automated test repositories. Each deletion
    is validated to ensure the repository was successfully removed.
    
    Args:
        org: GitHub Organization or User object
        topic: Topic to search for (e.g., 'createdby-automated-test-delete-me')
        
    Returns:
        int: Number of repositories deleted
    """
    deleted_count = 0
    
    logger.info(f"Searching for repositories with topic '{topic}'...")
    
    try:
        repos = org.get_repos()
        
        for repo in repos:
            if topic in repo.get_topics():
                repo_name = repo.name
                repo_full_name = repo.full_name
                
                logger.info(f"  Found test repo: {repo_name} - deleting...")
                
                try:
                    repo.delete()
                    time.sleep(1)
                    
                    # Validate deletion
                    try:
                        org.get_repo(repo_name)
                        # If we get here, repo still exists - deletion failed
                        raise RuntimeError(f"Deletion validation failed: {repo_name} still exists after delete() call")
                    except (UnknownObjectException, GithubException) as e:
                        if hasattr(e, 'status') and e.status == 404:
                            # 404 means repo is gone - success!
                            deleted_count += 1
                            logger.info(f"  ✓ Confirmed deleted: {repo_name}")
                        elif isinstance(e, UnknownObjectException):
                            # UnknownObjectException also means it's gone
                            deleted_count += 1
                            logger.info(f"  ✓ Confirmed deleted: {repo_name}")
                        else:
                            # Some other error during validation
                            raise RuntimeError(f"Could not validate deletion of {repo_name}: {e}")
                            
                except GithubException as e:
                    raise RuntimeError(f"Failed to delete {repo_name}: {e.status} - {e.data.get('message', str(e))}")
        
        if deleted_count > 0:
            logger.info(f"✓ Deleted {deleted_count} test repository/repositories")
        else:
            logger.info(f"✓ No test repositories found with topic '{topic}'")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error searching for repos by topic: {e}")
        return deleted_count


def set_repo_topics(github_client, repo, topics: list):
    """
    Set topics on a GitHub repository and verify they are set.
    
    Args:
        github_client: GitHub client object (used to fetch fresh repo)
        repo: GitHub Repository object
        topics: List of topic strings to set
        
    Raises:
        RuntimeError: If topics cannot be verified after setting or search index timeout
    """
    logger.info(f"Setting topics on {repo.full_name}: {', '.join(topics)}")
    
    repo.replace_topics(topics)
    time.sleep(2)
    
    # Verify topics were set
    actual_topics = repo.get_topics()
    if set(topics) != set(actual_topics):
        raise RuntimeError(
            f"Topic verification failed! Expected: {sorted(topics)}, Got: {sorted(actual_topics)}"
        )
    
    logger.info(f"✓ Topics verified: {', '.join(actual_topics)}")
    
    # CRITICAL: Poll GitHub's search index to verify topics are searchable
    # Without this verification, orphan cleanup from other tests may not find this repo's topics
    # and could incorrectly skip deleting it, or conversely, delete it prematurely
    logger.info(f"⏱️  Polling for GitHub topic search index to update (timeout: {DEFAULT_TIMEOUT}s)...")
    logger.info(f"   Repository: {repo.full_name}")
    
    start_time = time.time()
    poll_count = 0
    
    while time.time() - start_time < DEFAULT_TIMEOUT:
        poll_count += 1
        
        try:
            # Fetch repo completely fresh using the GitHub client to verify topics are searchable
            fresh_repo = github_client.get_repo(repo.full_name)
            fresh_topics = fresh_repo.get_topics()
            
            if set(topics) == set(fresh_topics):
                elapsed = time.time() - start_time
                logger.info(f"✓ Topics searchable in GitHub index after {elapsed:.1f}s ({poll_count} poll(s))")
                return
            else:
                logger.info(f"Poll {poll_count}: Topics not yet in search index. Expected: {sorted(topics)}, Got: {sorted(fresh_topics)}")
        except Exception as e:
            logger.info(f"Poll {poll_count}: Error checking topics: {e}")
        
        time.sleep(DEFAULT_POLL_INTERVAL)
    
    # Timeout reached
    elapsed = time.time() - start_time
    raise RuntimeError(
        f"Topic search index verification timeout after {elapsed:.1f}s ({poll_count} poll(s)). "
        f"Topics may not be searchable for orphan cleanup. Expected: {sorted(topics)}"
    )


def create_branch(repo, branch_name: str, source_branch: str = "main"):
    """
    Create a new branch from a source branch.
    
    Args:
        repo: GitHub Repository object
        branch_name: Name of the new branch
        source_branch: Source branch to create from (default: main)
        
    Returns:
        github.GitRef.GitRef: The created branch reference
    """
    logger.info(f"Creating branch: {branch_name} from {source_branch}")
    
    source_ref = repo.get_branch(source_branch)
    source_sha = source_ref.commit.sha
    
    new_ref = repo.create_git_ref(
        ref=f"refs/heads/{branch_name}",
        sha=source_sha
    )
    
    logger.info(f"✓ Branch created: {branch_name}")
    
    return new_ref


def create_dummy_commit(repo, branch_name: str, file_path: str, content: str, commit_message: str, skip_ci=True):
    """
    Create a file with a commit on a specific branch.
    
    Args:
        repo: GitHub Repository object
        branch_name: Branch to commit to
        file_path: Path for the new file
        content: File content
        commit_message: Commit message
        skip_ci: Whether to add [skip ci] to commit message (default: True)
        
    Returns:
        dict: Result from create_file with commit info
    """
    ci_suffix = " [skip ci]" if skip_ci else ""
    logger.info(f"Creating commit on branch {branch_name}: {commit_message}")
    
    result = repo.create_file(
        path=file_path,
        message=f"{commit_message}{ci_suffix}",
        content=content,
        branch=branch_name
    )
    
    commit_sha = result['commit'].sha
    logger.info(f"✓ Commit created")
    logger.info(f"  Full SHA: {commit_sha}")
    logger.info(f"  Short SHA: {commit_sha[:8]}")
    
    return result


def create_pull_request(repo, title: str, body: str, head_branch: str, base_branch: str = "main"):
    """
    Create a pull request.
    
    Args:
        repo: GitHub Repository object
        title: PR title
        body: PR description/body
        head_branch: Branch with changes (source)
        base_branch: Branch to merge into (target, default: main)
        
    Returns:
        github.PullRequest.PullRequest: The created PR
        
    Raises:
        GithubException: If PR creation fails
    """
    logger.info(f"Creating PR: {title} ({head_branch} -> {base_branch})")
    
    try:
        pr = repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch
        )
        
        logger.info(f"✓ PR created: #{pr.number} - {pr.html_url}")
        
        return pr
        
    except GithubException as e:
        logger.error(f"❌ Failed to create PR: {title}")
        logger.error(f"   Repository: {repo.full_name}")
        logger.error(f"   Head branch: {head_branch}")
        logger.error(f"   Base branch: {base_branch}")
        logger.error(f"   Error code: {e.status}")
        logger.error(f"   Error message: {e.data.get('message', str(e))}")
        
        if e.status == 403:
            logger.error(f"   💡 Troubleshooting hints:")
            logger.error(f"      - Check GitHub token has 'repo' scope")
            logger.error(f"      - If org uses SSO, authorize the token")
        
        raise


def close_pull_request(pr):
    """
    Close a pull request without merging.
    
    Args:
        pr: GitHub PullRequest object
    """
    logger.info(f"Closing PR: #{pr.number}")
    
    pr.edit(state="closed")
    
    logger.info(f"✓ PR closed: #{pr.number}")


def merge_pull_request(pr, merge_method: str = "merge", commit_message: Optional[str] = None):
    """
    Merge a pull request.
    
    Args:
        pr: GitHub PullRequest object
        merge_method: Merge method - 'merge', 'squash', or 'rebase'
        commit_message: Optional custom commit message
        
    Returns:
        github.PullRequestMergeStatus.PullRequestMergeStatus: Merge result
    """
    logger.info(f"Merging PR: #{pr.number} (method: {merge_method})")
    
    merge_kwargs = {"merge_method": merge_method}
    if commit_message is not None:
        merge_kwargs["commit_message"] = commit_message
    
    result = pr.merge(**merge_kwargs)
    
    logger.info(f"✓ PR merged: #{pr.number}")
    
    return result


def create_github_file(repo, file_path, content, commit_message, skip_ci=True):
    """
    Create a file in a GitHub repository with logging and retry logic for 404 errors.
    
    Args:
        repo: GitHub Repository object
        file_path: Path to the file
        content: File content as string
        commit_message: Git commit message
        skip_ci: Whether to add [skip ci] to commit message (default: True)
    
    Returns:
        GitHub ContentFile object
        
    Raises:
        GithubException: If creation fails after retries
    """
    ci_suffix = " [skip ci]" if skip_ci else ""
    logger.info(f"      File: {file_path}")
    logger.info(f"      Message: {commit_message}")
    logger.info(f"      Content:")
    logger.info("      " + "="*60)
    for line in content.split('\n'):
        logger.info(f"      {line}")
    logger.info("      " + "="*60)
    
    # Retry logic for 404 errors (GitHub propagation delays)
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            result = repo.create_file(
                path=file_path,
                message=f"{commit_message}{ci_suffix}",
                content=content
            )
            
            commit_sha = result['commit'].sha
            logger.info(f"      ✓ Committed to repository")
            logger.info(f"      Full SHA: {commit_sha}")
            logger.info(f"      Short SHA: {commit_sha[:8]}")
            
            return result
            
        except GithubException as e:
            if e.status == 404 and attempt < max_retries - 1:
                logger.info(f"      ⚠ Got 404, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(retry_delay)
                continue
            elif e.status == 422:
                # File exists, update instead
                logger.info(f"      File exists, updating instead...")
                existing_file = repo.get_contents(file_path)
                result = repo.update_file(
                    path=file_path,
                    message=f"{commit_message}{ci_suffix}",
                    content=content,
                    sha=existing_file.sha
                )
                
                commit_sha = result['commit'].sha
                logger.info(f"      ✓ File updated")
                logger.info(f"      Full SHA: {commit_sha}")
                logger.info(f"      Short SHA: {commit_sha[:8]}")
                
                return result
            else:
                # Re-raise if not a 404/422 or if we've exhausted retries
                raise


def delete_directory_contents(repo, path, max_retries=3, skip_ci=True):
    """
    Recursively delete all contents of a directory in a GitHub repository.
    
    Args:
        repo: GitHub Repository object
        path: Path to the directory to delete
        max_retries: Number of retries for 409 conflicts (default: 3)
        skip_ci: Whether to add [skip ci] to commit messages (default: True)
    """
    ci_suffix = " [skip ci]" if skip_ci else ""
    try:
        contents = repo.get_contents(path)
        
        if not isinstance(contents, list):
            contents = [contents]
        
        for item in contents:
            if item.type == "dir":
                logger.info(f"  Deleting directory: {item.path}")
                delete_directory_contents(repo, item.path, max_retries, skip_ci)
            else:
                logger.info(f"  Deleting file: {item.path}")
                
                # Retry logic for 409 conflicts (file SHA changed)
                for attempt in range(max_retries):
                    try:
                        # Refetch the file to get current SHA
                        current_file = repo.get_contents(item.path)
                        repo.delete_file(
                            path=item.path,
                            message=f"Clear directory: remove {item.path}{ci_suffix}",
                            sha=current_file.sha
                        )
                        break  # Success
                    except GithubException as e:
                        if e.status == 409 and attempt < max_retries - 1:
                            logger.info(f"    Retry {attempt + 1}/{max_retries - 1}: SHA conflict, refetching...")
                            time.sleep(1)
                            continue
                        else:
                            raise
    except GithubException as e:
        if e.status == 404:
            pass
        else:
            raise


def clear_apps_directory(repo, skip_ci=True):
    """
    Clear all contents from the apps/ directory in a GitHub repository.
    
    Args:
        repo: GitHub Repository object
        skip_ci: Whether to add [skip ci] to commit messages (default: True)
    
    Returns:
        int: Number of items deleted
    """
    ci_suffix = " [skip ci]" if skip_ci else ""
    logger.info("Clearing apps/ directory...")
    
    try:
        apps_contents = repo.get_contents("apps")
        
        if not isinstance(apps_contents, list):
            apps_contents = [apps_contents]
        
        items_count = len(apps_contents)
        logger.info(f"Found {items_count} items in apps/ directory")
        
        for item in apps_contents:
            if item.type == "dir":
                logger.info(f"Deleting directory: apps/{item.name}")
                delete_directory_contents(repo, item.path, skip_ci=skip_ci)
            else:
                logger.info(f"Deleting file: apps/{item.name}")
                repo.delete_file(
                    path=item.path,
                    message=f"Clear apps directory: remove {item.name}{ci_suffix}",
                    sha=item.sha
                )
        
        logger.info(f"✓ Successfully cleared apps/ directory ({items_count} items removed)")
        
        return items_count
        
    except GithubException as e:
        if e.status == 404:
            logger.info("✓ apps/ directory does not exist - nothing to clear")
            return 0
        else:
            raise

def get_captain_repo(token: str, repo_url: str):
    """
    Get a GitHub repository object for the captain domain repo using a separate token.
    
    Args:
        token: GitHub personal access token with access to the captain repo
        repo_url: Full GitHub URL (e.g., 'https://github.com/development-captains/nonprod.jupiter.onglueops.rocks')
        
    Returns:
        tuple: (Github client, Repository object)
        
    Raises:
        ValueError: If repo_url format is invalid
        GithubException: If repo access fails
    """
    import re
    
    # Parse the repo URL
    match = re.match(r'https://github\.com/([^/]+)/([^/]+)', repo_url)
    if not match:
        raise ValueError(f"Invalid captain repo URL format: {repo_url}")
    
    org_name, repo_name = match.groups()
    full_name = f"{org_name}/{repo_name}"
    
    logger.info(f"Connecting to captain repo: {full_name}")
    
    # Create GitHub client with the captain token
    from github import Auth
    auth = Auth.Token(token)
    g = Github(auth=auth)
    
    # Get the repository
    repo = g.get_repo(full_name)
    
    logger.info(f"✓ Connected to captain repo: {repo.html_url}")
    
    return g, repo


def create_or_update_file(repo, file_path: str, content: str, commit_message: str, skip_ci=True):
    """
    Create a file or update it if it already exists.
    
    This handles the GitHub API behavior where create_file fails with 422
    if the file already exists.
    
    Args:
        repo: GitHub Repository object
        file_path: Path to the file in the repository
        content: File content as string
        commit_message: Git commit message
        skip_ci: Whether to add [skip ci] to commit message (default: True)
        
    Returns:
        dict: Result from create_file or update_file with commit info
        
    Raises:
        RuntimeError: If file creation/update fails validation
        GithubException: If GitHub API call fails
    """
    ci_suffix = " [skip ci]" if skip_ci else ""
    try:
        # Try to create the file first
        logger.info(f"Creating file: {file_path}")
        
        result = repo.create_file(
            path=file_path,
            message=f"{commit_message}{ci_suffix}",
            content=content
        )
        
        # Validate the result
        if not result:
            raise RuntimeError(f"GitHub API returned None for {file_path}")
        if 'commit' not in result:
            raise RuntimeError(f"GitHub API response missing 'commit' key for {file_path}: {result}")
        if not hasattr(result['commit'], 'sha'):
            raise RuntimeError(f"GitHub API commit object missing 'sha' attribute for {file_path}")
        
        commit_sha = result['commit'].sha
        if not commit_sha:
            raise RuntimeError(f"GitHub API returned empty SHA for {file_path}")
        
        logger.info(f"✓ File created: {file_path}")
        logger.info(f"  Full SHA: {commit_sha}")
        logger.info(f"  Short SHA: {commit_sha[:8]}")
        logger.info(f"  URL: {repo.html_url}/blob/{repo.default_branch}/{file_path}")
        
        return result
        
    except GithubException as e:
        if e.status == 422:
            # File exists, need to update instead
            logger.info(f"File exists, updating: {file_path}")
            
            try:
                # Get the current file to get its SHA
                existing_file = repo.get_contents(file_path)
                
                result = repo.update_file(
                    path=file_path,
                    message=f"{commit_message}{ci_suffix}",
                    content=content,
                    sha=existing_file.sha
                )
                
                # Validate the result
                if not result:
                    raise RuntimeError(f"GitHub API returned None for {file_path}")
                if 'commit' not in result:
                    raise RuntimeError(f"GitHub API response missing 'commit' key for {file_path}: {result}")
                if not hasattr(result['commit'], 'sha'):
                    raise RuntimeError(f"GitHub API commit object missing 'sha' attribute for {file_path}")
                
                commit_sha = result['commit'].sha
                if not commit_sha:
                    raise RuntimeError(f"GitHub API returned empty SHA for {file_path}")
                
                logger.info(f"✓ File updated: {file_path}")
                logger.info(f"  Full SHA: {commit_sha}")
                logger.info(f"  Short SHA: {commit_sha[:8]}")
                logger.info(f"  URL: {repo.html_url}/blob/{repo.default_branch}/{file_path}")
                
                return result
            except GithubException as update_error:
                logger.error(f"Failed to update {file_path}: {update_error}")
                raise RuntimeError(f"Failed to update {file_path} after detecting it exists: {update_error}")
        else:
            logger.error(f"GitHub API error creating {file_path}: Status={e.status}, Data={e.data}")
            raise


def delete_file_if_exists(repo, file_path: str, commit_message: Optional[str] = None, skip_ci=True):
    """
    Delete a file from a repository if it exists.
    
    Args:
        repo: GitHub Repository object
        file_path: Path to the file to delete
        commit_message: Git commit message (defaults to "Delete {file_path}")
        skip_ci: Whether to add [skip ci] to commit message (default: True)
        
    Returns:
        str or None: Commit SHA if file was deleted, None if it didn't exist
    """
    ci_suffix = " [skip ci]" if skip_ci else ""
    if commit_message is None:
        commit_message = f"Delete {file_path}"
    
    try:
        # Get the file to get its SHA
        existing_file = repo.get_contents(file_path)
        
        logger.info(f"Deleting file: {file_path}")
        
        result = repo.delete_file(
            path=file_path,
            message=f"{commit_message}{ci_suffix}",
            sha=existing_file.sha
        )
        
        commit_sha = result['commit'].sha
        
        logger.info(f"✓ File deleted: {file_path}")
        logger.info(f"  Commit SHA: {commit_sha[:8]}")
        
        return commit_sha
        
    except GithubException as e:
        if e.status == 404:
            logger.info(f"File does not exist (nothing to delete): {file_path}")
            return None
        else:
            raise


def count_apps_in_repo(repo, apps_path='apps'):
    """
    Count the number of applications in a deployment-configurations repository.
    
    Applications are subdirectories in the apps/ folder. Each subdirectory
    represents one application that will be discovered by the ApplicationSet.
    
    Args:
        repo: PyGithub Repository object
        apps_path: Path to apps directory (default: 'apps')
        
    Returns:
        int: Number of app directories found
        
    Example:
        repo = g.get_repo("my-org/deployment-configurations")
        count = count_apps_in_repo(repo)
        # Returns 3 if apps/ contains: app1/, app2/, app3/
    """
    try:
        contents = repo.get_contents(apps_path)
        # Filter for directories only
        app_dirs = [item for item in contents if item.type == "dir"]
        return len(app_dirs)
    except Exception as e:
        logger.warning(f"Could not count apps in '{apps_path}': {e}")
        return 0


def create_multiple_files(repo, files: list, commit_message: str, branch: str = "main", skip_ci: bool = True):
    """
    Create multiple files in a single commit using the Git Data API.
    
    This is more efficient than creating files one at a time when you need
    to add several files together (e.g., Dockerfile + workflow).
    
    Args:
        repo: GitHub Repository object
        files: List of dicts with 'path' and 'content' keys
               Example: [{'path': 'Dockerfile', 'content': 'FROM alpine'}]
        commit_message: Git commit message
        branch: Target branch (default: main)
        skip_ci: Whether to add [skip ci] to commit message (default: True)
        
    Returns:
        str: Commit SHA of the new commit
        
    Example:
        files = [
            {'path': 'Dockerfile', 'content': 'FROM alpine:latest'},
            {'path': '.github/workflows/build.yaml', 'content': workflow_yaml}
        ]
        sha = create_multiple_files(repo, files, "Add container build setup")
    """
    import base64
    
    ci_suffix = " [skip ci]" if skip_ci else ""
    full_message = f"{commit_message}{ci_suffix}"
    
    logger.info(f"Creating {len(files)} files in single commit on branch '{branch}'")
    for f in files:
        logger.info(f"  📄 {f['path']}")
    
    # Get the current commit SHA for the branch
    branch_ref = repo.get_branch(branch)
    base_tree_sha = branch_ref.commit.commit.tree.sha
    base_commit_sha = branch_ref.commit.sha
    
    # Create tree elements for each file
    tree_elements = []
    for file_info in files:
        # Create a blob for the file content
        blob = repo.create_git_blob(
            content=base64.b64encode(file_info['content'].encode('utf-8')).decode('utf-8'),
            encoding='base64'
        )
        
        tree_elements.append({
            'path': file_info['path'],
            'mode': '100644',  # Regular file
            'type': 'blob',
            'sha': blob.sha
        })
    
    # Create a new tree with the files
    from github import InputGitTreeElement
    input_tree_elements = [
        InputGitTreeElement(
            path=elem['path'],
            mode=elem['mode'],
            type=elem['type'],
            sha=elem['sha']
        )
        for elem in tree_elements
    ]
    
    new_tree = repo.create_git_tree(input_tree_elements, base_tree=repo.get_git_tree(base_tree_sha))
    
    # Create the commit
    new_commit = repo.create_git_commit(
        message=full_message,
        tree=new_tree,
        parents=[repo.get_git_commit(base_commit_sha)]
    )
    
    # Update the branch reference to point to the new commit
    ref = repo.get_git_ref(f"heads/{branch}")
    ref.edit(sha=new_commit.sha)
    
    logger.info(f"✓ Created commit with {len(files)} files")
    logger.info(f"  Full SHA: {new_commit.sha}")
    logger.info(f"  Short SHA: {new_commit.sha[:8]}")
    
    return new_commit.sha