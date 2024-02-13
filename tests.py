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

    for time, value in ((0, 0.0),
                        (24, 10.0)):
        cmds.setKeyframe(str(transform),
                         time=[time],
                         attribute="translateY",
                         value=value)
    cmds.keyTangent(str(transform),
                    edit=True,
                    time=(0, 24),
                    attribute="translateY",
                    inTangentType="linear",
                    outTangentType="linear")

    # These floating point values can differ ever so slightly
    assert_almost_equals(transform["ty"].read(time=0.0), 0.0, places=5)
    assert_almost_equals(transform["ty"].read(time=0.5), 5.0, places=5)
    assert_almost_equals(transform["ty"].read(time=1.0), 10.0, places=5)

    # From the current context (Maya 2018 and above)
    if hasattr(om.MDGContext, "makeCurrent"):
        with cmdx.DGContext(0.0):
            assert_almost_equals(transform["ty"].read(), 0.0, places=5)
        with cmdx.DGContext(0.5):
            assert_almost_equals(transform["ty"].read(), 5.0, places=5)
        with cmdx.DGContext(1.0):
            assert_almost_equals(transform["ty"].read(), 10.0, places=5)

        # Custom units
        with cmdx.DGContext(0, cmdx.TimeUiUnit()):
            assert_almost_equals(transform["ty"].read(), 0.0, places=5)
        with cmdx.DGContext(12, cmdx.TimeUiUnit()):
            assert_almost_equals(transform["ty"].read(), 5.0, places=5)
        with cmdx.DGContext(24, cmdx.TimeUiUnit()):
            assert_almost_equals(transform["ty"].read(), 10.0, places=5)

        # Alternate syntax
        with cmdx.DGContext(cmdx.TimeUiUnit()(0)):
            assert_almost_equals(transform["ty"].read(), 0.0, places=5)
        with cmdx.DGContext(cmdx.TimeUiUnit()(12)):
            assert_almost_equals(transform["ty"].read(), 5.0, places=5)
        with cmdx.DGContext(cmdx.TimeUiUnit()(24)):
            assert_almost_equals(transform["ty"].read(), 10.0, places=5)


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

    # On scene open, the current scene is closed which *should*
    # invalidate all MObjects. However. An old MObject can sometimes
    # reference a new node, most typically the `top` camera node.#
    # It doesn't always happen, and appears random. So we should test
    # a few more times, just to make more sure.
    for attempt in range(5):
        with tempdir() as tmp:
            fname = os.path.join(tmp, "myScene.ma")
            cmds.file(rename=fname)
            cmds.file(save=True, type="mayaAscii")
            cmds.file(fname, open=True, force=True)
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
    # a cmdx.ExistError on account of trying to fetch an MObject
    # from a non-existing node.
    assert_raises(cmdx.ExistError, cmdx.encode, "|myNode")

    # Any operation on a deleted node raises ExistError
    try:
        print(nodeA.name())
    except cmdx.ExistError:
        pass
    else:
        assert False


@with_setup(new_scene)
def test_nodereuse_equalexist():
    """Node re-use on new, same-name nodes"""

    nodeA = cmdx.createNode("transform", name="myNode")
    nodeB = cmdx.createNode("transform", parent=nodeA)
    assert_is(cmdx.encode("|myNode"), nodeA)
    assert_is(nodeB.parent(), nodeA)

    cmds.file(new=True, force=True)

    assert_raises(cmdx.ExistError, cmdx.encode, "|myNode")
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

    descendents = list(gp.descendents(type=cmdx.tMesh))
    assert_equals(descendents, [m])


def test_keyable():
    """Plug.keyable = True works"""

    node = cmdx.createNode("transform")

    assert_equals(node["translateX"].keyable, True)
    node["translateX"].keyable = False
    assert_equals(node["translateX"].keyable, False)

    assert_equals(node["rotate"].keyable, True)
    node["rotate"].keyable = False
    assert_equals(node["rotate"].keyable, False)


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

    node = cmdx.createNode(cmdx.tTransform, name="myNode")
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


def test_modifier_badtype():
    """Modifier can't create non-existent types"""

    mod = cmdx.DagModifier()

    # This is the only call that throws an error
    # immediately as it is called. Great!
    assert_raises(TypeError, mod.createNode, "doesntExist")


def test_modifier_existing_connection():
    """Modifier fails on connecting to already-connected attribute"""

    mod = cmdx.DagModifier()
    node = mod.createNode("transform")
    mod.connect(node["translateX"], node["translateY"])
    mod.connect(node["translateZ"], node["translateY"], force=False)

    assert_raises(cmdx.ModifierError, mod.doIt)


def test_modifier_first_error():
    """Modifier throws only the first encountered error"""

    mod = cmdx.DagModifier()
    node = mod.createNode("transform")
    mod.connect(node["translateX"], node["translateY"])
    mod.setAttr(node["translateY"], 5.0)

    assert_raises(cmdx.ModifierError, mod.doIt)


@with_setup(new_scene)
def test_modifier_atomicity():
    """Modifier rolls back changes on failure"""

    mod = cmdx.DagModifier(atomic=True)
    node = mod.createNode("transform", name="UniqueName")
    mod.connect(node["translateX"], node["translateY"])
    mod.setAttr(node["translateY"], 5.0)

    assert_raises(cmdx.ModifierError, mod.doIt)

    # Node never got created
    assert "|UniqueName" not in cmds.ls()


def test_modifier_history():
    """Modifiers provide record of history on failure"""

    mod = cmdx.DagModifier()
    node = mod.createNode("transform", name="UniqueName")
    mod.connect(node["translateX"], node["translateY"])
    mod.setAttr(node["translateY"], 5.0)

    try:
        mod.doIt()
    except cmdx.ModifierError as e:
        tasks = [task[0] for task in e.history]
        assert_equals(tasks[0], "createNode")
        assert_equals(tasks[1], "connect")
        assert_equals(tasks[2], "setAttr")
    else:
        assert False, "I should have failed"


def test_modifier_undo():
    new_scene()

    with cmdx.DagModifier() as mod:
        mod.createNode("transform", name="nodeA")
        mod.createNode("transform", name="nodeB")
        mod.createNode("transform", name="nodeC")

    assert "|nodeC" in cmdx.ls()
    cmds.undo()
    assert "|nodeC" not in cmdx.ls()


def test_modifier_locked():
    """Modifiers properly undo setLocked"""

    new_scene()
    node = cmdx.createNode("transform")
    assert not node["translateX"].locked

    with cmdx.DagModifier() as mod:
        mod.setLocked(node["translateX"], True)

    assert node["translateX"].locked
    cmds.undo()
    assert not node["translateX"].locked
    cmds.redo()
    assert node["translateX"].locked
    cmds.undo()
    assert not node["translateX"].locked


def test_modifier_keyable():
    """Modifiers properly undo setKeyable"""

    new_scene()
    node = cmdx.createNode("transform")
    assert node["translateX"].keyable

    with cmdx.DagModifier() as mod:
        mod.setKeyable(node["translateX"], False)

    assert not node["translateX"].keyable
    cmds.undo()
    assert node["translateX"].keyable
    cmds.redo()
    assert not node["translateX"].keyable
    cmds.undo()
    assert node["translateX"].keyable


def test_modifier_nicename():
    """Modifiers properly undo setNiceName"""

    new_scene()
    node = cmdx.createNode("transform")
    node["myName"] = cmdx.Double()
    assert node["myName"].niceName == "My Name"

    with cmdx.DagModifier() as mod:
        mod.setNiceName(node["myName"], "Nice Name")

    assert node["myName"].niceName == "Nice Name"
    cmds.undo()
    assert node["myName"].niceName == "My Name"
    cmds.redo()
    assert node["myName"].niceName == "Nice Name"
    cmds.undo()
    assert node["myName"].niceName == "My Name"


def test_modifier_plug_cmds_undo():
    """cmds and Modifiers undo in the same chunk"""

    new_scene()
    with cmdx.DagModifier() as mod:
        mod.createNode("transform", name="cmdxNode")
        cmds.createNode("transform", name="cmdsNode")

    assert "|cmdxNode" in cmdx.ls()
    assert "|cmdsNode" in cmdx.ls()

    cmds.undo()

    assert "|cmdxNode" not in cmdx.ls()
    assert "|cmdsNode" not in cmdx.ls()

    cmds.redo()

    assert "|cmdxNode" in cmdx.ls()
    assert "|cmdsNode" in cmdx.ls()

    cmds.undo()

    assert "|cmdxNode" not in cmdx.ls()
    assert "|cmdsNode" not in cmdx.ls()


def test_commit_undo():
    """commit is as stable as Modifiers"""

    new_scene()

    # Maintain reference to this
    test_commit_undo.node = None

    def do():
        test_commit_undo.node = cmdx.createNode("transform", name="nodeA")

    do()

    def undo():
        cmdx.delete(test_commit_undo.node)

    cmdx.commit(undo=undo, redo=do)

    assert "|nodeA" in cmdx.ls()

    cmds.undo()

    assert "|nodeA" not in cmdx.ls()

    cmds.redo()

    assert "|nodeA" in cmdx.ls()

    cmds.undo()

    assert "|nodeA" not in cmdx.ls()


def test_modifier_redo():
    pass


def _setup_listrelatives_test():
    new_scene()
    cmds.createNode('transform', name='topGrp')
    cmds.polyCube(name='hierarchyCube', constructionHistory=False)
    cmds.parent('hierarchyCube', 'topGrp')
    cmds.createNode('transform', name='botGrp', parent='hierarchyCube')
    cmds.polyCube(name='worldCube', constructionHistory=False)
    cmds.blendShape('hierarchyCube', 'worldCube', name='cubeBlend')


@with_setup(_setup_listrelatives_test)
def test_listrelatives_children():

    result_cmdx = cmdx.listRelatives('hierarchyCube', children=True)
    result_cmdx = [i.name() for i in result_cmdx]
    result_cmds = cmds.listRelatives('hierarchyCube', children=True)

    assert_equals(result_cmdx, result_cmds)


@with_setup(_setup_listrelatives_test)
def test_listrelatives_alldescendents():

    result_cmdx = cmdx.listRelatives('topGrp', allDescendents=True)
    result_cmdx = [i.name() for i in result_cmdx]
    result_cmds = cmds.listRelatives('topGrp', allDescendents=True)

    # cmds has a special result order, so compare sets
    result_cmdx = set(result_cmdx)
    result_cmds = set(result_cmds)

    assert_equals(result_cmdx, result_cmds)


@with_setup(_setup_listrelatives_test)
def test_listrelatives_parent():

    result_cmdx = cmdx.listRelatives('hierarchyCubeShape', parent=True)
    result_cmdx = [i.name() for i in result_cmdx]
    result_cmds = cmds.listRelatives('hierarchyCubeShape', parent=True)

    assert_equals(result_cmdx, result_cmds)


@with_setup(_setup_listrelatives_test)
def test_listrelatives_shapes():

    result_cmdx = cmdx.listRelatives('worldCube', shapes=True)
    result_cmdx = [i.name() for i in result_cmdx]
    result_cmds = cmds.listRelatives('worldCube', shapes=True)

    assert_equals(result_cmdx, result_cmds)
