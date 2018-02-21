# -*- coding: utf-8 -*-
import os
import sys
import contextlib

from nose.tools import (
    with_setup,
    assert_equals,
    assert_raises,
    assert_is,
    assert_almost_equals,
)

import cmdx
from maya import cmds

__maya_version__ = int(cmds.about(version=True))


def new_scene():
    cmds.file(new=True, force=True)


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
    os.environ.pop(key)
    try:
        sys.modules.pop("cmdx")
        __import__("cmdx")
        yield
    finally:
        os.environ.update(env)


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
    node = cmdx.createNode("transform")
    id(node["translate"]) == id(node["translate"])

    with pop_environment("CMDX_ENABLE_PLUG_REUSE"):
        node = cmdx.createNode("transform")
        id(node["translate"]) != id(node["translate"])


@with_setup(new_scene)
def test_nodereuse():
    """Node re-use works ok"""

    nodeA = cmdx.createNode("transform", name="myNode")
    nodeB = cmdx.createNode("transform", parent=nodeA)
    assert_is(cmdx.encode("|myNode"), nodeA)
    assert_is(nodeB.parent(), nodeA)


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
