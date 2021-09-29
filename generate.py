#!/usr/bin/env python3
import argparse
import datetime
import logging
import operator
import os.path
import pathlib
import shutil
import subprocess
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
    parser.add_argument(
        '--skip-minify',
        '-m',
        action='store_true',
    )
    return parser


class Page(NamedTuple):
    id: str
    title: str
    summary: Optional[str]
    date: datetime.datetime


class Renderer:
    def __init__(
        self,
        templates: mako.lookup.TemplateLookup,
        outdir: pathlib.Path,
        content_root: pathlib.Path,
        minify: bool = True,
        base_render_args: Dict[str, Any] = {},
    ) -> None:
        self.__logger = logging.getLogger(str(self.__class__))
        self._templates = templates
        self._outdir = outdir
        self._content_root = content_root
        self._minify = minify
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

    @classmethod
    def _fix_node(cls, node: ET.Element) -> None:
        # sections
        for section in node.findall('section'):
            section.attrib['class'] = 'content'
            for h1 in section.findall('h1'):
                h1.attrib['class'] = 'title'
            cls._fix_node(section)
        # lists
        for dl in node.findall('dl'):
            dl.attrib['class'] = 'box has-background-success-light'
        # admonitions
        for aside in node.findall('aside'):
            if aside.attrib['class'] == 'admonition caution':
                aside.tag = 'div'
                aside.attrib['class'] = 'message is-warning'
                header = ET.SubElement(aside, 'div', {'class': 'message-header'})
                body = ET.SubElement(aside, 'div', {'class': 'message-body'})
                for h1 in aside.findall('h1'):
                    aside.remove(h1)
                    header.append(h1)
                    h1.tag = 'p'
                for p in aside.findall('p'):
                    aside.remove(p)
                    body.append(p)

    @classmethod
    def _fix_html(cls, html: str) -> str:
        """Fix rst2html5 generated HTML to use our styling."""
        xml = ET.fromstring('<body>' + html + '</body>')  # add some root node because ET needs one
        cls._fix_node(xml)
        new_html = ET.tostring(xml).decode()
        new_html = new_html.removeprefix('<body>').removesuffix('</body>')  # remove the root node we added
        return new_html

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
        meta = cls._extract_metadata(doc['whole'])
        args['meta'] = meta
        args['body'] = cls._fix_html(doc['body'])
        mtime = datetime.datetime.fromtimestamp(file.stat().st_mtime)
        args['mtime'] = mtime.isoformat()
        try:
            args['page'] = cls.page(file, meta)
        except KeyError:
            args['page'] = None

    @classmethod
    def metadata(cls, file: pathlib.Path) -> Dict[str, str]:
        return cls._extract_metadata(cls._rst_to_docutils(file)['whole'])

    @classmethod
    def page(
        cls,
        file: pathlib.Path,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Page:
        meta = metadata or cls.metadata(file)
        return Page(
            file.stem,
            meta['title'],
            meta.get('summary'),
            datetime.datetime.fromisoformat(meta['date']),
        )

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
        root = pathlib.Path(os.path.relpath(self._outdir, outfile.parent))
        static = root / 'static'
        args['root'] = root
        args['css'] = static / 'css'
        args['img'] = static / 'img'
        args['js'] = static / 'js'

        try:
            html = self._templates.get_template(template).render(**args)
        except Exception as e:
            html = mako.exceptions.html_error_template().render().decode()
            raise e
        finally:
            self._write(outfile, minify_html.minify(html) if self._minify else html)


def list_pages(path: pathlib.Path) -> Sequence[Page]:
    return sorted([
        Renderer.page(file) for file in path.iterdir()
    ], key=operator.attrgetter('id'))


def main(cli_args: Sequence[str]) -> None:
    parser = main_parser()
    args = parser.parse_args(cli_args)

    root = pathlib.Path(__file__).parent
    content = root / 'content'
    outdir = pathlib.Path(args.outdir)
    out_css = outdir / 'static' / 'css'

    out_css.mkdir(parents=True, exist_ok=True)

    templates = mako.lookup.TemplateLookup(directories=[root / 'templates'])
    renderer = Renderer(templates, outdir, content, not args.skip_minify, {
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

    # generate pygments theme
    pygments_css = subprocess.check_output([
        'pygmentize', '-S', 'default', '-f', 'html', '-a', 'pre'
    ])
    out_css.joinpath('pygments.css').write_bytes(pygments_css)

    # copy static files
    shutil.copytree(root / 'static', outdir / 'static', dirs_exist_ok=True)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main(sys.argv[1:])
