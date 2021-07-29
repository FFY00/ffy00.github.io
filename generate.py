#!/usr/bin/env python3
import argparse
import logging
import pathlib
import shutil
import sys
import xml.etree.ElementTree as ET

from typing import Any, Dict, NamedTuple, Optional, Sequence

import docutils.core
import mako.exceptions
import mako.lookup
import minify_html
import rst2html5


def main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'outdir',
        type=str,
        nargs='?',
        default='html',
        help='output directory',
    )
    parser.add_argument(
        '--url',
        '-u',
        type=str,
        default='https://ffy00.github.io',
    )
    return parser


class Renderer:
    def __init__(
        self,
        templates: mako.lookup.TemplateLookup,
        outdir: pathlib.Path,
        content_root: pathlib.Path,
        base_render_args: Dict[str, Any] = {},
    ) -> None:
        self.__logger = logging.getLogger(str(self.__class__))
        self._templates = templates
        self._outdir = outdir
        self._content_root = content_root
        self._args = base_render_args.copy()
        self._args['meta'] = {}

    def _write(self, file: pathlib.Path, html: str) -> None:
        file.parent.mkdir(parents=True, exist_ok=True)
        self.__logger.info(f'writing to {file}...')
        file.write_text(html)

    @staticmethod
    def _extract_metadata(html: str) -> Dict[str, str]:
        xml = ET.fromstring(html)
        head = xml.findall('head')[0]
        return {
            meta.get('name'): meta.get('content')  # type: ignore
            for meta in head.findall('meta')
            if meta.get('name')
        }

    @staticmethod
    def _fix_html(html: str) -> str:
        """Fix rst2html5 generated HTML to use our styling."""
        return html

    @staticmethod
    def _rst_to_docutils(file: pathlib.Path) -> Dict[str, str]:
        return docutils.core.publish_parts(
            writer=rst2html5.HTML5Writer(),
            source=file.read_text(),
        )

    @classmethod
    def _render_args_from_rst(cls, file: pathlib.Path, args: Dict[str, Any]) -> None:
        """Convert rst to html and fill render arguments (body and metadata)."""
        doc = cls._rst_to_docutils(file)
        args['body'] = cls._fix_html(doc['body'])
        args['meta'] = cls._extract_metadata(doc['whole'])

    @classmethod
    def metadata(cls, file: pathlib.Path) -> Dict[str, str]:
        return cls._extract_metadata(cls._rst_to_docutils(file)['whole'])

    def render(
        self,
        template: str,
        content_file: Optional[pathlib.Path] = None,
        render_args: Dict[str, Any] = {},
        outfile: Optional[pathlib.Path] = None,
    ) -> None:
        args = self._args.copy()
        args.update(render_args)

        if content_file:
            self._render_args_from_rst(content_file, args)
            if not outfile:
                outfile = content_file.relative_to(self._content_root).with_suffix('.html')
        if not outfile:
            raise ValueError('Neither `content_file` not `outfile` were supplied')
        outfile = self._outdir.joinpath(outfile)

        try:
            html = self._templates.get_template(template).render(**args)
        except Exception as e:
            html = mako.exceptions.html_error_template().render().decode()
            raise e
        finally:
            self._write(outfile, minify_html.minify(html))


class Page(NamedTuple):
    id: str
    title: str
    summary: Optional[str]


def list_pages(path: pathlib.Path) -> Sequence[Page]:
    files = list(path.iterdir())
    actual = [
        Page(file.stem, meta['title'], meta.get('summary'))
        for file, meta in zip(files, map(Renderer.metadata, files))
    ]
    return actual


def main(cli_args: Sequence[str]) -> None:
    parser = main_parser()
    args = parser.parse_args(cli_args)

    root = pathlib.Path(__file__).parent
    content = root / 'content'
    outdir = pathlib.Path(args.outdir)
    static = outdir / 'static'
    static.mkdir(parents=True, exist_ok=True)

    templates = mako.lookup.TemplateLookup(directories=[root / 'templates'])
    renderer = Renderer(templates, outdir, content, {
        'url': args.url,
    })

    # render
    renderer.render('index.html', content / 'index.rst')
    renderer.render(
        'blog-index.html',
        outfile=pathlib.Path('blog', 'index.html'),
        render_args={
            'posts': list_pages(content / 'blog'),
        },
    )
    for file in content.joinpath('blog').iterdir():
        renderer.render(
            'blog-post.html',
            file,
            outfile=pathlib.Path('blog', file.stem, 'index.html'),
        )

    # copy static files
    shutil.copytree(root / 'images', static / 'img', dirs_exist_ok=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main(sys.argv[1:])
