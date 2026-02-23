#!/usr/bin/env python3

# /// script
# requires-python = '>=3.11'
# dependencies = [
#   'docutils',
#   'rich',
#   'rich_argparse',
#   'mako',
#   'minify_html',
#   'rst2html5',
# ]
# ///

import argparse
import datetime
import logging
import operator
import os.path
import pathlib
import shutil
import subprocess
import sys
import types
import xml.etree.ElementTree as ET

from collections.abc import Collection, Iterable, Mapping
from typing import Any, Literal, NamedTuple, Self, Sequence

import docutils.core
import docutils.frontend
import docutils.parsers.rst
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
            if template_filename and template_lineno:
                # it's a mako template, override the frame info
                rich_frame.filename = template_filename
                rich_frame.lineno = template_lineno
            else:
                # if one is set, the other must be too
                assert not template_filename or not template_lineno
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


def docutils_parse_rst(
    file: pathlib.Path,
    extra_components: Collection[docutils.Component] = (),
) -> docutils.nodes.document:
    parser = docutils.parsers.rst.Parser()
    settings = docutils.frontend.get_default_settings(parser, *extra_components)
    document = docutils.utils.new_document(os.fspath(file), settings)
    parser.parse(file.read_text(), document)
    return document


class Page(NamedTuple):
    id: str
    title: str
    summary: str | None = None
    date: datetime.datetime | None = None

    @classmethod
    def from_metadata_dict(cls, id: str, data: dict[str, str], /) -> Self | None:
        try:
            return cls(
                id,
                data['title'],
                data.get('summary'),
                datetime.datetime.fromisoformat(data['date']) if 'date' in data else None,
            )
        except KeyError:
            return None

    @classmethod
    def from_file(cls, file: pathlib.Path) -> Self | None:
        document = docutils_parse_rst(file)
        metadata = {
            element.attributes['name']: element.attributes['content']
            for element in document
            if element.tagname == 'meta'
        }
        return cls.from_metadata_dict(file.stem, metadata)


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

        self._writer = rst2html5.HTML5Writer()

    def _write_html(self, file: pathlib.Path, html: str) -> None:
        file.parent.mkdir(parents=True, exist_ok=True)
        self.__logger.info(f'writing to {file}...')
        file.write_text(minify_html.minify(html) if self._minify else html)

    @classmethod
    def _fix_html(cls, node: ET.Element) -> None:
        # sections
        for section in node.findall('section'):
            section.attrib['class'] = 'content'
            for h1 in section.findall('h1'):
                h1.attrib['class'] = 'title'
            cls._fix_html(section)
        # lists
        for dl in node.findall('dl'):
            dl.attrib['class'] = 'box has-background-success-light'
        # tables
        for table in node.findall('table'):
            table.attrib['class'] = 'table'
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

    def render(
        self,
        template: str,
        content_file: pathlib.Path | None = None,
        render_args: dict[str, Any] = {},
        outfile: pathlib.Path | None = None,
        html_settings: dict | None = None,
    ) -> None:
        args = self._args.copy()
        args |= render_args

        if content_file:
            if not outfile:
                outfile = content_file.relative_to(self._content_root).with_suffix('.html')
            # Generate HTML from rST
            html = docutils.core.publish_string(
                source=content_file.read_text(),
                writer=rst2html5.HTML5Writer(),
                settings_overrides=html_settings,
            )
            # Find body and fix HTML
            xml = ET.fromstring(html).find('body')
            self._fix_html(xml)
            body = ET.tostring(xml).decode().strip()
            body = body.removeprefix('<body>').removesuffix('</body>')
            # Add render arguments
            stat = content_file.stat()
            ctime = datetime.datetime.fromtimestamp(stat.st_ctime)
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
            page = Page.from_file(content_file)
            if page and page.date:
                ctime = page.date
            args |= {
                'body': body,
                'ctime': ctime,
                'mtime': mtime,
                'page': page,
                'content_file': content_file,
            }

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

    def render_redirect_page(self, origin: pathlib.Path, target: pathlib.Path) -> None:
        assert origin.exists()
        self.render(
            'redirect.html',
            outfile=target,
            render_args={
                'new_url': origin.relative_to(target.parent, walk_up=True).as_posix(),
            },
        )


class Section(NamedTuple):
    name: str
    title: str
    directory: pathlib.Path
    output_path: pathlib.Path
    sort_by: Literal['id', 'title', 'ctime', 'mtime'] = 'id'
    index_template: str = 'article-index.html'
    article_template: str = 'article.html'
    content_html_settings: dict | None = None

    @property
    def pages(self) -> Mapping[Self, pathlib.Path]:
        page_info = [
            {
                'file': path,
                'page': (page := Page.from_file(path)),
                'id': page.id,
                'title': page.title,
                'ctime': path.stat().st_ctime,
                'mtime': path.stat().st_mtime,
            }
            for path in self.directory.iterdir()
            if path.is_file()
        ]
        return {
            info['page']: info['file']
            for info in sorted(page_info, key=operator.itemgetter(self.sort_by))
        }


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
    external = root / 'external'
    outdir = pathlib.Path(args.outdir).absolute()
    out_css = outdir / 'static' / 'css'

    out_css.mkdir(parents=True, exist_ok=True)

    sections = [
        Section(
            name='Blog',
            title='Blog Posts',
            directory=content / 'blog',
            output_path=pathlib.Path('blog'),
            sort_by='id',
        ),
        Section(
            name='Resources',
            title='Resources',
            directory=content / 'resources',
            output_path=pathlib.Path('resources'),
            sort_by='ctime',
        ),
        Section(
            name='Development Log',
            title='Development Log',
            directory=content / 'devlog',
            output_path=pathlib.Path('devlog'),
            sort_by='ctime',
            article_template='devlog-article.html',
            content_html_settings={'initial_header_level': 4},
        ),
    ]

    templates = mako.lookup.TemplateLookup(directories=[root / 'templates'])
    renderer = Renderer(
        templates,
        outdir,
        content_root=content,
        minify=not args.skip_minify,
        base_render_args={
            'url': args.url,
            'sections': sections,
        },
    )

    # render
    renderer.render('index.html', content / 'index.rst')
    for section in sections:
        renderer.render(
            template=section.index_template,
            outfile=section.output_path / 'index.html',
            render_args={
                'title': section.title,
                'pages': section.pages,
            },
        )
        for file in section.pages.values():
            renderer.render(
                template=section.article_template,
                content_file=file,
                outfile=section.output_path / file.stem / 'index.html',
                html_settings=section.content_html_settings,
            )

    # generate pygments theme
    pygments_css = subprocess.check_output(
        ['pygmentize', '-S', 'default', '-f', 'html', '-a', 'pre']
    )
    out_css.joinpath('pygments.css').write_bytes(pygments_css)

    # compile scss
    subprocess.check_call(
        [
            'sass',
            '--style=compressed',
            f'-I{external!s}',
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
