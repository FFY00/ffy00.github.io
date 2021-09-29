.. meta::
    :title: Python, Debian, and the install locations
    :date: 2021-09-29T02:30:00
    :summary: Deep dive into the Debian patching of Python install locations and
              how that is affecting the Python ecosystem and community.


Introduction
============

Today, I will be talking about the Debian patching of Python, more specifically,
the Debian patching of the Python install locations and interpreter
initialization in specific.

As some of you may know, the Python shipped by Debian is not exactly the same
Python as the Python core developers intended. Debian makes several intrusive
changes the Python distribution they ship. The last effort in documenting
this that I am aware of was `this gist`_ by Christian Heimes (tiran).

Distributors modifying software is not unheard of, in fact, it is fairly common.
It is sometimes required to get software to work properly on the target system.
However, generally, these modifications are kept fairly minimal. That is not
the case of the Debian Python, which has significant behavior discrepancies from
normal Python installations and ends up resulting in issues and lots of
frustration per part of the users and developers that have to deal with it.


Patched behavior and motivation
===============================

.. admonition:: Disclaimer
   :class: caution

   Please note that what I am about to describe here is to best of my knowledge
   the motivation from what I have discussed with people, but I may still be
   missing context and/or have forgotten things, so please take it with a grain
   of salt. If it is not accurate, please reach out to me and I will either
   update this post or make a new one and link it here.


Okay, let's take a look at what behavior Debian actually patches and why they do
it.

A normal Python installation to the ``/usr`` prefix will have a site packages
directory at ``/usr/lib/pythonX.Y/site-packages``. The site packages directory
is a place for user-installed packages, it is a mechanism that that Python us to
customize the default environment of the interpreter. That means packages
installed there will be available in the interpreter, so you will be able to
import them. This functionality is provided bt the ``site`` module, and can be
disabled by passing the ``-S`` option to the interpreter.

Install locations on Linux are governed by the `Filesystem Hierarchy Standard
(FHS)`_ specification, at least in the distributions that adopt it, which are
most of them, including Debian. It describes what each location on the system
means and how files are distributed. The bits relevant for us are the ``/usr``
and ``/usr/local`` paths. I am not gonna get into many details, but essentially
``/usr`` and ``/usr/local`` contain our program data, split into subdirectories
as specified by the `/usr hierarchy`_ page, with ``/usr`` being reserved for the
software installed by system vendor, and ``/usr/local`` for software installed
locally by the system administrator (generally, the user).

The `/usr/local hierarchy`_ pages says as follows:

    The /usr/local hierarchy is for use by the system administrator when installing
    software locally. It needs to be safe from being overwritten when the system
    software is updated. It may be used for programs and data that are shareable
    amongst a group of hosts, but not found in /usr.

    Locally installed software must be placed within /usr/local rather than /usr
    unless it is being installed to replace or upgrade software in /usr.

Which Debian understands to be the case of Python packages installed by pip. I
do not agree with that interpretation, because what we are doing when installing
Python packages via pip is customizing our Python installation. Now, I will
acknowledge that the line is fuzzy as some users use a pip as a way to
installing software without intending to customize the default environment of
the Python interpreter, but at the end of the day, they are still customizing
the Python environment.

I think the following makes is clear that installing data to ``/usr/local``
should not be used for programs in ``/usr``.

    It may be used for programs and data that are shareable amongst a group of
    hosts, but not found in /usr.

But alas, Debian thinks pip should place packages in ``/usr/local``, reserving
``/usr`` for the Python packages installed by Debian. This would mean
``/usr/lib/pythonX.Y/site-packages`` for Debian packages, and
``/usr/local/lib/pythonX.Y/site-packages`` for packages installed by pip. The
more attentive of you might have spotted the first problem, using 
``/usr/local/lib/pythonX.Y/site-packages`` conflicts with local Python
installations, which use the ``/usr/local`` prefix! Both ``/usr/bin/python`` and
``/usr/local/bin/python`` would be loading packages from
``/usr/local/lib/pythonX.Y/site-packages``. For this reason, Debian renamed
``site-packages`` to ``dist-packages`` in their Python.

They also remove the Python minor version from the install path for their
packages, making it ``/usr/lib/pythonX/dist-packages``. This is done to avoid
rebuilding all packages that contain Python modules when Python is updated.

So summarizing, Debian removes ``/usr/lib/pythonX.Y/site-packages`` from the
module import path search list (sys.path_), adds 
``/usr/lib/pythonX/dist-packages`` and
``/usr/local/lib/pythonX.Y/dist-packages``, and changes the default install
location to ``/usr/local/lib/pythonX.Y/dist-packages`` (well, only in one place,
but I am getting ahead of myself, we will have a look at this later).


How is it patched?
==================

Before looking at the details of how the patching is done, we need some
background on the following standard library modules.

distutils_
    ``distutils`` is a standard library module for building and installing
    Python packages. It is the predecessor for setuptools, which extends it
    (well, that is not technically 100% correct, but to avoid complicating
    things, you can understand it as so).
    ``distutils`` is deprecated and will be removed in Python 3.12.

sysconfig_
    ``sysconfig`` is a standard library module that provides access to the
    Python installation configuration details, like installation paths and
    configuration variables.

site_
    ``site`` is a module that is automatically imported during the interpreter
    initialization and adds user customizations, like providing access to user
    installed modules. It can be disabled by passing ``-S`` to the Python
    interpreter.

So, what exactly does Debian do to achieve their desired behavior?

Debian applies several patches to the Python install they distribute, which can
be found here_, but the relevant one for us is distutils-install-layout.diff_.

The patch adds two new install schemes to
``distutils.command.install.INSTALL_SCHEMES``, ``deb_system`` and
``unix_local``, overwrites the prefix selection logic in ``distutils`` to use
them, and overwrites the site packages paths in the ``site`` module to use their
desired paths instead of the default one.

There's also a sysconfig-debian-schemes.diff_ patch that adds the new install
schemes to ``sysconfig`` in the repo, but **they do not apply it**.


The issue
=========

As we saw above, Debian overwrites the site packages in paths in the ``site``
module, however, they do not patch ``sysconfig`` to represent those
modifications, only ``distutils``. This presents a really big problem, the 
install locations returned by ``sysconfig`` are incorrect.

.. code:: python

   >>> import sysconfig
   >>> sysconfig.get_paths()
   {'stdlib': '/usr/lib/python3.8',
    'platstdlib': '/usr/lib/python3.8',
    'purelib': '/usr/lib/python3.8/site-packages',
    'platlib': '/usr/lib/python3.8/site-packages',
    'include': '/usr/include/python3.8',
    'platinclude': '/usr/include/python3.8',
    'scripts': '/usr/bin',
    'data': '/usr'}

So, installers will get locations that have absolutely no effect on the
interpreter. The bigger problem though, is that Debian is so widely used that
this forces them to implement workarounds or add custom logic for Debian, but
this is not straightforward and requires knowledge of most of the quirks
explained in this post to be implemented correctly. This has been the source of
much frustration for lots of people, myself included.


I am stuck with it, what do I do?
=================================

In the unfortunate case you have to deal with this, well, you will have to load
the install locations from ``distutils``, which, as I mentioned above, is
deprecated and will be removed in Python 3.12.

.. code:: python

   import distutils.dist

   distribution = distutils.dist.Distribution({
       'name': 'some-python-package',
   })
   install_cmd = distribution.get_command_obj('install')
   install_cmd.finalize_options()

   locations = {
       'data': install_cmd.install_data,
       'headers': install_cmd.install_headers,
       'platlib': install_cmd.install_platlib,
       'purelib': install_cmd.install_purelib,
       'scripts': install_cmd.install_scripts,
   }

But wait, you can't. You cannot assume ``distutils`` is there! Debian partially
splits the ``distutils`` module, which is part of the standard library and
should be available on all Python installations. The user must have the
``python3-distutils`` package installed. One last thing to keep in mind, the
``distutils`` module is only partially split, so ``import distutils`` will work,
but importing any submodule other than ``distutils.version`` will not.

Debian does not add any custom logic here to raise an exception with a
descriptive error message asking the user to install ``python3-distutils``, like
they do with some of the other modules they split from the ``python3`` package,
so you probably want to do that yourself.

.. code:: python

   try:
       import distutils.dist
   except ModuleNotFoundError as e:
       raise ModuleNotFoundError(
           'No module named distutils.dist. Please make sure you have '
           'python3-distutils installed if you are on a Debian system.'
       ) from None

And this gets worse if you actually want to install to the system, which you
might if you are a build system that supports building Python modules (eg.
Meson). In which case, you will want to set the ``install_layout`` option to
``deb``, ``install_layout`` being an option added by Debian in their patching.

.. code:: python

   try:
       import distutils.dist
   except ModuleNotFoundError as e:
       raise ModuleNotFoundError(
           'No module named distutils.dist. Please make sure you have '
           'python3-distutils installed if you are on a Debian system.'
       ) from None

   import distutils.command.install

   distribution = distutils.dist.Distribution({
       'name': 'some-python-package',
   })
   install_cmd = distribution.get_command_obj('install')
   if 'deb_system' in distutils.command.install.INSTALL_SCHEMES:  # Debian distutils
       install_cmd.install_layout = 'deb'
   install_cmd.finalize_options()

   locations = {
       'data': install_cmd.install_data,
       'headers': install_cmd.install_headers,
       'platlib': install_cmd.install_platlib,
       'purelib': install_cmd.install_purelib,
       'scripts': install_cmd.install_scripts,
   }

And what about Python 3.12 and after? Well, I don't know. The correct answer
ignoring Debian would be to simply use ``sysconfig.get_paths()``. Our issue is
that we don't really know what Debian will do, and how exactly they will patch
Python. My best guess is that they will patch ``sysconfig``, as they should be
already, and that we will finally be able to rely on it (after 10 years of it
being in the standard library!).


How to fix it?
==============

Well, the solution seems fairly straightforward to me. Debian should patch
``sysconfig`` to reflect their changes to the ``site`` module initialization.

The necessary patching would be adding the ``deb_system`` and ``unix_local``
install schemes, and overwriting ``sysconfig._get_preferred_schemes()`` to
select ``unix_local``.


Conclusion
==========

Well, you now probably understand why the first thing most people tell you when
starting in Python development is to forget about your distro-provided Python,
and install it from source or use something like pyenv_. The Python installation
that Debian, and virtually all Debian-based distros, are distributing is
effectively broken.

What makes this worse is that this is just one of the multiple issues with the
patching Debian does to the Python installation they distribute. This has been a
massive pain point for years, and not much has been done about this. I truly
believe it has tarnished both Debian and Python's reputations, such to a degree
that some have suggested that the PSF_ should take up this issue and ask Debian
to either fix their Python distribution or rename it, because the Python Debian
is shipping is effectively not the Python released by developers. This sounds
very harsh, but honestly, I cannot blame them |--| this is has been a real issue
for years and nothing has been done about it.

I do not blame the Debian Python maintainer though, the details we discussed
here are very complex and there are many things to take into account, which are
rarely obvious.
I would say the issue is the lack of a Debian policy to address these
situations, if Debian has policies that force the maintainers to make such
invasive modifications to software, they should require a discussion to be
started with the project upstream asking for guidance and recommendations on how
to achieve the desired behavior, to minimize the negative impact the downstream
patching will have.

That said, I think the Python upstream strive to make the situation better for
downstream packagers. We have seen that vendors have certain needs that are not
being addressed, so we should try to fix that. I took a stab at solving this
with bpo-43976_ and bpo-44982_, but progress has been slow. The idea is that the
Python upstream should provide a way for vendors to customize certain aspects of
the distribution, like the install locations, and a way to identify custom
Python distributions.


.. |--| unicode:: U+2013 .. en dash

.. _this gist: https://gist.github.com/tiran/2dec9e03c6f901814f6d1e8dad09528e
.. _Filesystem Hierarchy Standard (FHS): https://refspecs.linuxfoundation.org/FHS_3.0/fhs.html
.. _/usr hierarchy: https://refspecs.linuxfoundation.org/FHS_3.0/fhs.html#theUsrHierarchy
.. _/usr/local hierarchy: https://refspecs.linuxfoundation.org/FHS_3.0/fhs.html#usrlocalLocalHierarchy
.. _sys.path: https://docs.python.org/3/library/sys.html#sys.path
.. _distutils: https://docs.python.org/3/library/distutils.html
.. _sysconfig: https://docs.python.org/3/library/sysconfig.html
.. _site: https://docs.python.org/3/library/site.html
.. _here: https://salsa.debian.org/cpython-team/python3/-/tree/master/debian/patches
.. _distutils-install-layout.diff: https://salsa.debian.org/cpython-team/python3/-/blob/master/debian/patches/distutils-install-layout.diff
.. _sysconfig-debian-schemes.diff: https://salsa.debian.org/cpython-team/python3/-/blob/master/debian/patches/sysconfig-debian-schemes.diff
.. _pyenv: https://github.com/pyenv/pyenv
.. _PSF: https://www.python.org/psf/
.. _bpo-43976: https://bugs.python.org/issue43976
.. _bpo-44982: https://bugs.python.org/issue44982
