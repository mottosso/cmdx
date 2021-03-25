try:
    # Python 2
    from sphinx.cmdline import main

except ImportError:
    # Python 3
    from sphinx.cmd.build import main

from maya import standalone

print("Initializing Maya..")
standalone.initialize()

# Build with Sphinx
main([
    "docs/source",
    "build/html",
    "-E",
    "-v"
])
