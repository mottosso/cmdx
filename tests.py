# -*- coding: utf-8 -*-
import os
import sys
import shutil
import tempfile
import contextlib

from nose.tools import (
    with_setup,
    assert_equals,
    assert_not_equals,
    assert_raises,
    assert_is,
    assert_is_not,
    assert_almost_equals,
)

import cmdx
from maya import cmds
from maya.api import OpenMaya as om

__maya_version__ = int(cmds.about(version=True))


def new_scene():
    cmds.file(new=True, force=True)


@contextlib.contextmanager
def tempdir():
    tmp = tempfile.mkdtemp()
    try:
        yield tmp
    finally:
        shutil.rmtree(tmp)


@contextlib.contextmanager
def environment(key, value=None):
    env = os.environ.copy()
    os.environ[key] = value or "1"
    try:
        sys.modules.pop("cmdx")
        yield __import__("cmdx")
    finally:
        os.environ.update(env)
        sys.modules.pop("cmdx")
        __import__("cmdx")


@contextlib.contextmanager
def pop_environment(key):
    env = os.environ.copy()
    os.environ.pop(key)
    try:
        sys.modules.pop("cmdx")
        yield __import__("cmdx")
    finally:
        os.environ.update(env)
        sys.modules.pop("cmdx")
        __import__("cmdx")


@with_setup(new_scene)
def test_createNode():
    """cmdx.createNode works"""
    node = cmdx.createNode("transform")
    parent = cmdx.createNode("transform", name="MyNode")
    assert_equals(parent.name(), "MyNode")
    child = cmdx.createNode("transform", name="MyNode", parent=parent)
    assert_equals(child, parent.child())

    node = cmdx.createNode("transform", name="MyNode")
    node = cmdx.createNode("transform", name="MyNode", parent=node)


@with_setup(new_scene)
def test_getattrtypes():
    """Explicit getAttr"""
    node = cmdx.createNode("transform")
    assert_equals(node["translate"].read(), (0.0, 0.0, 0.0))
    assert_equals(node["rotate"].read(), (0.0, 0.0, 0.0))
    assert_equals(node["scale"].read(), (1.0, 1.0, 1.0))
    assert_equals(node["tx"].read(), 0.0)
    assert_equals(node["ry"].read(), 0.0)
    assert_equals(node["sz"].read(), 1.0)


@with_setup(new_scene)
def test_getattrimplicit():
    """Implicit getAttr"""
    node = cmdx.createNode("transform")
    assert_equals(node["sz"], 1.0)


@with_setup(new_scene)
def test_getattrcomplex():
    """Complex getAttr"""
    node = cmdx.createNode("transform")
    assert_equals(node["worldMatrix"], ((
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ),))

    # Note the returned tuple in the above

    assert_equals(node["worldMatrix"][0], (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ))

    node["tx"] = 5.0
    assert_equals(node["worldMatrix"][0], (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        5.0, 0.0, 0.0, 1.0,
    ))

    locator = cmdx.createNode("locator", parent=node)
    assert_equals(locator["worldPosition"], (
        5.0, 0.0, 0.0
    ))


@with_setup(new_scene)
def test_getattrtime():
    """getAttr(time=)"""
    transform = cmdx.createNode("transform")

    for time, value in ((1, 1.0),
                        (10, 10.0)):
        cmds.setKeyframe(str(transform),
                         time=[time],
                         attribute="translateY",
                         value=value)
    cmds.keyTangent(str(transform),
                    edit=True,
                    time=(1, 10),
                    attribute="translateY",
                    outTangentType="linear")

    # These floating point values can differ ever so slightly
    assert_almost_equals(transform["ty"].read(time=1), 1.0, places=5)
    assert_almost_equals(transform["ty"].read(time=5), 5.0, places=5)
    assert_almost_equals(transform["ty"].read(time=10), 10.0, places=5)


def test_setattr():
    """Setting attributes works well"""
    transform = cmdx.createNode("transform")

    # Setting single with single
    transform["translateX"] = 1.0

    # Multi with multi
    transform["translate"] = (1.0, 2.0, 3.0)
    transform["translate"] = (1, 2, 3)  # Automatic cast to float

    # Multi with single
    transform["translate"] = 1.0
    assert_equals(transform["translate"].read(), (1.0, 1.0, 1.0))

    # Plug with plug
    transform["translate"] = transform["translate"]


@with_setup(new_scene)
def test_getcached():
    """Returning a cached plug works"""
    node = cmdx.createNode("transform")
    assert_equals(node["translate"], (0.0, 0.0, 0.0))
    assert_equals(node["rotate"], (0.0, 0.0, 0.0))
    node["tx"] = 5
    assert_equals(node["tx"], 5)
    node["tx"] = 10
    assert_equals(node["tx", cmdx.Cached], 5)
    assert_equals(node["tx"], 10)


def test_plugreuse():
    """Plug re-use works ok"""
    import cmdx
    node = cmdx.createNode("transform")
    id(node["translate"]) == id(node["translate"])


@with_setup(new_scene)
def test_nodereuse():
    """Node re-use works ok"""

    import cmdx
    nodeA = cmdx.createNode("transform", name="myNode")
    nodeB = cmdx.createNode("transform", parent=nodeA)
    assert_is(cmdx.encode("|myNode"), nodeA)
    assert_is(nodeB.parent(), nodeA)

    with tempdir() as tmp:
        fname = os.path.join(tmp, "myScene.ma")
        cmds.file(rename=fname)
        cmds.file(save=True, type="mayaAscii")
        cmds.file(fname, open=True, force=True)

        # On scene open, the current scene is closed, triggering
        # the nodeDestroyed callback which invalidates the node
        # for cmdx. Upon encoding this node anew, cmdx will
        # allocate a new instance for it.
        assert_is_not(cmdx.encode("|myNode"), nodeA)


@with_setup(new_scene)
def test_nodereuse_noexist():
    """Node re-use works on non-existent nodes"""

    nodeA = cmdx.createNode("transform", name="myNode")
    nodeB = cmdx.createNode("transform", parent=nodeA)
    assert_is(cmdx.encode("|myNode"), nodeA)
    assert_is(nodeB.parent(), nodeA)

    cmds.file(new=True, force=True)

    # Even if it's available for re-use, it will still throw
    # a ValueError on account of trying to fetch an MObject
    # from a non-existing node.
    assert_raises(ValueError, cmdx.encode, "|myNode")

    # Any operation on a deleted node raises RuntimeError
    assert_raises(RuntimeError, lambda: nodeA.name())


@with_setup(new_scene)
def test_nodereuse_equalexist():
    """Node re-use on new, same-name nodes"""

    nodeA = cmdx.createNode("transform", name="myNode")
    nodeB = cmdx.createNode("transform", parent=nodeA)
    assert_is(cmdx.encode("|myNode"), nodeA)
    assert_is(nodeB.parent(), nodeA)

    cmds.file(new=True, force=True)

    assert_raises(ValueError, cmdx.encode, "|myNode")
    nodeC = cmdx.createNode("transform", name="myNode")
    assert_is(cmdx.encode("|myNode"), nodeC)


@with_setup(new_scene)
def test_descendents():
    """Returning all descendents works"""
    gp = cmdx.createNode("transform")
    p = cmdx.createNode("transform", parent=gp)
    c = cmdx.createNode("transform", parent=p)

    descendents = list(gp.descendents())
    assert_equals(descendents, [p, c])


@with_setup(new_scene)
def test_descendents_typename():
    """Returning only descendents of typeName works"""
    gp = cmdx.createNode("transform")
    p = cmdx.createNode("transform", parent=gp)
    c = cmdx.createNode("transform", parent=p)
    m = cmdx.createNode("mesh", parent=c)

    descendents = list(gp.descendents(type="mesh"))
    assert_equals(descendents, [m])


@with_setup(new_scene)
def test_descendents_typeid():
    """Returning only descendents of typeName works"""
    gp = cmdx.createNode("transform")
    p = cmdx.createNode("transform", parent=gp)
    c = cmdx.createNode("transform", parent=p)
    m = cmdx.createNode("mesh", parent=c)

    descendents = list(gp.descendents(type=cmdx.Mesh))
    assert_equals(descendents, [m])


def test_keyable():
    """Plug.keyable = True works"""

    node = cmdx.createNode("transform")

    assert_equals(node["translateX"].keyable, True)
    node["translateX"].keyable = False
    assert_equals(node["translateX"].keyable, False)


def test_channelBox():
    """Plug.channelBox = True works"""

    node = cmdx.createNode("transform")

    assert_equals(node["translateX"].channelBox, False)
    node["translateX"].channelBox = True
    assert_equals(node["translateX"].channelBox, True)

    assert_equals(node["translate"].channelBox, False)
    node["translate"].channelBox = True
    assert_equals(node["translate"].channelBox, True)


def test_assign_tm():
    """Assign MTransformationMatrix works"""

    node = cmdx.createNode("transform")
    tm = node["worldMatrix"][0].asTm()
    node["translate"] = tm.translation()
    node["rotate"] = tm.rotation()


def test_assign_toangle():
    """Assign to Angle3 works"""

    node = cmdx.createNode("transform")
    node["Limits"] = cmdx.Angle3()
    node["Limits"] = (0, 0, 0)
    node["Limits"] = 0  # Crash!


@with_setup(new_scene)
def test_timings():
    """CMDX_TIMINGS outputs timing information"""

    import cmdx
    cmdx.createNode("transform", name="myNode")

    # Trigger re-use timings
    cmdx.encode("myNode")
    assert cmdx.LastTiming is None

    with environment("CMDX_TIMINGS") as cmdx:
        cmdx.encode("myNode")
        assert cmdx.LastTiming is not None, cmdx.LastTiming


@with_setup(new_scene)
def test_nodeoperators():
    """Node operators works"""

    node = cmdx.createNode(cmdx.Transform, name="myNode")
    assert_equals(node, "|myNode")
    assert_not_equals(node, "|NotEquals")
    assert_equals(str(node), repr(node))


@with_setup(new_scene)
def test_superclass():
    """cmdx.Node(dagmobject) creates a DagNode"""

    # Using the right class works
    mobj = om.MFnDagNode().create("transform")
    node = cmdx.DagNode(mobj)
    assert isinstance(node, cmdx.DagNode)

    mobj = om.MFnDependencyNode().create("polySplit")
    node = cmdx.Node(mobj)
    assert isinstance(node, cmdx.Node)

    # Using the wrong class works too
    mobj = om.MFnDagNode().create("transform")
    node = cmdx.Node(mobj)
    assert isinstance(node, cmdx.DagNode)

    mobj = om.MFnDependencyNode().create("polySplit")
    node = cmdx.DagNode(mobj)
    assert isinstance(node, cmdx.Node)
