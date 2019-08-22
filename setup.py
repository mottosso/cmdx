"""A fast subset of maya.cmds"""

import os
from setuptools import setup

__version__ = None
with open(os.path.join(os.path.dirname(__file__), "cmdx.py")) as f:
    for line in f:
        if line.startswith("__version__"):
            exec(line)
            break

assert __version__, "Could not determine version"


classifiers = [
    "Development Status :: 5 - Production/Stable",
    "License :: OSI Approved :: BSD License",
    "Intended Audience :: Developers",
    "Operating System :: OS Independent",
    "Programming Language :: Python",
    "Programming Language :: Python :: 2",
    "Programming Language :: Python :: 2.7",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.6",
    "Programming Language :: Python :: 3.7",
    "Topic :: Utilities",
    "Topic :: Software Development",
    "Topic :: Software Development :: Libraries :: Python Modules",
]


setup(
    name="cmdx",
    version=__version__,
    description=__doc__,
    keywords="Fast subset of maya.cmds",
    long_description=__doc__,
    url="https://github.com/mottosso/cmdx",
    author="Marcus Ottosson",
    author_email="me@mottosso.com",
    license="BSD",
    zip_safe=False,
    py_modules=["cmdx"],
    classifiers=classifiers,
)
