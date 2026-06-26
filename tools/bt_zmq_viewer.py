#!/usr/bin/env python3
"""Live viewer for the BTEng ZmqPublisher tick stream.

The turtle_controller embeds a BTEng ``ZmqPublisher`` that streams JSON tick
events over a ZMQ ``PUB`` socket (topic ``bteng``) on ``tcp://*:2667``. With the
container running in host-network mode the port is reachable straight from the
host, so just run this script while the demo is up:

    python3 tools/bt_zmq_viewer.py

This is the runnable equivalent of the copy-paste subscriber in docs/USAGE.md.
It needs only pyzmq on the host:  pip install pyzmq

There is no Groot2 here — Groot2 speaks BehaviorTree.CPP's wire protocol, which
is incompatible with BTEng's event stream.
"""

from __future__ import annotations

import argparse
import json
import sys

try:
    import zmq
except ImportError:
    sys.exit(
        "pyzmq is not installed. Install it with:  pip install pyzmq\n"
        "(The demo still runs without it; the controller just logs a warning.)"
    )

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 2667
TOPIC = b"bteng"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watch the BTEng tick/status event stream live.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Host where the ZmqPublisher is reachable.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="TCP port of the ZmqPublisher stream.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print each event as raw JSON instead of a formatted line.",
    )
    return parser.parse_args(argv)


def format_event(evt: dict) -> str:
    return (
        f"{evt.get('name', ''):<20} "
        f"{evt.get('status', ''):<8} "
        f"{evt.get('dur_ms', 0.0):>6.2f} ms "
        f"{evt.get('reason', '')}"
    ).rstrip()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    endpoint = f"tcp://{args.host}:{args.port}"

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.SUB)
    sock.connect(endpoint)
    sock.setsockopt(zmq.SUBSCRIBE, TOPIC)  # topic prefix

    print(f"Listening for BTEng tick events on {endpoint} … (Ctrl-C to quit)")
    try:
        while True:
            raw = sock.recv()
            _topic, _, payload = raw.partition(b" ")  # "bteng <json>"
            if args.raw:
                print(payload.decode("utf-8", "replace"))
                continue
            try:
                evt = json.loads(payload)
            except json.JSONDecodeError:
                print(f"<unparseable> {payload!r}")
                continue
            print(format_event(evt))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sock.close(linger=0)
        ctx.term()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
