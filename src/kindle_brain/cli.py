"""Unified CLI for Kindle Brain.

Usage:
    kindle-brain setup              # Interactive first-time setup
    kindle-brain sync               # Sync from Kindle or clippings file
    kindle-brain extract            # Extract book texts via Calibre
    kindle-brain enrich             # Golden nuggets + summaries
    kindle-brain generate           # Generate markdown files + catalog
    kindle-brain index              # Build vector index
    kindle-brain serve              # Start MCP server (stdio)
    kindle-brain search "query"     # CLI semantic search
    kindle-brain stats              # Library statistics
"""

import argparse
import json
import sys


def cmd_setup(args):
    """Interactive first-time setup."""
    from kindle_brain.paths import (
        get_data_dir, find_kindle_mount, find_clippings_file,
        find_calibre, config_path,
    )
    from kindle_brain.config import save_system_config
    import os

    print("=" * 50)
    print("  Kindle Brain — Setup")
    print("=" * 50)
    print()

    config = {}
    data_dir = get_data_dir()
    print(f"Data directory: {data_dir}")
    print()

    # 1. Detect Kindle
    kindle_mount = find_kindle_mount()
    clippings_file = None

    if args.clippings_file:
        clippings_file = args.clippings_file
        if not os.path.exists(clippings_file):
            print(f"Error: File not found: {clippings_file}")
            sys.exit(1)
        print(f"Clippings file: {clippings_file}")
    elif kindle_mount:
        print(f"Kindle detected at: {kindle_mount}")
        clippings_file = find_clippings_file(kindle_mount)
        config['kindle_mount'] = kindle_mount
    else:
        print("Kindle not connected.")
        print("You can run setup later with: kindle-brain sync --clippings-file /path/to/My\\ Clippings.txt")

    if clippings_file:
        config['clippings_file'] = clippings_file

        # Detect locale
        from kindle_brain.sync import detect_locale
        with open(clippings_file, 'r', encoding='utf-8') as f:
            sample = f.read(5000)
        locale = detect_locale(sample)
        config['locale'] = locale
        print(f"Detected language: {'Spanish' if locale == 'es' else 'English'}")

    print()

    # 2. Detect Calibre
    calibre = find_calibre()
    if calibre:
        config['calibre_path'] = calibre
        config['tier'] = 'full'
        print(f"Calibre found: {calibre}")
        print("Tier: FULL (highlights + golden nuggets from book texts)")
    else:
        config['tier'] = 'basic'
        print("Calibre not found.")
        print("Tier: BASIC (highlights only, no golden nuggets)")
        print("Install Calibre from https://calibre-ebook.com/ for full features.")

    print()

    # 3. Gemini API key
    api_key = os.environ.get('GOOGLE_API_KEY')
    if api_key:
        print(f"Gemini API key: configured (from environment)")
    else:
        print("Gemini API key not found.")
        print("Get a free key at: https://aistudio.google.com/")
        key = input("Paste your GOOGLE_API_KEY (or press Enter to skip): ").strip()
        if key:
            # Save to .env in data dir
            env_file = data_dir / ".env"
            with open(env_file, 'a') as f:
                f.write(f"\nGOOGLE_API_KEY={key}\n")
            print(f"Saved to {env_file}")
            os.environ['GOOGLE_API_KEY'] = key

    print()

    # Save config
    save_system_config(config)
    print(f"Config saved: {config_path()}")

    # 4. Initial sync if clippings available
    if clippings_file:
        print()
        print("-" * 40)
        print("Running initial sync...")
        from kindle_brain.sync import sync_clippings
        result = sync_clippings(clippings_file=clippings_file)
        if 'error' in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Synced {result['new_clippings']} clippings from {result['total_books']} books")

    # 5. Print Claude Desktop config
    print()
    print("=" * 50)
    print("  Setup complete!")
    print("=" * 50)
    print()
    print("To connect to Claude Desktop, add this to your config:")
    print("(Settings > Developer > Edit Config)")
    print()
    config_json = {
        "mcpServers": {
            "kindle-brain": {
                "command": "kindle-brain",
                "args": ["serve"]
            }
        }
    }
    print(json.dumps(config_json, indent=2))
    print()
    print("Next steps:")
    print("  kindle-brain enrich          # Add context + summaries (needs API key)")
    print("  kindle-brain generate        # Generate markdown files for Claude")
    print("  kindle-brain serve           # Start MCP server")


def cmd_sync(args):
    """Sync Kindle clippings."""
    from kindle_brain.sync import sync_clippings

    clippings_file = args.clippings_file
    if args.reset:
        from kindle_brain.sync import reset_sync
        reset_sync()
        return

    print("Syncing Kindle clippings...")
    result = sync_clippings(clippings_file=clippings_file)

    if 'error' in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"New clippings: {result['new_clippings']}")
    print(f"Duplicates skipped: {result.get('duplicates', 0)}")
    print(f"Total clippings: {result['total_clippings']}")
    print(f"Total books: {result['total_books']}")


def cmd_extract(args):
    """Extract book texts via Calibre."""
    from kindle_brain.paths import find_calibre
    from kindle_brain.extract import extract_books

    calibre = find_calibre()
    if not calibre:
        print("Error: Calibre not found. Install from https://calibre-ebook.com/")
        sys.exit(1)

    print("Extracting text from Kindle books...")
    result = extract_books()

    if 'error' in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"Books extracted: {result['extracted']}")
    print(f"Failed: {result['failed']}")
    print(f"Not found: {result['not_found']}")
    print(f"Total: {result['total_extracted']}/{result['total_books']}")


def cmd_enrich(args):
    """Run enrichment pipeline."""
    from kindle_brain.enrich import run_enrichment

    result = run_enrichment(
        book_id=args.book,
        rich_context=args.rich_context,
        skip_summaries=args.no_summaries,
        force=args.force,
    )

    if 'error' in result.get('context', {}):
        print(f"Error: {result['context']['error']}")
        sys.exit(1)


def cmd_generate(args):
    """Generate markdown files."""
    from kindle_brain.generate_md import generate_all, generate_library_index, generate_catalog, embed_fingerprints

    if args.library_index:
        print("Generating LIBRARY.md with semantic fingerprints...")
        result = generate_library_index()
        if 'error' in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Done! Generated: {result['generated']}, Failed: {result['failed']}")
    elif args.catalog:
        print("Generating CATALOG.md...")
        result = generate_catalog()
        if 'error' in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Done! {result['generated']} books, {result['chars']} chars")
    elif args.embed_fingerprints:
        print("Embedding fingerprints into book .md files...")
        result = embed_fingerprints()
        if 'error' in result:
            print(f"Error: {result['error']}")
        else:
            print(f"Done! Updated: {result['updated']}, No fingerprint: {result['no_fingerprint']}")
    else:
        print("Generating Markdown files...")
        result = generate_all(book_id=args.book)
        print(f"Done! Generated: {result['generated']}, Skipped: {result['skipped']}")


def cmd_index(args):
    """Build vector index."""
    from kindle_brain.index import index_clippings

    if args.full:
        print("Full re-index with Gemini Embedding 2...")
    else:
        print("Updating vector index...")

    result = index_clippings(full_reindex=args.full, book_id=args.book)

    if 'error' in result:
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"Indexed: {result['indexed']}")
    print(f"Total: {result['total']}")


def cmd_serve(args):
    """Start MCP server."""
    from kindle_brain.server.mcp_server import mcp
    mcp.run(transport="stdio")


def cmd_search(args):
    """Search highlights."""
    from kindle_brain.search import semantic_search, get_book_clippings, list_books, get_stats, format_result

    if args.stats:
        stats = get_stats()
        print(f"Books: {stats['total_books']}")
        print(f"Highlights: {stats['total_highlights']}")
        print(f"Golden nuggets: {stats['golden_nuggets']}")
        return

    if args.list_books:
        books = list_books()
        for book in books:
            author = f" by {book['author']}" if book['author'] else ""
            print(f"  {book['title']}{author} — {book['clipping_count']}h")
        print(f"\nTotal: {len(books)} books")
        return

    if args.book and not args.query:
        results = get_book_clippings(args.book)
        if results:
            print(f"# {results[0]['book_title']}\n")
            for i, r in enumerate(results, 1):
                print(format_result(r, i))
                print("\n---\n")
        return

    if not args.query:
        print("Usage: kindle-brain search \"your query\"")
        return

    results = semantic_search(args.query, top_k=args.top, book_filter=args.book)
    if not results:
        print(f"No results for: {args.query}")
        return

    for i, r in enumerate(results, 1):
        print(format_result(r, i))
        print("\n---\n")


def cmd_stats(args):
    """Show library statistics."""
    from kindle_brain.search import get_stats
    stats = get_stats()
    print("Kindle Brain Statistics")
    print(f"  Books: {stats['total_books']}")
    print(f"  Highlights: {stats['total_highlights']}")
    print(f"  Notes: {stats['total_notes']}")
    print(f"  Golden nuggets: {stats['golden_nuggets']}")
    print(f"  Enriched: {stats['enriched_clippings']}")
    print(f"  With summaries: {stats['books_with_summaries']}")
    if stats['date_range']['first']:
        print(f"  Date range: {stats['date_range']['first'][:10]} — {stats['date_range']['last'][:10]}")


def main():
    parser = argparse.ArgumentParser(
        prog='kindle-brain',
        description='Turn your Kindle highlights into a personal AI knowledge base',
    )
    parser.add_argument('--version', action='version', version='%(prog)s 0.1.0')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # setup
    p_setup = subparsers.add_parser('setup', help='Interactive first-time setup')
    p_setup.add_argument('--clippings-file', help='Path to My Clippings.txt')
    p_setup.set_defaults(func=cmd_setup)

    # sync
    p_sync = subparsers.add_parser('sync', help='Sync Kindle clippings')
    p_sync.add_argument('--clippings-file', help='Path to My Clippings.txt')
    p_sync.add_argument('--reset', action='store_true', help='Reset sync state')
    p_sync.set_defaults(func=cmd_sync)

    # extract
    p_extract = subparsers.add_parser('extract', help='Extract book texts via Calibre')
    p_extract.set_defaults(func=cmd_extract)

    # enrich
    p_enrich = subparsers.add_parser('enrich', help='Enrich with context + summaries')
    p_enrich.add_argument('--book', type=int, help='Process only this book_id')
    p_enrich.add_argument('--rich-context', action='store_true', help='Extract golden nuggets')
    p_enrich.add_argument('--no-summaries', action='store_true', help='Skip summary generation')
    p_enrich.add_argument('--force', action='store_true', help='Re-process all')
    p_enrich.set_defaults(func=cmd_enrich)

    # generate
    p_gen = subparsers.add_parser('generate', help='Generate markdown files')
    p_gen.add_argument('--book', type=int, help='Generate for this book_id only')
    p_gen.add_argument('--library-index', action='store_true', help='Generate LIBRARY.md')
    p_gen.add_argument('--catalog', action='store_true', help='Generate CATALOG.md')
    p_gen.add_argument('--embed-fingerprints', action='store_true', help='Embed fingerprints in book files')
    p_gen.set_defaults(func=cmd_generate)

    # index
    p_index = subparsers.add_parser('index', help='Build vector index')
    p_index.add_argument('--full', action='store_true', help='Full reindex')
    p_index.add_argument('--book', type=int, help='Index only this book_id')
    p_index.set_defaults(func=cmd_index)

    # serve
    p_serve = subparsers.add_parser('serve', help='Start MCP server')
    p_serve.set_defaults(func=cmd_serve)

    # search
    p_search = subparsers.add_parser('search', help='Search highlights')
    p_search.add_argument('query', nargs='?', help='Search query')
    p_search.add_argument('--book', '-b', help='Filter by book title')
    p_search.add_argument('--list-books', '-l', action='store_true')
    p_search.add_argument('--stats', '-s', action='store_true')
    p_search.add_argument('--top', '-t', type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    # stats
    p_stats = subparsers.add_parser('stats', help='Library statistics')
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == '__main__':
    main()
