# -*- coding: utf-8 -*-
import os
import sys
import json
import time
import types
import logging
import traceback
import operator
from functools import wraps

from maya import cmds
from maya.api import OpenMaya as om

PY3 = sys.version_info[0] == 3

# Bypass assertion error on unsupported Maya versions
IGNORE_VERSION = bool(os.getenv("CMDX_IGNORE_VERSION"))

# Output profiling information to console
# CAREFUL! This will flood your console. Use sparingly.
TIMINGS = bool(os.getenv("CMDX_TIMINGS"))

# Do not perform any caching of nodes or plugs
SAFE_MODE = bool(os.getenv("CMDX_SAFE_MODE"))

# Increase performance by not protecting against
# fatal crashes (e.g. operations on deleted nodes)
# This can be useful when you know for certain that a
# series of operations will happen in isolation, such
# as during an auto rigging build or export process.
ROGUE_MODE = not SAFE_MODE and bool(os.getenv("CMDX_ROGUE_MODE"))

# Increase performance by not bothering to free up unused memory
MEMORY_HOG_MODE = not SAFE_MODE and bool(os.getenv("CMDX_MEMORY_HOG_MODE"))

# Support undo/redo
ENABLE_UNDO = not SAFE_MODE

# Opt-in performance boosters
ENABLE_NODE_REUSE = not SAFE_MODE
ENABLE_PLUG_REUSE = not SAFE_MODE

if PY3:
    string_types = str,
else:
    string_types = basestring,

__version__ = "0.2.0"
__maya_version__ = int(cmds.about(version=True))

# TODO: Lower this requirement
if not IGNORE_VERSION:
    assert __maya_version__ >= 2015, "Requires Maya 2015 or newer"

self = sys.modules[__name__]
log = logging.getLogger("cmdx")

# Accessible via `cmdx.NodeReuseCount` etc.
Stats = self
Stats.NodeInitCount = 0
Stats.NodeReuseCount = 0
Stats.PlugReuseCount = 0
Stats.LastTiming = None

# Node reuse depends on this member
if ENABLE_NODE_REUSE and not hasattr(om, "MObjectHandle"):
    log.warning("Disabling node reuse (OpenMaya.MObjectHandle not found)")
    ENABLE_NODE_REUSE = False

TimeUnit = om.MTime.uiUnit()
DistanceUnit = om.MDistance.uiUnit()
AngleUnit = om.MAngle.uiUnit()

ExistError = type("ExistError", (RuntimeError,), {})
DoNothing = None

# Reusable objects, for performance
GlobalDagNode = om.MFnDagNode()
GlobalDependencyNode = om.MFnDependencyNode()

First = 0
Last = -1

history = dict()


def withTiming(text="{func}() {time:.2f} ns"):
    """Append timing information to a function

    Example:
        @withTiming()
        def function():
            pass

    """

    def timings_decorator(func):
        if not TIMINGS:
            # Do not wrap the function.
            # This yields zero cost to runtime performance
            return func

        @wraps(func)
        def func_wrapper(*args, **kwargs):
            t0 = time.clock()

            try:
                return func(*args, **kwargs)
            finally:
                t1 = time.clock()
                duration = (t1 - t0) * 10 ** 6  # microseconds

                Stats.LastTiming = duration

                log.debug(
                    text.format(func=func.__name__,
                                time=duration)
                )

        return func_wrapper
    return timings_decorator


def protected(func):
    """Prevent fatal crashes from illegal access to deleted nodes"""
    if ROGUE_MODE:
        return func

    @wraps(func)
    def func_wrapper(*args, **kwargs):
        if args[0]._destroyed:
            raise ExistError("Cannot perform operation on deleted node")
        return func(*args, **kwargs)

    return func_wrapper


class _Type(int):
    """Facilitate use of isinstance(space, _Type())"""


kShape = _Type(om.MFn.kShape)
kTransform = _Type(om.MFn.kTransform)
kJoint = _Type(om.MFn.kJoint)


class _Space(int):
    """Facilitate use of isinstance(space, _Space())"""


# Spaces
World = _Space(om.MSpace.kWorld)
Object = _Space(om.MSpace.kObject)
Transform = _Space(om.MSpace.kTransform)
PostTransform = _Space(om.MSpace.kPostTransform)
PreTransform = _Space(om.MSpace.kPreTransform)

kWorld = World
kObject = Object
kTransform = Transform
kPostTransform = PostTransform
kPreTransform = PreTransform


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

_Cached = type("Cached", (object,), {})  # For isinstance(x, _Cached)
Cached = _Cached()


class Singleton(type):
    """Re-use previous instances of Node

    Cost: 14 microseconds

    This enables persistent state of each node, even when
    a node is discovered at a later time, such as via
    :func:`DagNode.parent()` or :func:`DagNode.descendents()`

    Arguments:
        mobject (MObject): Maya API object to wrap
        exists (bool, optional): Whether or not to search for
            an existing Python instance of this node

    Example:
        >>> nodeA = createNode("transform", name="myNode")
        >>> nodeB = createNode("transform", parent=nodeA)
        >>> encode("|myNode") is nodeA
        True
        >>> nodeB.parent() is nodeA
        True

    """

    _instances = {}

    @withTiming()
    def __call__(cls, mobject, exists=True, modifier=None):
        handle = om.MObjectHandle(mobject)
        hsh = handle.hashCode()

        if exists and handle.isValid():
            try:
                node = cls._instances[hsh]
                assert not node._destroyed
            except KeyError:
                pass
            except AssertionError:
                pass
            else:
                Stats.NodeReuseCount += 1
                return node

        # It didn't exist, let's create one
        self = super(Singleton, cls).__call__(mobject, exists, modifier)
        cls._instances[hsh] = self
        return self


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
        >>> transform["worldMatrix"][0] >> decompose["inputMatrix"]
        >>> decompose["outputTranslate"]
        (5.0, 0.0, 0.0)

    """

    if ENABLE_NODE_REUSE:
        __metaclass__ = Singleton

    _Fn = om.MFnDependencyNode

    # Module-level cache of previously created instances of Node
    _Cache = dict()

    def __eq__(self, other):
        """MObject supports this operator explicitly"""
        try:
            # Better to ask forgivness than permission
            return self._mobject == other._mobject
        except AttributeError:
            return str(self) == str(other)

    def __ne__(self, other):
        try:
            return self._mobject != other._mobject
        except AttributeError:
            return str(self) != str(other)

    def __str__(self):
        return self.name()

    def __repr__(self):
        return self.name()

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
        cached = False
        if isinstance(key, (list, tuple)):
            key, items = key[0], key[1:]

            for item in items:
                if isinstance(item, _Unit):
                    unit = item
                elif isinstance(item, _Cached):
                    cached = True

        if cached:
            try:
                return CachedPlug(self._state["values"][key, unit])
            except KeyError:
                log.warning("No previous value found")

        try:
            plug = self.findPlug(key)
        except RuntimeError:
            raise ExistError("%s.%s" % (self.path(), key))

        return Plug(self, plug, unit=unit, key=key, modifier=self._modifier)

    def __setitem__(self, key, value):
        """Support item assignment of new attributes or values

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> node = createNode("transform", name="myNode")
            >>> node["myAttr"] = Double(default=1.0)
            >>> node["myAttr"] == 1.0
            True
            >>> node["rotateX", Degrees] = 1.0
            >>> node["rotateX"] = Degrees(1)
            >>> node["rotateX", Degrees]
            1.0
            >>> node["myDist"] = Distance()
            >>> node["myDist"] = node["translateX"]
            >>> node["myDist", Centimeters] = node["translateX", Meters]
            >>> round(node["rotateX", Radians], 3)
            0.017
            >>> node["myDist"] = Distance()
            Traceback (most recent call last):
            ...
            ExistError: myDist
            >>> node["notExist"] = 5
            Traceback (most recent call last):
            ...
            ExistError: |myNode.notExist
            >>> delete(node)

        """

        if isinstance(value, Plug):
            value = value.read()

        unit = None
        if isinstance(key, (list, tuple)):
            key, unit = key

            # Convert value to the given unit
            if isinstance(value, (list, tuple)):
                value = list(unit(v) for v in value)
            else:
                value = unit(value)

        # Create a new attribute
        elif isinstance(value, (tuple, list)):
            if isinstance(value[0], type):
                if issubclass(value[0], _AbstractAttribute):
                    Attribute, kwargs = value
                    attr = Attribute(key, **kwargs).create()

                    try:
                        return self.addAttr(attr)

                    except RuntimeError:
                        # NOTE: I can't be sure this is the only occasion
                        # where this exception is thrown. Stay catious.
                        raise ExistError(key)

        try:
            plug = self.findPlug(key)
        except RuntimeError:
            raise ExistError("%s.%s" % (self.path(), key))

        Plug(self, plug, unit=unit).write(value)

    def _onDestroyed(self, mobject):
        self._destroyed = True

        cid = om.MMessage.currentCallbackId()
        om.MMessage.removeCallback(cid)

        for callback in self.onDestroyed:
            try:
                callback()
            except Exception:
                traceback.print_exc()

    def __delitem__(self, key):
        self.deleteAttr(key)

    @withTiming()
    def __init__(self, mobject, exists=True, modifier=None):
        """Initialise Node

        Private members:
            mobject (om.MObject): Wrap this MObject
            fn (om.MFnDependencyNode): The corresponding function set
            modifier (om.MDagModifier, optional): Operations are
                deferred to this modifier.
            destroyed (bool): Has this node been destroyed by Maya?
            state (dict): Optional state for performance

        """

        self._mobject = mobject
        self._fn = self._Fn(mobject)
        self._modifier = modifier
        self._destroyed = False
        self._state = {
            "plugs": dict(),
            "values": dict(),
        }

        self.onDestroyed = list()

        Stats.NodeInitCount += 1

        # Monitor node deletion, to prevent accidental
        # use of MObject past its lifetime which may
        # result in a fatal crash.
        om.MNodeMessage.addNodeDestroyedCallback(
            mobject,
            self._onDestroyed,  # func
            None  # clientData
        ) if not ROGUE_MODE else DoNothing

    def object(self):
        """Return MObject of this node"""
        return self._mobject

    def isAlive(self):
        return not self._destroyed

    def typeId(self):
        """Return the native maya.api.MTypeId of this node

        Example:
            >>> node = createNode("transform")
            >>> node.typeId() == Transform
            True

        """

        return self._fn.typeId

    def isA(self, type):
        """Evaluate whether self is of `type`

        Arguments:
            type (int): MFn function set constant

        Example:
            >>> node = createNode("transform")
            >>> node.isA(kTransform)
            True
            >>> node.isA(kShape)
            False

        """

        return self._mobject.hasFn(type)

    # Module-level branch; evaluated on import
    if ENABLE_PLUG_REUSE:
        @withTiming("findPlug() reuse {time:.4f} ns")
        def findPlug(self, name, cached=False):
            """Cache previously found plugs, for performance

            Cost: 4.9 microseconds/call

            Part of the time taken in querying an attribute is the
            act of finding a plug given its name as a string.

            This causes a 25% reduction in time taken for repeated
            attribute queries. Though keep in mind that state is stored
            in the `cmdx` object which currently does not survive rediscovery.
            That is, if a node is created and later discovered through a call
            to `encode`, then the original and discovered nodes carry one
            state each.

            Additional challenges include storing the same plug for both
            long and short name of said attribute, which is currently not
            the case.

            Arguments:
                name (str): Name of plug to find
                cached (bool, optional): Return cached plug, or
                    throw an exception. Default to False, which
                    means it will run Maya's findPlug() and cache
                    the result.
                safe (bool, optional): Always find the plug through
                    Maya's API, defaults to False. This will not perform
                    any caching and is intended for use during debugging
                    to spot whether caching is causing trouble.

            Example:
                >>> node = createNode("transform")
                >>> node.findPlug("translateX", cached=True)
                Traceback (most recent call last):
                ...
                KeyError: "'translateX' not cached"
                >>> plug1 = node.findPlug("translateX")
                >>> isinstance(plug1, om.MPlug)
                True
                >>> plug1 is node.findPlug("translateX")
                True
                >>> plug1 is node.findPlug("translateX", cached=True)
                True

            """

            try:
                existing = self._state["plugs"][name]
                Stats.PlugReuseCount += 1
                return existing
            except KeyError:
                if cached:
                    raise KeyError("'%s' not cached" % name)

            plug = self._fn.findPlug(name, False)
            self._state["plugs"][name] = plug

            return plug

    else:
        @withTiming("findPlug() no reuse {time:.4f} ns")
        def findPlug(self, name):
            """Always lookup plug by name

            Cost: 27.7 microseconds/call

            """

            return self._fn.findPlug(name, False)

    def clear(self):
        """Clear transient state

        A node may cache previously queried values for performance
        at the expense of memory. This method erases any cached
        values, freeing up memory at the expense of performance.

        Example:
            >>> node = createNode("transform")
            >>> node["translateX"] = 5
            >>> node["translateX"]
            5.0
            >>> # Plug was reused
            >>> node["translateX"]
            5.0
            >>> # Value was reused
            >>> node.clear()
            >>> node["translateX"]
            5.0
            >>> # Plug and value was recomputed

        """

        self._state["plugs"].clear()
        self._state["values"].clear()

    @protected
    def name(self):
        """Return the name of this node

        Example:
            >>> node = createNode("transform", name="myName")
            >>> node.name()
            u'myName'

        """

        return self._fn.name()

    # Alias
    path = name

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
        """Return dictionary of all attributes

        Example:
            >>> import json
            >>> _ = cmds.file(new=True, force=True)
            >>> node = createNode("choice")
            >>> dump = node.dump()
            >>> isinstance(dump, dict)
            True
            >>> dump["choice1.caching"]
            False

        """

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
        """Return type name

        Example:
            >>> node = createNode("choice")
            >>> node.type()
            u'choice'

        """

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

        Example:
            >>> node = createNode("transform")
            >>> node.hasAttr("mysteryAttribute")
            False
            >>> node.hasAttr("translateX")
            True
            >>> node["myAttr"] = Double()  # Dynamic attribute
            >>> node.hasAttr("myAttr")
            True

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

    def connections(self, type=None, unit=None, plugs=False):
        """Yield plugs of node with a connection to any other plug

        Arguments:
            unit (int, optional): Return plug in this unit,
                e.g. Meters or Radians
            type (str, optional): Restrict output to nodes of this type,
                e.g. "transform" or "mesh"
            plugs (bool, optional): Return plugs, rather than nodes

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> a = createNode("transform", name="A")
            >>> b = createNode("multDoubleLinear", name="B")
            >>> a["ihi"] << b["ihi"]
            >>> list(a.connections()) == [b]
            True
            >>> list(b.connections()) == [a]
            True
            >>> a.connection() == b
            True

        """

        for plug in self._fn.getConnections():
            mobject = plug.node()

            if mobject.hasFn(om.MFn.kDagNode):
                node = DagNode(mobject)
            else:
                node = Node(mobject)

            if not type or type == node._fn.typeName:
                plug = Plug(node, plug, unit)
                for connection in plug.connections(plugs=plugs):
                    yield connection

    def connection(self, type=None, unit=None, plug=False):
        """Singular version of :func:`connections()`"""
        return next(self.connections(type, unit, plug), None)


class DagNode(Node):
    """A Maya DAG node

    The difference between this and Node is that a DagNode
    can have one or more children and one parent (multiple
    parents not supported).

    Example:
        >>> _ = cmds.file(new=True, force=True)
        >>> parent = createNode("transform")
        >>> child = createNode("transform", parent=parent)
        >>> child.parent() == parent
        True
        >>> next(parent.children()) == child
        True
        >>> parent.child() == child
        True
        >>> sibling = createNode("transform", parent=parent)
        >>> child.sibling() == sibling
        True
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

    @protected
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

    @protected
    def shortestPath(self):
        """Return shortest unique path to node

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> parent = createNode("transform", name="myParent")
            >>> child = createNode("transform", name="myChild", parent=parent)
            >>> child.shortestPath()
            u'myChild'
            >>> child = createNode("transform", name="myChild")
            >>> # Now `myChild` could refer to more than a single node
            >>> child.shortestPath()
            u'|myChild'

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

        mobject = child._mobject
        self._fn.addChild(mobject, index)

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

    def transform(self, space=Object):
        """Return MTransformationMatrix"""
        plug = self["worldMatrix"][0] if space == World else self["matrix"]
        return om.MFnMatrixData(plug._mplug.asMObject()).transformation()

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
            >>> parent.parent()

        """

        mobject = self._fn.parent(0)

        if mobject.apiType() == om.MFn.kWorld:
            return

        cls = self.__class__

        if not type or type == self._fn.__class__(mobject).typeName:
            return cls(mobject)

    def children(self, type=None, filter=om.MFn.kTransform):
        """Return children of node

        Arguments:
            type (str, optional): Return only children that match this type
            filter (int, optional): Return only children with this function set

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> a = createNode("transform", "a")
            >>> b = createNode("transform", "b", parent=a)
            >>> c = createNode("transform", "c", parent=a)
            >>> d = createNode("mesh", "d", parent=c)
            >>> list(a.children()) == [b, c]
            True
            >>> a.child() == b
            True
            >>> c.child(type="mesh")
            >>> c.child(type="mesh", filter=None) == d
            True
            >>> c.child(type=("mesh", "transform"), filter=None) == d
            True

        """

        cls = DagNode
        Fn = self._fn.__class__
        op = operator.eq

        if isinstance(type, (tuple, list)):
            op = operator.contains

        other = "typeId" if isinstance(type, om.MTypeId) else "typeName"

        for index in range(self._fn.childCount()):
            mobject = self._fn.child(index)

            if filter is not None and not mobject.hasFn(filter):
                continue

            if not type or op(type, getattr(Fn(mobject), other)):
                yield cls(mobject)

    def child(self, type=None, filter=om.MFn.kTransform):
        return next(self.children(type, filter), None)

    def shapes(self, type=None):
        return self.children(type, om.MFn.kShape)

    def shape(self, type=None):
        return next(self.shapes(type), None)

    def siblings(self, type=None):
        parent = self.parent()

        if parent is not None:
            for child in parent.children(type=type):
                if child != self:
                    yield child

    def sibling(self, type=None):
        return next(self.siblings(type), None)

    # Module-level expression; this isn't evaluated
    # at run-time, for that extra performance boost.
    if hasattr(om, "MItDag"):
        def descendents(self, type=None):
            """Faster and more efficient dependency graph traversal

            Requires Maya 2017+

            Example:
                >>> grandparent = createNode("transform")
                >>> parent = createNode("transform", parent=grandparent)
                >>> child = createNode("transform", parent=parent)
                >>> mesh = createNode("mesh", parent=child)
                >>> it = grandparent.descendents(type=Mesh)
                >>> next(it) == mesh
                True
                >>> next(it)
                Traceback (most recent call last):
                ...
                StopIteration

            """

            type = type or om.MFn.kInvalid
            typeName = None

            # Support filtering by typeName
            if isinstance(type, string_types):
                typeName = type
                type = om.MFn.kInvalid

            it = om.MItDag(om.MItDag.kDepthFirst, om.MFn.kInvalid)
            it.reset(
                self._mobject,
                om.MItDag.kDepthFirst,
                om.MIteratorType.kMObject
            )

            it.next()  # Skip self

            while not it.isDone():
                mobj = it.currentItem()
                node = DagNode(mobj)

                if typeName is None:
                    if not type or type == node._fn.typeId:
                        yield node
                else:
                    if not typeName or typeName == node._fn.typeName:
                        yield node

                it.next()

    else:
        def descendents(self, type=None):
            """Recursive, depth-first search; compliant with MItDag of 2017+

            Example:
                >>> grandparent = createNode("transform")
                >>> parent = createNode("transform", parent=grandparent)
                >>> child = createNode("transform", parent=parent)
                >>> mesh = createNode("mesh", parent=child)
                >>> it = grandparent.descendents(type=Mesh)
                >>> next(it) == mesh
                True
                >>> next(it)
                Traceback (most recent call last):
                ...
                StopIteration

            """

            def _descendents(node, children=None):
                children = children or list()
                children.append(node)
                for child in node.children(filter=None):
                    _descendents(child, children)

                return children

            # Support filtering by typeName
            typeName = None
            if isinstance(type, str):
                typeName = type
                type = om.MFn.kInvalid

            descendents = _descendents(self)[1:]  # Skip self

            for child in descendents:
                if typeName is None:
                    if not type or type == child._fn.typeId:
                        yield child
                else:
                    if not typeName or typeName == child._fn.typeName:
                        yield child

    def descendent(self, type=om.MFn.kInvalid):
        """Singular version of :func:`descendents()`

        A recursive, depth-first search.

        .. code-block:: python

            a
            |
            b---d
            |   |
            c   e

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> a = createNode("transform", "a")
            >>> b = createNode("transform", "b", parent=a)
            >>> c = createNode("transform", "c", parent=b)
            >>> d = createNode("transform", "d", parent=b)
            >>> e = createNode("transform", "e", parent=d)
            >>> a.descendent() == a.child()
            True
            >>> list(a.descendents()) == [b, c, d, e]
            True
            >>> f = createNode("mesh", "f", parent=e)
            >>> list(a.descendents(type="mesh")) == [f]
            True

        """

        return next(self.descendents(type), None)


class ObjectSet(Node):
    """Support list-type operations on objectSets"""


class Plug(object):
    def __abs__(self):
        """Return absolute value of plug

        Example:
            >>> node = createNode("transform")
            >>> node["tx"] = -10
            >>> abs(node["tx"])
            10.0

        """

        return abs(self.read())

    def __bool__(self):
        """if plug:

        Example:
            >>> node = createNode("transform")
            >>> node["tx"] = 10
            >>> if node["tx"]:
            ...   True
            ...
            True

        """

        return bool(self.read())

    # Python 3
    __nonzero__ = __bool__

    def __float__(self):
        """Return plug as floating point value

        Example:
            >>> node = createNode("transform")
            >>> float(node["visibility"])
            1.0

        """

        return float(self.read())

    def __int__(self):
        """Return plug as int

        Example:
            >>> node = createNode("transform")
            >>> int(node["visibility"])
            1

        """

        return int(self.read())

    def __eq__(self, other):
        """Compare plug to `other`

        Example:
            >>> node = createNode("transform")
            >>> node["visibility"] == True
            True
            >>> node["visibility"] == node["nodeState"]
            False
            >>> node["visibility"] != node["nodeState"]
            True

        """

        if isinstance(other, Plug):
            other = other.read()
        return self.read() == other

    def __ne__(self, other):
        if isinstance(other, Plug):
            other = other.read()
        return self.read() != other

    def __div__(self, other):
        """Python 2.x division

        Example:
            >>> node = createNode("transform")
            >>> node["tx"] = 5
            >>> node["ty"] = 2
            >>> node["tx"] / node["ty"]
            2.5

        """

        if isinstance(other, Plug):
            other = other.read()
        return self.read() / other

    def __floordiv__(self, other):
        """Integer division, e.g. self // other

        Example:
            >>> node = createNode("transform")
            >>> node["tx"] = 5
            >>> node["ty"] = 2
            >>> node["tx"] // node["ty"]
            2.0
            >>> node["tx"] // 2
            2.0

        """

        if isinstance(other, Plug):
            other = other.read()
        return self.read() // other

    def __truediv__(self, other):
        """Float division, e.g. self / other"""
        if isinstance(other, Plug):
            other = other.read()
        return self.read() / other

    def __add__(self, other):
        """Support legacy add string to plug

        Note:
            Adding to short name is faster, e.g. node["t"] + "x",
            than adding to longName, e.g. node["translate"] + "X"

        Example:
            >>> node = createNode("transform")
            >>> node["tx"] = 5
            >>> node["translate"] + "X"
            5.0
            >>> node["t"] + "x"
            5.0
            >>> try:
            ...   node["t"] + node["r"]
            ... except TypeError:
            ...   error = True
            ...
            >>> error
            True

        """

        if isinstance(other, str):
            try:
                # E.g. node["t"] + "x"
                return self._node[self.name() + other]
            except ExistError:
                # E.g. node["translate"] + "X"
                return self._node[self.name(long=True) + other]

        raise TypeError(
            "unsupported operand type(s) for +: 'Plug' and '%s'"
            % type(other)
        )

    def __str__(self):
        """Return value as str

        Example:
            >>> node = createNode("transform")
            >>> str(node["tx"])
            '0.0'

        """

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
        """Iterate over value as a tuple

        Example:
            >>> node = createNode("transform")
            >>> node["translate"] = (0, 1, 2)
            >>> for index, axis in enumerate(node["translate"]):
            ...   assert axis == float(index)
            ...   assert isinstance(axis, Plug)
            ...
            >>> a = createNode("transform")
            >>> a["myArray"] = Message(array=True)
            >>> b = createNode("transform")
            >>> c = createNode("transform")
            >>> a["myArray"][0] << b["message"]
            >>> a["myArray"][1] << c["message"]
            >>> a["myArray"][0] in list(a["myArray"])
            True
            >>> a["myArray"][1] in list(a["myArray"])
            True

        """

        if self._mplug.isArray:
            for index in range(self._mplug.evaluateNumElements()):
                yield self[index]

        elif self._mplug.isCompound:
            for index in range(self._mplug.numChildren()):
                yield self[index]

        else:
            for value in self.read():
                yield value

    def __getitem__(self, index):
        """Read from child of array or compound plug

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> node = createNode("transform", name="mynode")
            >>> node["translate"][0].read()
            0.0
            >>> node["visibility"][0]
            Traceback (most recent call last):
            ...
            TypeError: mynode.visibility does not support indexing

        """
        cls = self.__class__

        if self._mplug.isArray:
            item = self._mplug.elementByLogicalIndex(index)
            return cls(self._node, item, self._unit)

        elif self._mplug.isCompound:
            item = self._mplug.child(index)
            return cls(self._node, item, self._unit)

        else:
            raise TypeError(
                "%s does not support indexing" % self.path()
            )

    def __setitem__(self, index, value):
        """Write to child of array or compound plug

        Example:
            >>> node = createNode("transform")
            >>> node["translate"][0] = 5
            >>> node["tx"]
            5.0

        """

        self[index].write(value)

    def __init__(self, node, mplug, unit=None, key=None, modifier=None):
        """A Maya plug

        Arguments:
            node (Node): Parent Node of plug
            mplug (maya.api.OpenMaya.MPlug): Internal Maya plug
            unit (int, optional): Unit with which to read plug

        """

        assert isinstance(node, Node), "%s is not a Node" % node

        self._node = node
        self._mplug = mplug
        self._unit = unit
        self._cached = None
        self._key = key
        self._modifier = modifier

    def asDouble(self):
        """Return plug as double (Python float)

        Example:
            >>> node = createNode("transform")
            >>> node["translateX"] = 5.0
            >>> node["translateX"].asDouble()
            5.0

        """

        return self._mplug.asDouble()

    def asMatrix(self, time=None):
        """Return plug as MMatrix

        Example:
            >>> node1 = createNode("transform")
            >>> node2 = createNode("transform", parent=node1)
            >>> node1["translate"] = (0, 5, 0)
            >>> node2["translate"] = (0, 5, 0)
            >>> plug1 = node1["matrix"]
            >>> plug2 = node2["worldMatrix"][0]
            >>> mat1 = plug1.asMatrix()
            >>> mat2 = plug2.asMatrix()
            >>> mat = mat1 * mat2
            >>> tm = TransformationMatrix(mat)
            >>> list(tm.translation())
            [0.0, 15.0, 0.0]

        """

        context = om.MDGContext.kNormal

        if time is not None:
            context = om.MDGContext(om.MTime(time, om.MTime.uiUnit()))

        return om.MFnMatrixData(self._mplug.asMObject(context)).matrix()

    def asTransformationMatrix(self, time=None):
        """Return plug as TransformationMatrix

        Example:
            >>> node = createNode("transform")
            >>> node["translateY"] = 12
            >>> node["rotate"] = 1
            >>> tm = node["matrix"].asTm()
            >>> map(round, tm.rotation())
            [1.0, 1.0, 1.0]
            >>> list(tm.translation())
            [0.0, 12.0, 0.0]

        """

        return TransformationMatrix(self.asMatrix(time))

    # Alias
    asTm = asTransformationMatrix

    @property
    def locked(self):
        return self._mplug.isLocked

    @property
    def channelBox(self):
        return self._mplug.isChannelBox

    @channelBox.setter
    def channelBox(self, value):
        om.MFnAttribute(self._mplug.attribute()).channelBox = value

    @property
    def keyable(self):
        return self._mplug.isKeyable

    @keyable.setter
    def keyable(self, value):
        om.MFnAttribute(self._mplug.attribute()).keyable = value

    def type(self):
        """Retrieve API type of plug as string

        Example:
            >>> node = createNode("transform")
            >>> node["translate"].type()
            'kAttribute3Double'
            >>> node["translateX"].type()
            'kDoubleLinearAttribute'

        """

        return self._mplug.attribute().apiTypeStr

    def path(self):
        return self._mplug.partialName(
            includeNodeName=True,
            useLongNames=True,
            useFullAttributePath=True
        )

    def name(self, long=False):
        return self._mplug.partialName(
            includeNodeName=False,
            useLongNames=long,
            useFullAttributePath=True
        )

    def read(self, unit=None, time=None):
        unit = unit if unit is not None else self._unit
        context = None

        if time is not None:
            context = om.MDGContext(om.MTime(time, om.MTime.uiUnit()))

        try:
            value = _plug_to_python(
                self._mplug,
                unit=unit,
                context=context
            )

            # Store cached value
            self._node._state["values"][self._key, unit] = value

            return value

        except RuntimeError:
            raise

        except TypeError:
            # Expected errors
            log.error("'%s': failed to read attribute" % self.path())
            raise

    def write(self, value):
        try:
            _python_to_plug(value, self)
            self._cached = value

        except RuntimeError:
            raise

        except TypeError:
            log.error("'%s': failed to write attribute" % self.path())
            raise

    def connect(self, other):
        if not getattr(self._modifier, "isDone", True):
            return self._modifier.connect(self._mplug, other._mplug)

        mod = om.MDGModifier()
        mod.connect(self._mplug, other._mplug)
        mod.doIt()

    def disconnect(self, other):
        if not getattr(self._modifier, "isDone", True):
            return self._modifier.disconnect(self._mplug, other._mplug)

        mod = om.MDGModifier()
        mod.disconnect(self._mplug, other._mplug)
        mod.doIt()

    def connections(self,
                    type=None,
                    source=True,
                    destination=True,
                    plugs=False,
                    unit=None):
        """Yield plugs connected to self

        Arguments:
            source (bool, optional): Return source plugs,
                default is True
            destination (bool, optional): Return destination plugs,
                default is True
            unit (int, optional): Return plug in this unit, e.g. Meters

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> a = createNode("transform", name="A")
            >>> b = createNode("multDoubleLinear", name="B")
            >>> a["ihi"] << b["ihi"]
            >>> a["ihi"].connection() == b
            True
            >>> b["ihi"].connection() == a
            True
            >>> a["ihi"]
            2

        """

        op = operator.eq
        other = "typeId"

        if isinstance(type, string_types):
            other = "typeName"

        if isinstance(type, (tuple, list)):
            op = operator.contains

        for plug in self._mplug.connectedTo(source, destination):
            mobject = plug.node()

            if mobject.hasFn(om.MFn.kDagNode):
                node = DagNode(mobject)
            else:
                node = Node(mobject)

            if not type or op(type, getattr(node._fn, other)):
                yield Plug(node, plug, unit) if plugs else node

    def connection(self,
                   type=None,
                   source=True,
                   destination=True,
                   plug=False,
                   unit=None):
        """Return first connection from :func:`connections()`"""
        return next(self.connections(type=type,
                                     source=source,
                                     destination=destination,
                                     plugs=plug,
                                     unit=unit), None)

    def source(self, unit=None):
        cls = self.__class__
        plug = self._mplug.source()
        node = plug.node()
        if node.hasFn(om.MFn.kDagNode):
            node = DagNode(node)
        else:
            node = Node(node)

        if not plug.isNull:
            return cls(node, plug, unit)

    def node(self):
        return self._node


class TransformationMatrix(om.MTransformationMatrix):
    def translation(self, space=None):
        """This method does not typically support optional arguments"""
        space = space or kTransform
        return super(TransformationMatrix, self).translation(space)


class Vector(om.MVector):
    """Maya's MVector

    Example:
        >>> vec = Vector(1, 0, 0)
        >>> vec * Vector(0, 1, 0)  # Dot product
        0.0
        >>> vec ^ Vector(0, 1, 0)  # Cross product
        maya.api.OpenMaya.MVector(0, 0, 1)

    """


class CachedPlug(Plug):
    """Returned in place of an actual plug"""
    def __init__(self, value):
        self._value = value

    def read(self):
        return self._value


def _plug_to_python(plug, unit=None, context=None):
    """Convert native `plug` to Python type

    Arguments:
        plug (om.MPlug): Native Maya plug
        unit (int, optional): Return value in this unit, e.g. Meters
        context (om.MDGContext, optional): Return value in this context

    """

    assert not plug.isNull, "'%s' was null" % plug

    if context is None:
        context = om.MDGContext.kNormal

    # Multi attributes
    #   _____
    #  |     |
    #  |     ||
    #  |     ||
    #  |_____||
    #   |_____|
    #

    if plug.isArray and plug.isCompound:
        # E.g. locator["worldPosition"]
        return _plug_to_python(
            plug.elementByLogicalIndex(0), unit, context
        )

    elif plug.isArray:
        # E.g. transform["worldMatrix"][0]
        # E.g. locator["worldPosition"][0]
        return tuple(
            _plug_to_python(
                plug.elementByLogicalIndex(index),
                unit,
                context
            )
            for index in range(plug.evaluateNumElements())
        )

    elif plug.isCompound:
        return tuple(
            _plug_to_python(plug.child(index), unit, context)
            for index in range(plug.numChildren())
        )

    # Simple attributes
    #   _____
    #  |     |
    #  |     |
    #  |     |
    #  |_____|
    #
    attr = plug.attribute()
    type = attr.apiType()
    if type == om.MFn.kTypedAttribute:
        innerType = om.MFnTypedAttribute(attr).attrType()

        if innerType == om.MFnData.kAny:
            # E.g. choice["input"][0]
            return None

        elif innerType == om.MFnData.kMatrix:
            # E.g. transform["worldMatrix"][0]
            if plug.isArray:
                plug = plug.elementByLogicalIndex(0)

            return tuple(
                om.MFnMatrixData(plug.asMObject(context)).matrix()
            )

        elif innerType == om.MFnData.kString:
            return plug.asString(context)

        elif innerType == om.MFnData.kInvalid:
            # E.g. time1.timewarpIn_Hidden
            # Unsure of why some attributes are invalid
            return None

        else:
            raise TypeError("Unsupported typed type: %s"
                            % innerType)

    elif type == om.MFn.kMatrixAttribute:
        return tuple(om.MFnMatrixData(plug.asMObject(context)).matrix())

    elif type == om.MFnData.kDoubleArray:
        raise TypeError("%s: kDoubleArray is not supported" % plug)

    elif type in (om.MFn.kDoubleLinearAttribute,
                  om.MFn.kFloatLinearAttribute):

        if unit is None:
            return plug.asMDistance(context).asUnits(DistanceUnit)
        elif unit == Millimeters:
            return plug.asMDistance(context).asMillimeters()
        elif unit == Centimeters:
            return plug.asMDistance(context).asCentimeters()
        elif unit == Meters:
            return plug.asMDistance(context).asMeters()
        elif unit == Kilometers:
            return plug.asMDistance(context).asKilometers()
        elif unit == Inches:
            return plug.asMDistance(context).asInches()
        elif unit == Feet:
            return plug.asMDistance(context).asFeet()
        elif unit == Miles:
            return plug.asMDistance(context).asMiles()
        elif unit == Yards:
            return plug.asMDistance(context).asYards()
        else:
            raise TypeError("Unsupported unit '%d'" % unit)

    elif type in (om.MFn.kDoubleAngleAttribute,
                  om.MFn.kFloatAngleAttribute):
        if unit is None:
            return plug.asMAngle(context).asUnits(om.MAngle.uiUnit())
        elif unit == Degrees:
            return plug.asMAngle(context).asDegrees()
        elif unit == Radians:
            return plug.asMAngle(context).asRadians()
        elif unit == AngularSeconds:
            return plug.asMAngle(context).asAngSeconds()
        elif unit == AngularMinutes:
            return plug.asMAngle(context).asAngMinutes()
        else:
            raise TypeError("Unsupported unit '%d'" % unit)

    # Number
    elif type == om.MFn.kNumericAttribute:
        innerType = om.MFnNumericAttribute(attr).numericType()

        if innerType == om.MFnNumericData.kBoolean:
            return plug.asBool(context)

        elif innerType in (om.MFnNumericData.kShort,
                           om.MFnNumericData.kInt,
                           om.MFnNumericData.kLong,
                           om.MFnNumericData.kByte):
            return plug.asInt(context)

        elif innerType in (om.MFnNumericData.kFloat,
                           om.MFnNumericData.kDouble,
                           om.MFnNumericData.kAddr):
            return plug.asDouble(context)

        else:
            raise TypeError("Unsupported numeric type: %s"
                            % innerType)

    # Enum
    elif type == om.MFn.kEnumAttribute:
        return plug.asShort(context)

    elif type == om.MFn.kMessageAttribute:
        # In order to comply with `if plug:`
        return True

    elif type == om.MFn.kTimeAttribute:
        return plug.asShort(context)

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

    # Compound values

    if isinstance(value, (tuple, list)):
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

    # Native Maya types

    elif isinstance(value, om.MEulerRotation):
        for index, value in enumerate(value):
            value = om.MAngle(value, om.MAngle.kRadians)
            _python_to_plug(value, plug[index])

    elif isinstance(value, om.MAngle):
        plug._mplug.setMAngle(value)

    elif isinstance(value, om.MDistance):
        plug._mplug.setMDistance(value)

    elif isinstance(value, om.MTime):
        plug._mplug.setMTime(value)

    elif isinstance(value, om.MVector):
        for index, value in enumerate(value):
            _python_to_plug(value, plug[index])

    elif plug._mplug.isCompound:
        count = plug._mplug.numChildren()
        return _python_to_plug([value] * count, plug)

    # Native Python types

    elif isinstance(value, str):
        plug._mplug.setString(value)

    elif isinstance(value, int):
        plug._mplug.setInt(value)

    elif isinstance(value, float):
        plug._mplug.setDouble(value)

    elif isinstance(value, bool):
        plug._mplug.setBool(value)

    else:
        raise TypeError("Unsupported Python type '%s'" % value.__class__)


def encode(path):
    """Convert relative or absolute `path` to cmdx Node

    Fastest conversion from absolute path to Node

    Arguments:
        path (str): Absolute or relative path to DAG or DG node

    """

    assert isinstance(path, string_types), "%s was not string" % path

    selectionList = om.MSelectionList()

    try:
        selectionList.add(path)
    except RuntimeError:
        raise ValueError("'%s' does not exist" % path)

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

    try:
        return node.shortestPath()
    except AttributeError:
        return node.name()


# The original class does not support adding
# members to self at run-time.
class _MDGModifier(om.MDGModifier):
    def __init__(self, *args, **kwargs):
        super(_MDGModifier, self).__init__(*args, **kwargs)
        self.isDone = False


class _MDagModifier(om.MDagModifier):
    def __init__(self, *args, **kwargs):
        super(_MDagModifier, self).__init__(*args, **kwargs)
        self.isDone = False


class _BaseModifier(object):
    """Interactively edit an existing scenegraph with support for undo/redo"""

    Type = _MDGModifier

    def __enter__(self):
        self._modifier = self.Type()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self._modifier.doIt()
        self._modifier.isDone = True
        commit(self._modifier.undoIt, self._modifier.doIt)

    def doIt(self):
        self._modifier.doIt()

    def undoIt(self):
        self._modifier.undoIt()

    def createNode(self, type, name=None):
        mobj = self._modifier.createNode(type)

        if name is not None:
            self._modifier.renameNode(mobj, name)

        return Node(mobj, exists=False, modifier=self._modifier)

    def getAttr(self, node, key):
        return node[key]

    def setAttr(self, node, key, value):
        node[key] = value

    def connect(self, plug1, plug2):
        plug1 >> plug2


class DGModifier(_BaseModifier):
    """Modifier for DG nodes"""

    Type = _MDGModifier


class DagModifier(_BaseModifier):
    """Modifier for DAG nodes

    Example:
        >>> with DagModifier() as mod:
        ...     node1 = mod.createNode("transform")
        ...     node2 = mod.createNode("transform", parent=node1)
        ...     mod.setAttr(node1, "translate", (1, 2, 3))
        ...     value = mod.getAttr(node1, "translateX")
        ...     mod.connect(node1 + ".translate", node2 + ".translate")
        ...
        >>> value
        1.0
        >>> node2["translate"][0]
        1.0
        >>> node2["translate"][1]
        2.0
        >>> with DagModifier() as mod:
        ...     node1 = mod.createNode("transform")
        ...     node2 = mod.createNode("transform", parent=node1)
        ...     node1["translate"] = (5, 6, 7)
        ...     node1["translate"] >> node2["translate"]
        ...
        >>> node2["translate"][0]
        5.0
        >>> node2["translate"][1]
        6.0

    """

    Type = _MDagModifier

    def createNode(self, type, name=None, parent=None):
        parent = parent._mobject if parent else om.MObject.kNullObj
        mobj = self._modifier.createNode(type, parent)

        if name is not None:
            self._modifier.renameNode(mobj, name)

        return DagNode(mobj, exists=False, modifier=self._modifier)

    def parent(self, node, parent=None):
        self._modifier.reparentNode(node._mobject, parent)

    def rename(self, node, name):
        self._modifier.renameNode(node._mobject, parent)


def createNode(type, name=None, parent=None):
    """Create a new node

    This function forms the basic building block
    with which to create new nodes in Maya.

    .. note:: Missing arguments `shared` and `skipSelect`
    .. tip:: For additional performance, `type` may be given as an MTypeId

    Arguments:
        type (str): Type name of new node, e.g. "transform"
        name (str, optional): Sets the name of the newly-created node
        parent (Node, optional): Specifies the parent in the DAG under which
            the new node belongs

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
    except RuntimeError as e:
        log.debug(str(e))
        raise TypeError("Unrecognized node type '%s'" % type)

    if fn is GlobalDagNode or mobj.hasFn(om.MFn.kDagNode):
        return DagNode(mobj, exists=False)
    else:
        return Node(mobj, exists=False)


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
                  allDescendents=False,
                  parent=False,
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

    elif allDescendents:
        return list(node.descendents(type=type))

    elif shapes:
        return list(node.shapes(type=type))

    elif parent:
        return [node.parent(type=type)]

    elif children:
        return list(node.children(type=type))


def listConnections(attr):
    """List connections of `attr`

    Arguments:
        attr (Plug or Node):

    Example:
        >>> node1 = createNode("transform")
        >>> node2 = createNode("mesh", parent=node1)
        >>> node1["v"] >> node2["v"]
        >>> listConnections(node1) == [node2]
        True
        >>> listConnections(node1 + ".v") == [node2]
        True
        >>> listConnections(node1["v"]) == [node2]
        True
        >>> listConnections(node2) == [node1]
        True

    """

    return list(node for node in attr.connections())


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


def delete(*nodes):
    mod = om.MDGModifier()

    for node in nodes:
        mobject = node._mobject
        mod.deleteNode(mobject)

    mod.doIt()


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

    def __ne__(self, other):
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
    Multi = None

    def __init__(self, name, children=None, **kwargs):
        if not children and self.Multi:
            default = kwargs.pop("default", None)
            children, Type = self.Multi
            children = tuple(
                Type(name + child, default=default[index], **kwargs)
                if default else Type(name + child, **kwargs)
                for index, child in enumerate(children)
            )

            self["children"] = children

        else:
            self["children"] = children

        super(Compound, self).__init__(name, **kwargs)

    def default(self):
        # Compound itself has no defaults, only it's children do
        pass

    def create(self):
        mobj = super(Compound, self).create()
        default = super(Compound, self).default()

        for index, child in enumerate(self["children"]):
            if child["default"] is None and default is not None:
                child["default"] = default[index]

            self.Fn.addChild(child.create())

        return mobj

    def read(self, handle):
        """Read from MDataHandle"""
        output = list()

        for child in self["children"]:
            child_handle = handle.child(child["mobject"])
            output.append(child.read(child_handle))

        return tuple(output)


class Angle3(Compound):
    Multi = ("XYZ", Angle)


class Distance3(Compound):
    Multi = ("XYZ", Distance)


# --------------------------------------------------------
#
# Undo/Redo Support
#
# NOTE: Localised version of apiundo.py 0.2.0
# https://github.com/mottosso/apiundo
#
# In Maya, history is maintained by "commands". Each command is an instance of
# MPxCommand that encapsulates a series of API calls coupled with their
# equivalent undo/redo API calls. For example, the `createNode` command
# is presumably coupled with `cmds.delete`, `setAttr` is presumably
# coupled with another `setAttr` with the previous values passed in.
#
# Thus, creating a custom command involves subclassing MPxCommand and
# implementing coupling your do, undo and redo into one neat package.
#
# cmdx however doesn't fit into this framework.
#
# With cmdx, you call upon API calls directly. There is little to no
# correlation between each of your calls, which is great for performance
# but not so great for conforming to the undo/redo framework set forth
# by Autodesk.
#
# To work around this, without losing out on performance or functionality,
# a generic command is created, capable of hosting arbitrary API calls
# and storing them in the Undo/Redo framework.
#
#   >>> node = cmdx.createNode("transform")
#   >>> cmdx.commit(lambda: cmdx.delete(node))
#
# Now when you go to undo, the `lambda` is called. It is then up to you
# the developer to ensure that what is being undone actually relates
# to what you wanted to have undone. For example, it is perfectly
# possible to add an unrelated call to history.
#
#   >>> node = cmdx.createNode("transform")
#   >>> cmdx.commit(lambda: cmdx.setAttr(node + "translateX", 5))
#
# The result would be setting an attribute to `5` when attempting to undo.
#
# --------------------------------------------------------


# Support for multiple co-existing versions of apiundo.
# NOTE: This is important for vendoring, as otherwise a vendored apiundo
# could register e.g. cmds.apiUndo() first, causing a newer version
# to inadvertently use this older command (or worse yet, throwing an
# error when trying to register it again).
command = "_apiUndo_%s" % __version__.replace(".", "_")

# This module is both a Python module and Maya plug-in.
# Data is shared amongst the two through this "module"
name = "_cmdxShared"
if name not in sys.modules:
    sys.modules[name] = types.ModuleType(name)

shared = sys.modules[name]
shared.undo = None
shared.redo = None


def commit(undo, redo=lambda: None):
    """Commit `undo` and `redo` to history

    Arguments:
        undo (func): Call this function on next undo
        redo (func, optional): Like `undo`, for for redo

    """

    if not ENABLE_UNDO:
        return

    if not hasattr(cmds, command):
        install()

    # Precautionary measure.
    # If this doesn't pass, odds are we've got a race condition.
    # NOTE: This assumes calls to `commit` can only be done
    # from a single thread, which should already be the case
    # given that Maya's API is not threadsafe.
    assert shared.redo is None
    assert shared.undo is None

    # Temporarily store the functions at module-level,
    # they are later picked up by the command once called.
    shared.undo = undo
    shared.redo = redo

    # Let Maya know that something is undoable
    getattr(cmds, command)()


def install():
    """Load this module as a plug-in

    Call this prior to using the module

    """

    if not ENABLE_UNDO:
        return

    cmds.loadPlugin(__file__, quiet=True)


def uninstall():
    if not ENABLE_UNDO:
        return

    # Plug-in may exist in undo queue and
    # therefore cannot be unloaded until flushed.
    cmds.flushUndo()

    cmds.unloadPlugin(os.path.basename(__file__))


def maya_useNewAPI():
    pass


class _apiUndo(om.MPxCommand):
    def doIt(self, args):
        self.undo = shared.undo
        self.redo = shared.redo

        # Facilitate the above precautionary measure
        shared.undo = None
        shared.redo = None

    def undoIt(self):
        self.undo()

    def redoIt(self):
        self.redo()

    def isUndoable(self):
        # Without this, the above undoIt and redoIt will not be called
        return True


def initializePlugin(plugin):
    om.MFnPlugin(plugin).registerCommand(
        command,
        _apiUndo
    )


def uninitializePlugin(plugin):
    om.MFnPlugin(plugin).deregisterCommand(command)


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
# Developers: See cmdt.py for a list of all available types and their IDs
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
Joint = om.MTypeId(0x4a4f494e)
Transform = om.MTypeId(0x5846524d)
TransformGeometry = om.MTypeId(0x5447454f)
WtAddMatrix = om.MTypeId(0x4457414d)
