"""Open a merge request in the demo fork (for testing Prior-Art Review / the webhook).

Creates a branch, commits a file change, and opens an MR. Returns the MR iid.
Run: python demo_mr.py
"""

from __future__ import annotations

import os
import time
import urllib.parse

import requests
from dotenv import load_dotenv

load_dotenv()

API = "https://gitlab.com/api/v4"


def open_demo_mr(
    title: str = "chore: re-add fdignore to prevent markdown edits",
    file_path: str = ".fdignore",
    content: str = "# prevent fd from rewriting generated markdown docs\n*.md\n",
) -> dict:
    pid = os.environ["GITLAB_PROJECT_ID_DEMO"]
    headers = {"PRIVATE-TOKEN": os.environ["GITLAB_TOKEN"]}

    project = requests.get(f"{API}/projects/{pid}", headers=headers, timeout=30).json()
    default_branch = project["default_branch"]
    branch = f"recall-demo-{int(time.time())}"

    requests.post(
        f"{API}/projects/{pid}/repository/branches",
        headers=headers,
        params={"branch": branch, "ref": default_branch},
        timeout=30,
    ).raise_for_status()

    quoted = urllib.parse.quote(file_path, safe="")
    payload = {"branch": branch, "content": content, "commit_message": title}
    resp = requests.post(f"{API}/projects/{pid}/repository/files/{quoted}", headers=headers, json=payload, timeout=30)
    if resp.status_code >= 400:  # file may already exist -> update instead
        requests.put(f"{API}/projects/{pid}/repository/files/{quoted}", headers=headers, json=payload, timeout=30).raise_for_status()

    mr = requests.post(
        f"{API}/projects/{pid}/merge_requests",
        headers=headers,
        json={"source_branch": branch, "target_branch": default_branch, "title": title},
        timeout=30,
    ).json()
    return {"iid": mr["iid"], "web_url": mr["web_url"], "project_id": pid}


if __name__ == "__main__":
    info = open_demo_mr()
    print(f"opened MR !{info['iid']} -> {info['web_url']}")
