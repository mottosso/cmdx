# -*- coding: utf-8 -*-
"""PyMEL done right"""
from maya import cmds
from maya.api import OpenMaya as om

# Inherit all of cmds (4000+ members)
# Many of these members aren't for working with nodes
locals().update({
    key: value
    for key, value in cmds.__dict__.items()

    # Preserve internal members, e.g.
    #   __builtins__
    #   __doc__
    #   __file__
    #   __name__
    #   __package__
    #   __path__
    if not key.startswith("__")
})

NotExistError = type("NotExistError", (Exception,), {})

Transform = om.MTypeId(0x5846524d)


class Node(str):
    def __str__(self):
        return self.path

    def __repr__(self):
        return self.path

    def __add__(self, other):
        return self.path + other

    def __getitem__(self, key):
        return Attribute(self, key)

    def __setitem__(self, key, value):
        type = None
        if isinstance(value, Attribute):
            value = value.read()
            type = value.type

        Attribute(self, key).write(value, type)

    def __new__(cls, uuid):
        self = super(Node, cls).__new__(cls, uuid)
        self._uuid = uuid
        return self

    @property
    def uuid(self):
        return self._uuid

    @property
    def path(self):
        try:
            return cmds.ls(self, long=True)[0]
        except IndexError:
            raise NotExistError("%s has been deleted" % self._uuid)

    @property
    def basename(self):
        return self.path.rsplit("|", 1)[-1]

    def split(self, delimiter, count=-1):
        return self.path.split(delimiter, count)

    def rsplit(self, delimiter, count=-1):
        return self.path.rsplit(delimiter, count)

    def parent(self, type=None):
        kwargs = {"parent": True}

        if type:
            kwargs["type"] = type

        return ((listRelatives(self, **kwargs) or []) + [None])[0]

    def children(self, type=None):
        kwargs = {"children": True}

        if type:
            kwargs["type"] = type

        return listRelatives(self, **kwargs) or []

    def shapes(self, type=None):
        kwargs = {"shapes": True}

        if type:
            kwargs["type"] = type

        return listRelatives(self, **kwargs) or []


class Attribute(str):
    def __str__(self):
        return str(self.read())

    def __repr__(self):
        return str(self.read())

    def __new__(cls, node=None, key=None, type=None, keyable=True):
        self = super(Attribute, cls).__new__(cls, key)

        self._node = node
        self._type = type
        self._keyable = keyable

        return self

    def __rshift__(self, other):
        """Support connecting attributes via A >> B"""
        self.connect(other)

    def __lshift__(self, other):
        """Support connecting attributes via A << B"""
        other.connect(self)

    def type(self):
        return self._type

    def read(self):
        value = getAttr(self._node + "." + self)

        # Unpack [(0, 1, 2)] -> (0, 1, 2)
        # E.g. translate is normally returned this way
        if isinstance(value, list) and isinstance(value[0], tuple):
            value = value[0]

        return value

    def write(self, value, type=None):
        kwargs = {}

        if not isinstance(value, (tuple, list)):
            value = [value]

        if type:
            kwargs["type"] = type

        elif isinstance(value, str):
            kwargs["type"] = "string"

        elif isinstance(value, (tuple, list)) and len(value) == 3:
            kwargs["type"] = "double3"

        else:
            raise TypeError("Unsupported type: '%s'" % value)

        setAttr(self._node + "." + self, *value, **kwargs)

    def connect(self, other):
        connectAttr(self._node + "." + self,
                    other._node + "." + other)


# DOCUMENTATION
# =============
#
# Module pre-processing functions.
#
# Each of Maya's commands take as input one of four types of node reference:
#   1. Single arg, arbitrary kwargs, e.g. `
#   2. Multiple args, arbitrary kwargs, e.g. `cmds.parentConstraint
#   3. Single AND multiple args, arbitrary kwargs, e.g. `cmds.select`
#   4. Arbitrary args, arbitrary kwargs, e.g. `cmds.move`
#
# Some references are made with an attribute
#   e.g. cmds.getAttr("myNode.translateX")
#
# The following encapsulates these inputs so as to increase readability
#   of which functions are wrapped, and the manner in which they are
#   wrapped. The key is uniformity; they are all equal, which means bugs
#   are centralised and easier to solve. There is however the risk of
#   esoteric argument handling, such as `cmds.move` which takes a node
#   reference as the 4th argument, `cmds.move(0, 0, 0, node)`.
#
#
# PERFORMANCE
# ===========
#
# The complexity of the part surrounding `wrapper()`
#   affects the time taken to import the module.
#
# The complexity of the contents of `wrapper()` affects the
#   run-time performance of the wrapped function.
#
# A balance is struck where run-time performance is
#   the most important, but import time must also be
#   considered. In an ideal scenario, they are both fast.

def UnchangedOut(result):
    return result


def OneOut(result):
    return encode(result) if result else None


def ManyOut(results):
    results = results or []
    if not isinstance(results, (tuple, list)):
        results = [results]

    return [
        encode(result) for result in results
    ]


def OneOrNoneIn(func, result=UnchangedOut):
    def wrapper(*args, **kwargs):
        if args:
            args = list(args)
            args[0] = decode(args[0])

        return result(
            func(*args, **kwargs)
        )

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def OneIn(func, additional=None, override=None, result=UnchangedOut):
    """Function that takes exactly one argument

    func("single")  # 1. Plain single argument

    """

    additional = additional or []
    override = override or {}

    def wrapper(*args, **kwargs):
        args = list(args)
        args = [decode(args.pop(0))] + args

        for key in kwargs.keys():
            if key in additional:
                kwargs[key] = decode(kwargs[key])

        for key, value in override.items():
            kwargs[key] = value

        return result(
            func(*args, **kwargs)
        )

    wrapper.__doc__ = func.__doc__
    wrapper.__name__ = func.__name__
    return wrapper


def ManyIn(func, additional=None, override=None, result=UnchangedOut):
    """Function that takes either multiple arguments

    In addition, each inner argument may be a tuple or list

    func("arg1")               # 0. Plain single argument
    func("arg1", "arg2")       # 1. Plain multiple arguments
    func("arg1", ["arg2"])     # 2. Mixed arguments
    func(["arg1"])             # 3. Nested single argument
    func(["arg1", "arg2"])     # 4. Nested multiple arguments

    """

    additional = additional or []
    override = override or {}

    def wrapper(*args, **kwargs):
        arguments = list()

        for index, argument in enumerate(args):
            if isinstance(argument, (tuple, list)):
                arguments += [decode(arg) for arg in argument]
            else:
                arguments += [decode(argument)]

        for key in kwargs.keys():
            if key in additional:
                kwargs[key] = decode(kwargs[key])

        for key, value in override.items():
            kwargs[key] = value

        return result(
            func(*arguments, **kwargs)
        )

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def UnchangedIn(func, additional=None, result=UnchangedOut):
    def wrapper(*args, **kwargs):
        for key in kwargs.keys():
            if key in additional:
                kwargs[key] = decode(kwargs[key])

        return result(
            func(*args, **kwargs)
        )

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def encode(path):
    assert path, "No path specified"
    uuids = cmds.ls(path, uuid=True)
    assert len(uuids) > 0, "No matches found for '%s'" % path
    assert len(uuids) < 2, "%d matches found for '%s'" % (len(uuids), path)
    return Node(uuids[0])


def decode(uuid):
    try:
        return cmds.ls(uuid, long=True)[0]
    except IndexError:
        raise NotExistError("%s has been deleted" % uuid)


listConnections = ManyIn(cmds.listConnections, result=ManyOut)
nodeType = OneIn(cmds.nodeType)
objExists = UnchangedIn(cmds.objExists)
select = ManyIn(cmds.select)
rename = OneIn(cmds.rename, result=OneOut)
parent = ManyIn(cmds.parent, result=OneOut)
ls = ManyIn(cmds.ls, override={"long": True}, result=ManyOut)
getAttr = ManyIn(cmds.getAttr)
xform = ManyIn(cmds.xform)
shadingNode = OneIn(cmds.shadingNode, additional=["parent"], result=OneOut)
addAttr = UnchangedIn(cmds.addAttr)
setAttr = UnchangedIn(cmds.setAttr)
connectAttr = UnchangedIn(cmds.connectAttr)
parent = ManyIn(cmds.parent, result=ManyOut)

circle = UnchangedIn(cmds.circle, result=ManyOut)
curve = UnchangedIn(cmds.curve, result=OneOut)
delete = ManyIn(cmds.delete, result=ManyOut)

parentConstraint = ManyIn(cmds.parentConstraint, result=ManyOut)
pointConstraint = ManyIn(cmds.pointConstraint, result=ManyOut)
poleVectorConstraint = ManyIn(cmds.poleVectorConstraint, result=ManyOut)
aimConstraint = ManyIn(cmds.aimConstraint, result=ManyOut)
joint = OneOrNoneIn(cmds.joint, result=OneOut)
hide = ManyIn(cmds.hide)
dgeval = UnchangedIn(cmds.dgeval)
sets = ManyIn(cmds.sets, additional=["forceElement"], result=ManyOut)
ikHandle = UnchangedIn(cmds.ikHandle,
                       additional=["startJoint", "endEffector"],
                       result=ManyOut)
listRelatives = ManyIn(cmds.listRelatives,
                       override={"fullPath": True},
                       result=ManyOut)


def createNode(type, name=None, parent=None):
    kwargs = {}

    if name:
        kwargs["name"] = name

    if type in ("transform",):
        fn = om.MFnDagNode

        if parent:
            kwargs["parent"] = parent
    else:
        fn = om.MFnDependencyNode

    mobj = fn().create(type, **kwargs)
    uuid = fn(mobj).uuid()
    return Node(str(uuid))


def _read(plug):
    attr = plug.attribute()
    type = attr.apiType()

    # Compound
    if type in (om.MFn.kAttribute3Double,
                om.MFn.kAttribute3Float,
                om.MFn.kCompoundAttribute):

        if plug.isCompound:
            count = plug.numChildren()
            return tuple(
                _read(plug.child(c)) for c in range(count)
            )
        else:
            raise TypeError("Type '%s' unsupported" % type)

    # Distance
    elif type in (om.MFn.kDoubleLinearAttribute,
                  om.MFn.kFloatLinearAttribute):
        return plug.asMDistance().asCentimeters()

    # Angle
    elif type in (om.MFn.kDoubleAngleAttribute,
                  om.MFn.kFloatAngleAttribute):
        return plug.asMAngle().asDegrees()

    # Typed
    elif type == om.MFn.kTypedAttribute:
        innerType = om.MFnTypedAttribute(attr).attrType()

        # Matrix
        if innerType == om.MFnData.kMatrix:
            return om.MFnMatrixData(plug.asMObject()).matrix()
        # String
        elif innerType == om.MFnData.kString:
            return plug.asString()

        else:
            raise TypeError("Unsupported typed type: %s" % innerType)

    # Matrix
    elif type == om.MFn.kMatrixAttribute:
        return om.MFnMatrixData(plug.asMObject()).matrix()

    # Number
    elif type == om.MFn.kNumericAttribute:
        innerType = om.MFnNumericAttribute(attr).numericType()

        if innerType == om.MFnNumericData.kBoolean:
            return plug.asBool()

        elif innerType in (om.MFnNumericData.kShort,
                           om.MFnNumericData.kInt,
                           om.MFnNumericData.kLong,
                           om.MFnNumericData.kByte):
            return plug.asInt()

        elif innerType in (om.MFnNumericData.kFloat,
                           om.MFnNumericData.kDouble,
                           om.MFnNumericData.kAddr):
            return plug.asDouble()

        else:
            raise TypeError("Unsupported numeric type: %s" % innerType)

    # Enum
    elif type == om.MFn.kEnumAttribute:
        return plug.asShort()

    elif type == om.MFn.kMessageAttribute:
        return None

    else:
        raise TypeError("Type '%s' unsupported" % type)


def getAttr2(node, name):
    fn = om.MFnDagNode(node)
    attr = fn.attribute(name)
    plug = fn.findPlug(attr, False)
    return _read(plug)


def move(*args, **kwargs):
    """Special case, last argument is a node"""
    args = list(args)
    args[-1] = decode(args[-1])
    cmds.move(*args, **kwargs)


def nameExists(name):
    return cmds.objExists(name)


def mkdirs(path):
    try:
        # If it exists
        return encode(path)
    except AssertionError:
        pass

    nodes = list()
    parent = "|"
    for index, node in enumerate(path.split("|")):
        if not node:
            continue

        kwargs = {"name": node}
        if parent.strip("|"):
            kwargs["parent"] = parent

        if not cmds.objExists(parent + node):
            nodes += [cmds.createNode("transform", **kwargs)]

        parent += node + "|"

    return encode(nodes[-1])
