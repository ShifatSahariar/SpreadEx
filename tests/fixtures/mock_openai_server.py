"""A scripted OpenAI-compatible chat-completions server for offline tests of LLM generators.

Answers the two kinds of request Fuzz4All makes: autoprompt distillation (its system message names
an auto-prompting tool) gets a fixed summary; generation gets fenced MiniCalc expressions, drawn
deterministically from a list that mixes valid, invalid and crashing inputs. Every request is
recorded, including the Authorization header, so a test can check what reached the "provider".
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EXPRESSIONS = [
    "1 + 2 * 3", "(4 - 1) / 2", "7 % 0", "2 ** 3", "(1 + (2 * (3 - 4)))", "5 / 0",
    "3.5 * -2", "((1)", "9 % 4 + 1", "-(-(-8)) % 0", "12 / 4 / 3", "1 +",
]


class MockOpenAI:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self._i = 0
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                mock.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                      "body": body})
                if not self.path.endswith("/chat/completions"):
                    self.send_response(404)
                    self.end_headers()
                    return
                messages = body.get("messages") or []
                system = " ".join(m.get("content", "") for m in messages if m.get("role") == "system")
                n = int(body.get("n") or 1)
                if "auto-prompting" in system:
                    contents = ["MiniCalc evaluates arithmetic expressions with + - * / % and "
                                "parentheses over integers and decimals."] * n
                else:
                    contents = []
                    for _ in range(n):
                        contents.append("```\n" + EXPRESSIONS[mock._i % len(EXPRESSIONS)] + "\n```")
                        mock._i += 1
                payload = {
                    "id": "mock", "object": "chat.completion", "model": body.get("model"),
                    "choices": [{"index": i, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": c}}
                                for i, c in enumerate(contents)],
                    "usage": {"prompt_tokens": 10 * n, "completion_tokens": 5 * n,
                              "total_tokens": 15 * n},
                }
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
