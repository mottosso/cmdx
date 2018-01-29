"""Test Pure Python functionality"""

import os
import sys
import nose

if __name__ == "__main__":
    print("Initialising Maya..")
    from maya import standalone, cmds
    standalone.initialize()
    cmds.loadPlugin("matrixNodes", quiet=True)

    argv = sys.argv[:]
    argv.extend([
        "--verbose",
        "--with-doctest",

        "--with-coverage",
        "--cover-html",
        "--cover-package", "cmdx",
        "--cover-erase",
        "--cover-tests",

        "tests.py",
        "cmdx.py",
    ])

    nose.main(argv=argv)

    if os.getenv("TRAVIS_JOB_ID"):
        import coveralls
        coveralls.wear()
    else:
        sys.stdout.write("Skipping coveralls")
