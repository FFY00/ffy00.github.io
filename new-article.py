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
        super().__init__(code=code)
        self.msg = msg


def main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'id',
        type=str,
        help='article id',
    )
    parser.add_argument(
        'title',
        type=str,
        help='article title',
    )
    parser.add_argument(
        '--draft',
        action='store_true',
        help='create article as draft',
    )
    return parser


def find_next_id_number(path: pathlib.Path) -> str:
    files = sorted(path.iterdir())
    return '{:02}'.format(int(files[-1].name.split('-')[0]) + 1)


def main(cli_args: Sequence[str]) -> None:
    parser = main_parser()
    args = parser.parse_args(cli_args)

    root = pathlib.Path(__file__).parent
    blog = root / 'content' / 'blog-draft' if args.draft else 'blog'
    blog.mkdir(parents=True, exist_ok=True)

    name = args.id
    if not args.draft:
        name = f'{find_next_id_number(blog)}-{name}'
    article_path = blog / f'{name}.rst'
    if article_path.exists():
        raise ScriptError(f'blog article path already exists: {article_path}')

    templates = mako.lookup.TemplateLookup(directories=[root / 'templates'])
    article_data = templates.get_template('new-blog-article.rst').render(
        title=args.title,
        date=datetime.datetime.now().isoformat(),
    )
    article_path.write_text(article_data)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except ScriptError as e:
        print(e.msg, file=sys.stderr)
        raise
