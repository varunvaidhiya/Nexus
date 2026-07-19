"""nexus-agent CLI.

nexus-agent sync            # one pass, exit
nexus-agent run             # sync every interval_seconds
nexus-agent handoff --repo ~/code/webapp --task <uuid>   # write NEXUS_BRIEF.md
nexus-agent --config x.toml sync
"""

import argparse
import logging
import sys
from pathlib import Path

from nexus_agent import handoff as handoff_module
from nexus_agent import runner
from nexus_agent.config import load_config
from nexus_agent.state import SyncState


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nexus-agent",
        description="Nexus companion agent — read-only local-log watcher.",
    )
    parser.add_argument("--config", type=Path, default=None, help="path to nexus-agent.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync", help="one sync pass, then exit")
    sub.add_parser("run", help="sync continuously")
    handoff_parser = sub.add_parser(
        "handoff", help="write a NEXUS_BRIEF.md primer into a repo (requires [handoff] enabled)"
    )
    handoff_parser.add_argument("--repo", type=Path, required=True, help="repo to write into")
    handoff_parser.add_argument("--target", default="claude_code")
    handoff_parser.add_argument("--task", default=None, help="task UUID")
    handoff_parser.add_argument("--conversation", default=None, help="conversation UUID")
    handoff_parser.add_argument("--instructions", default=None)
    handoff_parser.add_argument(
        "--launch", action="store_true", help="launch the target tool in the repo after writing"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as exc:
        print(f"nexus-agent: {exc}", file=sys.stderr)
        return 2

    if args.command == "sync":
        state = SyncState(config.state_path)
        state.load()
        with runner.make_client(config) as client:
            pushed = runner.sync_once(config, client, state)
        print(f"synced {pushed} conversation(s)")
        return 0

    if args.command == "handoff":
        try:
            with runner.make_client(config) as client:
                brief = handoff_module.fetch_brief(
                    client,
                    target=args.target,
                    task_id=args.task,
                    conversation_id=args.conversation,
                    instructions=args.instructions,
                )
            path = handoff_module.write_primer(config, args.repo, brief)
        except handoff_module.HandoffError as exc:
            print(f"nexus-agent: {exc}", file=sys.stderr)
            return 2
        print(f"wrote {path}")
        if args.launch:
            try:
                return handoff_module.launch(args.target, path.parent)
            except handoff_module.HandoffError as exc:
                print(f"nexus-agent: {exc}", file=sys.stderr)
                return 2
        command = handoff_module.launch_command(args.target)
        if command:
            print("to continue there:", " ".join(command))
        return 0

    runner.run_forever(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
