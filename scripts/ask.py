"""Ask a question and print the streamed answer as it arrives.

    uv run python scripts/ask.py "How can the agreement be terminated?" --document-id 1

A minimal Server-Sent Events client: read the response line by line, pair
each `event:` line with the `data:` line after it, and react to the event type.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--document-id", type=int)
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()

    body: dict[str, object] = {"question": args.question}
    if args.document_id is not None:
        body["document_id"] = args.document_id
    request = urllib.request.Request(
        f"{args.url}/ask",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )

    event = None
    try:
        with urllib.request.urlopen(request) as response:
            for raw in response:  # iterating a response yields one line at a time, as it arrives
                line = raw.decode("utf-8").rstrip("\n")
                if line.startswith("event: "):
                    event = line.removeprefix("event: ")
                elif line.startswith("data: "):
                    show(event, json.loads(line.removeprefix("data: ")))
    except urllib.error.HTTPError as exc:
        # 404 / 422 arrive as normal JSON errors, before any streaming starts.
        sys.exit(f"[http {exc.code}] {exc.read().decode()}")


def show(event: str | None, data: dict) -> None:
    if event == "token":
        print(data["text"], end="", flush=True)
    elif event == "tool_call":
        print(f"[tool] {data['name']}({json.dumps(data['input'])})", file=sys.stderr)
    elif event == "tool_result" and data["is_error"]:
        print(f"[tool] {data['name']} returned an error", file=sys.stderr)
    elif event == "done":
        usage = data["usage"]
        print(
            f"\n\n[done] {data['stop_reason']} in {data['steps']} steps, {data['latency_ms']} ms, "
            f"{usage['input_tokens']} input / {usage['output_tokens']} output tokens",
            file=sys.stderr,
        )
    elif event == "error":
        print(f"\n[error] {data['code']}: {data['message']}", file=sys.stderr)


if __name__ == "__main__":
    main()
