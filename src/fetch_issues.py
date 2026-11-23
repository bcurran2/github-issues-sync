"""Fetch issues from a GitHub repository and land them in BigQuery."""
import argparse
import json
import time
import os
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from google.cloud import bigquery
from google.api_core.exceptions import NotFound

load_dotenv()

API_URL = "https://api.github.com"

SCHEMA = [
    bigquery.SchemaField("id", "INT64"),
    bigquery.SchemaField("number", "INT64"),
    bigquery.SchemaField("state", "STRING"),
    bigquery.SchemaField("title", "STRING"),
    bigquery.SchemaField("author", "STRING"),
    bigquery.SchemaField("labels", "STRING", mode="REPEATED"),
    bigquery.SchemaField("comments", "INT64"),
    bigquery.SchemaField("created_at", "TIMESTAMP"),
    bigquery.SchemaField("updated_at", "TIMESTAMP"),
    bigquery.SchemaField("closed_at", "TIMESTAMP"),
    bigquery.SchemaField("html_url", "STRING"),
    bigquery.SchemaField("payload", "STRING"),
    bigquery.SchemaField("_loaded_at", "TIMESTAMP"),
]

def get_with_retry(url, headers, params=None, max_attempts=5):
    """GET with exponential backoff on network errors and 5xx responses."""
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == max_attempts:
                raise
            wait = 2 ** attempt
            print(f"Network error ({exc.__class__.__name__}), retry {attempt}/{max_attempts - 1} in {wait}s")
            time.sleep(wait)
            continue
        if resp.status_code in (500, 502, 503, 504) and attempt < max_attempts:
            wait = 2 ** attempt
            print(f"GitHub returned {resp.status_code}, retry {attempt}/{max_attempts - 1} in {wait}s")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp

def wait_if_rate_limited(resp):
    """Sleep until the rate limit resets if GitHub says we've run out."""
    remaining = resp.headers.get("X-RateLimit-Remaining")
    if remaining is not None and int(remaining) == 0:
        reset = int(resp.headers.get("X-RateLimit-Reset", 0))
        wait = max(reset - int(time.time()), 0) + 1
        print(f"Rate limit reached, sleeping {wait}s until reset")
        time.sleep(wait)


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
        resp = get_with_retry(url, headers=headers, params=params)
        batch = resp.json()
        wait_if_rate_limited(resp)
        # The issues endpoint also returns pull requests; keep only real issues.
        issues.extend(i for i in batch if "pull_request" not in i)
        pages += 1
        if max_pages and pages >= max_pages:
            break
        url = resp.links.get("next", {}).get("url")
        params = None  # the "next" URL already carries the query string
    return issues


def to_raw_row(issue, loaded_at):
    """Turn one API issue into a flat row, keeping the full JSON in payload."""
    return {
        "id": issue["id"],
        "number": issue["number"],
        "state": issue["state"],
        "title": issue["title"],
        "author": (issue.get("user") or {}).get("login"),
        "labels": [label["name"] for label in issue.get("labels", [])],
        "comments": issue["comments"],
        "created_at": issue["created_at"],
        "updated_at": issue["updated_at"],
        "closed_at": issue["closed_at"],
        "html_url": issue["html_url"],
        "payload": json.dumps(issue),
        "_loaded_at": loaded_at,
    }


def load_to_bigquery(rows, project, dataset, table="issues_raw"):
    """Append rows to the raw table, creating it with the schema if needed."""
    client = bigquery.Client(project=project)
    table_id = f"{project}.{dataset}.{table}"
    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = client.load_table_from_json(rows, table_id, job_config=job_config)
    job.result()
    return len(rows)

def refresh_issues(project, dataset):
    """Rebuild the clean issues table: the latest version of each issue from raw."""
    client = bigquery.Client(project=project)
    sql = f"""
    CREATE OR REPLACE TABLE `{project}.{dataset}.issues` AS
    SELECT * EXCEPT (rn)
    FROM (
        SELECT *, ROW_NUMBER() OVER (
            PARTITION BY id ORDER BY updated_at DESC, _loaded_at DESC
        ) AS rn
        FROM `{project}.{dataset}.issues_raw`
    )
    WHERE rn = 1
    """
    client.query(sql).result()

def get_cursor(project, dataset):
    """Newest updated_at already loaded, or None if nothing is loaded yet."""
    client = bigquery.Client(project=project)
    sql = f"select max(updated_at) as newest from `{project}.{dataset}.issues_raw`"
    try:
        row = next(iter(client.query(sql).result()))
    except NotFound:
        return None
    return row.newest.strftime("%Y-%m-%dT%H:%M:%SZ") if row.newest else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("TARGET_REPO"))
    parser.add_argument("--since", help="Only issues updated at or after this ISO timestamp")
    parser.add_argument("--max-pages", type=int, help="Stop after this many pages (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Print counts only, load nothing")
    args = parser.parse_args()

    token = os.environ["GITHUB_TOKEN"]
    project, dataset = os.environ["GCP_PROJECT"], os.environ["BQ_DATASET"]
    since = args.since or get_cursor(project, dataset)
    print(f"Fetching issues updated since: {since or 'the beginning'}")
    issues = fetch_issues(args.repo, token, since, args.max_pages)
    print(f"Fetched {len(issues)} issues from {args.repo}")
    if issues:
        print(f"Oldest updated_at: {issues[0]['updated_at']}")
        print(f"Newest updated_at: {issues[-1]['updated_at']}")

    if args.dry_run or not issues:
        return

    loaded_at = datetime.now(timezone.utc).isoformat()
    rows = [to_raw_row(i, loaded_at) for i in issues]
    n = load_to_bigquery(rows, project, dataset)
    print(f"Loaded {n} rows into {dataset}.issues_raw")
    refresh_issues(project, dataset)
    print(f"Rebuilt {dataset}.issues")

if __name__ == "__main__":
    main()