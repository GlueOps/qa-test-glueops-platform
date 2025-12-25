"""Shared fixtures for UI tests."""
import pytest
from .helpers import (
    get_browser_connection,
    create_incognito_context,
    cleanup_browser
)


@pytest.fixture
def page(request, captain_domain):
    """Playwright page fixture for pytest-html-plus auto screenshot capture.
    
    This fixture:
    - Creates a browser connection (BrowserBase or local Chrome)
    - Sets up an incognito context for test isolation
    - Exposes the page to pytest-html-plus for automatic screenshot capture
    - Automatically cleans up browser resources after the test
    """
    playwright, browser, session = get_browser_connection()
    context = create_incognito_context(browser)
    page_instance = context.new_page()
    
    # Attach page to request for pytest-html-plus to find it
    request.node.page_for_screenshot = page_instance
    
    yield page_instance
    
    # Cleanup
    cleanup_browser(playwright, page_instance, context, session)
