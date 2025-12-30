#!/usr/bin/env python3
"""Simple script to list pytest test node IDs."""
import pytest
import sys
import io

class TestCollector:
    def __init__(self):
        self.tests = []
    
    def pytest_collection_finish(self, session):
        """Called after collection is complete."""
        for item in session.items:
            self.tests.append(item.nodeid)

if __name__ == "__main__":
    collector = TestCollector()
    # Suppress all pytest output by redirecting stdout/stderr
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    
    pytest.main(["--collect-only", "-q"], plugins=[collector])
    
    # Restore stdout/stderr
    sys.stdout = old_stdout
    sys.stderr = old_stderr
    
    # Print only the test node IDs
    for test in collector.tests:
        print(test)
