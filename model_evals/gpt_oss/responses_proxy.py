#!/usr/bin/env python3
"""Small logging compatibility proxy for Codex-to-vLLM Responses requests."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from collections import Counter
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-port", type=int, default=8001)
    parser.add_argument("--upstream", default="http://127.0.0.1:8000")
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:
            return

        def _proxy(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else None
            if body and self.path.endswith("/responses"):
                payload = json.loads(body)
                original_tools = payload.get("tools", [])

                # Codex exposes connected-app and native web-search tools as
                # Responses API extensions.  vLLM 0.19 rejects those tool
                # types.  They are not required for this local harness: the
                # ordinary command tools provide shell, Python/SymPy, and
                # network-command access.
                payload["tools"] = [
                    tool for tool in original_tools
                    if tool.get("type") == "function"
                ]
                # Match the generation budget recorded by the benchmark run
                # manifests.  Codex omits this field for fallback model
                # metadata, otherwise allowing vLLM to use the entire context
                # window for one turn.
                payload.setdefault("max_output_tokens", 32768)
                body = json.dumps(payload, separators=(",", ":")).encode()
                with args.log.open("a") as handle:
                    handle.write(json.dumps({
                        "time": datetime.now(timezone.utc).isoformat(),
                        "path": self.path,
                        "input_types": dict(Counter(
                            item.get("type", "unknown")
                            for item in payload.get("input", [])
                            if isinstance(item, dict)
                        )),
                        "tool_types_before": dict(Counter(
                            tool.get("type", "unknown")
                            for tool in original_tools
                        )),
                        "tool_types_forwarded": dict(Counter(
                            tool.get("type", "unknown")
                            for tool in payload.get("tools", [])
                        )),
                        "max_output_tokens": payload["max_output_tokens"],
                    }) + "\n")
            headers = {key: value for key, value in self.headers.items()
                       if key.lower() not in {"host", "content-length", "connection"}}
            request = urllib.request.Request(args.upstream.rstrip("/") + self.path,
                                             data=body, headers=headers, method=self.command)
            try:
                response = urllib.request.urlopen(request, timeout=3700)
            except urllib.error.HTTPError as error:
                response = error
            self.send_response(response.status)
            for key, value in response.headers.items():
                if key.lower() not in {"connection", "transfer-encoding", "content-length"}:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            while chunk := response.read(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
            self.close_connection = True

        do_GET = _proxy
        do_POST = _proxy

    class Server(ThreadingHTTPServer):
        request_queue_size = 512

    Server(("127.0.0.1", args.listen_port), Handler).serve_forever()


if __name__ == "__main__":
    main()
