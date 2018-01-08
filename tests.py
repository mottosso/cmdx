from nose.tools import (
    with_setup,
    assert_equals
)

import cmdx
from maya import cmds


def new_scene():
    cmds.file(new=True, force=True)


@with_setup(new_scene)
def test_createNode():
    node = cmdx.createNode("transform")
    parent = cmdx.createNode("transform", "MyNode")
    assert_equals(parent.name(), "MyNode")
    child = cmdx.createNode("transform", "MyNode", parent)
    assert parent in child.children()

    node = cmdx.createNode("transform", name="MyNode")
    node = cmdx.createNode("transform", name="MyNode", parent=node)
