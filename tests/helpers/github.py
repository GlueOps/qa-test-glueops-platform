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


def create_repo(org, repo_name: str, description: str = "Test repository", private: bool = False, verbose: bool = True):
    """
    Create a new GitHub repository in an organization.
    
    Args:
        org: GitHub Organization object
        repo_name: Name for the new repository
        description: Repository description
        private: Whether the repo should be private (default: False)
        verbose: Whether to log creation details
        
    Returns:
        github.Repository.Repository: The created repository
    """
    if verbose:
        logger.info(f"Creating repository: {repo_name} (private={private})")
    
    new_repo = org.create_repo(
        name=repo_name,
        description=description,
        private=private,
        auto_init=True
    )
    
    time.sleep(2)
    
    if verbose:
        logger.info(f"✓ Repository created: {new_repo.html_url}")
    
    return new_repo


def delete_repo(repo, verbose: bool = True):
    """
    Delete a GitHub repository.
    
    Args:
        repo: GitHub Repository object to delete
        verbose: Whether to log deletion details
    """
    repo_name = repo.full_name
    if verbose:
        logger.info(f"Deleting repository: {repo_name}")
    
    repo.delete()
    
    if verbose:
        logger.info(f"✓ Repository deleted: {repo_name}")


def delete_repo_if_exists(org, repo_name: str, verbose: bool = True) -> bool:
    """
    Delete a repository if it exists (for cleanup before/after tests).
    
    Args:
        org: GitHub Organization object
        repo_name: Name of the repository to delete
        verbose: Whether to log details
        
    Returns:
        bool: True if repo was deleted, False if it didn't exist
    """
    try:
        existing_repo = org.get_repo(repo_name)
        if verbose:
            logger.info(f"Found existing repository: {repo_name} - deleting...")
        existing_repo.delete()
        time.sleep(2)
        if verbose:
            logger.info(f"✓ Repository deleted: {repo_name}")
        return True
    except UnknownObjectException:
        if verbose:
            logger.info(f"Repository {repo_name} does not exist (nothing to delete)")
        return False
    except GithubException as e:
        if e.status == 404:
            if verbose:
                logger.info(f"Repository {repo_name} does not exist (nothing to delete)")
            return False
        raise


def delete_repos_by_topic(org, topic: str, verbose: bool = True, min_age_seconds: int = 120) -> int:
    """
    Delete all repositories in an organization that have a specific topic.
    
    This is used for cleanup of automated test repositories. Only deletes repositories
    older than min_age_seconds to avoid race conditions with newly created test repos
    whose topics haven't propagated to GitHub's search index yet.
    
    Args:
        org: GitHub Organization or User object
        topic: Topic to search for (e.g., 'createdby-automated-test-delete-me')
        verbose: Whether to log details
        min_age_seconds: Minimum age in seconds before a repo can be deleted (default: 120)
        
    Returns:
        int: Number of repositories deleted
    """
    import datetime
    deleted_count = 0
    skipped_count = 0
    
    if verbose:
        logger.info(f"Searching for repositories with topic '{topic}'...")
    
    try:
        repos = org.get_repos()
        current_time = datetime.datetime.now(datetime.timezone.utc)
        
        for repo in repos:
            if topic in repo.get_topics():
                # Check repo age to avoid deleting newly created repos
                repo_age = (current_time - repo.created_at).total_seconds()
                
                if repo_age < min_age_seconds:
                    if verbose:
                        logger.info(f"  Found test repo: {repo.name} - skipping (too new: {int(repo_age)}s old)")
                    skipped_count += 1
                    continue
                
                if verbose:
                    logger.info(f"  Found test repo: {repo.name} - deleting (age: {int(repo_age)}s)...")
                try:
                    repo.delete()
                    deleted_count += 1
                    time.sleep(1)
                except GithubException as e:
                    logger.warning(f"  ⚠ Failed to delete {repo.name}: {e.status}")
        
        if verbose:
            if deleted_count > 0:
                logger.info(f"✓ Deleted {deleted_count} test repository/repositories")
            if skipped_count > 0:
                logger.info(f"  (Skipped {skipped_count} repo(s) created within last {min_age_seconds}s)")
            if deleted_count == 0 and skipped_count == 0:
                logger.info(f"✓ No test repositories found with topic '{topic}'")
        
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error searching for repos by topic: {e}")
        return deleted_count


def set_repo_topics(repo, topics: list, verbose: bool = True):
    """
    Set topics on a GitHub repository and verify they are set.
    
    Args:
        repo: GitHub Repository object
        topics: List of topic strings to set
        verbose: Whether to log details
        
    Raises:
        RuntimeError: If topics cannot be verified after setting
    """
    if verbose:
        logger.info(f"Setting topics: {', '.join(topics)}")
    
    repo.replace_topics(topics)
    time.sleep(2)
    
    # Verify topics were set
    actual_topics = repo.get_topics()
    if set(topics) != set(actual_topics):
        raise RuntimeError(
            f"Topic verification failed! Expected: {sorted(topics)}, Got: {sorted(actual_topics)}"
        )
    
    if verbose:
        logger.info(f"✓ Topics verified: {', '.join(actual_topics)}")
    
    # CRITICAL: Wait for GitHub's search index to update
    # Without this delay, orphan cleanup from other tests may not find this repo's topics
    # and could incorrectly skip deleting it, or conversely, delete it prematurely
    if verbose:
        logger.info("⏱️  Waiting 5s for GitHub topic search index to update...")
    time.sleep(5)


def create_branch(repo, branch_name: str, source_branch: str = "main", verbose: bool = True):
    """
    Create a new branch from a source branch.
    
    Args:
        repo: GitHub Repository object
        branch_name: Name of the new branch
        source_branch: Source branch to create from (default: main)
        verbose: Whether to log creation details
        
    Returns:
        github.GitRef.GitRef: The created branch reference
    """
    if verbose:
        logger.info(f"Creating branch: {branch_name} from {source_branch}")
    
    source_ref = repo.get_branch(source_branch)
    source_sha = source_ref.commit.sha
    
    new_ref = repo.create_git_ref(
        ref=f"refs/heads/{branch_name}",
        sha=source_sha
    )
    
    if verbose:
        logger.info(f"✓ Branch created: {branch_name}")
    
    return new_ref


def create_dummy_commit(repo, branch_name: str, file_path: str, content: str, commit_message: str, verbose: bool = True):
    """
    Create a file with a commit on a specific branch.
    
    Args:
        repo: GitHub Repository object
        branch_name: Branch to commit to
        file_path: Path for the new file
        content: File content
        commit_message: Commit message
        verbose: Whether to log details
        
    Returns:
        dict: Result from create_file with commit info
    """
    if verbose:
        logger.info(f"Creating commit on branch {branch_name}: {commit_message}")
    
    result = repo.create_file(
        path=file_path,
        message=commit_message,
        content=content,
        branch=branch_name
    )
    
    if verbose:
        logger.info(f"✓ Commit created: {result['commit'].sha[:8]}")
    
    return result


def create_pull_request(repo, title: str, body: str, head_branch: str, base_branch: str = "main", verbose: bool = True):
    """
    Create a pull request.
    
    Args:
        repo: GitHub Repository object
        title: PR title
        body: PR description/body
        head_branch: Branch with changes (source)
        base_branch: Branch to merge into (target, default: main)
        verbose: Whether to log details
        
    Returns:
        github.PullRequest.PullRequest: The created PR
        
    Raises:
        GithubException: If PR creation fails
    """
    if verbose:
        logger.info(f"Creating PR: {title} ({head_branch} -> {base_branch})")
    
    try:
        pr = repo.create_pull(
            title=title,
            body=body,
            head=head_branch,
            base=base_branch
        )
        
        if verbose:
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


def close_pull_request(pr, verbose: bool = True):
    """
    Close a pull request without merging.
    
    Args:
        pr: GitHub PullRequest object
        verbose: Whether to log details
    """
    if verbose:
        logger.info(f"Closing PR: #{pr.number}")
    
    pr.edit(state="closed")
    
    if verbose:
        logger.info(f"✓ PR closed: #{pr.number}")


def merge_pull_request(pr, merge_method: str = "merge", commit_message: Optional[str] = None, verbose: bool = True):
    """
    Merge a pull request.
    
    Args:
        pr: GitHub PullRequest object
        merge_method: Merge method - 'merge', 'squash', or 'rebase'
        commit_message: Optional custom commit message
        verbose: Whether to log details
        
    Returns:
        github.PullRequestMergeStatus.PullRequestMergeStatus: Merge result
    """
    if verbose:
        logger.info(f"Merging PR: #{pr.number} (method: {merge_method})")
    
    merge_kwargs = {"merge_method": merge_method}
    if commit_message is not None:
        merge_kwargs["commit_message"] = commit_message
    
    result = pr.merge(**merge_kwargs)
    
    if verbose:
        logger.info(f"✓ PR merged: #{pr.number}")
    
    return result


def create_github_file(repo, file_path, content, commit_message, verbose=True, log_content=False):
    """
    Create a file in a GitHub repository with logging and retry logic for 404 errors.
    
    Args:
        repo: GitHub Repository object
        file_path: Path to the file
        content: File content as string
        commit_message: Git commit message
        verbose: Whether to log creation details (default: True)
        log_content: Whether to log the full file content (default: False)
    
    Returns:
        GitHub ContentFile object
        
    Raises:
        GithubException: If creation fails after retries
    """
    if verbose:
        logger.info(f"      File: {file_path}")
        logger.info(f"      Message: {commit_message}")
        
        if log_content:
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
                message=commit_message,
                content=content
            )
            
            if verbose:
                logger.info(f"      ✓ Committed to repository")
            
            return result
            
        except GithubException as e:
            if e.status == 404 and attempt < max_retries - 1:
                if verbose:
                    logger.info(f"      ⚠ Got 404, retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(retry_delay)
                continue
            else:
                # Re-raise if not a 404 or if we've exhausted retries
                raise


def delete_directory_contents(repo, path, verbose=True, max_retries=3):
    """
    Recursively delete all contents of a directory in a GitHub repository.
    
    Args:
        repo: GitHub Repository object
        path: Path to the directory to delete
        verbose: Whether to log deletion details (default: True)
        max_retries: Number of retries for 409 conflicts (default: 3)
    """
    try:
        contents = repo.get_contents(path)
        
        if not isinstance(contents, list):
            contents = [contents]
        
        for item in contents:
            if item.type == "dir":
                if verbose:
                    logger.info(f"  Deleting directory: {item.path}")
                delete_directory_contents(repo, item.path, verbose, max_retries)
            else:
                if verbose:
                    logger.info(f"  Deleting file: {item.path}")
                
                # Retry logic for 409 conflicts (file SHA changed)
                for attempt in range(max_retries):
                    try:
                        # Refetch the file to get current SHA
                        current_file = repo.get_contents(item.path)
                        repo.delete_file(
                            path=item.path,
                            message=f"Clear directory: remove {item.path}",
                            sha=current_file.sha
                        )
                        break  # Success
                    except GithubException as e:
                        if e.status == 409 and attempt < max_retries - 1:
                            if verbose:
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


def clear_apps_directory(repo, verbose=True):
    """
    Clear all contents from the apps/ directory in a GitHub repository.
    
    Args:
        repo: GitHub Repository object
        verbose: Whether to log operations (default: True)
    
    Returns:
        int: Number of items deleted
    """
    if verbose:
        logger.info("Clearing apps/ directory...")
    
    try:
        apps_contents = repo.get_contents("apps")
        
        if not isinstance(apps_contents, list):
            apps_contents = [apps_contents]
        
        items_count = len(apps_contents)
        if verbose:
            logger.info(f"Found {items_count} items in apps/ directory")
        
        for item in apps_contents:
            if item.type == "dir":
                if verbose:
                    logger.info(f"Deleting directory: apps/{item.name}")
                delete_directory_contents(repo, item.path, verbose)
            else:
                if verbose:
                    logger.info(f"Deleting file: apps/{item.name}")
                repo.delete_file(
                    path=item.path,
                    message=f"Clear apps directory: remove {item.name}",
                    sha=item.sha
                )
        
        if verbose:
            logger.info(f"✓ Successfully cleared apps/ directory ({items_count} items removed)")
        
        return items_count
        
    except GithubException as e:
        if e.status == 404:
            if verbose:
                logger.info("✓ apps/ directory does not exist - nothing to clear")
            return 0
        else:
            raise

def get_captain_repo(token: str, repo_url: str, verbose: bool = True):
    """
    Get a GitHub repository object for the captain domain repo using a separate token.
    
    Args:
        token: GitHub personal access token with access to the captain repo
        repo_url: Full GitHub URL (e.g., 'https://github.com/development-captains/nonprod.jupiter.onglueops.rocks')
        verbose: Whether to log details
        
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
    
    if verbose:
        logger.info(f"Connecting to captain repo: {full_name}")
    
    # Create GitHub client with the captain token
    from github import Auth
    auth = Auth.Token(token)
    g = Github(auth=auth)
    
    # Get the repository
    repo = g.get_repo(full_name)
    
    if verbose:
        logger.info(f"✓ Connected to captain repo: {repo.html_url}")
    
    return g, repo


def create_or_update_file(repo, file_path: str, content: str, commit_message: str, verbose: bool = True):
    """
    Create a file or update it if it already exists.
    
    This handles the GitHub API behavior where create_file fails with 422
    if the file already exists.
    
    Args:
        repo: GitHub Repository object
        file_path: Path to the file in the repository
        content: File content as string
        commit_message: Git commit message
        verbose: Whether to log details
        
    Returns:
        dict: Result from create_file or update_file with commit info
        
    Raises:
        RuntimeError: If file creation/update fails validation
        GithubException: If GitHub API call fails
    """
    try:
        # Try to create the file first
        if verbose:
            logger.info(f"Creating file: {file_path}")
        
        result = repo.create_file(
            path=file_path,
            message=commit_message,
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
        
        if verbose:
            logger.info(f"✓ File created: {file_path}")
            logger.info(f"  Commit SHA: {commit_sha[:8]}")
            logger.info(f"  URL: {repo.html_url}/blob/{repo.default_branch}/{file_path}")
        
        return result
        
    except GithubException as e:
        if e.status == 422:
            # File exists, need to update instead
            if verbose:
                logger.info(f"File exists, updating: {file_path}")
            
            try:
                # Get the current file to get its SHA
                existing_file = repo.get_contents(file_path)
                
                result = repo.update_file(
                    path=file_path,
                    message=commit_message,
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
                
                if verbose:
                    logger.info(f"✓ File updated: {file_path}")
                    logger.info(f"  Commit SHA: {commit_sha[:8]}")
                    logger.info(f"  URL: {repo.html_url}/blob/{repo.default_branch}/{file_path}")
                
                return result
            except GithubException as update_error:
                logger.error(f"Failed to update {file_path}: {update_error}")
                raise RuntimeError(f"Failed to update {file_path} after detecting it exists: {update_error}")
        else:
            logger.error(f"GitHub API error creating {file_path}: Status={e.status}, Data={e.data}")
            raise


def delete_file_if_exists(repo, file_path: str, commit_message: Optional[str] = None, verbose: bool = True) -> bool:
    """
    Delete a file from a repository if it exists.
    
    Args:
        repo: GitHub Repository object
        file_path: Path to the file to delete
        commit_message: Git commit message (defaults to "Delete {file_path}")
        verbose: Whether to log details
        
    Returns:
        bool: True if file was deleted, False if it didn't exist
    """
    if commit_message is None:
        commit_message = f"Delete {file_path}"
    
    try:
        # Get the file to get its SHA
        existing_file = repo.get_contents(file_path)
        
        if verbose:
            logger.info(f"Deleting file: {file_path}")
        
        repo.delete_file(
            path=file_path,
            message=commit_message,
            sha=existing_file.sha
        )
        
        if verbose:
            logger.info(f"✓ File deleted: {file_path}")
        
        return True
        
    except GithubException as e:
        if e.status == 404:
            if verbose:
                logger.info(f"File does not exist (nothing to delete): {file_path}")
            return False
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