# cmdx and cmdx interop
from maya import cmds
import cmdx

node = cmds.createNode("transform")
node = cmds.rename(node, "MyNode")

node = cmdx.encode(node)
node["rotate"] = (0, 45, 0)

cmds.select(str(node))
