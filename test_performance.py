# -*- coding: utf-8 -*-
import os
import sys
import timeit
import contextlib

from maya import cmds, mel, OpenMaya as om1
from maya.api import OpenMaya as om2
import cmdx

from flaky import flaky
from nose.tools import (
    assert_greater,
)

timings = {}


def Compare(method,
            task,
            func,
            setup=None,
            number=200,
            repeat=4,
            precision=1,
            quiet=True):

    setup = setup or (lambda: None)

    text = "%s %s: %.1f ms (%.2f {precision}/call)".format(
        precision="μs" if precision else "ms"
    )

    results = timeit.Timer(func, setup=setup).repeat(
        repeat=repeat, number=number)

    if not quiet:
        print(text % (
            task,
            method,
            10 ** 3 * sum(results),
            10 ** (6 if precision else 3) * min(results) / number
        ))

    if task not in timings:
        timings[task] = {}

    # Store for comparison
    timings[task][method] = {
        "func": func,
        "number": number,
        "results": results,
        "min": min(results),
        "percall": min(results) / number
    }


@contextlib.contextmanager
def environment(key, value=None):
    env = os.environ.copy()
    os.environ[key] = value or "1"
    try:
        sys.modules.pop("cmdx")
        __import__("cmdx")
        yield
    finally:
        os.environ.update(env)


@contextlib.contextmanager
def pop_environment(key):
    env = os.environ.copy()
    os.environ.pop(key, None)
    try:
        sys.modules.pop("cmdx")
        __import__("cmdx")
        yield
    finally:
        os.environ.update(env)


def New(setup=None):
    cmds.file(new=True, force=True)
    (setup or (lambda: None))()


@flaky(max_runs=20, min_passes=3)
def test_createNode_performance():
    """createNode cmdx vs cmds > 2x"""

    versions = (
        ("mel", lambda: mel.eval("createNode \"transform\"")),
        ("cmds", lambda: cmds.createNode("transform")),
        ("cmdx", lambda: cmdx.createNode(cmdx.tTransform)),
        # ("PyMEL", lambda: pm.createNode("transform")),
        ("API 1.0", lambda: om1.MFnDagNode().create("transform")),
        ("API 2.0", lambda: om2.MFnDagNode().create("transform")),
    )

    for contender, test in versions:
        Compare(contender, "createNode", test, setup=New)

    cmdx_vs_cmds = (
        timings["createNode"]["cmds"]["percall"] /
        timings["createNode"]["cmdx"]["percall"]
    )

    cmdx_vs_api = (
        timings["createNode"]["API 2.0"]["percall"] /
        timings["createNode"]["cmdx"]["percall"]
    )

    assert_greater(cmdx_vs_cmds, 0.5)  # at most 2x slower than cmds
    assert_greater(cmdx_vs_api, 0.20)  # at most 5x slower than API 2.0


@flaky(max_runs=20, min_passes=3)
def test_rouge_mode():
    """CMDX_ROGUE_MODE is faster"""

    node = cmdx.createNode("transform")
    Compare("norogue", "createNode", node.name)

    with environment("CMDX_ROGUE_MODE"):
        node = cmdx.createNode("transform")
        Compare("rogue", "createNode", node.name)

    rogue_vs_norogue = (
        timings["createNode"]["norogue"]["percall"] /
        timings["createNode"]["rogue"]["percall"]
    )

    assert_greater(rogue_vs_norogue, 0.9)
