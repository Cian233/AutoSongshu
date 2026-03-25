from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from .agent import PentestCoordinator
from .config import load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autosongshu-agent",
        description="Authorized web pentest agent powered by AgentScope and CDP.",
    )
    parser.add_argument("--config", required=True, help="Path to the YAML config file.")
    parser.add_argument("--goal", required=True, help="Assessment goal for the agent.")
    parser.add_argument(
        "--start-url",
        help="Override engagement.start_url from the config file.",
    )
    parser.add_argument(
        "--skill-dir",
        action="append",
        default=[],
        help="Additional skill directory to register. Can be provided multiple times.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console()

    config = load_config(args.config)
    if args.start_url:
        config.engagement.start_url = args.start_url
    if args.skill_dir:
        config.skills.directories.extend(str(Path(item).resolve()) for item in args.skill_dir)

    coordinator = PentestCoordinator(config)
    result = coordinator.run(args.goal)

    console.print("[bold green]Agent finished[/bold green]")
    console.print(f"Artifacts: {result.artifact_dir}")
    console.print(result.final_message)
    return 0
