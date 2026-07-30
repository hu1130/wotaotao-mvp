"""Manage and query the local knowledge base."""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.knowledge.service import KnowledgeService


def main() -> int:
    parser = argparse.ArgumentParser(description="Local knowledge base tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Index local knowledge files")
    index_parser.add_argument("paths", nargs="*", help="Files or directories to index")
    index_parser.add_argument("--reset", action="store_true", help="Clear old index first")

    search_parser = subparsers.add_parser("search", help="Search indexed knowledge")
    search_parser.add_argument("query")
    search_parser.add_argument("--top-k", type=int, default=None)

    ask_parser = subparsers.add_parser("ask", help="Ask with grounded knowledge context")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--top-k", type=int, default=None)

    subparsers.add_parser("stats", help="Show index stats")
    args = parser.parse_args()

    service = KnowledgeService()
    if args.command == "index":
        data = service.index_paths(args.paths or None, reset=args.reset)
    elif args.command == "search":
        data = [service._result_to_dict(item) for item in service.search(args.query, args.top_k)]
    elif args.command == "ask":
        data = service.answer(args.question, args.top_k)
    else:
        data = service.stats()

    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
