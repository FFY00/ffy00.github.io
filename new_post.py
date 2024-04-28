#!/usr/bin/env python3
import argparse
import datetime
import pathlib
import sys

from typing import Sequence

import mako.lookup


class ScriptError(SystemExit):
    def __init__(self, msg: str, code: int = 1) -> None:
        super().__init__(code=code)
        self.msg = msg


def main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'id',
        type=str,
        help='post id',
    )
    parser.add_argument(
        'title',
        type=str,
        help='post title',
    )
    return parser


def find_next_id_number(path: pathlib.Path) -> str:
    files = sorted(path.iterdir())
    return '{:02}'.format(int(files[-1].name.split('-')[0]) + 1)


def main(cli_args: Sequence[str]) -> None:
    parser = main_parser()
    args = parser.parse_args(cli_args)

    root = pathlib.Path(__file__).parent
    blog = root / 'content' / 'blog'

    templates = mako.lookup.TemplateLookup(directories=[root / 'templates'])

    rst = templates.get_template('new-blog-post.rst').render(
        title=args.title,
        date=datetime.datetime.now().isoformat(),
    )
    blog.joinpath(f'{find_next_id_number(blog)}-{args.id}.rst').write_text(rst)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except ScriptError as e:
        print(e.msg, file=sys.stderr)
        raise
