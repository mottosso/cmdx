from nose.tools import (
	with_setup,
	assert_equals
)

import cmdx

def new_scene():
	cmdx.file(new=True, force=True)


@with_setup(new_scene)
def test_createNode():
	noname = cmdx.createNode("transform")
	name = cmdx.createNode("transform", name="MyName")
	assert_equals(name.basename, "MyName")
	parent = cmdx.createNode("transform", parent=name)
	shared = cmdx.createNode("multMatrix", name="myMult", shared=True)