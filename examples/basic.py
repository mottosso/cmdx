# Basic scenegraph manipulation
import cmdx

node1 = cmdx.createNode("transform")
node2 = cmdx.createNode(cmdx.Transform)

node1["tx"] = 2.5
print(node1)
print(node1["tx"])
# 2.5

node1["tx"] >> node2["tx"]
print(node2["tx"])
# 2.5
