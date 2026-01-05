import csv
import os
import re
import sys
from datetime import datetime

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

load_dotenv()

EMAIL = os.getenv("EMAIL") or ""
BITBUCKET_API_TOKEN = os.getenv("BITBUCKET_API_TOKEN") or ""
BITBUCKET_WORKSPACE = os.getenv("BITBUCKET_WORKSPACE") or ""
BITBUCKET_REPOSITORIES = os.getenv("BITBUCKET_REPOSITORIES") or ""

JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN") or ""
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL") or ""

if not all([EMAIL, BITBUCKET_API_TOKEN, BITBUCKET_WORKSPACE, BITBUCKET_REPOSITORIES]):
    print("Error: Missing required environment variables.")
    print(
        "Ensure EMAIL, BITBUCKET_API_TOKEN, BITBUCKET_WORKSPACE, and BITBUCKET_REPOSITORIES are set."
    )
    sys.exit(1)

JIRA_AUTH = HTTPBasicAuth(EMAIL, JIRA_API_TOKEN) if JIRA_API_TOKEN else None
JIRA_HEADERS = {"Accept": "application/json"}
JIRA_ISSUE_CACHE = {}

JIRA_ISSUE_KEY_REGEX = re.compile(r"[A-Z]+-\d+")

DEBUG_LOG_FILE = "jira_api_debug.log"


def format_qa_date(iso_date):
    """Convert ISO 8601 date to YYYY-MM-DD format."""
    if iso_date:
        try:
            return datetime.fromisoformat(iso_date.replace("Z", "+00:00")).strftime(
                "%Y-%m-%d"
            )
        except ValueError:
            return iso_date
    return ""


def log_jira_debug(message):
    """Log Jira API debug messages to file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")


REPO_LIST = [r.strip() for r in BITBUCKET_REPOSITORIES.split(",") if r.strip()]
API_BASE = "https://api.bitbucket.org/2.0"
AUTH = HTTPBasicAuth(EMAIL, BITBUCKET_API_TOKEN)
HEADERS = {"Accept": "application/json"}

QA_REGEX = re.compile(r"(DEV )?QA", re.IGNORECASE)


def get_user_uuid(session):
    """Fetches the authenticated user's UUID."""
    url = f"{API_BASE}/user"
    resp = session.get(url)
    resp.raise_for_status()
    return resp.json()["uuid"]


def get_approved_prs(session, repo_slug, user_uuid):
    """Fetches merged PRs approved by the user."""
    url = f"{API_BASE}/repositories/{BITBUCKET_WORKSPACE}/{repo_slug}/pullrequests"
    query = f'state="MERGED" AND comment_count > 0 AND author.uuid!="{user_uuid}"'
    params = {
        "q": query,
        "pagelen": 50,
        "fields": "values.id,values.title,values.links,values.participants,values.source,next",
    }

    approved_prs = []

    while url:
        print(f"  Fetching PRs from: {url}...")
        resp = session.get(url, params=params)
        if resp.status_code == 404:
            print(f"  Warning: Repository {repo_slug} not found or access denied.")
            return []
        resp.raise_for_status()

        data = resp.json()
        for pr in data.get("values", []):
            for p in pr.get("participants", []):
                if p.get("user", {}).get("uuid") == user_uuid and p.get("approved"):
                    approved_prs.append(pr)
                    break

        url = data.get("next")
        params = {}

    return approved_prs


def find_qa_comment(session, repo_slug, pr_id, user_uuid):
    """Checks for QA comments by the user in a specific PR."""
    url = f"{API_BASE}/repositories/{BITBUCKET_WORKSPACE}/{repo_slug}/pullrequests/{pr_id}/comments"
    params = {
        "q": f'user.uuid="{user_uuid}"',
        "pagelen": 50,
        "fields": "values.content.raw,values.created_on,next",
    }

    while url:
        resp = session.get(url, params=params)
        if resp.status_code != 200:
            break

        data = resp.json()
        for comment in data.get("values", []):
            raw_content = comment.get("content", {}).get("raw", "")
            if QA_REGEX.search(raw_content):
                return comment.get("created_on")

        url = data.get("next")
        params = {}

    return None


def extract_jira_issue_key(pr):
    """Extracts Jira issue key from PR title, falling back to source branch name."""
    pr_title = pr.get("title", "")
    match = JIRA_ISSUE_KEY_REGEX.search(pr_title)
    if match:
        return match.group(0)

    branch_name = pr.get("source", {}).get("branch", {}).get("name", "")
    match = JIRA_ISSUE_KEY_REGEX.search(branch_name)
    return match.group(0) if match else None


def get_jira_issue_type(session, issue_key):
    """Fetches issue type from Jira API. For Sub-tasks, returns the parent's type from embedded data."""
    if not JIRA_BASE_URL or not JIRA_AUTH:
        return None

    if issue_key in JIRA_ISSUE_CACHE:
        return JIRA_ISSUE_CACHE[issue_key]

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}"
    log_jira_debug(f"Request: GET {url}")
    log_jira_debug(f"Auth: {EMAIL} (hidden token)")

    try:
        resp = session.get(url, auth=JIRA_AUTH, headers=JIRA_HEADERS)
        status_code = resp.status_code
        log_jira_debug(f"Status: {status_code}")

        if status_code == 200:
            response_data = resp.json()
            log_jira_debug(f"Response: {response_data}")

            issue_type = (
                response_data.get("fields", {}).get("issuetype", {}).get("name", None)
            )
            log_jira_debug(f"Extracted Issue Type: {issue_type}")

            if issue_type == "Sub-task":
                parent = response_data.get("fields", {}).get("parent", {})
                parent_fields = parent.get("fields", {})
                parent_issue_type = parent_fields.get("issuetype", {}).get("name", None)

                if parent_issue_type:
                    log_jira_debug(
                        f"Sub-task detected. Using parent type from embedded data: {parent_issue_type}"
                    )
                    JIRA_ISSUE_CACHE[issue_key] = parent_issue_type
                    return parent_issue_type

            JIRA_ISSUE_CACHE[issue_key] = issue_type
            return issue_type
        else:
            response_text = resp.text
            log_jira_debug(f"Response: {response_text}")
            JIRA_ISSUE_CACHE[issue_key] = None
            return None
    except requests.exceptions.RequestException as e:
        log_jira_debug(f"Error: {e}")
        JIRA_ISSUE_CACHE[issue_key] = None
        return None


def main():
    log_jira_debug("=== Jira API Debug Log Started ===")
    log_jira_debug(f"JIRA_BASE_URL: {JIRA_BASE_URL}")
    log_jira_debug(f"JIRA_AUTH configured: {bool(JIRA_AUTH)}")

    session = requests.Session()
    session.auth = AUTH
    session.headers.update(HEADERS)

    jira_session = None
    if JIRA_AUTH:
        jira_session = requests.Session()
        jira_session.auth = JIRA_AUTH
        jira_session.headers.update(JIRA_HEADERS)

    print("Authenticating...")
    try:
        user_uuid = get_user_uuid(session)
        print(f"Authenticated as UUID: {user_uuid}")
    except requests.exceptions.RequestException as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)

    results = []

    for repo in REPO_LIST:
        print(f"Processing repository: {repo}")
        prs = get_approved_prs(session, repo, user_uuid)
        print(f"  Found {len(prs)} approved PRs. Checking comments...")

        for pr in prs:
            pr_id = pr["id"]
            qa_date = find_qa_comment(session, repo, pr_id, user_uuid)

            if qa_date:
                print(f"  [MATCH] PR #{pr_id}: {pr['title']}")
                issue_key = extract_jira_issue_key(pr)
                issue_type = (
                    get_jira_issue_type(jira_session, issue_key)
                    if jira_session
                    else None
                )
                results.append(
                    {
                        "Repository": repo,
                        "PR ID": pr_id,
                        "Issue Key": issue_key or "",
                        "Issue Type": issue_type or "",
                        "Title": pr["title"],
                        "URL": pr["links"]["html"]["href"],
                        "QA Date": format_qa_date(qa_date),
                    }
                )

    output_file = "qa_reviews_report.csv"
    if results:
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "Repository",
                    "PR ID",
                    "Issue Key",
                    "Issue Type",
                    "Title",
                    "URL",
                    "QA Date",
                ],
            )
            writer.writeheader()
            writer.writerows(results)
        print(f"\nSuccess! Report generated: {output_file} ({len(results)} records)")
    else:
        print("\nNo QA reviews found.")


if __name__ == "__main__":
    main()
