#!/usr/bin/env python3
"""A scripted OpenAI-compatible endpoint, for testing a plugin's tools without a model.

Why this exists. A plugin's tools only earn their keep when the agent can actually
call them, and checking that normally costs an API key, credits and a nondeterministic
model. This server speaks just enough of the Chat Completions API for DeepSeek Harness
to talk to it, and answers with a tool call you choose. The harness does the rest: it
validates the arguments, runs the real tool, applies the real permission policy, and
records a real turn.

It also prints the tool schemas the harness sent, which is the fastest way to see
whether your plugin's tools actually reached the model's catalogue.

    python3 scripts/mock-provider.py --call 'brain_capture({"title":"Mock note","content":"Written by the mock provider","tags":"demo"})'

Then in DSH, add a custom provider:

    Provider ID   mock
    Base URL      http://127.0.0.1:4111/v1
    Protocol      openai-completions
    API key       anything
    Model         mock-model

Send any message in a session: the harness will call the tool you scripted, feed the
result back, and this server will answer with a short summary of what happened.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CALL_RE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*\((.*)\)\s*$", re.S)


def parse_call(text: str) -> tuple[str, str]:
    """`name({"a":1})` -> ("name", '{"a":1}'). Arguments stay a JSON *string*: that is what the wire carries."""
    match = CALL_RE.match(text)
    if not match:
        raise SystemExit(f"--call must look like tool_name({{...}}), got: {text!r}")
    name, raw = match.group(1), match.group(2).strip() or "{}"
    json.loads(raw)  # fail here, not three layers deep inside the harness
    return name, raw


class Handler(BaseHTTPRequestHandler):
    tool_call: tuple[str, str] = ("", "{}")
    verbose: bool = True
    turn: int = 0

    def log_message(self, *_args):  # the default logger writes a line per request to stderr
        pass

    # ── plumbing ────────────────────────────────────────────────────────────
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
        # Model discovery: DSH offers a "fetch available models" button.
        if self.path.rstrip("/").endswith("/models"):
            body = json.dumps({"object": "list", "data": [{"id": "mock-model", "object": "model"}]}).encode()
            self._send(200, body, "application/json")
        else:
            self._send(404, b"{}", "application/json")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        request = json.loads(self.rfile.read(length) or b"{}")
        Handler.turn += 1
        self._report(request)

        # The harness sends the whole transcript every time, so "has a tool message"
        # is not the question — earlier turns have those too. What matters is whether
        # the LAST message is the result of the call we just asked for: if it is, the
        # turn is finished and we answer in prose; otherwise we ask for the call.
        messages = request.get("messages", [])
        last = messages[-1] if messages else {}
        if last.get("role") == "tool":
            content = f"Done. The harness ran `{self.tool_call[0]}` and it returned:\n\n{str(last.get('content'))[:800]}"
            message = {"role": "assistant", "content": content}
        else:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": f"call_mock_{Handler.turn}",
                    "type": "function",
                    "function": {"name": self.tool_call[0], "arguments": self.tool_call[1]},
                }],
            }

        if request.get("stream"):
            self._stream(message)
        else:
            self._send(200, json.dumps(self._completion(message)).encode(), "application/json")

    # ── responses ───────────────────────────────────────────────────────────
    def _completion(self, message: dict) -> dict:
        return {
            "id": f"chatcmpl-mock-{Handler.turn}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "mock-model",
            "choices": [{
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    def _stream(self, message: dict) -> None:
        """Server-sent events, the shape every OpenAI-compatible client expects."""
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()

        def chunk(delta: dict, finish: str | None = None) -> None:
            payload = {
                "id": f"chatcmpl-mock-{Handler.turn}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "mock-model",
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
            self.wfile.flush()

        chunk({"role": "assistant"})
        if message.get("tool_calls"):
            call = message["tool_calls"][0]
            # Tool-call deltas carry an index; arguments may arrive in pieces, so send
            # them in two to exercise the client's accumulation path.
            args = call["function"]["arguments"]
            half = len(args) // 2
            chunk({"tool_calls": [{"index": 0, "id": call["id"], "type": "function",
                                   "function": {"name": call["function"]["name"], "arguments": args[:half]}}]})
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": args[half:]}}]})
            chunk({}, "tool_calls")
        else:
            for piece in (message["content"] or "").splitlines(keepends=True):
                chunk({"content": piece})
            chunk({}, "stop")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    # ── what the harness actually sent ──────────────────────────────────────
    def _report(self, request: dict) -> None:
        if not self.verbose:
            return
        tools = [t.get("function", {}).get("name") for t in request.get("tools") or []]
        print(f"\n--- request {Handler.turn}: model={request.get('model')} "
              f"stream={bool(request.get('stream'))} messages={len(request.get('messages', []))}")
        print(f"    tools offered ({len(tools)}): {', '.join(sorted(n for n in tools if n)) or 'none'}")
        for name in tools:
            if name and name.startswith("brain_"):
                schema = next(t for t in request["tools"] if t.get("function", {}).get("name") == name)
                params = list((schema["function"].get("parameters") or {}).get("properties", {}))
                print(f"      * {name}({', '.join(params)})")
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--call", required=True, help='tool call to script, e.g. \'brain_search({"query":"pytorch"})\'')
    parser.add_argument("--port", type=int, default=4111)
    parser.add_argument("--quiet", action="store_true", help="do not print the tool catalogue the harness sends")
    args = parser.parse_args()

    Handler.tool_call = parse_call(args.call)
    Handler.verbose = not args.quiet
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"mock provider on http://127.0.0.1:{args.port}/v1  (model: mock-model)")
    print(f"scripted call: {Handler.tool_call[0]}({Handler.tool_call[1]})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
