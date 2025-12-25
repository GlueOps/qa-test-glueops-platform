#!/usr/bin/env python3
"""Debug all three services to understand the flow."""

import os
import sys
from playwright.sync_api import sync_playwright

captain_domain = os.environ.get("CAPTAIN_DOMAIN", "nonprod.foobar.onglueops.rocks")

with sync_playwright() as p:
    print("🌐 Connecting to Chrome at localhost:9222...")
    browser = p.chromium.connect_over_cdp("http://localhost:9222")
    context = browser.contexts[0]
    
    # Close existing pages
    for page in context.pages:
        page.close()
    
    page = context.new_page()
    
    # Test ArgoCD
    print("\n" + "="*60)
    print("TESTING ARGOCD")
    print("="*60)
    argocd_url = f"https://argocd.{captain_domain}/login?return_url=https%3A%2F%2Fargocd.{captain_domain}%2Fapplications"
    print(f"Navigating to: {argocd_url}")
    page.goto(argocd_url)
    page.wait_for_load_state("networkidle")
    print(f"Current URL: {page.url}")
    
    if f"argocd.{captain_domain}" in page.url and "github.com" not in page.url:
        print("Still on ArgoCD - looking for button...")
        try:
            btn = page.get_by_role("button", name="Log in via GitHub SSO")
            print(f"  Button visible: {btn.is_visible()}")
            print(f"  Button count: {page.locator('button').count()}")
            
            # Show all buttons
            buttons = page.locator("button").all()
            print(f"\nAll buttons on page ({len(buttons)}):")
            for i, b in enumerate(buttons[:10]):
                try:
                    text = b.inner_text(timeout=100)
                    if text.strip():
                        print(f"  {i+1}. '{text.strip()}'")
                except:
                    pass
        except Exception as e:
            print(f"  Error: {e}")
    elif "github.com" in page.url:
        print("Already redirected to GitHub!")
    
    page.screenshot(path="/tmp/argocd_debug.png")
    print("Screenshot: /tmp/argocd_debug.png")
    
    # Test Grafana
    print("\n" + "="*60)
    print("TESTING GRAFANA")
    print("="*60)
    page.goto(f"https://grafana.{captain_domain}/login")
    page.wait_for_load_state("networkidle")
    print(f"Current URL: {page.url}")
    
    if f"grafana.{captain_domain}" in page.url and "github.com" not in page.url:
        print("Still on Grafana - looking for link...")
        try:
            link = page.get_by_role("link", name="Sign in with GitHub SSO")
            print(f"  Link visible: {link.is_visible()}")
            print(f"  Link count: {page.locator('a').count()}")
        except Exception as e:
            print(f"  Error: {e}")
    elif "github.com" in page.url:
        print("Already redirected to GitHub!")
    
    page.screenshot(path="/tmp/grafana_debug.png")
    print("Screenshot: /tmp/grafana_debug.png")
    
    # Test Vault
    print("\n" + "="*60)
    print("TESTING VAULT")
    print("="*60)
    page.goto(f"https://vault.{captain_domain}")
    page.wait_for_load_state("networkidle")
    print(f"Current URL: {page.url}")
    
    if f"vault.{captain_domain}" in page.url and "github.com" not in page.url:
        print("Still on Vault - looking for elements...")
        try:
            role = page.get_by_role("textbox", name="Role")
            print(f"  Role field visible: {role.is_visible()}")
            
            btn = page.get_by_role("button", name="Sign in with OIDC Provider")
            print(f"  OIDC button visible: {btn.is_visible()}")
        except Exception as e:
            print(f"  Error: {e}")
    elif "github.com" in page.url:
        print("Already redirected to GitHub!")
    
    page.screenshot(path="/tmp/vault_debug.png")
    print("Screenshot: /tmp/vault_debug.png")
    
    page.close()
    print("\n✅ Done! Check screenshots in /tmp/")
