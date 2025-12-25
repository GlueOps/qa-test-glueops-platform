"""
GitOps Deployment Workflow Tests

Tests the end-to-end GitOps workflow for deploying applications
through the GlueOps platform.
"""
import pytest
from github import GithubException


def delete_directory_contents(repo, path):
    """
    Recursively delete all contents of a directory in a GitHub repository.
    
    Args:
        repo: GitHub Repository object
        path: Path to the directory to delete
    """
    try:
        contents = repo.get_contents(path)
        
        if not isinstance(contents, list):
            contents = [contents]
        
        for item in contents:
            if item.type == "dir":
                # Recursively delete subdirectory
                print(f"  Deleting directory: {item.path}")
                delete_directory_contents(repo, item.path)
            else:
                # Delete file
                print(f"  Deleting file: {item.path}")
                repo.delete_file(
                    path=item.path,
                    message=f"Clear apps directory: remove {item.path}",
                    sha=item.sha
                )
    except GithubException as e:
        if e.status == 404:
            # Already deleted or doesn't exist
            pass
        else:
            raise


@pytest.mark.gitops
def test_create_custom_deployment_repo(ephemeral_github_repo):
    """
    Test creating a custom deployment repository from template.
    
    This test:
    1. Creates an ephemeral repo from the deployment-configurations template
    2. Clears out the apps/ directory in the new repo
    3. Prepares the repo for custom application deployment
    
    The apps/ folder will be populated with test applications in subsequent steps.
    """
    repo = ephemeral_github_repo
    
    # Verify the repository was created
    assert repo is not None
    assert repo.name is not None
    print(f"Created test repository: {repo.full_name}")
    
    # Get the apps directory contents
    try:
        apps_contents = repo.get_contents("apps")
        
        if not isinstance(apps_contents, list):
            apps_contents = [apps_contents]
        
        print(f"Found {len(apps_contents)} items in apps/ directory")
        
        # Delete all contents within the apps/ folder (files and directories)
        # Note: We're only deleting from OUR copy, not the template
        for item in apps_contents:
            if item.type == "dir":
                print(f"Deleting directory: apps/{item.name}")
                delete_directory_contents(repo, item.path)
            else:
                print(f"Deleting file: apps/{item.name}")
                repo.delete_file(
                    path=item.path,
                    message=f"Clear apps directory: remove {item.name}",
                    sha=item.sha
                )
        
        print("Successfully cleared apps/ directory")
        
        # Verify apps directory is now empty
        try:
            remaining = repo.get_contents("apps")
            if isinstance(remaining, list):
                assert len(remaining) == 0, f"apps/ directory should be empty but has {len(remaining)} items"
            else:
                pytest.fail("apps/ directory should be empty but still contains content")
        except GithubException as e:
            # 404 is expected if directory is now empty/doesn't exist
            if e.status == 404:
                print("apps/ directory is now empty (404 returned)")
            else:
                raise
    
    except GithubException as e:
        if e.status == 404:
            print("apps/ directory does not exist in template - this is fine")
        else:
            raise
    
    # Create 100 nested folders with Hello.txt files
    print("\nCreating 100 nested directories with Hello.txt files...")
    import time
    
    for i in range(1, 5):
        folder_name = f"hello{i}"
        file_path = f"apps/{folder_name}/{folder_name}/Hello.txt"
        file_content = f"hello{i}"
        
        print(f"Creating: {file_path}")
        repo.create_file(
            path=file_path,
            message=f"Add {folder_name} application",
            content=file_content
        )
    
    print(f"\n✓ Successfully created 100 applications in apps/ directory")
    
    # Verify the structure
    apps_contents = repo.get_contents("apps")
    print(f"Verification: apps/ directory now contains {len(apps_contents)} items")
    
    # Wait 30 seconds for manual inspection
    print("\n⏳ Waiting 30 seconds for manual inspection...")
    print(f"   Repository URL: {repo.html_url}")
    time.sleep(30)
    print("✓ Wait complete, proceeding with cleanup...")
