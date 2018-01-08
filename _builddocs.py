from sphinx.cmdline import main
from maya import standalone

print("Initializing Maya..")
standalone.initialize()

# Build with Sphinx
main([
    "",
    "docs/source",
    "docs/build",
    "-E",
    "-v"
])
