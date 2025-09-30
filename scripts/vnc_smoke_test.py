#!/usr/bin/env python3
"""Smoke-test the VNC gateway via the public control-plane API.

The script creates a VNC-enabled session, waits until the runner reports an
HTTP viewer URL and then fetches the page to ensure the deployment proxies the
request correctly.
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
from typing import Any, Dict, Optional


def _build_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}{suffix}"


def _open_url(
    request: urllib.request.Request,
    *,
    context: Optional[ssl.SSLContext],
    timeout: float,
) -> urllib.response.addinfourl:
    if context is not None:
        return urllib.request.urlopen(request, timeout=timeout, context=context)
    return urllib.request.urlopen(request, timeout=timeout)


def _api_request(
    base_url: str,
    path: str,
    *,
    method: str,
    payload: Optional[Dict[str, Any]] = None,
    context: Optional[ssl.SSLContext],
    timeout: float,
) -> Dict[str, Any]:
    url = _build_url(base_url, path)
    data: Optional[bytes] = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with _open_url(request, context=context, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode()
        except Exception:  # pragma: no cover - defensive fallback
            detail = exc.reason if isinstance(exc.reason, str) else repr(exc.reason)
        raise SystemExit(f"{method} {url} failed: {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"{method} {url} failed: {exc}") from exc


def _delete_session(
    base_url: str,
    worker: str,
    session_id: str,
    *,
    context: Optional[ssl.SSLContext],
    timeout: float,
) -> None:
    path = f"/sessions/{urllib.parse.quote(worker)}/{urllib.parse.quote(session_id)}"
    request = urllib.request.Request(
        _build_url(base_url, path),
        method="DELETE",
        headers={"Content-Type": "application/json"},
    )
    try:
        _open_url(request, context=context, timeout=timeout)
    except Exception:
        # Session deletion failures are not fatal for the smoke test, but we log
        # them to stderr for visibility.
        print(
            f"Warning: failed to delete session {worker}/{session_id}",
            file=sys.stderr,
        )


def _fetch_vnc_page(url: str, *, context: Optional[ssl.SSLContext], timeout: float) -> int:
    request = urllib.request.Request(url)
    try:
        with _open_url(request, context=context, timeout=timeout) as response:
            return getattr(response, "status", response.getcode())
    except urllib.error.HTTPError as exc:
        return exc.code
    except urllib.error.URLError as exc:
        raise SystemExit(f"Failed to reach VNC page {url}: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base",
        default="http://localhost:9000/api",
        help="Base URL of the control-plane API (default: %(default)s)",
    )
    parser.add_argument(
        "--worker",
        help="Prefer a specific worker when creating the session",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds to wait between session status checks (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="Overall timeout for session readiness in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=10.0,
        help="Timeout in seconds for individual HTTP requests (default: %(default)s)",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification",
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="Do not delete the created session when the test finishes",
    )
    args = parser.parse_args()

    ssl_context = ssl._create_unverified_context() if args.insecure else None

    payload: Dict[str, Any] = {"vnc": True, "headless": False}
    if args.worker:
        payload["worker"] = args.worker

    session = _api_request(
        args.api_base,
        "/sessions",
        method="POST",
        payload=payload,
        context=ssl_context,
        timeout=args.request_timeout,
    )
    worker = session["worker"]
    session_id = session["id"]

    print(f"Created session {worker}/{session_id}")

    vnc_http: Optional[str] = session.get("vnc", {}).get("http")
    deadline = time.monotonic() + args.timeout
    while not vnc_http and time.monotonic() < deadline:
        time.sleep(args.poll_interval)
        descriptor = _api_request(
            args.api_base,
            f"/sessions/{urllib.parse.quote(worker)}/{urllib.parse.quote(session_id)}",
            method="GET",
            context=ssl_context,
            timeout=args.request_timeout,
        )
        vnc_http = descriptor.get("vnc", {}).get("http")

    if not vnc_http:
        if not args.keep_session:
            _delete_session(
                args.api_base,
                worker,
                session_id,
                context=ssl_context,
                timeout=args.request_timeout,
            )
        raise SystemExit("Timed out waiting for the session to expose a VNC URL")

    print(f"Checking VNC viewer page: {vnc_http}")
    status_code = _fetch_vnc_page(vnc_http, context=ssl_context, timeout=args.request_timeout)
    if status_code != 200:
        if not args.keep_session:
            _delete_session(
                args.api_base,
                worker,
                session_id,
                context=ssl_context,
                timeout=args.request_timeout,
            )
        raise SystemExit(f"Expected HTTP 200 from VNC page, received {status_code}")

    print("VNC viewer page returned HTTP 200")

    if not args.keep_session:
        _delete_session(
            args.api_base,
            worker,
            session_id,
            context=ssl_context,
            timeout=args.request_timeout,
        )
        print("Session deleted")


if __name__ == "__main__":
    main()
