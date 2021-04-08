"""Tools for interacting with Sphinx."""
import os.path as op
import sys
from pathlib import Path
from typing import Optional, Union

from sphinx.application import Sphinx
from sphinx.cmd.build import handle_exception
from sphinx.util.docutils import docutils_namespace, patch_docutils
from sphinx_external_toc.api import SiteMap

from .config import get_final_config
from .pdf import update_latex_documents

REDIRECT_TEXT = """
<meta http-equiv="Refresh" content="0; url={first_page}" />
"""

ROOT = Path(__file__)


def build_sphinx(
    sourcedir,
    outputdir,
    *,
    use_external_toc=True,
    confdir=None,
    path_config=None,
    noconfig=False,
    confoverrides=None,
    doctreedir=None,
    filenames=None,
    force_all=False,
    quiet=False,
    really_quiet=False,
    builder="html",
    freshenv=False,
    warningiserror=False,
    tags=None,
    verbosity=0,
    jobs=None,
    keep_going=False,
) -> Union[int, Exception]:
    """Sphinx build "main" command-line entry.

    This is a slightly modified version of
    https://github.com/sphinx-doc/sphinx/blob/3.x/sphinx/cmd/build.py#L198.

    """
    #######################
    # Configuration creation
    sphinx_config, config_meta = get_final_config(
        user_yaml=Path(path_config) if path_config else None,
        cli_config=confoverrides or {},
        sourcedir=Path(sourcedir),
        use_external_toc=use_external_toc,
    )

    ##################################
    # Preparing Sphinx build arguments

    # Configuration directory
    if noconfig:
        confdir = None
    elif not confdir:
        confdir = sourcedir

    # Doctrees directory
    if not doctreedir:
        doctreedir = Path(outputdir).parent.joinpath(".doctrees")

    if jobs is None:
        jobs = 1

    # Manually re-building files in filenames
    if filenames is None:
        filenames = []
    missing_files = []
    for filename in filenames:
        if not op.isfile(filename):
            missing_files.append(filename)
    if missing_files:
        raise IOError("cannot find files %r" % missing_files)

    if force_all and filenames:
        raise ValueError("cannot combine -a option and filenames")

    # Debug args (hack to get this to pass through properly)
    def debug_args():
        pass

    debug_args.pdb = False
    debug_args.verbosity = False
    debug_args.traceback = False

    # Logging behavior
    status = sys.stdout
    warning = sys.stderr
    error = sys.stderr
    if quiet:
        status = None
    if really_quiet:
        status = warning = None

    ###################
    # Build with Sphinx
    app = None  # In case we fail, this allows us to handle the exception
    try:
        # These patches temporarily override docutils global variables,
        # such as the dictionaries of directives, roles and nodes
        # NOTE: this action is not thread-safe and not suitable for asynchronous use!
        with patch_docutils(confdir), docutils_namespace():
            app = Sphinx(
                srcdir=sourcedir,
                confdir=confdir,
                outdir=outputdir,
                doctreedir=doctreedir,
                buildername=builder,
                confoverrides=sphinx_config,
                status=status,
                warning=warning,
                freshenv=freshenv,
                warningiserror=warningiserror,
                tags=tags,
                verbosity=verbosity,
                parallel=jobs,
                keep_going=keep_going,
            )
            app.srcdir = Path(app.srcdir).as_posix()
            app.outdir = Path(app.outdir).as_posix()
            app.confdir = Path(app.confdir).as_posix()
            app.doctreedir = Path(app.doctreedir).as_posix()

            # We have to apply this update after the sphinx initialisation,
            # since default_latex_documents is dynamically generated
            # see sphinx/builders/latex/__init__.py:default_latex_documents
            new_latex_documents = update_latex_documents(
                app.config.latex_documents, config_meta["latex_doc_overrides"]
            )
            app.config.latex_documents = new_latex_documents

            # Build latex_doc tuples based on --individualpages option request
            if config_meta["latex_individualpages"]:
                from .pdf import autobuild_singlepage_latexdocs

                # Ask Builder to read the source files to fetch titles and documents
                app.builder.read()
                latex_documents = autobuild_singlepage_latexdocs(app)
                app.config.latex_documents = latex_documents

            app.build(force_all, filenames)

            # Write an index.html file in the root to redirect to the first page
            # TODO when would this be required?
            path_index = outputdir.joinpath("index.html")
            site_map: Optional[SiteMap] = getattr(app.env, "external_site_map", None)
            if not path_index.exists() and site_map:
                first_page = site_map.root.docname.split(".")[0] + ".html"
                with open(path_index, "w", encoding="utf8") as ff:
                    ff.write(REDIRECT_TEXT.format(first_page=first_page))

            return app.statuscode

    except (Exception, KeyboardInterrupt) as exc:
        handle_exception(app, debug_args, exc, error)
        return exc
