import cmdx

class CustomLocatorNode(cmdx.LocatorNode):
    name = "customLocatorNode"
    typeid = cmdx.TypeId(0x85006)

    attributes = [
        cmdx.String("myString"),
        cmdx.Message("myMessage"),
        cmdx.Matrix("myMatrix"),
        cmdx.Time("myTime", default=0.0),
    ]

    affects = [
        ("myString", "myMatrix"),
        ("myMessage", "myMatrix"),
        ("myTime", "myMatrix"),
    ]


# Tell Maya to use Maya API 2.0
initializePlugin2 = cmdx.initialize2(CustomNode)
uninitializePlugin2 = cmdx.uninitialize2(CustomNode)

"""
Now from Maya, load the plug-in like normal

from maya import cmds
cmds.loadPlugin("/path/to/locatornode.py")
cmds.createNode("customLocatorNode")

You should now see your custom locator node in your viewport!
"""