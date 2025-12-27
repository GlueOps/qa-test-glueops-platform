"""GitHub helper functions for GitOps testing."""
import logging
import time
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
        private: Whether the repo should be private (default: False for public)
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
        auto_init=True  # Creates with README so we have a commit
    )
    
    # Wait for repo to be fully initialized
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
        time.sleep(2)  # Give GitHub API time to process deletion
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
    
    # Get the SHA of the source branch
    source_ref = repo.get_branch(source_branch)
    source_sha = source_ref.commit.sha
    
    # Create the new branch
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
        github.PullRequest.PullRequest: The created PR (has .html_url for browser navigation)
        
    Raises:
        GithubException: If PR creation fails (logs details before raising)
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
        if 'documentation_url' in e.data:
            logger.error(f"   Documentation: {e.data['documentation_url']}")
        
        # Common troubleshooting hints
        if e.status == 403:
            logger.error(f"   💡 Troubleshooting hints:")
            logger.error(f"      - Check GitHub token has 'repo' scope (not just 'public_repo')")
            logger.error(f"      - If org uses SSO, authorize the token at:")
            logger.error(f"        Settings → Developer settings → Personal access tokens → Configure SSO")
            logger.error(f"      - Consider using fine-grained tokens if classic tokens are restricted")
        
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


def merge_pull_request(pr, merge_method: str = "merge", commit_message: str = None, verbose: bool = True):
    """
    Merge a pull request.
    
    Args:
        pr: GitHub PullRequest object
        merge_method: Merge method - 'merge', 'squash', or 'rebase' (default: merge)
        commit_message: Optional custom commit message
        verbose: Whether to log details
        
    Returns:
        github.PullRequestMergeStatus.PullRequestMergeStatus: Merge result
    """
    if verbose:
        logger.info(f"Merging PR: #{pr.number} (method: {merge_method})")
    
    # Build merge arguments - only include commit_message if provided
    merge_kwargs = {"merge_method": merge_method}
    if commit_message is not None:
        merge_kwargs["commit_message"] = commit_message
    
    result = pr.merge(**merge_kwargs)
    
    if verbose:
        logger.info(f"✓ PR merged: #{pr.number}")
    
    return result


def create_github_file(repo, file_path, content, commit_message, verbose=True, log_content=False):
    """
    Create a file in a GitHub repository with logging.
    
    Args:
        repo: GitHub Repository object
        file_path: Path to the file (e.g., "apps/myapp/values.yaml")
        content: File content as string
        commit_message: Git commit message
        verbose: Whether to log creation details (default: True)
        log_content: Whether to log the full file content (default: False)
    
    Returns:
        GitHub ContentFile object
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
    
    result = repo.create_file(
        path=file_path,
        message=commit_message,
        content=content
    )
    
    if verbose:
        logger.info(f"      ✓ Committed to repository")
    
    return result


def delete_directory_contents(repo, path, verbose=True):
    """
    Recursively delete all contents of a directory in a GitHub repository.
    
    Args:
        repo: GitHub Repository object
        path: Path to the directory to delete
        verbose: Whether to log deletion details (default: True)
    """
    try:
        contents = repo.get_contents(path)
        
        if not isinstance(contents, list):
            contents = [contents]
        
        for item in contents:
            if item.type == "dir":
                if verbose:
                    logger.info(f"  Deleting directory: {item.path}")
                delete_directory_contents(repo, item.path, verbose)
            else:
                if verbose:
                    logger.info(f"  Deleting file: {item.path}")
                repo.delete_file(
                    path=item.path,
                    message=f"Clear directory: remove {item.path}",
                    sha=item.sha
                )
    except GithubException as e:
        if e.status == 404:
            # Already deleted or doesn't exist
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
        
        # Delete all contents within the apps/ folder
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
