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


def New(setup=None):
    cmds.file(new=True, force=True)
    (setup or (lambda: None))()


def Test(method, task, func, setup=None, number=1000, precision=2):
    results = timeit.Timer(
        func,
        setup=setup or (lambda: None)
    ).repeat(repeat=5, number=number)

    text = "%s %s: %.1f ms (%.{precision}f ms/call)".format(
        precision=precision
    )

    print(text % (
        task,
        method,
        1000 * min(results),
        1000 * min(results) / number
    ))

    if task not in data:
        data[task] = {}

    # Store for plot
    data[task][method] = {
        "func": func,
        "number": number,
        "results": results,
        "min": min(results),
        "percall": min(results) / number
    }


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


def getPlugValue(inPlug):
    pAttribute = inPlug.attribute()
    apiType = pAttribute.apiType()

    # Compounds
    if apiType in [om2.MFn.kAttribute3Double,
                   om2.MFn.kAttribute3Float,
                   om2.MFn.kCompoundAttribute]:

        if inPlug.isCompound:
            result = []
            for c in range(inPlug.numChildren()):
                result.append(getPlugValue(inPlug.child(c)))
            return result
        else:
            raise TypeError("Type '%s' unsupported" % apiType)

    # Distance
    elif apiType in [om2.MFn.kDoubleLinearAttribute,
                     om2.MFn.kFloatLinearAttribute]:
        return inPlug.asMDistance().asCentimeters()

    # Angle
    elif apiType in [om2.MFn.kDoubleAngleAttribute,
                     om2.MFn.kFloatAngleAttribute]:
        return inPlug.asMAngle().asDegrees()

    # Typed
    elif apiType == om2.MFn.kTypedAttribute:
        pType = om2.MFnTypedAttribute(pAttribute).attrType()
        # Matrix
        if pType == om2.MFnData.kMatrix:
            return om2.MFnMatrixData(inPlug.asMObject()).matrix()
        # String
        elif pType == om2.MFnData.kString:
            return inPlug.asString()

    # Matrix
    elif apiType == om2.MFn.kMatrixAttribute:

        return om2.MFnMatrixData(inPlug.asMObject()).matrix()

    # Number
    elif apiType == om2.MFn.kNumericAttribute:
        pType = om2.MFnNumericAttribute(pAttribute).numericType()
        if pType == om2.MFnNumericData.kBoolean:
            return inPlug.asBool()
        elif pType in [om2.MFnNumericData.kShort, om2.MFnNumericData.kInt,
                       om2.MFnNumericData.kLong, om2.MFnNumericData.kByte]:
            return inPlug.asInt()
        elif pType in [om2.MFnNumericData.kFloat, om2.MFnNumericData.kDouble,
                       om2.MFnNumericData.kAddr]:
            return inPlug.asDouble()

    # Enum
    elif apiType == om2.MFn.kEnumAttribute:
        return inPlug.asInt()

    else:
        raise TypeError("Type '%s' unsupported" % apiType)


New()

node = cmdx.createNode("transform", name="Node")
path = node.path
pynode = pm.PyNode(path)
api1node = om1.MFnDagNode().create("transform")
api2node = om2.MFnDagNode().create("transform")

Test("cmdx", "import", lambda: reload(cmdx), number=100)
Test("cmds", "import", lambda: reload(cmds), number=100)
Test("PyMEL", "import", reload_pymel, number=1)

Test("mel", "uuid", lambda: mel.eval("ls -uid %s" % path), precision=4)
Test("cmds", "uuid", lambda: cmds.ls(path, uuid=True), precision=4)
Test("cmdx", "uuid", lambda: node.uuid, precision=4)
Test("API 1.0", "uuid", lambda: om1.MFnDagNode(api1node).uuid())
Test("API 2.0", "uuid", lambda: om2.MFnDagNode(api2node).uuid())

Test("cmds", "long", lambda: cmds.ls(path, long=True), precision=4)
Test("cmdx", "long", lambda: node.path, precision=4)
Test("PyMEL", "long", lambda: pm.ls(path, long=True), precision=4)
Test("API 1.0", "uuid", lambda: om1.MFnDagNode(api1node).fullPathName())
Test("API 2.0", "uuid", lambda: om2.MFnDagNode(api2node).fullPathName())

def getAttr2():
    attr = om2.MFnDagNode(api2node).attribute(0)
    plug = om2.MFnDagNode(api2node).findPlug(attr, False)
    return getPlugValue(plug)


Test("mel", "getAttr", lambda: mel.eval("getAttr %s" % (path + ".tx")))
Test("cmds", "getAttr", lambda: cmds.getAttr(path + ".tx"))
Test("cmdx", "getAttr", lambda: cmdx.getAttr(node + ".tx"))
Test("PyMEL", "getAttr", lambda: pynode.tx.get())
Test("API 2.0", "getAttr", getAttr2)

Test("mel", "createNode", lambda: mel.eval("createNode \"transform\""), New)
Test("cmds", "createNode", lambda: cmds.createNode("transform"), New)
Test("cmdx", "createNode", lambda: cmdx.createNode("transform"), New)
Test("PyMEL", "createNode", lambda: pm.createNode("transform"), New)
Test("API 1.0", "createNode", lambda: om1.MFnDagNode().create("transform"), New)
Test("API 2.0", "createNode", lambda: om2.MFnDagNode().create("transform"), New)

New(lambda: [cmds.createNode("transform") for _ in range(100)])

Test("mel", "ls", lambda: mel.eval("ls"))
Test("cmds", "ls", lambda: cmds.ls())
Test("cmdx", "ls", lambda: cmdx.ls())
Test("PyMEL", "ls", lambda: pm.ls())

New()

nodes = [cmds.createNode("transform") for _ in range(1000)]
attrs = ["%s.tx" % _ for _ in nodes]

Test("cmds", "getAttr (map)", lambda: cmds.getAttr(attrs), number=100)
Test("cmdx", "getAttr (map)", lambda: cmds.getAttr(attrs), number=100)

Test("cmdx", "getAttr (multi)", lambda: [
    cmdx.getAttr(attr) for attr in attrs], number=100)
Test("cmds", "getAttr (multi)", lambda: [
    cmds.getAttr(attr) for attr in attrs], number=100)
Test("PyMEL", "getAttr (multi)", lambda: [
    pm.getAttr(attr) for attr in attrs], number=100)

New()

node = cmdx.createNode("transform")
pynode = pm.PyNode(node.path)

Test("cmdx", "node.attr", lambda: node["tx"].value, number=10000)
Test("PyMEL", "node.attr", lambda: pynode.tx, number=10000)

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
    order = ("mel", "cmds", "cmdx", "PyMEL")

    for task, methods in data.items():
        chart = pygal.HorizontalBar()
        chart.title = task + " (ms)"
        for method in order:
            values = methods.get(method, {})
            if not values:
                continue
            chart.add(method, 1000 * values.get("percall", 0))

        fname = os.path.join(
            dirname, r"%s.svg" % task
        )

        chart.render_to_file(fname)


# Draw plots
dirname = os.path.join(os.path.dirname(cmdx.__file__), "plots")
stacked(data, dirname)
horizontal(data, dirname)
