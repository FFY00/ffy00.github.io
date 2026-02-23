#!/usr/bin/env python3

# /// script
# dependencies = [
#   "mako",
# ]
# ///

import argparse
import datetime
import pathlib
import sys

from typing import Sequence

import mako.lookup


class ScriptError(SystemExit):
    def __init__(self, msg: str, code: int = 1) -> None:
        super().__init__(code)
        self.msg = msg


def main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'date',
        type=str,
        nargs='?',
        help='development log entry date',
    )
    return parser


def main(cli_args: Sequence[str]) -> None:
    parser = main_parser()
    args = parser.parse_args(cli_args)

    if args.date:
        date = datetime.date.fromisoformat(args.date)
    else:
        date = datetime.date.today()
    calendar = date.isocalendar()

    entry_name = f'{calendar.year:04}-W{calendar.week:02}'

    root = pathlib.Path(__file__).parent
    devlog = root / 'content' / 'devlog'
    devlog.mkdir(parents=True, exist_ok=True)

    entry_path = devlog / f'{entry_name}.rst'
    if entry_path.exists():
        raise ScriptError(f'Development log entry {entry_path.name!r} already exists')

    templates = mako.lookup.TemplateLookup(directories=[root / 'templates'])
    article_data = templates.get_template('new-devlog-entry.rst').render(
        date=datetime.datetime.now().isoformat(),
        entry_name=entry_name,
    )
    entry_path.write_text(article_data)
    print(f'Created {entry_path.name}...')


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except ScriptError as e:
        print(e.msg, file=sys.stderr)
        raise
