# UI Testing Guide - GlueOps Platform

**AI Context Document** - Comprehensive guide for UI testing patterns and lessons learned.

## Overview

UI tests validate web-based authentication and user interface functionality for GlueOps platform services using Playwright. Tests connect to a Chrome browser via CDP (Chrome DevTools Protocol) for realistic browser automation.

**Technology Stack:**
- Playwright 1.40.0+ (Chromium via CDP)
- pyotp 2.9.0+ (TOTP 2FA code generation)
- Python 3.11+
- Docker containerization with Chrome connection

## Architecture

### Test Structure

```
tests/ui/
├── helpers.py                        # Shared UI test utilities
├── conftest.py                       # Pytest fixtures (github_credentials, captain_domain)
├── test_argocd_login_example.py      # ArgoCD applications page test
├── test_grafana_login_example.py     # Grafana dashboard test
└── test_vault_login_example.py       # Vault secrets page test
```

### Core Components

#### 1. Browser Connection (CDP)

Tests connect to an existing Chrome browser instance running at `localhost:9222`:

```python
playwright, browser, session = get_browser_connection()
context = create_incognito_context(browser)  # Uses default context (contexts[0])
page = create_new_page(context)
```

**Key Details:**
- Uses CDP (Chrome DevTools Protocol) at `ws://localhost:9222`
- Connects to **existing** browser (doesn't launch new one)
- Uses **default browser context** (contexts[0]) not true incognito
- Clears cookies and storage between tests instead of closing context
- Navigates existing pages to `about:blank` to avoid ERR_ABORTED errors

**Why CDP?**
- Allows connection to externally managed browser
- No need to bundle Chromium in Docker
- Can observe tests visually by running Chrome in foreground

#### 2. GitHub OAuth Flow

All services use GitHub SSO via dex (OAuth proxy). The critical pattern:

```python
# Pattern discovered: OAuth services redirect BACK to login page after GitHub OAuth
# The SSO button/link must be clicked AGAIN to establish the session

# 1. Navigate to target page (will redirect to GitHub OAuth)
page.goto(target_url, wait_until="load", timeout=30000)

# 2. Complete GitHub OAuth if redirected
if "github.com" in page.url:
    complete_github_oauth_flow(page, github_credentials)
    page.wait_for_timeout(3000)

# 3. CRITICAL: Click SSO button/link AGAIN after returning to login page
if "/login" in page.url or "/auth" in page.url:
    # Click the SSO button/link based on service
    page.get_by_role("button/link", name="SSO Button Name").click()
    page.wait_for_timeout(5000)
    
    # May redirect to GitHub again for authorization
    if "github.com" in page.url:
        complete_github_oauth_flow(page, github_credentials)
        page.wait_for_timeout(3000)

# 4. Navigate to final target page
page.goto(target_url, wait_until="load", timeout=30000)
page.wait_for_timeout(5000)  # Wait for content to render

# 5. Take screenshot
take_screenshot(page, "Description", attach_screenshot)
```

#### 3. GitHub OAuth Handler

Centralized function handles all GitHub authentication scenarios:

```python
complete_github_oauth_flow(page, credentials)
```

**Handles:**
- GitHub login page (username/password)
- OTP/2FA challenges (generates TOTP codes with pyotp)
- Passkeys prompts (clicks "Don't ask again for this browser")
- OAuth authorization page (clicks Authorize button with dynamic text)
- Already authenticated scenarios (direct redirect back to service)

**Returns:** Boolean indicating success

#### 4. Wait Strategies

**Critical Lesson:** Different apps require different wait strategies!

**Standard Apps (Grafana, Vault):**
```python
page.goto(url, wait_until="networkidle", timeout=30000)
```

**Websocket Apps (ArgoCD):**
```python
page.goto(url, wait_until="load", timeout=30000)  # NOT networkidle!
page.wait_for_timeout(5000)  # Fixed timeout for rendering
```

**Why?** 
- ArgoCD uses websockets for real-time updates
- Page never reaches "networkidle" state (active connections)
- Use `wait_until="load"` and fixed timeouts instead

#### 5. Cookie Clearing Strategy

**Problem:** Closing pages during test execution caused ERR_ABORTED errors

**Solution:** Navigate existing pages to `about:blank` instead:

```python
def create_incognito_context(browser):
    context = browser.contexts[0]  # Use default context
    
    # Navigate existing pages to about:blank instead of closing
    for page in context.pages:
        try:
            page.goto("about:blank", wait_until="load", timeout=5000)
        except Exception:
            pass
    
    # Clear cookies and storage multiple times for thorough cleanup
    context.clear_cookies()
    context.clear_permissions()
    # ... more clearing ...
```

## Service-Specific Patterns

### ArgoCD

**Target Page:** `/applications` (shows deployed apps)

**SSO Element:** Button with text "Log in via GitHub SSO"

**Wait Strategy:** `wait_until="load"` (websockets!)

```python
argocd_url = f"https://argocd.{captain_domain}"
argocd_applications_url = f"{argocd_url}/applications"

# Navigate directly to applications page
page.goto(argocd_applications_url, wait_until="load", timeout=30000)

# Handle OAuth if redirected
if "github.com" in page.url:
    complete_github_oauth_flow(page, github_credentials)
    page.wait_for_timeout(3000)

# Click SSO button if on login page
if "/login" in page.url:
    page.get_by_role("button", name="Log in via GitHub SSO").click()
    page.wait_for_timeout(5000)
    
    if "github.com" in page.url:
        complete_github_oauth_flow(page, github_credentials)
        page.wait_for_timeout(3000)

# Final navigation
page.goto(argocd_applications_url, wait_until="load", timeout=30000)
page.wait_for_timeout(5000)

# Verify success
if "/applications" not in page.url:
    raise Exception(f"Failed to reach applications page. Current URL: {page.url}")

take_screenshot(page, "ArgoCD Applications Page", attach_screenshot)
```

**Screenshot:** 852KB (showing application list)

### Grafana

**Target Page:** `/` (home/dashboards)

**SSO Element:** Link with text "Sign in with GitHub SSO"

**Wait Strategy:** `wait_until="load"` (standard)

```python
grafana_url = f"https://grafana.{captain_domain}"
grafana_home_url = f"{grafana_url}/"

# Navigate to home page
page.goto(grafana_home_url, wait_until="load", timeout=30000)

# Handle OAuth if redirected
if "github.com" in page.url:
    complete_github_oauth_flow(page, github_credentials)
    page.wait_for_timeout(3000)

# Click SSO link if on login page
if "/login" in page.url:
    page.get_by_role("link", name="Sign in with GitHub SSO").click()
    page.wait_for_timeout(5000)
    
    if "github.com" in page.url:
        complete_github_oauth_flow(page, github_credentials)
        page.wait_for_timeout(3000)

# Final navigation
page.goto(grafana_home_url, wait_until="load", timeout=30000)
page.wait_for_timeout(5000)

# Verify success
if "/login" in page.url:
    raise Exception("Failed to login to Grafana - still on login page")

take_screenshot(page, "Grafana Home Page", attach_screenshot)
```

**Screenshot:** 504KB (showing dashboard)

### Vault

**Target Page:** `/ui/vault/secrets` (secrets browser)

**SSO Element:** 
- Textbox with name "Role" (fill with "reader")
- Button with text "Sign in with OIDC Provider"

**Wait Strategy:** `wait_until="load"` (standard) with **navigation expectation**

**Special Case:** Must wait for navigation after clicking OIDC button!

```python
vault_url = f"https://vault.{captain_domain}"
vault_secrets_url = f"{vault_url}/ui/vault/secrets"

# Navigate to secrets page
page.goto(vault_secrets_url, wait_until="load", timeout=30000)

# Handle OAuth if redirected
if "github.com" in page.url:
    complete_github_oauth_flow(page, github_credentials)
    page.wait_for_timeout(3000)

# Fill role and click OIDC button if on auth page
if "/auth" in page.url or page.url.endswith("/ui/"):
    page.get_by_role("textbox", name="Role").fill("reader")
    page.wait_for_timeout(1000)
    
    # CRITICAL: Wait for navigation after clicking button
    with page.expect_navigation(wait_until="load", timeout=30000):
        page.get_by_role("button", name="Sign in with OIDC Provider").click()
    
    page.wait_for_timeout(3000)
    
    if "github.com" in page.url:
        complete_github_oauth_flow(page, github_credentials)
        page.wait_for_timeout(3000)

# Wait for Vault to load
page.wait_for_timeout(3000)

# Verify success
if "/auth" in page.url or page.url.endswith("/ui/"):
    raise Exception("Failed to login to Vault - still on auth page")

take_screenshot(page, "Vault Logged In", attach_screenshot)
```

**Screenshot:** 85KB (showing secrets interface)

## Key Lessons Learned

### 1. OAuth Redirect Pattern (CRITICAL!)

**Discovery:** OAuth services using dex redirect **back to their login page** after GitHub OAuth completes. The session isn't established until the SSO button/link is clicked **again**.

**Why?** 
- First OAuth establishes GitHub authentication
- Service needs explicit "sign in" action to create local session
- OAuth callback URL includes `return_url` parameter pointing back to login

**Evidence:** 
```
After OAuth, current URL: https://argocd.../login?return_url=https://argocd.../applications
```

**Pattern:**
1. Navigate to target → Redirects to GitHub
2. Complete GitHub OAuth → Redirects to service `/login` page
3. Click SSO button/link → Establishes authenticated session
4. Navigate to target → Success!

### 2. Websocket Wait Strategy

**Problem:** ArgoCD test timed out waiting for `networkidle`

**Discovery:** ArgoCD uses websockets for real-time application updates. The page maintains active connections and never reaches "networkidle" state.

**Solution:** Use `wait_until="load"` instead of `wait_until="networkidle"` for websocket-based SPAs

**How to identify:** 
- Test hangs waiting for networkidle
- Browser dev tools shows active WebSocket connections
- App updates in real-time (live data streaming)

### 3. Navigation vs Fixed Timeouts

**Best Practices:**

**After user actions (clicks, form fills):**
```python
page.get_by_role("button", name="Submit").click()
page.wait_for_timeout(3000)  # Fixed timeout for response
```

**When navigating to pages:**
```python
page.goto(url, wait_until="load", timeout=30000)  # Wait for load event
page.wait_for_timeout(5000)  # Additional time for JS to render
```

**Why?** User actions may or may not trigger navigation. Fixed timeouts ensure we wait for any processing.

### 4. Cookie Clearing Strategy

**Problem:** Closing pages with `page.close()` during test execution caused:
```
net::ERR_ABORTED
```

**Root Cause:** CDP connection doesn't fully control page lifecycle. Closing pages while browser is navigating causes errors.

**Solution:** 
- Keep pages open, navigate to `about:blank`
- Clear cookies/storage in context instead
- More reliable for CDP-based connections

### 5. Volume Mounting for Screenshots

**Problem:** Screenshots weren't visible on host filesystem

**Cause:** Docker container's `/app/reports` directory wasn't mounted

**Solution:** Mount reports directory as volume:
```bash
docker run -v "$(pwd)/reports:/app/reports" ...
```

**Benefits:**
- Screenshots persist after container exits
- Can review screenshots visually
- Useful for debugging test failures

## Fixtures

### github_credentials

Provides GitHub authentication credentials from environment variables:

```python
@pytest.fixture
def github_credentials():
    return {
        'username': os.getenv('GITHUB_USERNAME'),
        'password': os.getenv('GITHUB_PASSWORD'),
        'otp_secret': os.getenv('GITHUB_OTP_SECRET')
    }
```

**Required Environment Variables:**
- `GITHUB_USERNAME` - GitHub email/username
- `GITHUB_PASSWORD` - GitHub password
- `GITHUB_OTP_SECRET` - TOTP secret key for 2FA (base32 encoded)

### captain_domain

Provides the cluster domain for constructing service URLs:

```python
@pytest.fixture
def captain_domain():
    return os.getenv('CAPTAIN_DOMAIN', 'nonprod.foobar.onglueops.rocks')
```

**Environment Variable:**
- `CAPTAIN_DOMAIN` - Cluster domain (e.g., `nonprod.foobar.onglueops.rocks`)

## Helper Functions

### get_browser_connection()

Connects to Chrome via CDP at `localhost:9222`:

```python
playwright, browser, session = get_browser_connection()
```

**Returns:** Tuple of (playwright instance, browser, session)

**Raises:** Exception if connection fails

### create_incognito_context(browser)

Returns the default browser context with cleared cookies/storage:

```python
context = create_incognito_context(browser)
```

**Note:** Uses `contexts[0]` (default context), not true incognito. Clears state instead.

### create_new_page(context)

Creates a new page in the context:

```python
page = create_new_page(context)
```

**Returns:** Page object with default viewport

### complete_github_oauth_flow(page, credentials)

Handles the complete GitHub OAuth authentication flow:

```python
success = complete_github_oauth_flow(page, github_credentials)
```

**Handles:**
- Login page (username/password)
- OTP/2FA challenges (generates TOTP code)
- Passkeys prompts
- OAuth authorization page
- Already authenticated scenarios

**Returns:** Boolean indicating success

**Important:** Assumes page is already on GitHub domain!

### take_screenshot(page, description, attach_screenshot_fn)

Captures screenshot and saves to reports directory:

```python
take_screenshot(page, "ArgoCD Applications Page", attach_screenshot)
```

**Filename Format:** `{description_snake_case}_{timestamp}.png`

**Location:** `reports/screenshots/`

**Pytest Integration:** Uses `attach_screenshot_fn` (from pytest-html) to attach screenshot to HTML report

### cleanup_browser(playwright, page, context, session)

Cleans up browser resources:

```python
cleanup_browser(playwright, page, context, session)
```

**Actions:**
- Closes page (if exists)
- Closes context (if exists)
- Stops Playwright

**Note:** Use in `finally` block to ensure cleanup on test failure

## Test Markers

UI tests use these pytest markers:

- `@pytest.mark.authenticated` - Requires GitHub OAuth authentication
- `@pytest.mark.oauth_redirect` - Involves OAuth redirects
- `@pytest.mark.ui` - UI test (browser-based)
- `@pytest.mark.slow` - Takes >30s to complete

## Running UI Tests

### Docker (Recommended)

Requires Chrome running at `localhost:9222`:

```bash
# Start Chrome in separate terminal
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug

# Run authenticated UI tests
make ui-auth

# Run OAuth redirect tests
make ui-oauth

# Run all UI tests
make ui
```

### Local Execution

```bash
# Install dependencies
make local-install

# Start Chrome with debugging
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug

# Run tests
pytest tests/ui/ -m authenticated -v
```

### Required Environment Variables

Set these before running UI tests:

```bash
export CAPTAIN_DOMAIN="nonprod.foobar.onglueops.rocks"
export GITHUB_USERNAME="your-email@example.com"
export GITHUB_PASSWORD="your-password"
export GITHUB_OTP_SECRET="YOUR_TOTP_SECRET"  # Base32 encoded
```

## Debugging

### Viewing Test Execution

Since tests connect to existing Chrome at `localhost:9222`, you can **watch tests execute live**:

1. Start Chrome with debugging in foreground
2. Run tests in another terminal
3. Watch browser navigate and interact with pages

### Screenshot Analysis

Screenshots are saved to `reports/screenshots/`:

```bash
ls -lht reports/screenshots/ | head -10  # Latest screenshots
```

**Indicators of success:**
- **File size** - Correct pages are usually different sizes than login pages
- **Filename timestamp** - Verify it's from recent test run
- **Visual inspection** - Open PNG to see actual page content

**Example:**
```
-rw-r--r-- 1 root root 853K Dec 25 02:03 argocd_applications_page_20251225_020320.png  ✅
-rw-r--r-- 1 root root 1.9M Dec 25 01:48 argocd_applications_page_20251225_014841.png  ❌
```
Smaller file = applications page with data (correct)  
Larger file = login page with graphics (incorrect)

### Common Failures

**Timeout waiting for networkidle:**
- Check if app uses websockets
- Change to `wait_until="load"`

**Still on login page after OAuth:**
- Verify SSO button/link is clicked after OAuth redirect
- Check URL after OAuth to confirm on login page

**Connection refused to Chrome:**
- Ensure Chrome is running with `--remote-debugging-port=9222`
- Check Chrome is running on `localhost` not in container

**Screenshot not found:**
- Verify reports directory is mounted: `-v "$(pwd)/reports:/app/reports"`
- Check Docker volume mount in Makefile

**OTP code invalid:**
- Verify `GITHUB_OTP_SECRET` is correct base32 encoding
- Check system clock is synchronized (TOTP is time-based)

## Performance

**Test Execution Times:**
- ArgoCD: ~35 seconds
- Grafana: ~35 seconds  
- Vault: ~30 seconds
- **Total (sequential):** ~100 seconds (1m40s)

**Factors:**
- GitHub OAuth latency (7-10s)
- Page load times (3-5s)
- Fixed timeouts for reliability (3-5s)
- Multiple navigation steps

**Optimization Opportunities:**
- Reuse authenticated session across tests (requires session management)
- Reduce fixed timeouts where safe
- Parallel execution (if Chrome supports multiple CDP connections)

## Security Considerations

### Credentials

**Never commit credentials to git!**

- Use environment variables
- Rotate credentials regularly
- Use dedicated test account (not personal)
- Enable 2FA for test account

### TOTP Secret

**GITHUB_OTP_SECRET format:** Base32 encoded string (e.g., `XXXXXXXXXXXXXX`)

**Where to get it:**
- GitHub → Settings → Password and authentication
- Two-factor authentication → Authenticator app
- **Save the secret key** when setting up 2FA (before scanning QR code)
- Or use recovery codes to reset 2FA and get new secret

### Chrome Debugging Port

**WARNING:** Chrome debugging port (`9222`) provides **full browser control**!

**Production:** Never expose `localhost:9222` to external network

**Development:** 
- Use `--user-data-dir=/tmp/chrome-debug` for isolated profile
- Close Chrome after testing
- Don't use personal Chrome profile with debugging enabled

## Best Practices

### 1. Always Use the OAuth Pattern

Every service using dex requires the double-click pattern:

```python
# Navigate → OAuth → Click SSO again → Navigate → Success
```

Don't try to shortcut this - it won't work!

### 2. Wait Strategy by App Type

**Websocket apps:** `wait_until="load"` + fixed timeouts  
**Standard apps:** `wait_until="networkidle"` is fine

### 3. Verify Success Before Screenshot

Always check URL or page content before taking screenshot:

```python
if "/login" in page.url:
    raise Exception("Still on login page")
```

Prevents false positives from screenshot of wrong page.

### 4. Use Fixed Timeouts After User Actions

After clicking buttons/links, use fixed timeouts:

```python
page.get_by_role("button", name="Submit").click()
page.wait_for_timeout(3000)  # Give it time to process
```

Navigations may or may not happen immediately.

### 5. Clean Up in Finally Block

Always clean up browser resources:

```python
try:
    # ... test code ...
finally:
    cleanup_browser(playwright, page, context, session)
```

Prevents resource leaks if test fails.

### 6. Volume Mount for Screenshots

Always mount reports directory:

```bash
-v "$(pwd)/reports:/app/reports"
```

Makes screenshots accessible after container exits.

## Future Enhancements

### Potential Improvements

1. **Session Reuse** - Cache authenticated session to avoid OAuth per test
2. **Parallel Execution** - Run tests in parallel with multiple browser contexts
3. **Visual Regression** - Compare screenshots to baseline images
4. **Network Mocking** - Mock slow/failing API calls for negative tests
5. **Accessibility Testing** - Validate WCAG compliance
6. **Mobile Testing** - Test responsive layouts with mobile viewports
7. **Cross-Browser** - Test with Firefox, WebKit in addition to Chromium
8. **Video Recording** - Record test execution for debugging

### Additional Services

UI tests could be added for:
- **Prometheus** - Validate metrics dashboard loads
- **Alertmanager** - Check alert list and silences
- **Loki** - Validate log viewer interface
- **Backstage** - Test service catalog (if deployed)

---

**Last Updated**: December 25, 2025  
**Version**: 1.0.0  
**Maintainer**: GlueOps Platform Team
