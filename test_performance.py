# -*- coding: utf-8 -*-
import timeit

from maya import cmds, mel, OpenMaya as om1
from maya.api import OpenMaya as om2
import cmdx

timings = {}


def Compare(method,
            task,
            func,
            setup=None,
            teardown=None,
            number=100,
            repeat=1,
            precision=1,
            quiet=True):

    results = list()

    setup = setup or (lambda: None)
    teardown = teardown or (lambda: None)

    text = "%s %s: %.1f ms (%.2f {precision}/call)".format(
        precision="μs" if precision else "ms"
    )

    for iteration in range(repeat):
        setup()
        results += [timeit.Timer(func).timeit(number)]
        teardown()

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
        "min": sum(results),
        "percall": min(results) / number
    }


def New(setup=None):
    cmds.file(new=True, force=True)
    (setup or (lambda: None))()


def test_createNode_performance():
    """createNode cmdx vs cmds > 2x"""

    versions = (
        ("mel", lambda: mel.eval("createNode \"transform\"")),
        ("cmds", lambda: cmds.createNode("transform")),
        ("cmdx", lambda: cmdx.createNode(cmdx.Transform)),
        # ("PyMel", lambda: pm.createNode("transform")),
        ("API 1.0", lambda: om1.MFnDagNode().create("transform")),
        ("API 2.0", lambda: om2.MFnDagNode().create("transform")),
    )

    for contender, test in versions:
        Compare(contender, "createNode", test, setup=New)
