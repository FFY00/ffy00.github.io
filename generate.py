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
import textwrap
import types
import xml.etree.ElementTree as ET

from collections.abc import Iterable
from typing import Any, NamedTuple, Sequence

import docutils.core
import mako.exceptions
import mako.lookup
import minify_html
import rich.logging
import rich.traceback
import rich_argparse
import rst2html5


def mako_rich_traceback(
    exception: BaseException,
    *,
    # rich.traceback.Traceback.from_exception kwargs
    width: int | None = 100,
    code_width: int | None = 88,
    extra_lines: int = 3,
    theme: str | None = None,
    word_wrap: bool = False,
    show_locals: bool = False,
    locals_max_length: int = rich.traceback.LOCALS_MAX_LENGTH,
    locals_max_string: int = rich.traceback.LOCALS_MAX_STRING,
    locals_hide_dunder: bool = True,
    locals_hide_sunder: bool = False,
    indent_guides: bool = True,
    suppress: Iterable[str | types.ModuleType] = (),
    max_frames: int = 100,
) -> rich.traceback.Traceback:
    """Make a rich traceback with mako template information."""

    if not exception:
        exception = sys.exception()

    rich_trace = rich.traceback.Traceback.extract(
        type(exception),
        exception,
        exception.__traceback__,
        # rich.traceback.Traceback.extract kwargs
        show_locals=show_locals,
        locals_max_length=locals_max_length,
        locals_max_string=locals_max_string,
        locals_hide_dunder=locals_hide_dunder,
        locals_hide_sunder=locals_hide_sunder,
    )

    # Add missing mako information to the rich traceback.
    stack_exception = exception
    # ``rich.traceback.Stack`` is an object containing the information for each
    # exception in the chain (as-in walking the ``exception.__context__``
    # attribute).
    for rich_stack in reversed(rich_trace.stacks):
        mako_tb = mako.exceptions.RichTraceback(stack_exception, stack_exception.__traceback__)
        # ``rich.traceback.Frame`` is an object containing the frame information
        # needed to generate the traceback text for the user.
        for rich_frame, mako_frame in zip(rich_stack.frames, mako_tb.records):
            _, _, _, _, template_filename, template_lineno, _, _ = mako_frame
            if template_filename and template_lineno:  # it's a mako template, override the frame info
                rich_frame.filename = template_filename
                rich_frame.lineno = template_lineno
            else:
                assert not template_filename or not template_lineno  # if one is set, the other must be too
        stack_exception = stack_exception.__context__

    return rich.traceback.Traceback(
        rich_trace,
        # rich.traceback.Traceback.__init__ kwargs
        width=width,
        code_width=code_width,
        extra_lines=extra_lines,
        theme=theme,
        word_wrap=word_wrap,
        show_locals=show_locals,
        indent_guides=indent_guides,
        locals_max_length=locals_max_length,
        locals_max_string=locals_max_string,
        locals_hide_dunder=locals_hide_dunder,
        locals_hide_sunder=locals_hide_sunder,
        suppress=suppress,
        max_frames=max_frames,
    )


def main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        formatter_class=rich_argparse.RichHelpFormatter,
    )
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
    summary: str | None
    date: datetime.datetime


class Renderer:
    _ADMONITION_CLASSES = {
        'caution': 'is-warning',
        'note': 'is-info',
    }

    def __init__(
        self,
        templates: mako.lookup.TemplateLookup,
        outdir: pathlib.Path,
        content_root: pathlib.Path,
        minify: bool = True,
        base_render_args: dict[str, Any] = {},
    ) -> None:
        self.__logger = logging.getLogger(str(self.__class__))
        self._templates = templates
        self._outdir = outdir
        self._content_root = content_root
        self._minify = minify
        self._args = base_render_args.copy()
        self._args['meta'] = {}

    def _write_html(self, file: pathlib.Path, html: str) -> None:
        file.parent.mkdir(parents=True, exist_ok=True)
        self.__logger.info(f'writing to {file}...')
        file.write_text(minify_html.minify(html) if self._minify else html)

    @staticmethod
    def _extract_metadata(html: str) -> dict[str, str]:
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
            classes = aside.attrib['class'].split(' ')
            if 'admonition' in classes:
                aside.tag = 'div'
                aside.attrib['class'] = 'message'
                for admoniton_class, new_class in cls._ADMONITION_CLASSES.items():
                    if admoniton_class in classes:
                        aside.attrib['class'] += f' {new_class}'
                header = ET.SubElement(aside, 'div', {'class': 'message-header'})
                body = ET.SubElement(aside, 'div', {'class': 'message-body'})
                for h1 in aside.findall('h1'):
                    aside.remove(h1)
                    header.append(h1)
                    h1.tag = 'p'
                for body_tag in ('p', 'ul'):
                    for elem in aside.findall(body_tag):
                        aside.remove(elem)
                        body.append(elem)

    @classmethod
    def _fix_html(cls, html: str) -> str:
        """Fix rst2html5 generated HTML to use our styling."""
        xml = ET.fromstring('<body>' + html + '</body>')  # add some root node because ET needs one
        cls._fix_node(xml)
        new_html = ET.tostring(xml).decode()
        new_html = new_html.removeprefix('<body>').removesuffix('</body>')  # remove the root node we added
        return new_html

    @staticmethod
    def _rst_to_docutils(file: pathlib.Path) -> dict[str, str]:
        return docutils.core.publish_parts(
            writer=rst2html5.HTML5Writer(),
            source=file.read_text(),
        )

    @classmethod
    def _render_args_from_rst(cls, file: pathlib.Path, args: dict[str, Any]) -> None:
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
    def metadata(cls, file: pathlib.Path) -> dict[str, str]:
        return cls._extract_metadata(cls._rst_to_docutils(file)['whole'])

    @classmethod
    def page(
        cls,
        file: pathlib.Path,
        metadata: dict[str, str] | None = None,
    ) -> Page:
        meta = metadata or cls.metadata(file)
        return Page(
            file.stem,
            meta['title'],
            meta.get('summary'),
            datetime.datetime.fromisoformat(meta['date']),
        )

    def render_redirect_page(self, origin: pathlib.Path, target: pathlib.Path) -> None:
        assert origin.exists()
        new_url = origin.relative_to(target.parent, walk_up=True).as_posix()
        html = textwrap.dedent(f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Redirecting...</title>
                <link rel="canonical" href="{new_url}" />
                <meta charset="utf-8" />
                <meta http-equiv="refresh" content="0; url={new_url}" />
            </head>
            <body>
                <p>Redirecting...</p>
            </body>
            </html>
        """)
        target.parent.mkdir(exist_ok=True, parents=True)
        self._write_html(target, html)

    def render(
        self,
        template: str,
        content_file: pathlib.Path | None = None,
        render_args: dict[str, Any] = {},
        outfile: pathlib.Path | None = None,
    ) -> None:
        args = self._args.copy()
        args.update(render_args)

        if content_file:
            self._render_args_from_rst(content_file, args)
            if not outfile:
                outfile = content_file.relative_to(self._content_root).with_suffix('.html')
        if not outfile:
            raise ValueError("Neither 'content_file' not 'outfile' were supplied")
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
            self._write_html(outfile, html)


def list_pages(path: pathlib.Path) -> Sequence[Page]:
    return sorted([Renderer.page(file) for file in path.iterdir()], key=operator.attrgetter('id'))


def backwards_compatibility_fixes(renderer: Renderer, outdir: pathlib.Path) -> None:
    renderer.render_redirect_page(
        outdir / 'blog' / 'index.html',
        outdir / 'posts' / 'index.html',
    )
    renderer.render_redirect_page(
        outdir / 'blog' / '01-gsoc-2020' / 'index.html',
        outdir / 'posts' / '01-gsoc-2020' / 'index.html',
    )


def main(cli_args: Sequence[str]) -> None:
    parser = main_parser()
    args = parser.parse_args(cli_args)

    root = pathlib.Path(__file__).parent
    content = root / 'content'
    outdir = pathlib.Path(args.outdir)
    out_css = outdir / 'static' / 'css'

    out_css.mkdir(parents=True, exist_ok=True)

    templates = mako.lookup.TemplateLookup(directories=[root / 'templates'])
    renderer = Renderer(
        templates,
        outdir,
        content,
        not args.skip_minify,
        {'url': args.url},
    )

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
    pygments_css = subprocess.check_output(['pygmentize', '-S', 'default', '-f', 'html', '-a', 'pre'])
    out_css.joinpath('pygments.css').write_bytes(pygments_css)

    # compile scss
    subprocess.check_call(
        [
            'sassc',
            '--style=compressed',
            os.fspath(root / 'scss' / 'style.scss'),
            os.fspath(out_css / 'style.css'),
        ]
    )

    # copy static files
    shutil.copytree(root / 'static', outdir / 'static', dirs_exist_ok=True)

    backwards_compatibility_fixes(renderer, outdir)


def excepthook(
    type_: type[BaseException],
    value: BaseException,
    traceback: types.TracebackType | None,
) -> None:
    """Custom except hook that prints tracebacks with rich.

    It uses ``mako_rich_traceback`` to add the mako template information to the rich traceback.
    """
    assert type_ is type(value)
    assert traceback is value.__traceback__
    rich.print(mako_rich_traceback(value))


if __name__ == '__main__':
    sys.excepthook = excepthook
    logging.basicConfig(level=logging.INFO, handlers=[rich.logging.RichHandler()])

    main(sys.argv[1:])
