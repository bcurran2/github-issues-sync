# GitHub Issues Sync

An incremental data integration: pulls issues from a public GitHub repository through the GitHub REST API and keeps a BigQuery table in sync with them. Records change over time (issues get edited, closed, relabeled), so this project is about doing that safely: only fetching what changed, never duplicating rows when a job reruns, and surviving rate limits and flaky responses.

**Status:** just started. Nothing below is built yet.

## Why this project

The EIA pipeline loads data that never changes once published. Real integrations deal with records that do change. This project practices:

- incremental loads using a saved cursor (last `updated_at` seen)
- idempotent writes (a rerun never creates duplicates), using a BigQuery MERGE
- API pagination, authentication, rate-limit handling, retries with backoff
- tests with mocked API responses
- dbt models and a scheduled run on top of the synced data

## Decisions made up front

- Source repo to sync: `dbt-labs/dbt-core` (public, active, plenty of issues). Easy to change in `.env`.
- Destination: a new BigQuery dataset `gh_raw` (and `gh_dev` for dbt) in the existing `eia-energy-pipeline` GCP project, so there's no new project to set up.
- Authentication: a GitHub personal access token with no extra scopes (public data only). Unauthenticated calls are limited to 60 per hour, which is too low.
- Pull requests also appear in the issues endpoint. Decide in milestone 1 whether to keep or filter them.

## Milestones (one small piece at a time)

1. **Fetch.** Pull issues page by page (100 per page, follow the pagination links) with a `--dry-run` flag that prints counts and saves nothing.
2. **Land raw.** Append the fetched issues to a BigQuery raw table, stamped with `_loaded_at`, like the EIA project.
3. **Upsert.** MERGE the raw rows into a clean `issues` table keyed on the issue id, so rerunning the job never duplicates anything. Test it by running twice and counting rows.
4. **Incremental.** Save the newest `updated_at` seen, and on the next run fetch only issues changed since then (the API's `since` parameter).
5. **Reliability.** Retries with backoff, rate-limit handling (read the remaining-requests headers and wait), logging, and pytest tests using mocked responses.
6. **Model and schedule.** dbt staging model and a monthly issues opened vs closed mart with tests, and a scheduled GitHub Actions run using the same keyless Google Cloud login as the EIA project.
7. **Write up.** README design notes, and a screenshot of a simple dashboard if it adds something.

## Setup (tomorrow's first loop)

1. Create the folder and repo, and push the first commit (same loop as the EIA project).
2. Create a GitHub personal access token and put it in `.env` (copy `.env.example`).
3. Create the virtual environment and install `requirements.txt`.
4. Start milestone 1.

## Repo layout (planned)

```
src/        sync code
tests/      pytest tests with mocked API responses
dbt/        models and tests (milestone 6)
.github/    scheduled workflow (milestone 6)
```
