"""GitHub helper functions for GitOps testing."""
import logging
from github import GithubException

logger = logging.getLogger(__name__)


def create_github_file(repo, file_path, content, commit_message, verbose=True):
    """
    Create a file in a GitHub repository with logging.
    
    Args:
        repo: GitHub Repository object
        file_path: Path to the file (e.g., "apps/myapp/values.yaml")
        content: File content as string
        commit_message: Git commit message
        verbose: Whether to log creation details (default: True)
    
    Returns:
        GitHub ContentFile object
    """
    if verbose:
        logger.info(f"      Creating: {file_path}")
        logger.info(f"      Message: {commit_message}")
    
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
