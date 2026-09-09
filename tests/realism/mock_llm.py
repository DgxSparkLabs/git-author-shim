#!/usr/bin/env python3
"""Zero-credential mock LLM endpoint for the auth-free realism gate.

This speaks just enough of two provider wire formats to make a *real*
coding-agent binary (``claude``, ``omp``) perform exactly one ``Bash`` tool
call -- a ``git commit`` -- and then stop:

* Anthropic Messages  -- ``POST {ANTHROPIC_BASE_URL}/v1/messages``  (primary;
  what ``claude`` and ``omp --model <anthropic>`` speak)
* OpenAI Chat Completions -- ``POST {OPENAI_BASE_URL}/chat/completions``
  (secondary; for an OpenAI-completions ``omp`` provider)

No credential is ever validated: any ``x-api-key`` / ``Authorization`` header,
or none, is accepted and the server never returns 401/400. Nothing leaves the
loopback interface. So the harness under test needs no auth, no quota and no
network -- yet it still launches ``git`` through its own real tool runtime,
which is the whole point of the realism gate.

Protocol, deterministic two turns:

* Turn 1 -- the request carries no prior tool result, so the reply is a single
  tool call (``tool_use`` / ``tool_calls``) whose input is
  ``{"command": "<the canned git command>"}``. The harness runs it; PATH's
  ``git`` is the shim, which stamps the bot identity.
* Turn 2 -- the request now carries the ``tool_result`` (Anthropic) or a
  ``role: "tool"`` message (OpenAI), so the reply is a plain ``end_turn`` /
  ``stop``. Emitting a second tool call would trip ``--max-turns 2``.

Streaming is the default (the CLIs send ``"stream": true`` and a custom base
URL enables a byte-level idle watchdog), so every SSE event is flushed the
instant it is written; a ``"stream": false`` body gets the equivalent JSON.

The canned command comes from ``$MOCK_TOOL_COMMAND`` (or ``--command``); the
default is a harmless empty commit. Run standalone for debugging::

    python tests/realism/mock_llm.py --port 8765 --command 'git commit --allow-empty -m hi'

Sources for the wire shapes (verified against official docs):
* Anthropic streaming + tool_use:
  https://platform.claude.com/docs/en/build-with-claude/streaming
* Anthropic tool_use JSON:
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls
* OpenAI function calling / streaming:
  https://developers.openai.com/api/docs/guides/function-calling
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_DEFAULT_COMMAND = 'git commit --allow-empty -m "realism-gate empty commit"'
_DEFAULT_MODEL = "claude-sonnet-4-6"


def _tool_command(server: MockServer) -> str:
    # $MOCK_TOOL_COMMAND wins so an in-thread server and a subprocess server can
    # both be steered by the launching test without reconstructing the object.
    return os.environ.get("MOCK_TOOL_COMMAND") or server.tool_command


def _find_tool_name(body: dict[str, Any], default: str) -> str:
    """Echo the exact tool-name casing the client advertised.

    ``claude`` advertises ``Bash`` (capital B); ``omp`` advertises ``bash``.
    Replying with the wrong casing yields a no-op tool call, so mirror whatever
    the request's ``tools[]`` calls the shell tool.
    """
    for tool in body.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        # Anthropic: {"name": ...}. OpenAI: {"type":"function","function":{"name":...}}.
        name = tool.get("name")
        if not name and isinstance(tool.get("function"), dict):
            name = tool["function"].get("name")
        if isinstance(name, str) and name.lower() == "bash":
            return name
    return default


def _anthropic_has_tool_result(body: dict[str, Any]) -> bool:
    for message in body.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    return True
    return False


def _openai_has_tool_result(body: dict[str, Any]) -> bool:
    return any(
        isinstance(m, dict) and m.get("role") == "tool" for m in body.get("messages") or []
    )


# --------------------------------------------------------------------------------------
# Anthropic Messages payloads
# --------------------------------------------------------------------------------------

def _anthropic_tool_use_events(model: str, tool_name: str, command: str) -> list[tuple[str, dict]]:
    tool_input = json.dumps({"command": command})
    return [
        ("message_start", {
            "type": "message_start",
            "message": {
                "id": "msg_mock_1", "type": "message", "role": "assistant",
                "content": [], "model": model, "stop_reason": None,
                "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        }),
        ("content_block_start", {
            "type": "content_block_start", "index": 0,
            "content_block": {
                "type": "tool_use", "id": "toolu_bash_1", "name": tool_name, "input": {},
            },
        }),
        ("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": tool_input},
        }),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 16},
        }),
        ("message_stop", {"type": "message_stop"}),
    ]


def _anthropic_stop_events(model: str) -> list[tuple[str, dict]]:
    return [
        ("message_start", {
            "type": "message_start",
            "message": {
                "id": "msg_mock_2", "type": "message", "role": "assistant",
                "content": [], "model": model, "stop_reason": None,
                "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        }),
        ("content_block_start", {
            "type": "content_block_start", "index": 0,
            "content_block": {"type": "text", "text": ""},
        }),
        ("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": "done"},
        }),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 1},
        }),
        ("message_stop", {"type": "message_stop"}),
    ]


def _anthropic_tool_use_json(model: str, tool_name: str, command: str) -> dict:
    return {
        "id": "msg_mock_1", "type": "message", "role": "assistant", "model": model,
        "content": [{
            "type": "tool_use", "id": "toolu_bash_1", "name": tool_name,
            "input": {"command": command},
        }],
        "stop_reason": "tool_use", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 16},
    }


def _anthropic_stop_json(model: str) -> dict:
    return {
        "id": "msg_mock_2", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "text", "text": "done"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


# --------------------------------------------------------------------------------------
# OpenAI Chat Completions payloads
# --------------------------------------------------------------------------------------

def _openai_tool_call_chunks(model: str, tool_name: str, command: str) -> list[dict]:
    args = json.dumps({"command": command})
    return [
        {"id": "chatcmpl-mock-1", "object": "chat.completion.chunk", "created": 0, "model": model,
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": None, "tool_calls": [
             {"index": 0, "id": "call_git1", "type": "function",
              "function": {"name": tool_name, "arguments": ""}}]}, "finish_reason": None}]},
        {"id": "chatcmpl-mock-1", "object": "chat.completion.chunk", "created": 0, "model": model,
         "choices": [{"index": 0, "delta": {"tool_calls": [
             {"index": 0, "function": {"arguments": args}}]}, "finish_reason": None}]},
        {"id": "chatcmpl-mock-1", "object": "chat.completion.chunk", "created": 0, "model": model,
         "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
    ]


def _openai_stop_chunks(model: str) -> list[dict]:
    return [
        {"id": "chatcmpl-mock-2", "object": "chat.completion.chunk", "created": 0, "model": model,
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": "done"},
                      "finish_reason": None}]},
        {"id": "chatcmpl-mock-2", "object": "chat.completion.chunk", "created": 0, "model": model,
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]


def _openai_tool_call_json(model: str, tool_name: str, command: str) -> dict:
    return {
        "id": "chatcmpl-mock-1", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_git1", "type": "function",
             "function": {"name": tool_name, "arguments": json.dumps({"command": command})}}]},
            "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 16, "total_tokens": 17},
    }


def _openai_stop_json(model: str) -> dict:
    return {
        "id": "chatcmpl-mock-2", "object": "chat.completion", "created": 0, "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "done"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class _Handler(BaseHTTPRequestHandler):
    # HTTP/1.0 so the response ends at connection close: SSE readers consume until
    # EOF and we never have to compute a Content-Length for a streamed body.
    protocol_version = "HTTP/1.0"
    server: MockServer

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - stdlib signature
        if self.server.verbose:
            sys.stderr.write("[mock_llm] " + (fmt % args) + "\n")
            sys.stderr.flush()

    def _note(self, msg: str) -> None:
        sys.stderr.write(f"[mock_llm] {msg}\n")
        sys.stderr.flush()

    # -- generic replies ---------------------------------------------------------------
    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def _send_empty(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def _send_anthropic_sse(self, events: list[tuple[str, dict]]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for name, data in events:
            chunk = f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()
            self.wfile.write(chunk)
            self.wfile.flush()

    def _send_openai_sse(self, chunks: list[dict]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for chunk in chunks:
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    # -- routing ------------------------------------------------------------------------
    def do_HEAD(self) -> None:  # noqa: N802 - stdlib signature
        self._send_empty(200)

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        path = self.path.split("?", 1)[0]
        if path == "/v1/models":
            self._send_json({"object": "list", "data": []})
            return
        self._send_empty(200)

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        path = self.path.split("?", 1)[0]
        body = self._read_body()
        model = body.get("model") or _DEFAULT_MODEL
        stream = bool(body.get("stream"))
        command = _tool_command(self.server)

        if path.startswith("/v1/messages"):
            if path.endswith("/count_tokens"):
                self._send_json({"input_tokens": 1})
                return
            if _anthropic_has_tool_result(body):
                self._note(f"anthropic stop turn (stream={stream})")
                if stream:
                    self._send_anthropic_sse(_anthropic_stop_events(model))
                else:
                    self._send_json(_anthropic_stop_json(model))
                return
            tool_name = _find_tool_name(body, "Bash")
            self._note(f"anthropic tool_use name={tool_name!r} stream={stream} cmd={command!r}")
            if stream:
                self._send_anthropic_sse(_anthropic_tool_use_events(model, tool_name, command))
            else:
                self._send_json(_anthropic_tool_use_json(model, tool_name, command))
            return

        if path.endswith("/chat/completions"):
            if _openai_has_tool_result(body):
                self._note(f"openai stop turn (stream={stream})")
                if stream:
                    self._send_openai_sse(_openai_stop_chunks(model))
                else:
                    self._send_json(_openai_stop_json(model))
                return
            tool_name = _find_tool_name(body, "bash")
            self._note(f"openai tool_call turn name={tool_name!r} stream={stream} cmd={command!r}")
            if stream:
                self._send_openai_sse(_openai_tool_call_chunks(model, tool_name, command))
            else:
                self._send_json(_openai_tool_call_json(model, tool_name, command))
            return

        # Unknown path: never fail the client -- an empty 200 keeps warmups happy.
        self._send_empty(200)


class MockServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, host: str, port: int, command: str, verbose: bool = False) -> None:
        super().__init__((host, port), _Handler)
        self.tool_command = command
        self.verbose = verbose


def serve_in_thread(host: str = "127.0.0.1", port: int = 0, command: str = _DEFAULT_COMMAND,
                    verbose: bool = False) -> tuple[MockServer, threading.Thread]:
    """Start the mock on a background daemon thread; return ``(server, thread)``.

    ``port=0`` binds a free port; read it from ``server.server_address[1]``.
    """
    server = MockServer(host, port, command, verbose=verbose)
    thread = threading.Thread(target=server.serve_forever, name="mock-llm", daemon=True)
    thread.start()
    return server, thread


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--command", default=os.environ.get("MOCK_TOOL_COMMAND", _DEFAULT_COMMAND))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    server = MockServer(args.host, args.port, args.command, verbose=args.verbose)
    host, port = server.server_address[0], server.server_address[1]
    sys.stderr.write(f"[mock_llm] listening on http://{host}:{port} command={args.command!r}\n")
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
