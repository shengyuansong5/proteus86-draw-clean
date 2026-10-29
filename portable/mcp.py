"""Portable startup: create only the explicitly scoped output, then run shared MCP."""
import argparse
from pathlib import Path

from proteus86.bridge_operations import Operations
from proteus86.bridge import main as bridge_main


def prepare_output(workspace, output):
    # Reuse the core's lexical, ancestor/reparse and containment checks before
    # making a missing startup directory. No model-provided shell is involved.
    with_scope = Operations(workspace, workspace)
    try:
        target = with_scope.path(output, write=True)
        target.mkdir(parents=True, exist_ok=True)
        return target
    finally:
        with_scope.close()


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    args, _ = parser.parse_known_args()
    if not args.output_root.exists():
        prepare_output(args.workspace, args.output_root)
    bridge_main()


if __name__ == '__main__':
    main()
