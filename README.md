# Bitbucket QA Review Auditor

## Objective

Identify and report all Pull Requests across specified repositories where the authenticated user has performed a "QA" review.

## Prerequisites

Environment variables must be configured:

- `BITBUCKET_EMAIL`: Atlassian account email.
- `BITBUCKET_API_TOKEN`: [API Token](https://id.atlassian.com/manage-profile/security/api-tokens) with read-only scope.
- `BITBUCKET_WORKSPACE`: Target workspace slug.
- `BITBUCKET_REPOSITORIES`: Comma-separated list of repository slugs (e.g., `spp-react,jeteye-backend`).
- `JIRA_API_TOKEN`: Jira API token (no scopes required).
- `JIRA_BASE_URL`: Jira instance base URL (e.g., `https://your-domain.atlassian.net`).

### API Token Setup

Two tokens are required from [https://id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens):

**Bitbucket Token:**
- Click "Create API token with scopes"
- Select all Bitbucket read scopes to ensure full access
- Used for: Repository and PR data retrieval

**Jira Token:**
- Click the main "Create API token" button (no scopes selection)
- Used for: Issue type and parent issue resolution

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
- `fields`: `values.participants,values.id,values.links,values.source,next`
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

### 5. Jira Issue Type Resolution (Optional)

**Endpoint:** `GET /rest/api/3/issue/{issue_key}`

- Fetches issue type from Jira API
- If issue type is "Sub-task", extracts parent issue type from embedded data
- Falls back to parent type (Story, Task, or Bug)
- Caches results to minimize API calls

### 6. Issue Key Extraction Logic

- Primary: Extract from PR title using regex `[A-Z]+-\d+`
- Fallback: Extract from source branch name if no match in title

### 7. Output Generation

- **Format:** CSV
- **Columns:** `Repository`, `PR ID`, `Issue Key`, `Issue Type`, `Title`, `URL`, `QA Date`
- **Destination:** `./qa_reviews_report.csv`
