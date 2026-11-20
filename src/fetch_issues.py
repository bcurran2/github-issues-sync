"""Fetch issues from a GitHub repository."""
import argparse
import os

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.github.com"


def fetch_issues(repo, token, since=None, max_pages=None):
    """Return all issues (not pull requests) for a repo, following pagination."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params = {"state": "all", "per_page": 100, "sort": "updated", "direction": "asc"}
    if since:
        params["since"] = since

    url = f"{API_URL}/repos/{repo}/issues"
    issues = []
    pages = 0
    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        # The issues endpoint also returns pull requests; keep only real issues.
        issues.extend(i for i in batch if "pull_request" not in i)
        pages += 1
        if max_pages and pages >= max_pages:
            break
        url = resp.links.get("next", {}).get("url")
        params = None  # the "next" URL already carries the query string
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("TARGET_REPO"))
    parser.add_argument("--since", help="Only issues updated at or after this ISO timestamp")
    parser.add_argument("--max-pages", type=int, help="Stop after this many pages (for testing)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts only. Nothing is saved yet; this matters once milestone 2 adds saving.",
    )
    args = parser.parse_args()

    token = os.environ["GITHUB_TOKEN"]
    issues = fetch_issues(args.repo, token, args.since, args.max_pages)
    print(f"Fetched {len(issues)} issues from {args.repo}")
    if issues:
        print(f"Oldest updated_at: {issues[0]['updated_at']}")
        print(f"Newest updated_at: {issues[-1]['updated_at']}")


if __name__ == "__main__":
    main()