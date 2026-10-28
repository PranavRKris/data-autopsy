"""`autopsy serve`: run the service and the web UI."""
from __future__ import annotations

import argparse
import logging

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    from autopsy.service.app import create_app
    from autopsy.service.engine import Service

    parser = argparse.ArgumentParser(prog="autopsy serve", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-dir", help="where the service keeps its database, secrets, manifests and baselines")
    parser.add_argument("--no-scheduler", action="store_true", help="never run scheduled checks")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if args.host not in LOOPBACK:
        print("WARNING: this service has no authentication. Anyone who can reach it can add connections and read "
              "the data they expose. Bind it to 127.0.0.1 or put it behind your own access control.")
    service = Service(args.state_dir)
    print(f"Pipeline Autopsy on http://{args.host}:{args.port}  (state in {service.state_dir})")
    hosts = {"localhost", "127.0.0.1", "::1"} if args.host in LOOPBACK else None
    app = create_app(service, scheduler=not args.no_scheduler, allowed_hosts=hosts)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0
