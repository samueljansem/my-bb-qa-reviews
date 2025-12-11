import csv
import os
import re
import sys

import requests
from dotenv import load_dotenv
from requests.auth import HTTPBasicAuth

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
EMAIL = os.getenv("BITBUCKET_EMAIL")
API_TOKEN = os.getenv("BITBUCKET_API_TOKEN")
WORKSPACE = os.getenv("BITBUCKET_WORKSPACE")
REPOSITORIES = os.getenv("BITBUCKET_REPOSITORIES")

if not all([EMAIL, API_TOKEN, WORKSPACE, REPOSITORIES]):
    print("Error: Missing required environment variables.")
    print(
        "Ensure BITBUCKET_EMAIL, BITBUCKET_API_TOKEN, BITBUCKET_WORKSPACE, and BITBUCKET_REPOSITORIES are set."
    )
    sys.exit(1)

REPO_LIST = [r.strip() for r in REPOSITORIES.split(",") if r.strip()]
API_BASE = "https://api.bitbucket.org/2.0"
AUTH = HTTPBasicAuth(EMAIL, API_TOKEN)
HEADERS = {"Accept": "application/json"}

# Regex for "QA" or "DEV QA" (case insensitive)
QA_REGEX = re.compile(r"(DEV )?QA", re.IGNORECASE)


def get_user_uuid(session):
    """Fetches the authenticated user's UUID."""
    url = f"{API_BASE}/user"
    resp = session.get(url)
    resp.raise_for_status()
    return resp.json()["uuid"]


def get_approved_prs(session, repo_slug, user_uuid):
    """Fetches merged PRs approved by the user."""
    url = f"{API_BASE}/repositories/{WORKSPACE}/{repo_slug}/pullrequests"
    # Query: Merged, has comments, not authored by me
    query = f'state="MERGED" AND comment_count > 0 AND author.uuid!="{user_uuid}"'
    params = {
        "q": query,
        "pagelen": 50,
        "fields": "values.id,values.title,values.links,values.participants,next",
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
            # Check if user is a participant and approved
            for p in pr.get("participants", []):
                if p.get("user", {}).get("uuid") == user_uuid and p.get("approved"):
                    approved_prs.append(pr)
                    break

        url = data.get("next")
        params = {}  # Clear params for next URL as it includes them

    return approved_prs


def find_qa_comment(session, repo_slug, pr_id, user_uuid):
    """Checks for QA comments by the user in a specific PR."""
    url = (
        f"{API_BASE}/repositories/{WORKSPACE}/{repo_slug}/pullrequests/{pr_id}/comments"
    )
    # Query: Comments by me
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


def main():
    session = requests.Session()
    session.auth = AUTH
    session.headers.update(HEADERS)

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
                results.append(
                    {
                        "Repository": repo,
                        "PR ID": pr_id,
                        "Title": pr["title"],
                        "URL": pr["links"]["html"]["href"],
                        "QA Date": qa_date,
                    }
                )

    # Write to CSV
    output_file = "qa_reviews_report.csv"
    if results:
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=["Repository", "PR ID", "Title", "URL", "QA Date"]
            )
            writer.writeheader()
            writer.writerows(results)
        print(f"\nSuccess! Report generated: {output_file} ({len(results)} records)")
    else:
        print("\nNo QA reviews found.")


if __name__ == "__main__":
    main()
