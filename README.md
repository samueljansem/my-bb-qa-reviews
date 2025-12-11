# Bitbucket QA Review Auditor

## Objective

Identify and report all Pull Requests across specified repositories where the authenticated user has performed a "DEV QA" or "QA" review.

## Prerequisites

Environment variables must be configured:

- `BITBUCKET_EMAIL`: Atlassian account email.
- `BITBUCKET_API_TOKEN`: [API Token](https://id.atlassian.com/manage-profile/security/api-tokens) with read-only scope.
- `BITBUCKET_WORKSPACE`: Target workspace slug.
- `BITBUCKET_REPOSITORIES`: Comma-separated list of repository slugs (e.g., `spp-react,jeteye-backend`).

## Authentication

The script uses **Basic HTTP Authentication** (RFC-2617).

- **Username**: Your Atlassian account email (from `BITBUCKET_EMAIL`).
- **Password**: Your App Password (from `BITBUCKET_API_TOKEN`).

## Architecture & Flow

### 1. Identity Resolution

**Endpoint:** `GET /2.0/user`

- Retrieve authenticated user's `uuid`.
- **Purpose:** Robustly identify the user in subsequent filters (avoiding username mutability issues).

### 2. Pull Request Discovery (Per Repository)

**Endpoint:** `GET /2.0/repositories/{workspace}/{repo_slug}/pullrequests`
**Query Parameters:**

- `state="MERGED"`: Only completed work.
- `comment_count > 0`: Optimization to skip silent PRs.
- `author.uuid != "{user_uuid}"`: Exclude self-authored PRs.
- `fields`: `values.participants,values.id,values.links,next`
  **Logic:**
- Iterate through pages.
- Filter for PRs where `participants` contains `{user_uuid}` with `approved=true`.

### 3. Comment Analysis

**Endpoint:** `GET /2.0/repositories/{workspace}/{repo_slug}/pullrequests/{pr_id}/comments`
**Query Parameters:**

- `q=user.uuid="{user_uuid}"`: Fetch only comments by the auditor.
  **Logic:**
- Apply Case-Insensitive Regex: `/(DEV )?QA/i` on `content.raw`.
- If match found: Record PR details.

### 4. Output Generation

- **Format:** CSV
- **Columns:** `Repository`, `PR ID`, `Title`, `URL`, `QA Date` (derived from comment).
- **Destination:** `./qa_reviews_report.csv`
