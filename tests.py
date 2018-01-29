# -*- coding: utf-8 -*-
from nose.tools import (
    with_setup,
    assert_equals,
    assert_almost_equals,
)

import cmdx
from maya import cmds

__maya_version__ = int(cmds.about(version=True))


def new_scene():
    cmds.file(new=True, force=True)


@with_setup(new_scene)
def test_createNode():
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
    assert_equals(node["worldMatrix"], (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ))

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
    node = cmdx.createNode("transform")
    assert_equals(node["translate"], (0.0, 0.0, 0.0))
    assert_equals(node["rotate"], (0.0, 0.0, 0.0))
    node["tx"] = 5
    assert_equals(node["tx"], 5)
    node["tx"] = 10
    assert_equals(node["tx", cmdx.Cached], 5)
    assert_equals(node["tx"], 10)
