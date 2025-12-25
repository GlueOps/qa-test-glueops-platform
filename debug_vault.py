#!/usr/bin/env python3
"""
Debug script to test Vault login flow interactively.
Connect to Chrome at localhost:9222 and step through the login process.
"""

import os
import sys
import time
from playwright.sync_api import sync_playwright

# Get credentials from environment
username = os.environ.get("GITHUB_USERNAME")
password = os.environ.get("GITHUB_PASSWORD")
otp_secret = os.environ.get("GITHUB_OTP_SECRET")
captain_domain = os.environ.get("CAPTAIN_DOMAIN", "nonprod.foobar.onglueops.rocks")

if not all([username, password, otp_secret]):
    print("❌ Missing credentials. Set GITHUB_USERNAME, GITHUB_PASSWORD, GITHUB_OTP_SECRET")
    sys.exit(1)

print(f"🔐 Using credentials: {username}")
print(f"🌐 Using captain domain: {captain_domain}")

with sync_playwright() as p:
    print("\n🌐 Connecting to Chrome at localhost:9222...")
    browser = p.chromium.connect_over_cdp("http://localhost:9222")
    
    print(f"📊 Connected! Contexts: {len(browser.contexts)}")
    
    # Use the default context
    context = browser.contexts[0]
    
    # Close existing pages
    for page in context.pages:
        page.close()
    
    # Create new page
    page = context.new_page()
    
    vault_url = f"https://vault.{captain_domain}"
    
    print(f"\n🔍 Step 1: Navigate to Vault")
    print(f"   URL: {vault_url}")
    page.goto(vault_url)
    page.wait_for_load_state("networkidle")
    print(f"   Current URL: {page.url}")
    
    print("\n🔍 Step 2: Fill in Role field")
    try:
        role_field = page.get_by_role("textbox", name="Role")
        role_field.wait_for(state="visible", timeout=5000)
        role_field.fill("reader")
        print("   ✅ Filled Role with 'reader'")
    except Exception as e:
        print(f"   ❌ Could not find Role field: {e}")
    
    print("\n🔍 Step 3: Look for 'Sign in with OIDC Provider' button")
    try:
        oidc_button = page.get_by_role("button", name="Sign in with OIDC Provider")
        oidc_button.wait_for(state="visible", timeout=5000)
        print("   ✅ Found button!")
        
        print("\n🔍 Step 4: Set up popup handler and click button")
        
        # Define popup handler
        popup_detected = {"value": None}
        
        def handle_popup(popup):
            print(f"   🎯 POPUP DETECTED! URL: {popup.url}")
            popup_detected["value"] = popup
        
        page.on("popup", handle_popup)
        
        # Click the button
        print("   Clicking 'Sign in with OIDC Provider'...")
        oidc_button.click()
        
        # Wait a bit to see if popup appears
        time.sleep(3)
        
        if popup_detected["value"]:
            popup = popup_detected["value"]
            print(f"\n   ✅ Popup opened!")
            print(f"   Popup URL: {popup.url}")
            print(f"   Popup title: {popup.title()}")
        else:
            print(f"\n   ⚠️  No popup detected")
            print(f"   Main page URL: {page.url}")
            print(f"   Main page title: {page.title()}")
        
    except Exception as e:
        print(f"   ❌ Button not found or error: {e}")
    
    print("\n📸 Taking screenshot...")
    page.screenshot(path="/tmp/debug_vault.png")
    print("   Screenshot saved to /tmp/debug_vault.png")
    
    if popup_detected["value"]:
        popup_detected["value"].screenshot(path="/tmp/debug_vault_popup.png")
        print("   Popup screenshot saved to /tmp/debug_vault_popup.png")
    
    print(f"\n📍 Final main page URL: {page.url}")
    
    print("\n⏸️  Pausing - you can inspect the browser now")
    print("   Press Enter to continue...")
    input()
    
    # Cleanup
    if popup_detected["value"]:
        popup_detected["value"].close()
    page.close()
    print("✅ Done!")
