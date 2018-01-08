# -*- coding: utf-8 -*-
import os
import sys
import json
import logging

from maya import cmds
from maya.api import OpenMaya as om

IGNORE_VERSION = bool(os.getenv("CMDX_IGNORE_VERSION"))

__version__ = "0.1.0"
__maya_version__ = int(cmds.about(version=True))

# TODO: Lower this requirement
if not IGNORE_VERSION:
    assert __maya_version__ >= 2015, "Requires Maya 2015 or newer"

self = sys.modules[__name__]
log = logging.getLogger("cmdx")

NotExistError = type("NotExistError", (KeyError,), {})
AlreadyExistError = type("AlreadyExistError", (KeyError,), {})

# Reusable objects, for performance
GlobalDagNode = om.MFnDagNode()
GlobalDependencyNode = om.MFnDependencyNode()

First = 0
Last = -1


class _Unit(int):
    """A Maya unit, for unit-attributes such as Angle and Distance

    Because the resulting classes are subclasses of `int`, there
    is virtually no run-time performance penalty to using it as
    an integer. No additional Python is called, most notably when
    passing the integer class to the Maya C++ binding (which wouldn't
    call our overridden methods anyway).

    The added overhead to import time is neglible.

    """

    def __new__(cls, unit, enum):
        self = super(_Unit, cls).__new__(cls, enum)
        self._unit = unit
        return self

    def __call__(self, enum):
        return self._unit(enum, self)


# Angular units
Degrees = _Unit(om.MAngle, om.MAngle.kDegrees)
Radians = _Unit(om.MAngle, om.MAngle.kRadians)
AngularMinutes = _Unit(om.MAngle, om.MAngle.kAngMinutes)
AngularSeconds = _Unit(om.MAngle, om.MAngle.kAngSeconds)

# Distance units
Millimeters = _Unit(om.MDistance, om.MDistance.kMillimeters)
Centimeters = _Unit(om.MDistance, om.MDistance.kCentimeters)
Meters = _Unit(om.MDistance, om.MDistance.kMeters)
Kilometers = _Unit(om.MDistance, om.MDistance.kKilometers)
Inches = _Unit(om.MDistance, om.MDistance.kInches)
Feet = _Unit(om.MDistance, om.MDistance.kFeet)
Miles = _Unit(om.MDistance, om.MDistance.kMiles)
Yards = _Unit(om.MDistance, om.MDistance.kYards)


class Node(object):
    """A Maya dependency node

    Example:
        >>> _ = cmds.file(new=True, force=True)
        >>> decompose = createNode("decomposeMatrix", name="decompose")
        >>> str(decompose)
        'decompose'
        >>> alias = encode(decompose.name())
        >>> decompose == alias
        True
        >>> transform = createNode("transform")
        >>> transform["tx"] = 5
        >>> transform >> decompose
        >>> decompose["outputTranslate"]
        (5.0, 0, 0)

    """

    _Fn = om.MFnDependencyNode

    def __eq__(self, other):
        """MObject supports this operator explicitly"""
        return self._mobject == other._mobject

    def __neq__(self, other):
        return self._mobject != other._mobject

    def __str__(self):
        return self.name()

    def __repr__(self):
        return self.name()

    def __rshift__(self, other):
        """Support connecting nodes via A >> B"""
        return self.connect(other)

    def __lshift__(self, other):
        """Support connecting nodes via A << B"""
        other.connect(self)

    def __add__(self, other):
        """Support legacy + '.attr' behavior

        Example:
            >>> node = createNode("transform")
            >>> getAttr(node + ".tx")
            0.0
            >>> delete(node)

        """

        return self[other.strip(".")]

    def __getitem__(self, key):
        """Get plug from self

        Arguments:
            key (str, tuple): String lookup of attribute,
                optionally pass tuple to include unit.

        Example:
            >>> node = createNode("transform")
            >>> node["translate"] = (1, 1, 1)
            >>> node["translate", Meters]
            (0.01, 0.01, 0.01)

        """

        unit = None
        if isinstance(key, (list, tuple)):
            key, unit = key

        try:
            plug = self._fn.findPlug(key, False)
        except RuntimeError:
            raise NotExistError(key)

        return Plug(self, plug, unit=unit)

    def __setitem__(self, key, value):
        """Support item assignment of new attributes or values

        Example:
            >>> node = createNode("transform")
            >>> node["myAttr"] = Double(default=1.0)
            >>> node["myAttr"] == 1.0
            True
            >>> node["rotateX", Degrees] = 1.0
            >>> node["rotateX"] = Degrees(1)
            >>> node["rotateX", Degrees]
            1.0
            >>> round(node["rotateX", Radians], 3)
            0.017
            >>> delete(node)

        """

        unit = None
        if isinstance(key, (list, tuple)):
            key, unit = key
            value = unit(value)

        # Create a new attribute
        if isinstance(value, (tuple, list)):
            if isinstance(value[0], type):
                if issubclass(value[0], _AbstractAttribute):
                    Attribute, kwargs = value
                    attr = Attribute(key, **kwargs).create()

                    try:
                        return self.addAttr(attr)

                    except RuntimeError:
                        # NOTE: I can't be sure this is the only occasion
                        # where this exception is thrown. Stay catious.
                        raise AlreadyExistError(key)

        # Set an existing attribute
        if isinstance(value, Plug):
            value = value.read(unit=unit)

        try:
            plug = self._fn.findPlug(key, False)
        except RuntimeError:
            raise KeyError(key)

        Plug(self, plug, unit=unit).write(value)

    def __delitem__(self, key):
        self.deleteAttr(key)

    def __init__(self, mobject):
        self._mobject = mobject
        self._fn = self._Fn(mobject)

    def name(self):
        """Return the name of this node

        Example:
            >>> node = createNode("transform", name="myName")
            >>> node.name()
            u'myName'

        """

        return self._fn.name()

    def uuid(self):
        """Return UUID of node

        Example:
            >>> node = createNode("transform")
            >>> uuid = node.uuid()

        """

        return self._fn.uuid()

    def connect(self, other):
        """Attempt to automatically connect one node to another

        This makes a "best guess" estimate on which plugs of which
        node to connect. For example, connecting two Transform nodes
        results in their transformation channels - translate, rotate
        and scale - to be connected.

        Example:
            >>> node1 = createNode("transform")
            >>> node2 = createNode("transform")
            >>> node1 >> node2
            >>> for connection in node1["t"].connections():
            ...   assert connection == node2["t"]
            ...

        """

        if self == other:
            raise TypeError("Cannot connect node to itself")

        this_type = self.type()
        other_type = other.type()

        if this_type == "transform" and other_type == "transform":
            self["translate"] >> other["translate"]
            self["rotate"] >> other["rotate"]
            self["scale"] >> other["scale"]

        elif this_type == "decomposeMatrix" and other_type == "transform":
            self["outputTranslate"] >> other["translate"]
            self["outputRotate"] >> other["rotate"]
            self["outputScale"] >> other["scale"]

        elif this_type == "transform" and other_type == "decomposeMatrix":
            self["outputTranslate"] << other["translate"]
            self["outputRotate"] << other["rotate"]
            self["outputScale"] << other["scale"]

        else:
            raise TypeError(
                "Could not determine how to connect %s -> %s"
                % (this_type, other_type)
            )

    def update(self, attrs):
        """Add `attrs` to self

        Arguments:
            attrs (dict): Key/value pairs of name and attribute

        Example:
            >>> node = createNode("transform")
            >>> node.update({
            ...   "translateX": 1.0,
            ...   "translateY": 1.0,
            ...   "translateZ": 5.0,
            ... })
            ...
            >>> node["tx"] == 1.0
            True

        """

        for key, value in attrs.items():
            self[key] = value

    def pop(self, key):
        """Delete an attribute

        Arguments:
            key (str): Name of attribute to delete

        Example:
            >>> node = createNode("transform")
            >>> node["myAttr"] = Double()
            >>> node.pop("myAttr")
            >>> node.hasAttr("myAttr")
            False

        """

        del self[key]

    def dump(self, detail=0):
        """Return dictionary of all attributes"""

        attrs = {}
        count = self._fn.attributeCount()
        for index in range(count):
            obj = self._fn.attribute(index)
            plug = self._fn.findPlug(obj, False)

            try:
                value = Plug(self, plug).read()
            except RuntimeError:
                # TODO: Support more types of attributes,
                # such that this doesn't need to happen.
                value = None

            attrs[plug.name()] = value

        return attrs

    def dumps(self, indent=4, sortKeys=True):
        """Return a JSON compatible dictionary of all attributes"""
        return json.dumps(self.dump(), indent=indent, sort_keys=sortKeys)

    def type(self):
        """Return type name"""
        return self._fn.typeName

    def addAttr(self, attr):
        """Add a new dynamic attribute to node

        Arguments:
            attr (Plug): Add this attribute

        Example:
            >>> node = createNode("transform")
            >>> attr = Double("myAttr", default=5.0)
            >>> node.addAttr(attr)
            >>> node["myAttr"] == 5.0
            True

        """

        if isinstance(attr, _AbstractAttribute):
            attr = attr.create()

        self._fn.addAttribute(attr)

    def hasAttr(self, attr):
        """Return whether or not `attr` exists

        Arguments:
            attr (str): Name of attribute to check

        """

        return self._fn.hasAttribute(attr)

    def deleteAttr(self, attr):
        """Delete `attr` from node

        Arguments:
            attr (Plug): Attribute to remove

        Example:
            >>> node = createNode("transform")
            >>> node["myAttr"] = Double()
            >>> node.deleteAttr("myAttr")
            >>> node.hasAttr("myAttr")
            False

        """

        if not isinstance(attr, Plug):
            attr = self[attr]

        attribute = attr._mplug.attribute()
        self._fn.removeAttribute(attribute)

    def connections(self, unit=None):
        """Yield plugs of node with a connection to any other plug

        Arguments:
            unit (int, optional): Return plug in this unit,
                e.g. Meters or Radians

        """

        for plug in self._fn.getConnections():
            yield Plug(plug.node(), plug, unit)


class DagNode(Node):
    """A Maya DAG node

    The difference between this and Node is that a DagNode
    can have children and a parent.

    Example:
        >>> parent = createNode("transform")
        >>> child = createNode("transform", parent=parent)
        >>> child.parent() == parent
        True
        >>> next(parent.children()) == child
        True
        >>> parent.child() == child
        True
        >>> sibling = createNode("transform", parent=parent)
        >>> list(parent.siblings()) == [child, sibling]
        >>> shape = createNode("mesh", parent=child)
        >>> child.shape() == shape
        True
        >>> shape.parent() == child
        True

    """

    _Fn = om.MFnDagNode

    def __str__(self):
        return self.path()

    def __repr__(self):
        return self.path()

    def path(self):
        """Return full path to node

        Example:
            >>> parent = createNode("transform", "myParent")
            >>> child = createNode("transform", "myChild", parent=parent)
            >>> child.name()
            u'myChild'
            >>> child.path()
            u'|myParent|myChild'

        """

        return self._fn.fullPathName()

    def shortestPath(self):
        """Return shortest unique path to node

        Example:
            >>> parent = createNode("transform", "myParent")
            >>> child = createNode("transform", "myChild", parent=parent)
            >>> child.shortestPath()
            u'myChild'
            >>> child = createNode("transform", "myChild")
            >>> # Now `myChild` could refer to more than a single node
            >>> child.shortestPath()
            u'myParent|myChild'

        """

        return self._fn.partialPathName()

    def addChild(self, child, index=Last):
        """Add `child` to self

        Arguments:
            child (Node): Child to add
            index (int, optional): Physical location in hierarchy,
                defaults to cmdx.Last

        Example:
            >>> parent = createNode("transform")
            >>> child = createNode("transform")
            >>> parent.addChild(child)

        """

        self._fn.addChild(child._mobject, index)

    def assembly(self):
        """Return the top-level parent of node

        Example:
            >>> parent1 = createNode("transform")
            >>> parent2 = createNode("transform")
            >>> child = createNode("transform", parent=parent1)
            >>> grandchild = createNode("transform", parent=child)
            >>> child.assembly() == parent1
            True
            >>> parent2.assembly() == parent2
            True

        """

        path = self._fn.getPath()

        root = None
        for level in range(path.length() - 1):
            root = path.pop()

        return self.__class__(root.node()) if root else self

    # Alias
    root = assembly

    def parent(self, type=None):
        """Return parent of node

        Arguments:
            type (str, optional): Return parent, only if it matches this type

        Example:
            >>> parent = createNode("transform")
            >>> child = createNode("transform", parent=parent)
            >>> child.parent() == parent
            True
            >>> not child.parent(type="camera")
            True

        """

        mobject = self._fn.parent(0)

        if mobject.apiType() == om.MFn.kWorld:
            return

        cls = self.__class__
        fn = self._fn.__class__(mobject)

        if not type or type == fn.typeName:
            return cls(mobject)

    def children(self, type=None, filter=om.MFn.kTransform):
        """Return children of node

        Arguments:
            type (str, optional): Return only children that match this type
            filter (int, optional): Return only children with this function set

        """

        cls = self.__class__
        Fn = self._fn.__class__

        for index in range(self._fn.childCount()):
            mobject = self._fn.child(index)

            if not mobject.hasFn(filter):
                continue

            fn = Fn(mobject)
            if not type or type == fn.typeName:
                yield cls(mobject)

    def child(self, type=None):
        return next(self.children(type), None)

    def shapes(self, type=None):
        return self.children(type, om.MFn.kShape)

    def shape(self, type=None):
        return next(self.shapes(type), None)

    def siblings(self):
        pass

    def descendents(self, type=om.MFn.kInvalid):
        assert __maya_version__ >= 2017, "Requires Maya 2017 or newer"
        typeName = None

        # Support filtering by typeName
        if isinstance(type, str):
            typeName = type
            type = om.MFn.kInvalid

        it = om.MItDag(om.MItDag.kDepthFirst, om.MFn.kInvalid)
        it.reset(self._mobject, om.MItDag.kDepthFirst, type)

        while not it.isDone():
            mobj = it.currentItem()
            node = DagNode(mobj)

            if not typeName or typeName == node._fn.typeName:
                yield node

            it.next()


class Plug(object):
    def __abs__(self):
        return abs(self.read())

    def __bool__(self):
        """if plug:"""
        return bool(self.read())

    # Python 3
    __nonzero__ = __bool__

    def __float__(self):
        return float(self.read())

    def __int__(self):
        return int(self.read())

    def __eq__(self, other):
        if isinstance(other, type(self)):
            other = other.read()
        return self.read() == other

    def __neq__(self, other):
        if isinstance(other, type(self)):
            other = other.read()
        return self.read() != other

    def __div__(self, other):
        """Python 2.x division"""
        if isinstance(other, type(self)):
            other = other.read()
        return self.read() / other

    def __floordiv__(self, other):
        """Integer division, e.g. self // other"""
        if isinstance(other, type(self)):
            other = other.read()
        return self.read() // other

    def __truediv__(self, other):
        """Float division, e.g. self / other"""
        if isinstance(other, type(self)):
            other = other.read()
        return self.read() / other

    def __add__(self, other):
        if isinstance(other, str):
            return self._node[self.name() + other]

        raise TypeError(
            "unsupported operand type(s) for +: 'Plug' and '%s'"
            % type(other)
        )

    def __str__(self):
        return str(self.read())

    def __repr__(self):
        return str(self.read())

    def __rshift__(self, other):
        """Support connecting attributes via A >> B"""
        self.connect(other)

    def __lshift__(self, other):
        """Support connecting attributes via A << B"""
        other.connect(self)

    def __iter__(self):
        for value in self.read():
            yield value

    def __getitem__(self, index):
        cls = self.__class__

        if self._mplug.isArray:
            index = self._mplug.elementByLogicalIndex(index)
            return cls(self._node, index, self._unit)

        elif self._mplug.isCompound:
            index = self._mplug.child(index)
            return cls(self._node, index, self._unit)

        else:
            raise TypeError("%s does not support indexing "
                            "(it is neither array nor "
                            "compound attribute)" % self.path())

    def __init__(self, node, mplug, unit=None):
        self._node = node
        self._mplug = mplug
        self._unit = unit

    def type(self):
        return self._mplug.attribute().apiTypeStr

    def path(self):
        return self._mplug.partialName(
            includeNodeName=True,
            useLongNames=True,
            useFullAttributePath=True
        )

    def name(self):
        return self._mplug.partialName(
            includeNodeName=False,
            useLongNames=False,
            useFullAttributePath=True
        )

    def read(self):
        try:
            return _plug_to_python(self._mplug, self._unit)

        except RuntimeError:
            raise

        except TypeError:
            # Expected errors
            log.warning("'%s': failed to read attribute" % self.path())
            return None

    def write(self, value):
        try:
            return _python_to_plug(value, self)

        except RuntimeError:
            raise

        except TypeError:
            log.warning("'%s': failed to write attribute" % self.path())
            return None

    def connect(self, other):
        mod = om.MDGModifier()
        mod.connect(self._mplug, other._mplug)
        mod.doIt()

    def connections(self, source=True, destination=True, unit=None):
        """Yield plugs connected to self

        Arguments:
            source (bool, optional): Return source plugs,
                default is True
            destination (bool, optional): Return destination plugs,
                default is True
            unit (int, optional): Return plug in this unit, e.g. Meters

        """

        cls = self.__class__

        for plug in self._mplug.connectedTo(source, destination):
            yield cls(plug.node(), plug, unit)


def _plug_to_python(plug, unit=None):
    """Convert native `plug` to Python type

    Arguments:
        plug (om.MPlug): Native Maya plug

    """

    if plug.isCompound:
        return tuple(
            _plug_to_python(plug.child(index), unit)
            for index in range(plug.numChildren())
        )

    elif plug.isArray:
        # E.g. transform["worldMatrix"]
        return tuple(
            _plug_to_python(plug.elementByLogicalIndex(index), unit)
            for index in range(plug.numElements())
        )

    attr = plug.attribute()
    type = attr.apiType()
    if type == om.MFn.kTypedAttribute:
        innerType = om.MFnTypedAttribute(attr).attrType()

        if innerType == om.MFnData.kAny:
            # E.g. choice["input"][0]
            return None

        elif innerType == om.MFnData.kMatrix:
            # E.g. transform["worldMatrix"][0]
            return tuple(om.MFnMatrixData(plug.asMObject()).matrix())

        elif innerType == om.MFnData.kString:
            return plug.asString()

        elif innerType == om.MFnData.kInvalid:
            # E.g. time1.timewarpIn_Hidden
            # Unsure of why some attributes are invalid
            return None

        else:
            raise TypeError("Unsupported typed type: %s"
                            % innerType)

    elif type == om.MFn.kMatrixAttribute:
        return tuple(om.MFnMatrixData(plug.asMObject()).matrix())

    elif type in (om.MFn.kDoubleLinearAttribute,
                  om.MFn.kFloatLinearAttribute):
        if unit is None:
            return plug.asMDistance().asUnits(om.MDistance.uiUnit())
        elif unit == Millimeters:
            return plug.asMDistance().asMillimeters()
        elif unit == Centimeters:
            return plug.asMDistance().asCentimeters()
        elif unit == Meters:
            return plug.asMDistance().asMeters()
        elif unit == Kilometers:
            return plug.asMDistance().asKilometers()
        elif unit == Inches:
            return plug.asMDistance().asInches()
        elif unit == Feet:
            return plug.asMDistance().asFeet()
        elif unit == Miles:
            return plug.asMDistance().asMiles()
        elif unit == Yards:
            return plug.asMDistance().asYards()
        else:
            raise TypeError("Unsupported unit '%d'" % unit)

    elif type in (om.MFn.kDoubleAngleAttribute,
                  om.MFn.kFloatAngleAttribute):
        if unit is None:
            return plug.asMAngle().asUnits(om.MAngle.uiUnit())
        elif unit == Degrees:
            return plug.asMAngle().asDegrees()
        elif unit == Radians:
            return plug.asMAngle().asRadians()
        elif unit == AngularSeconds:
            return plug.asMAngle().asAngSeconds()
        elif unit == AngularMinutes:
            return plug.asMAngle().asAngMinutes()
        else:
            raise TypeError("Unsupported unit '%d'" % unit)

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
            raise TypeError("Unsupported numeric type: %s"
                            % innerType)

    # Enum
    elif type == om.MFn.kEnumAttribute:
        return plug.asShort()

    elif type == om.MFn.kMessageAttribute:
        return None

    elif type == om.MFn.kTimeAttribute:
        return plug.asShort()

    elif type == om.MFn.kInvalid:
        raise TypeError("%s was invalid" % plug.name())

    else:
        raise TypeError("Unsupported type '%s'" % type)


def _python_to_plug(value, plug):
    """Pass value of `value` to `plug`

    Arguments:
        value (any): Instance of Python or Maya type
        plug (Plug): Target plug to which value is applied

    """

    # Native Python types

    if isinstance(value, str):
        plug._mplug.setString(value)

    elif isinstance(value, int):
        plug._mplug.setInt(value)

    elif isinstance(value, float):
        plug._mplug.setDouble(value)

    elif isinstance(value, bool):
        plug._mplug.setBool(value)

    # Native Maya types

    elif isinstance(value, om.MAngle):
        plug._mplug.setMAngle(value)

    elif isinstance(value, om.MDistance):
        plug._mplug.setMDistance(value)

    elif isinstance(value, om.MTime):
        plug._mplug.setMTime(value)

    # Compound values

    elif isinstance(value, (tuple, list)):
        for index, value in enumerate(value):

            # Tuple values are assumed flat:
            #   e.g. (0, 0, 0, 0)
            # Nested values are not supported:
            #   e.g. ((0, 0), (0, 0))
            # Those can sometimes appear in e.g. matrices
            if isinstance(value, (tuple, list)):
                raise TypeError(
                    "Unsupported nested Python type: %s"
                    % value.__class__
                )

            _python_to_plug(value, plug[index])

    else:
        raise TypeError("Unsupported Python type '%s'" % value.__class__)


def encode(path):
    """Convert relative or absolute `path` to cmdx Node

    Fastest conversion from absolute path to Node

    Arguments:
        path (str): Absolute or relative path to DAG or DG node

    """

    selectionList = om.MSelectionList()
    selectionList.add(path)
    mobj = selectionList.getDependNode(0)

    if mobj.hasFn(om.MFn.kDagNode):
        return DagNode(mobj)
    else:
        return Node(mobj)


def decode(node):
    """Convert cmdx Node to shortest unique path

    This is the same as `node.shortestPath()`
    To get an absolute path, use `node.path()`

    """

    return node.shortestPath()


def createNode(type, name=None, parent=None, skipSelect=True, shared=False):
    """Create a new node

    This function forms the basic building block
    with which to create new nodes in Maya.

    .. note:: Missing arguments `shared` and `skipSelect`
    .. tip:: For performance, `type` may be given as a TypeId

    Arguments:
        type (str): Type name of new node, e.g. "transform"
        name (str, optional): Sets the name of the newly-created node
        parent (Node, optional): Specifies the parent in the DAG under which
            the new node belongs
        skipSelect (bool, optional): Unused; always True
        shared (bool, optional): Unused; always False

    Example:
        >>> node = createNode("transform")  # Type as string
        >>> node = createNode(Transform)  # Type as ID

    """

    kwargs = {}
    fn = GlobalDependencyNode

    if name:
        kwargs["name"] = name

    if parent:
        kwargs["parent"] = parent._mobject
        fn = GlobalDagNode

    try:
        mobj = fn.create(type, **kwargs)
    except RuntimeError:
        raise TypeError("Unrecognized node type '%s'" % type)

    if fn is GlobalDagNode or mobj.hasFn(om.MFn.kDagNode):
        return DagNode(mobj)
    else:
        return Node(mobj)


def getAttr(attr, type=None):
    """Read `attr`

    Arguments:
        attr (Plug): Attribute as a cmdx.Plug
        type (str, optional): Unused

    Example:
        >>> node = createNode("transform")
        >>> getAttr(node + ".translateX")
        0.0

    """

    return attr.read()


def setAttr(attr, value, type=None):
    """Write `value` to `attr`

    Arguments:
        attr (Plug): Existing attribute to edit
        value (any): Value to write
        type (int, optional): Unused

    Example:
        >>> node = createNode("transform")
        >>> setAttr(node + ".translateX", 5.0)

    """

    attr.write(value)


def addAttr(node,
            longName,
            attributeType,
            shortName=None,
            enumName=None,
            defaultValue=None):
    """Add new attribute to `node`

    Arguments:
        node (Node): Add attribute to this node
        longName (str): Name of resulting attribute
        attributeType (str): Type of attribute, e.g. `string`
        shortName (str, optional): Alternate name of attribute
        enumName (str, optional): Options for an enum attribute
        defaultValue (any, optional): Default value of attribute

    Example:
        >>> node = createNode("transform")
        >>> addAttr(node, "myString", attributeType="string")
        >>> addAttr(node, "myDouble", attributeType=Double)

    """

    at = attributeType
    if isinstance(at, type) and issubclass(at, _AbstractAttribute):
        Attribute = attributeType

    else:
        # Support legacy maya.cmds interface
        Attribute = {
            "double": Double,
            "double3": Double3,
            "string": String,
            "long": Long,
            "bool": Boolean,
            "enume": Enum,
        }[attributeType]

    kwargs = {
        "shortName": shortName,
        "default": defaultValue
    }

    if enumName:
        kwargs["fields"] = enumName.split(":")

    attribute = Attribute(longName, **kwargs)
    node.addAttr(attribute)


def listRelatives(node,
                  type=None,
                  children=False,
                  allDesdencents=False,
                  fullPath=True,
                  parent=False,
                  path=True,
                  noIntermediate=False,
                  allParents=False,
                  shapes=False):
    """List relatives of `node`

    Arguments:
        node (DagNode): Node to enquire about
        type (int, optional): Only return nodes of this type
        children (bool, optional): Return children of `node`
        parent (bool, optional): Return parent of `node`
        shapes (bool, optional): Return only children that are shapes
        allDescendents (bool, optional): Return descendents of `node`
        fullPath (bool, optional): Unused; nodes are always exact
        path (bool, optional): Unused; nodes are always exact

    Example:
        >>> parent = createNode("transform")
        >>> child = createNode("transform", parent=parent)
        >>> listRelatives(child, parent=True) == [parent]
        True

    """

    if not isinstance(node, DagNode):
        return None

    elif allDesdencents:
        return list(node.descendents(type=type))

    elif shapes:
        return list(node.shapes(type=type))

    elif parent:
        return [node.parent(type=type)]

    elif children:
        return list(node.children(type=type))


def listConnections(attr,
                    source=False,
                    destination=True,
                    connections=False,
                    exactType=False,
                    plugs=False,
                    shapes=False,
                    skipConversionNodes=False,
                    type=None):
    """List connections to `attr`

    Arguments:
        attr (Plug or Node):
        connections (bool, optional): List plugs from both
            source and destination
        destination (bool, optional): List plugs from the destination side
        source (bool, optional): List plugs from the source side
        type (str, optional): When returning nodes, only return nodes
            of this node type; e.g. "transform"
        exactType (bool, optional): Unused; always True
        skipConversionNodes (bool, optional): Unused; always False

    Example:
        >>> node1 = createNode("transform")
        >>> node2 = createNode("transform")
        >>> node1["tx"] >> node2["tx"]
        >>> listConnections(node1) == [node2]
        True
        >>> listConnections(node1 + ".tx") == [node2]
        True
        >>> listConnections(node1["tx"]) == [node2]
        True

    """

    if connections:
        destination, source = True, True

    if isinstance(attr, Plug):
        its = [attr.connections(
            destination=destination,
            source=source,
        )]

    elif isinstance(attr, Node):
        # Return connections to all
        # connected attributes of Node
        its = iter(
            a.connections(
                destination=destination,
                source=source
            )
            for a in attr.connections()
        )

    else:
        raise TypeError("Invalid type '%s'" % type(attr))

    output = list()
    for it in its:
        for plug in it:

            if plugs:
                output.append(plug)
                continue

            node = plug._mplug.node()

            if not shapes and node.hasFn(om.MFn.kShape):
                node = om.MFnDagNode(node).parent(0)

            if not type or type == node.typeName():
                if node.hasFn(om.MFn.kDagNode):
                    node = DagNode(node)
                else:
                    node = Node(node)

                output.append(node)

    return output


def connectAttr(src, dst):
    """Connect `src` to `dst`

    Arguments:
        src (Plug): Source plug
        dst (Plug): Destination plug

    Example:
        >>> src = createNode("transform")
        >>> dst = createNode("transform")
        >>> connectAttr(src + ".rotateX", dst + ".scaleY")

    """

    src.connect(dst)


def ls(selection=False, type=om.MFn.kInvalid):
    nodes = list()

    if selection:
        return self.selection(type)

    it = om.MItDependencyNodes(type)
    while not it.isDone():
        mobj = it.thisNode()

        if mobj.hasFn(om.MFn.kDagNode):
            nodes.append(DagNode(mobj))
        else:
            nodes.append(Node(mobj))

        it.next()

    return nodes


def selection(type=None):
    # TODO: Needs a faster solution without `cmds`
    kwargs = {"selection": True, "long": True}

    if type:
        kwargs["type"] = type

    return [
        encode(path) for path in cmds.ls(**kwargs)
    ]

    nodes = list()
    selectionList = om.MGlobal.getActiveSelectionList()

    if not selectionList.length() > 0:
        return nodes

    it = om.MItSelectionList(selectionList, om.MFn.kDagNode)

    while not it.isDone():
        mobj = it.currentItem()

        if mobj.hasFn(om.MFn.kDagNode):
            nodes.append(DagNode(mobj))
        else:
            nodes.append(Node(mobj))

        it.next()


def delete(*nodes):
    mod = om.MDGModifier()

    for node in nodes:
        mod.deleteNode(node._mobject)

    mod.doIt()


def select(nodes, replace=True):
    if not isinstance(nodes, (tuple, list)):
        nodes = [nodes]

    # TODO: Needs a faster solution without `cmds`
    nodes = [decode(node) for node in nodes]
    cmds.select(nodes, replace=replace)


def parent(children, parent, relative=True, absolute=False):
    assert isinstance(parent, DagNode), "parent must be DagNode"

    if not isinstance(children, (tuple, list)):
        children = [children]

    for child in children:
        assert isinstance(child, DagNode), "child must be DagNode"
        parent.addChild(child)


def objExists(obj):
    if isinstance(obj, (Node, Plug)):
        obj = obj.path()

    try:
        om.MSelectionList().add(obj)
    except RuntimeError:
        return False
    else:
        return True


# --------------------------------------------------------
#
# Attribute Types
#
# --------------------------------------------------------


class _AbstractAttribute(dict):
    Fn = None
    Type = None
    Default = None

    Readable = True
    Writable = True
    Cached = False  # Cache in datablock?
    Storable = True  # Write value to file?
    Hidden = False  # Display in Attribute Editor?

    Array = False
    Connectable = True

    Keyable = True
    ChannelBox = False

    def __eq__(self, other):
        try:
            # Support Attribute -> Attribute comparison
            return self["name"] == other["name"]
        except AttributeError:
            # Support Attribute -> string comparison
            return self["name"] == other

    def __neq__(self, other):
        try:
            return self["name"] != other["name"]
        except AttributeError:
            return self["name"] != other

    def __hash__(self):
        """Support storing in set()"""
        return hash(self["name"])

    def __repr__(self):
        """Avoid repr depicting the full contents of this dict"""
        return self["name"]

    def __new__(cls, *args, **kwargs):
        if not args:
            return cls, kwargs
        return super(_AbstractAttribute, cls).__new__(cls, *args, **kwargs)

    def __init__(self,
                 name,
                 shortName=None,
                 default=None,
                 label=None,

                 writable=None,
                 readable=None,
                 cached=None,
                 storable=None,
                 keyable=None,
                 hidden=None,
                 channelBox=None,
                 array=False,
                 connectable=True):

        self["name"] = name
        self["shortName"] = shortName or name
        self["label"] = label
        self["default"] = default or self.Default

        self["writable"] = writable or self.Writable
        self["readable"] = readable or self.Readable
        self["cached"] = cached or self.Cached
        self["storable"] = storable or self.Storable
        self["keyable"] = keyable or self.Keyable
        self["hidden"] = hidden or self.Hidden
        self["channelBox"] = channelBox or self.ChannelBox
        self["array"] = array or self.Array
        self["connectable"] = connectable or self.Connectable

        # Filled in on creation
        self["mobject"] = None

    def default(self):
        """Return one of three available values

        Resolution order:
            1. Argument
            2. Node default (from cls.defaults)
            3. Attribute default

        """

        if self["default"] is not None:
            return self["default"]

        return self.Default

    def type(self):
        return self.Type

    def create(self):
        args = [
            arg
            for arg in (self["name"],
                        self["shortName"],
                        self.type())
            if arg is not None
        ]

        default = self.default()
        if default:
            if isinstance(default, (list, tuple)):
                args += default
            else:
                args += [default]

        self["mobject"] = self.Fn.create(*args)

        # 3 μs
        self.Fn.storable = self["storable"]
        self.Fn.readable = self["readable"]
        self.Fn.writable = self["writable"]
        self.Fn.hidden = self["hidden"]
        self.Fn.channelBox = self["channelBox"]
        self.Fn.keyable = self["keyable"]
        self.Fn.array = self["array"]

        if self["label"] is not None:
            self.Fn.setNiceNameOverride(self["label"])

        return self["mobject"]

    def read(self, data):
        pass


class Enum(_AbstractAttribute):
    Fn = om.MFnEnumAttribute()
    Type = None
    Default = 0

    Keyable = True

    def __init__(self, name, fields=None, default=0, label=None):
        super(Enum, self).__init__(name, default, label)

        self.update({
            "fields": fields or (name,),
        })

    def create(self):
        attr = super(Enum, self).create()

        for index, field in enumerate(self["fields"]):
            self.Fn.addField(field, index)

        return attr

    def read(self, data):
        return data.inputValue(self["mobject"]).asShort()


class Divider(Enum):
    """Visual divider in channel box"""

    def __init__(self, label):
        super(Divider, self).__init__("_", fields=(label,), label=" ")


class String(_AbstractAttribute):
    Fn = om.MFnTypedAttribute()
    Type = om.MFnData.kString
    Default = ""

    def default(self):
        default = super(String, self).default()
        return om.MFnStringData().create(default)

    def read(self, data):
        return data.inputValue(self["mobject"]).asString()


class Message(_AbstractAttribute):
    Fn = om.MFnMessageAttribute()
    Type = None
    Default = None
    Storable = False


class Matrix(_AbstractAttribute):
    Fn = om.MFnMatrixAttribute()

    Default = (0.0,) * 4 * 4  # Identity matrix

    Array = True
    Readable = True
    Keyable = False
    Hidden = False

    def default(self):
        return None

    def read(self, data):
        return data.inputValue(self["mobject"]).asMatrix()


class Long(_AbstractAttribute):
    Fn = om.MFnNumericAttribute()
    Type = om.MFnNumericData.kLong
    Default = 0

    def read(self, data):
        return data.inputValue(self["mobject"]).asLong()


class Double(_AbstractAttribute):
    Fn = om.MFnNumericAttribute()
    Type = om.MFnNumericData.kDouble
    Default = 0.0

    def read(self, data):
        return data.inputValue(self["mobject"]).asDouble()


class Double3(_AbstractAttribute):
    Fn = om.MFnNumericAttribute()
    Type = None
    Default = (0.0,) * 3

    def default(self):
        default = self.get("default")

        # Support single-value default
        if isinstance(default, int):
            default = (default, default, default)

        children = list()
        for index, child in enumerate("XYZ"):
            attribute = self.Fn.create(self["name"] + child,
                                       self["shortName"] + child,
                                       om.MFnNumericData.kDouble,
                                       default[index])
            children.append(attribute)

        return children

    def read(self, data):
        return data.inputValue(self["mobject"]).asDouble3()


class Boolean(_AbstractAttribute):
    Fn = om.MFnNumericAttribute()
    Type = om.MFnNumericData.kBoolean
    Default = True

    def read(self, data):
        return data.inputValue(self["mobject"]).asBool()


class AbstractUnit(_AbstractAttribute):
    Fn = om.MFnUnitAttribute()
    Default = 0.0
    Min = None
    Max = None
    SoftMin = None
    SoftMax = None


class Angle(AbstractUnit):
    def default(self):
        default = super(Angle, self).default()

        # When no unit was explicitly passed, assume degrees
        if not isinstance(default, om.MAngle):
            default = om.MAngle(default, om.MAngle.kDegrees)

        return default


class Time(AbstractUnit):
    def default(self):
        default = super(Time, self).default()

        # When no unit was explicitly passed, assume seconds
        if not isinstance(default, om.MTime):
            default = om.MTime(default, om.MTime.kSeconds)

        return default


class Distance(AbstractUnit):
    def default(self):
        default = super(Distance, self).default()

        # When no unit was explicitly passed, assume centimeters
        if not isinstance(default, om.MDistance):
            default = om.MDistance(default, om.MDistance.kCentimeters)

        return default


class Compound(_AbstractAttribute):
    Fn = om.MFnCompoundAttribute()

    def __init__(self, name, children, **kwargs):
        super(Compound, self).__init__(name, **kwargs)
        self["children"] = children

    def create(self):
        mobj = super(Compound, self).create()

        for child in self["children"]:
            self.Fn.addChild(child.create())

        return mobj


# --------------------------------------------------------
#
# Commonly Node Types
#
# Creating a new node using a pre-defined Type ID is 10% faster
# than doing it using a string, but keeping all (~800) around
# has a negative impact on maintainability and readability of
# the project, so a balance is struck where only the most
# performance sensitive types are included here.
#
# --------------------------------------------------------


AddDoubleLinear = om.MTypeId(0x4441444c)
AddMatrix = om.MTypeId(0x44414d58)
AngleBetween = om.MTypeId(0x4e414254)
MultMatrix = om.MTypeId(0x444d544d)
AngleDimension = om.MTypeId(0x4147444e)
BezierCurve = om.MTypeId(0x42435256)
Camera = om.MTypeId(0x4443414d)
Choice = om.MTypeId(0x43484345)
Chooser = om.MTypeId(0x43484f4f)
Condition = om.MTypeId(0x52434e44)
Mesh = om.MTypeId(0x444d5348)
NurbsCurve = om.MTypeId(0x4e435256)
NurbsSurface = om.MTypeId(0x4e535246)
Transform = om.MTypeId(0x5846524d)
TransformGeometry = om.MTypeId(0x5447454f)
WtAddMatrix = om.MTypeId(0x4457414d)
