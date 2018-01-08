# -*- coding: utf-8 -*-
"""Plot performance comparisons between mel, cmds, cmdx and PyMEL"""

import os
import sys
import timeit
import importlib
from copy import deepcopy

from maya import cmds, mel
from maya import OpenMaya as om1
from maya.api import OpenMaya as om2
from pymel import core as pm

import cmdx

try:
    # Python 3 support
    reload = importlib.reload
except AttributeError:
    pass

try:
    # Mock irrelevant pygal dependency
    sys.modules["pkg_resources"] = type("Mock", (object,), {
        "iter_entry_points": lambda *args, **kwargs: []
    })()

    import pygal
except ImportError:
    raise ImportError("plot.py requires pygal")

# Results from tests end up here
data = dict()

# Precisions
Milliseconds = 0
Nanoseconds = 1


def Test(method,
         task,
         func,
         setup=None,
         teardown=None,
         number=1000,
         repeat=5,
         precision=1):

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

    print(text % (
        task,
        method,
        10 ** 3 * sum(results),
        10 ** (6 if precision else 3) * min(results) / number
    ))

    if task not in data:
        data[task] = {}

    # Store for plot
    data[task][method] = {
        "func": func,
        "number": number,
        "results": results,
        "min": sum(results),
        "percall": min(results) / number
    }


def New(setup=None):
    cmds.file(new=True, force=True)
    (setup or (lambda: None))()


def reload_pymel():
    """PyMEL consists of many submodules

    PyMEL does initialisation on import.
    The duration of the initialisation increases
    linearly with the number of plug-ins available
    on import.

    """

    for mod in sys.modules.copy():
        if mod.startswith("pymel"):
            sys.modules.pop(mod)

    import pymel.core
    pymel.core  # avoid linter warning


New()

node = cmdx.createNode("transform", name="Node")
path = node.path()
pynode = pm.PyNode(path)
api1node = om1.MFnDagNode().create("transform")
api2node = om2.MFnDagNode().create("transform")
api1mfn = om1.MFnDagNode(api1node)
api2mfn = om2.MFnDagNode(api2node)


def om1GetAttr():
    """Fastest way of getting an attribute with API 2.0"""
    plug = api2mfn.findPlug("translateX", False)
    return plug.asDouble()


def om2GetAttr():
    """Fastest way of getting an attribute with API 2.0"""
    plug = api2mfn.findPlug("translateX", False)
    return plug.asDouble()


def om1SetAttr(value):
    """Fastest way of getting an attribute with API 2.0"""
    plug = api2mfn.findPlug("translateX", False)
    return plug.setDouble(value)


def om2SetAttr(value):
    """Fastest way of getting an attribute with API 2.0"""
    plug = api2mfn.findPlug("translateX", False)
    return plug.setDouble(value)


Test("cmdx", "import", lambda: reload(cmdx), number=100)
Test("cmds", "import", lambda: reload(cmds), number=100)
Test("PyMEL", "import", reload_pymel, number=1)

Test("cmds", "long", lambda: cmds.ls(path, long=True))
Test("cmdx", "long", lambda: node.path())
Test("PyMEL", "long", lambda: pm.ls(path, long=True))
Test("API 1.0", "long", lambda: api2mfn.fullPathName())
Test("API 2.0", "long", lambda: api2mfn.fullPathName())

Test("mel", "getAttr", lambda: mel.eval("getAttr %s" % (path + ".tx")), number=10000)
Test("cmds", "getAttr", lambda: cmds.getAttr(path + ".tx"), number=10000)
Test("cmdx", "getAttr", lambda: cmdx.getAttr(node + ".tx", type=cmdx.Double), number=10000)
Test("PyMEL", "getAttr", lambda: pynode.tx.get(), number=10000)
Test("API 1.0", "getAttr", lambda: om1GetAttr(), number=10000)
Test("API 2.0", "getAttr", lambda: om2GetAttr(), number=10000)

Test("mel", "setAttr", lambda: mel.eval("setAttr %s %s" % (path + ".tx", 5)))
Test("cmds", "setAttr", lambda: cmds.setAttr(path + ".tx", 5))
Test("cmdx", "setAttr", lambda: cmdx.setAttr(node + ".tx", 5, type=cmdx.Double))
Test("PyMEL", "setAttr", lambda: pm.setAttr(pynode + ".tx", 5))
Test("API 1.0", "setAttr", lambda: om1SetAttr(5))
Test("API 2.0", "setAttr", lambda: om2SetAttr(5))

Test("cmdx", "node.attr", lambda: node["tx"].read(), number=10000)
Test("PyMEL", "node.attr", lambda: pynode.tx.get(), number=10000)

Test("cmdx", "node.attr=5", lambda: node["tx"].write(5), number=10000)
Test("PyMEL", "node.attr=5", lambda: pynode.tx.set(5), number=10000)

Test("mel", "createNode", lambda: mel.eval("createNode \"transform\""), New)
Test("cmds", "createNode", lambda: cmds.createNode("transform"), New)
Test("cmdx", "createNode", lambda: cmdx.createNode(cmdx.Transform), New)
Test("PyMEL", "createNode", lambda: pm.createNode("transform"), New)
Test("API 1.0", "createNode", lambda: om1.MFnDagNode().create("transform"), New)
Test("API 2.0", "createNode", lambda: om2.MFnDagNode().create("transform"), New)

New()

parent = cmdx.createNode("transform")
path = parent.path()
pynode = pm.PyNode(path)

for x in range(100):
    cmdx.createNode("transform", parent=parent)

Test("mel", "listRelatives", lambda: mel.eval('listRelatives -children "transform1"'))
Test("cmds", "listRelatives", lambda: cmds.listRelatives(path, children=True))
Test("cmdx", "listRelatives", lambda: cmdx.listRelatives(parent, children=True))
Test("PyMEL", "listRelatives", lambda: pm.listRelatives(pynode, children=True))

New(lambda: [cmds.createNode("transform") for _ in range(100)])

def lsapi(om):
    it = om.MItDependencyNodes()
    while not it.isDone():
        it.thisNode()
        it.next()

Test("mel", "ls", lambda: mel.eval("ls"))
Test("cmds", "ls", lambda: cmds.ls())
Test("cmdx", "ls", lambda: list(cmdx.ls()))
Test("PyMEL", "ls", lambda: pm.ls())
Test("API 1.0", "ls", lambda: lsapi(om1))
Test("API 2.0", "ls", lambda: lsapi(om2))

New()

node1 = cmdx.createNode("transform")
node2 = cmdx.createNode("transform")


def teardown():
    cmds.disconnectAttr("transform1.tx", "transform2.tx")


melconnect = 'connectAttr "transform1.tx" "transform2.tx"'
Test("mel", "connectAttr", lambda: mel.eval(melconnect), teardown=teardown, number=1, repeat=1000)
Test("cmds", "connectAttr", lambda: cmds.connectAttr("transform1.tx", "transform2.tx"), teardown=teardown, number=1, repeat=5000)
Test("cmdx", "connectAttr", lambda: cmdx.connectAttr(node1["tx"], node2["tx"]), teardown=teardown, number=1, repeat=5000)
Test("PyMEL", "connectAttr", lambda: pm.connectAttr("transform1.tx", "transform2.tx"), teardown=teardown, number=1, repeat=5000)

New()

def teardown():
    cmds.deleteAttr("transform1.myAttr")


node = cmdx.createNode("transform")
path = node.path()

meladdattr = 'addAttr -ln "myAttr" -at double -dv 0 transform1;'
Test("mel", "addAttr", lambda: mel.eval(meladdattr), number=1, repeat=1000, teardown=teardown)
Test("cmds", "addAttr", lambda: cmds.addAttr(path, longName="myAttr", attributeType="double", defaultValue=0), number=1, repeat=1000, teardown=teardown)
Test("cmdx", "addAttr", lambda: cmdx.addAttr(node, longName="myAttr", attributeType=cmdx.Double, defaultValue=0), number=1, repeat=1000, teardown=teardown)
Test("PyMEL", "addAttr", lambda: pm.addAttr(path, longName="myAttr", attributeType="double", defaultValue=0), number=1, repeat=1000, teardown=teardown)

Test("cmdx", "node.addAttr", lambda: node.addAttr(cmdx.Double("myAttr")), number=1, repeat=1000, teardown=teardown)

#
# Render performance characteristics as bar charts
#
# |___
# |___|_______
# |___________|
# |______|___
# |__________|____
# |_______________|________

# Mock irrelevant pygal dependency
sys.modules["pkg_resources"] = type("Mock", (object,), {
    "iter_entry_points": lambda *args, **kwargs: []
})()


def stacked(data, dirname):
    data = deepcopy(data)
    tasks = sorted(data.keys())

    # Use a fixed order of methods in the plot
    methods = ("mel", "cmds", "PyMEL", "cmdx")

    # [group1 result, group2 result, ... of MEL]
    # [group1 result, group2 result, ... of cmds]
    # ...

    cols = list()
    for method in methods:
        col = list()
        for task in tasks:
            col += [data[task].get(method, {}).get("min", 0)]
        cols.append(col)

    # Normalise along Y-axis
    rows = zip(*cols)

    for index, row in enumerate(rows[:]):
        rows[index] = [100.0 * col / sum(row) for col in row]

    cols = zip(*rows)

    line_chart = pygal.StackedBar()
    line_chart.title = "cmdx performance plot (in %)"
    line_chart.x_labels = tasks

    for method, col in enumerate(cols):
        line_chart.add(methods[method], col)

    fname = os.path.join(dirname, "stacked.svg")
    line_chart.render_to_file(fname)


def horizontal(data, dirname):
    data = deepcopy(data)
    order = ("PyMEL", "mel", "cmds", "cmdx")

    for task, methods in data.items():
        chart = pygal.HorizontalBar()
        chart.title = task + u" (μs)"
        for method in order:
            values = methods.get(method, {})
            if not values:
                continue
            chart.add(method, 10 ** 6 * values.get("percall", 0))

        fname = os.path.join(
            dirname, r"%s.svg" % task
        )

        chart.render_to_file(fname)


def average(x, y, data):
    data = deepcopy(data)

    times_faster = list()
    print("|         | Times       | Task")
    print("|:--------|:------------|:------------")
    for task, methods in data.items():
        try:
            a = methods[x]["percall"]
            b = methods[y]["percall"]
        except KeyError:
            continue

        faster = a / float(b)
        print("| cmdx is | %.1fx faster | %s" % (faster, task))
        times_faster.append(faster)

    average = sum(times_faster) / len(times_faster)
    return round(average, 2)


# Draw plots
dirname = os.path.join(os.path.dirname(cmdx.__file__), "plots")
stacked(data, dirname)
horizontal(data, dirname)
avg = average("PyMEL", "cmdx", data)
print("- cmdx is on average %.2fx faster than PyMEL" % avg)
avg = average("cmds", "cmdx", data)
print("- cmdx is on average %.2fx faster than cmds" % avg)