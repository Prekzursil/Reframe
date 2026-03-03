#!/usr/bin/env python3
"""Auto-approve Percy builds for a commit SHA.

Required env: PERCY_TOKEN
Optional env: BROWSERSTACK_USERNAME, BROWSERSTACK_ACCESS_KEY
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_BASE = "https://percy.io/api/v1"
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)


class PercyApiError(RuntimeError):
    pass


def _request_json(
    *,
    token: str | None,
    method: str,
    path: str,
    query: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    basic_auth: tuple[str, str] | None = None,
) -> dict[str, Any]:
    suffix = ""
    if query:
        suffix = "?" + urllib.parse.urlencode(query)
    url = f"{API_BASE}{path}{suffix}"

    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json",
        "User-Agent": "reframe-percy-auto-approve",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    if basic_auth is not None:
        user, key = basic_auth
        auth = f"{user}:{key}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(auth).decode("ascii")
    elif token:
        headers["Authorization"] = f"Token token={token}"
    else:
        raise ValueError("Token or basic auth is required")

    req = urllib.request.Request(url=url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise PercyApiError(f"HTTP {exc.code}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise PercyApiError(str(exc)) from exc

    if not raw:
        return {}
    payload_json = json.loads(raw)
    if not isinstance(payload_json, dict):
        raise PercyApiError("Unexpected Percy payload")
    return payload_json


def _select_unreviewed_build(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data")
    if not isinstance(data, list):
        return None
    builds = [item for item in data if isinstance(item, dict)]
    builds.sort(key=lambda item: str((item.get("attributes") or {}).get("created-at") or ""), reverse=True)
    for build in builds:
        attrs = build.get("attributes") if isinstance(build.get("attributes"), dict) else {}
        state = str(attrs.get("state") or "").lower()
        review_state = str(attrs.get("review-state") or "").lower()
        if state == "finished" and review_state == "unreviewed":
            return build
    return None


def _query_builds(*, token: str, sha: str, limit: int, branch: str | None = None) -> dict[str, Any]:
    query = {
        "filter[sha]": sha,
        "filter[state]": "finished",
        "page[limit]": str(limit),
    }
    if branch:
        query["filter[branch]"] = branch
    return _request_json(
        token=token,
        method="GET",
        path="/builds",
        query=query,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auto-approve Percy build for SHA")
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""))
    parser.add_argument("--branch", default=os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME", ""))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--retry-attempts", type=int, default=6)
    parser.add_argument("--retry-delay-seconds", type=int, default=5)
    args = parser.parse_args(argv or sys.argv[1:])

    token = str(os.environ.get("PERCY_TOKEN", "")).strip()
    browserstack_username = str(os.environ.get("BROWSERSTACK_USERNAME", "")).strip() or None
    browserstack_access_key = str(os.environ.get("BROWSERSTACK_ACCESS_KEY", "")).strip() or None

    if not token:
        print("approved=false")
        print("reason=missing-token")
        return 1

    sha = str(args.sha or "").strip()
    if not SHA_RE.fullmatch(sha):
        print("approved=false")
        print("reason=invalid-sha")
        return 1

    branch = str(args.branch or "").strip() or None
    retry_attempts = max(1, int(args.retry_attempts))
    retry_delay_seconds = max(1, int(args.retry_delay_seconds))

    selected = None
    for attempt in range(1, retry_attempts + 1):
        selected = _select_unreviewed_build(
            _query_builds(token=token, sha=sha, limit=args.limit, branch=branch)
        )

        # Percy indexing can lag briefly after build finalization.
        # If the branch-filtered query misses the fresh build, fallback to SHA-only.
        if selected is None and branch:
            selected = _select_unreviewed_build(
                _query_builds(token=token, sha=sha, limit=args.limit, branch=None)
            )

        if selected is not None:
            break
        if attempt < retry_attempts:
            time.sleep(retry_delay_seconds)

    if not selected:
        print("approved=false")
        print("reason=no-unreviewed-build")
        print(f"attempts={retry_attempts}")
        return 0

    build_id = str(selected.get("id") or "").strip()
    if not build_id:
        print("approved=false")
        print("reason=missing-build-id")
        return 1

    basic_auth: tuple[str, str] | None = None
    if browserstack_username and browserstack_access_key:
        basic_auth = (browserstack_username, browserstack_access_key)

    _request_json(
        token=token if basic_auth is None else None,
        method="POST",
        path="/reviews",
        payload={
            "data": {
                "type": "reviews",
                "attributes": {"state": "approved"},
                "relationships": {"build": {"data": {"type": "builds", "id": build_id}}},
            }
        },
        basic_auth=basic_auth,
    )

    print("approved=true")
    print("reason=build-approved")
    print(f"build_id={build_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
