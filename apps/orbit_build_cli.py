"""Minimal build management CLI for ORBIT materialized builds."""

from __future__ import annotations

import argparse
import json
import shlex

from orbit.runtime.governance.build_state_store import BuildStateStore


def main() -> None:
    parser = argparse.ArgumentParser(description="ORBIT build management CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-candidate", help="Create a candidate build record")
    create.add_argument("--mode", choices=["dev", "evo"], default="dev")

    materialize = sub.add_parser("materialize-candidate", help="Create a materialized candidate build")
    materialize.add_argument("--mode", choices=["dev", "evo"], default="dev")

    sub.add_parser("promote-candidate", help="Promote current candidate build to active")
    sub.add_parser("print-active-launch", help="Print the launch command for the active build")

    args = parser.parse_args()
    store = BuildStateStore()

    if args.command == "create-candidate":
        manifest = store.create_candidate_build_record(runtime_mode=args.mode)
        print(manifest.model_dump_json(indent=2))
        return

    if args.command == "materialize-candidate":
        manifest = store.materialize_candidate_build(runtime_mode=args.mode)
        print(manifest.model_dump_json(indent=2))
        return

    if args.command == "promote-candidate":
        pointer = store.promote_candidate_to_active()
        print(pointer.model_dump_json(indent=2))
        return

    if args.command == "print-active-launch":
        command = store.active_launch_command()
        print(" ".join(shlex.quote(part) for part in command))
        return

    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
