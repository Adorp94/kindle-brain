#!/usr/bin/env python3
"""
Master update script: runs the full pipeline when Kindle is connected.
sync → extract → enrich → index
"""

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR / "scripts"))

KINDLE_MOUNT = "/Volumes/Kindle"


def run_update(skip_summaries: bool = False) -> dict:
    """Run the full update pipeline."""
    results = {}

    print("=" * 60)
    print("KINDLE CLIPPINGS UPDATE")
    print("=" * 60)

    # Check Kindle connection
    kindle_connected = os.path.exists(KINDLE_MOUNT)
    if kindle_connected:
        print(f"\n✓ Kindle connected at {KINDLE_MOUNT}")
    else:
        print(f"\n⚠ Kindle not connected (some operations may be limited)")

    # Step 1: Sync clippings
    print("\n" + "-" * 40)
    print("STEP 1: Syncing clippings")
    print("-" * 40)

    from sync import sync_clippings
    sync_result = sync_clippings()

    if 'error' in sync_result:
        print(f"Error: {sync_result['error']}")
        if not kindle_connected:
            print("Connect your Kindle and try again.")
        return {'error': sync_result['error']}

    results['sync'] = sync_result
    print(f"  New clippings: {sync_result['new_clippings']}")
    print(f"  Total clippings: {sync_result['total_clippings']}")
    print(f"  Total books: {sync_result['total_books']}")

    # Step 2: Extract text from books
    print("\n" + "-" * 40)
    print("STEP 2: Extracting book text")
    print("-" * 40)

    from extract_text import extract_books
    extract_result = extract_books()

    if 'error' in extract_result:
        print(f"Warning: {extract_result['error']}")
    else:
        results['extract'] = extract_result
        print(f"  Books extracted: {extract_result['extracted']}")
        print(f"  Total extracted: {extract_result['total_extracted']}/{extract_result['total_books']}")

    # Step 3: Enrich clippings
    print("\n" + "-" * 40)
    print("STEP 3: Enriching clippings")
    print("-" * 40)

    from enrich import enrich_clippings, generate_summaries

    enrich_result = enrich_clippings()

    if 'error' in enrich_result:
        print(f"Warning: {enrich_result['error']}")
    else:
        results['enrich'] = enrich_result
        print(f"  Clippings enriched: {enrich_result['enriched']}")

    # Generate summaries (if API key available and not skipped)
    if not skip_summaries:
        print("\n  Generating summaries...")
        summary_result = generate_summaries()
        if 'error' not in summary_result:
            results['summaries'] = summary_result
            print(f"  Book summaries: {summary_result['book_summaries']}")
            print(f"  Chapter summaries: {summary_result['chapter_summaries']}")
        else:
            print(f"  Skipping summaries: {summary_result['error']}")

    # Step 4: Update vector index
    print("\n" + "-" * 40)
    print("STEP 4: Updating vector index")
    print("-" * 40)

    from index import index_clippings
    index_result = index_clippings()

    if 'error' in index_result:
        print(f"Warning: {index_result['error']}")
    else:
        results['index'] = index_result
        print(f"  Indexed this run: {index_result['indexed']}")
        print(f"  Total in index: {index_result['total']}")

    # Summary
    print("\n" + "=" * 60)
    print("UPDATE COMPLETE")
    print("=" * 60)

    sync_data = results.get('sync', {})
    extract_data = results.get('extract', {})
    enrich_data = results.get('enrich', {})
    index_data = results.get('index', {})

    print(f"\nSynced {sync_data.get('new_clippings', 0)} new clippings from {sync_data.get('new_books', 0)} books.")

    if extract_data.get('extracted', 0) > 0:
        print(f"Extracted text from {extract_data['extracted']} new books.")

    if enrich_data.get('enriched', 0) > 0:
        print(f"Enriched {enrich_data['enriched']} clippings with context.")

    if index_data.get('indexed', 0) > 0:
        print(f"Indexed {index_data['indexed']} new clippings.")

    print(f"\nReady to search! Use: python scripts/search.py \"your query\"")

    return results


if __name__ == '__main__':
    skip_summaries = '--no-summaries' in sys.argv

    try:
        run_update(skip_summaries=skip_summaries)
    except KeyboardInterrupt:
        print("\n\nUpdate interrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError during update: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
