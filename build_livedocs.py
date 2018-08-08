#!/usr/bin/env python
import io
import re


def parse(fname):
    """Return blocks of code as list of dicts

    Arguments:
        fname (str): Relative name of caveats file

    """

    blocks = list()
    with io.open(fname, "r", encoding="utf-8") as f:
        in_block = False
        current_block = None
        current_header = ""

        for line in f:

            # Doctests are within a quadruple hashtag header.
            if line.startswith("### "):
                current_header = line.rstrip()

            # The actuat test is within a fenced block.
            if line.startswith("```"):
                in_block = False

            if in_block:
                current_block.append(line)

            if line.startswith("```python"):
                in_block = True
                current_block = list()
                current_block.append(current_header)
                blocks.append(current_block)

    tests = list()
    for block in blocks:
        header = (
            block[0].strip("# ")  # Remove Markdown
                    .rstrip()     # Remove newline
                    .lower()      # PEP08
        )

        # Remove unsupported characters
        header = re.sub(r"\W", "_", header)

        # Adding "untested" anywhere in the first line of
        # the doctest excludes it from the test.
        if "untested" in block[1].lower():
            continue

        tests.append({
            "header": header,
            "body": block[1:]
        })

    return tests


def format_(blocks):
    """Produce Python module from blocks of tests

    Arguments:
        blocks (list): Blocks of tests from func:`parse()`

    """

    tests = list()
    function_count = 0  # For each test to have a unique name

    for block in blocks:

        # Validate docstring format of body
        if not any(line[:3] == ">>>" for line in block["body"]):
            # A doctest requires at least one `>>>` directive.
            continue

        function_count += 1
        block["header"] = block["header"]
        block["count"] = str(function_count)
        block["body"] = "    ".join(block["body"])
        tests.append(u"""\

def test_{count}_{header}():
    '''Test {header}

    {body}
    '''

""".format(**block))

    return tests


if __name__ == '__main__':
    blocks = parse("README.md")
    tests = format_(blocks)

    # Write formatted tests
    # with open("test_docs.py", "w") as f:
    with io.open("test_docs.py", "w", encoding="utf-8") as f:
        f.write(u"""\
# -*- coding: utf-8 -*-
from nose.tools import assert_raises
from maya import standalone
standalone.initialize()

from maya import cmds
import cmdx

""")
        f.write("".join(tests))
