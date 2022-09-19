from __future__ import annotations

import functools
import logging
import shutil
import tempfile
from os.path import isdir, isfile, join
from urllib.parse import urlsplit

import jinja2.exceptions

from mkdocs.commands.build import build
from mkdocs.config import load_config
from mkdocs.exceptions import Abort
from mkdocs.livereload import LiveReloadServer

log = logging.getLogger(__name__)


def serve(
    config_file=None,
    dev_addr=None,
    strict=None,
    theme=None,
    theme_dir=None,
    livereload='livereload',
    watch_theme=False,
    watch=[],
    **kwargs,
):
    """
    Start the MkDocs development server

    By default it will serve the documentation on http://localhost:8000/ and
    it will rebuild the documentation and refresh the page automatically
    whenever a file is edited.
    """
    # Create a temporary build directory, and set some options to serve it
    # PY2 returns a byte string by default. The Unicode prefix ensures a Unicode
    # string is returned. And it makes MkDocs temp dirs easier to identify.
    site_dir = tempfile.mkdtemp(prefix='mkdocs_')

    def mount_path(config):
        return urlsplit(config['site_url'] or '/').path

    get_config = functools.partial(
        load_config,
        config_file=config_file,
        dev_addr=dev_addr,
        strict=strict,
        theme=theme,
        theme_dir=theme_dir,
        site_dir=site_dir,
        **kwargs,
    )

    live_server = livereload in ('dirty', 'livereload')
    dirty = livereload == 'dirty'

    def builder(config=None):
        log.info("Building documentation...")
        if config is None:
            config = get_config()

        # combine CLI watch arguments with config file values
        if config["watch"] is None:
            config["watch"] = watch
        else:
            config["watch"].extend(watch)

        # Override a few config settings after validation
        config['site_url'] = 'http://{}{}'.format(config['dev_addr'], mount_path(config))

        build(config, live_server=live_server, dirty=dirty)

    config = get_config()
    config['plugins'].run_event('startup', command='serve', dirty=dirty)

    try:
        # Perform the initial build
        builder(config)

        host, port = config['dev_addr']
        server = LiveReloadServer(
            builder=builder, host=host, port=port, root=site_dir, mount_path=mount_path(config)
        )

        def error_handler(code):
            if code in (404, 500):
                error_page = join(site_dir, f'{code}.html')
                if isfile(error_page):
                    with open(error_page, 'rb') as f:
                        return f.read()

        server.error_handler = error_handler

        if live_server:
            # Watch the documentation files, the config file and the theme files.
            server.watch(config['docs_dir'])
            server.watch(config['config_file_path'])

            if watch_theme:
                for d in config['theme'].dirs:
                    server.watch(d)

            # Run `serve` plugin events.
            server = config['plugins'].run_event('serve', server, config=config, builder=builder)

            for item in config['watch']:
                server.watch(item)

        try:
            server.serve()
        except KeyboardInterrupt:
            print()
            log.info("Shutting down...")
        finally:
            server.shutdown()
    except jinja2.exceptions.TemplateError:
        # This is a subclass of OSError, but shouldn't be suppressed.
        raise
    except OSError as e:  # pragma: no cover
        # Avoid ugly, unhelpful traceback
        raise Abort(f'{type(e).__name__}: {e}')
    finally:
        config['plugins'].run_event('shutdown')
        if isdir(site_dir):
            shutil.rmtree(site_dir)
