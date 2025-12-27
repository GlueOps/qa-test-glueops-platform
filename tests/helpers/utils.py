"""
Common utility functions for tests.

This module provides general-purpose utilities like progress bars,
section headers, and formatted output that can be used across test suites.
"""
import time
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def display_progress_bar(wait_time, interval=15, description="Waiting", verbose=True):
    """
    Display a progress bar with time tracking.
    
    Args:
        wait_time: Total time to wait in seconds
        interval: Update interval in seconds (default: 15)
        description: Description of what we're waiting for (default: "Waiting")
        verbose: Whether to display progress (default: True)
    
    Returns:
        float: Actual elapsed time in seconds
    """
    if not verbose:
        time.sleep(wait_time)
        return wait_time
    
    logger.info(f"\n⏳ {description}...")
    logger.info(f"\n   Progress:")
    
    start_time = time.time()
    
    for remaining in range(wait_time, 0, -interval):
        elapsed = wait_time - remaining
        elapsed_min = elapsed // 60
        elapsed_sec = elapsed % 60
        remaining_min = remaining // 60
        remaining_sec = remaining % 60
        
        # Progress bar (20 segments for 100%)
        progress_pct = (elapsed / wait_time) * 100
        filled = int(progress_pct / 5)
        bar = "█" * filled + "░" * (20 - filled)
        
        timestamp = datetime.now().strftime('%H:%M:%S')
        logger.info(f"   [{timestamp}] {bar} {progress_pct:5.1f}% | "
              f"Elapsed: {elapsed_min:02d}:{elapsed_sec:02d} | "
              f"Remaining: {remaining_min:02d}:{remaining_sec:02d}")
        
        time.sleep(interval)
    
    actual_elapsed = time.time() - start_time
    logger.info(f"\n✓ Wait complete! Total time: {int(actual_elapsed)}s")
    
    return actual_elapsed


def print_section_header(title, verbose=True):
    """
    Print a formatted section header.
    
    Args:
        title: Section title
        verbose: Whether to print (default: True)
    """
    if verbose:
        logger.info("\n" + "="*70)
        logger.info(title)
        logger.info("="*70)


def print_summary_list(items, title="Items", verbose=True):
    """
    Print a formatted list of items.
    
    Args:
        items: List of items to print
        title: Title for the list (default: "Items")
        verbose: Whether to print (default: True)
    """
    if not verbose:
        return
    
    logger.info(f"\n{title}:")
    for idx, item in enumerate(items, 1):
        if isinstance(item, dict):
            # Format dict nicely
            name = item.get('name', 'Unknown')
            extra = {k: v for k, v in item.items() if k != 'name'}
            logger.info(f"  [{idx}] {name}")
            for key, value in extra.items():
                logger.info(f"       {key}: {value}")
        else:
            logger.info(f"  [{idx}] {item}")
