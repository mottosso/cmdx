# -*- coding: utf-8 -*-

import re
import os
import sys
import json
import time
import math
import types
import logging
import getpass
import operator
import traceback
import collections
import contextlib
from functools import wraps

from maya import cmds
from maya.api import OpenMaya as om, OpenMayaAnim as oma, OpenMayaUI as omui
from maya import OpenMaya as om1, OpenMayaMPx as ompx1, OpenMayaUI as omui1

__version__ = "0.6.1"

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

ENABLE_PEP8 = True

# Support undo/redo (mandatory)
ENABLE_UNDO = True

# Required
ENABLE_PLUG_REUSE = True

if PY3:
    long = int
    string_types = str,
else:
    long = long
    string_types = str, basestring, unicode

try:
    __maya_version__ = int(cmds.about(version=True))
except (AttributeError, ValueError):
    __maya_version__ = 2015  # E.g. Preview Release 95

if not IGNORE_VERSION:
    assert __maya_version__ >= 2015, "Requires Maya 2015 or newer"

# Hack for static typing analysis
#
# the test below only passes in the IDE such as VSCode
# Maya doesn't know or care about the `typing` library
MYPY = False
if MYPY:
    from typing import *
    # Fake-declare some Python2-only types to fix Pylance
    # analyzer false positives (Pylance is Python3-only)
    basestring = unicode = str
    long = int
    buffer = bytearray
    file = object
del MYPY

self = sys.modules[__name__]
self.installed = False
log = logging.getLogger("cmdx")

# Aliases - API 1.0
om1 = om1
omui1 = omui1

# Aliases - API 2.0
om = om
oma = oma
omui = omui

# Accessible via `cmdx.NodeReuseCount` etc.
Stats = self
Stats.NodeInitCount = 0
Stats.NodeReuseCount = 0
Stats.PlugReuseCount = 0
Stats.LastTiming = None

# Node reuse depends on this member
if not hasattr(om, "MObjectHandle"):
    log.warning("Node reuse might not work in this version of Maya "
                "(OpenMaya.MObjectHandle not found)")

# DEPRECATED
MTime = om.MTime
MDistance = om.MDistance
MAngle = om.MAngle

TimeType = om.MTime
DistanceType = om.MDistance
AngleType = om.MAngle
ColorType = om.MColor

ExistError = type("ExistError", (RuntimeError,), {})
LockedError = type("LockedError", (ValueError,), {})
DoNothing = None

# Reusable objects, for performance
GlobalDagNode = om.MFnDagNode()
GlobalDependencyNode = om.MFnDependencyNode()

First = 0
Last = -1

# Animation curve interpolation, from MFnAnimCurve::TangentType
Stepped = 5
Linear = 2
Smooth = 4

history = dict()


class ModifierError(RuntimeError):
    def __init__(self, history):
        tasklist = list()
        for task in history:
            cmd, args, kwargs = task
            tasklist += [
                "%s(%s)" % (cmd, ", ".join(map(repr, args)))
            ]

        message = (
            "An unexpected internal failure occurred, "
            "these tasks were attempted:\n- " +
            "\n- ".join(tasklist)
        )

        self.history = history
        super(ModifierError, self).__init__(message)


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


@contextlib.contextmanager
def _undo_chunk(name):
    try:
        cmds.undoInfo(chunkName=name, openChunk=True)
        yield
    finally:
        cmds.undoInfo(chunkName=name, closeChunk=True)


def _isalive(mobj):
    """Make as sure as humanly-possible that this mobject is safe"""

    # Rare case of an empty MObject being passed, e.g. MObject()
    if mobj.isNull():
        return False

    handle = om.MObjectHandle(mobj)

    # The node has been destroyed, e.g. new scene or flushed undo
    if not handle.isValid():
        return False

    # The node is present in the scene, but has been removed. Could
    # potentially be undone and given new life. We don't care.
    if not handle.isAlive():
        return False

    return True


def _camel_to_title(text):
    """Convert camelCase `text` to Title Case

    Example:
        >>> _camel_to_title("mixedCase")
        'Mixed Case'
        >>> _camel_to_title("myName")
        'My Name'
        >>> _camel_to_title("you")
        'You'
        >>> _camel_to_title("You")
        'You'
        >>> _camel_to_title("This is That")
        'This Is That'

    """

    return re.sub(
        r"((?<=[a-z])[A-Z]|(?<!\A)[A-Z](?=[a-z]))",
        r" \1", text
    ).title().replace("  ", " ")


def protected(func):
    """Prevent fatal crashes from illegal access to deleted nodes"""
    if ROGUE_MODE:
        return func

    @wraps(func)
    def func_wrapper(*args, **kwargs):
        node = args[0]
        assert isinstance(node, Node), "arg[0] should have been a cmdx.Node"

        if node.destroyed or not _isalive(node._mobject):
            raise ExistError("Cannot perform operation on deleted node")

        return func(*args, **kwargs)

    return func_wrapper


def add_metaclass(metaclass):
    """Add metaclass to Python 2 and 3 class

    Helper decorator, from six.py

    """

    def wrapper(cls):
        orig_vars = cls.__dict__.copy()
        slots = orig_vars.get("__slots__")
        if slots is not None:
            if isinstance(slots, str):
                slots = [slots]
            for slots_var in slots:
                orig_vars.pop(slots_var)
        orig_vars.pop("__dict__", None)
        orig_vars.pop("__weakref__", None)
        if hasattr(cls, "__qualname__"):
            orig_vars["__qualname__"] = cls.__qualname__
        return metaclass(cls.__name__, cls.__bases__, orig_vars)
    return wrapper


class _Type(int):
    """Facilitate use of isinstance(space, _Type)"""


MFn = om.MFn
kDagNode = _Type(om.MFn.kDagNode)
kShape = _Type(om.MFn.kShape)
kTransform = _Type(om.MFn.kTransform)
kJoint = _Type(om.MFn.kJoint)
kSet = _Type(om.MFn.kSet)
kDeformer = _Type(om.MFn.kGeometryFilt)
kConstraint = _Type(om.MFn.kConstraint)


class _Space(int):
    """Facilitate use of isinstance(space, _Space)"""


# Spaces
sWorld = _Space(om.MSpace.kWorld)
sObject = _Space(om.MSpace.kObject)
sTransform = _Space(om.MSpace.kTransform)
sPostTransform = _Space(om.MSpace.kPostTransform)
sPreTransform = _Space(om.MSpace.kPreTransform)

kXYZ = om.MEulerRotation.kXYZ
kYZX = om.MEulerRotation.kYZX
kZXY = om.MEulerRotation.kZXY
kXZY = om.MEulerRotation.kXZY
kYXZ = om.MEulerRotation.kYXZ
kZYX = om.MEulerRotation.kZYX


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


def AngleUiUnit():
    """Dynamic angle UI unit

    Unlike other angle units, this can be modified by the user at run-time
    hence it needs to be a function rather than a variable.

    """

    return _Unit(om.MAngle, om.MAngle.uiUnit())


# Distance units
Millimeters = _Unit(om.MDistance, om.MDistance.kMillimeters)
Centimeters = _Unit(om.MDistance, om.MDistance.kCentimeters)
Meters = _Unit(om.MDistance, om.MDistance.kMeters)
Kilometers = _Unit(om.MDistance, om.MDistance.kKilometers)
Inches = _Unit(om.MDistance, om.MDistance.kInches)
Feet = _Unit(om.MDistance, om.MDistance.kFeet)
Miles = _Unit(om.MDistance, om.MDistance.kMiles)
Yards = _Unit(om.MDistance, om.MDistance.kYards)


def DistanceUiUnit():
    """Dynamic distance UI unit

    Unlike other distance units, this can be modified by the user at run-time
    hence it needs to be a function rather than a variable.

    """

    return _Unit(om.MDistance, om.MDistance.uiUnit())


# Time units
Milliseconds = _Unit(om.MTime, om.MTime.kMilliseconds)
Minutes = _Unit(om.MTime, om.MTime.kMinutes)
Seconds = _Unit(om.MTime, om.MTime.kSeconds)


def TimeUiUnit():
    """Unlike other time units, this can be modified by the user at run-time"""
    return _Unit(om.MTime, om.MTime.uiUnit())


# Alias
UiUnit = TimeUiUnit


_Cached = type("Cached", (object,), {})  # For isinstance(x, _Cached)
Cached = _Cached()

_data = collections.defaultdict(dict)


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
        hx = "%x" % hsh

        if exists and handle.isValid():
            try:
                node = cls._instances[hx]
                assert not node._destroyed

            except KeyError:
                pass

            except AssertionError:
                # He's dead Jim
                cls._instances.pop(hx)

            else:
                Stats.NodeReuseCount += 1
                return node

        # It hasn't been instantiated before, let's do that.
        # But first, make sure we instantiate the right type
        if mobject.hasFn(om.MFn.kDagContainer):
            sup = ContainerNode
        elif mobject.hasFn(om.MFn.kContainer):
            sup = ContainerNode
        elif mobject.hasFn(om.MFn.kDagNode):
            sup = DagNode
        elif mobject.hasFn(om.MFn.kSet):
            sup = ObjectSet
        elif mobject.hasFn(om.MFn.kAnimCurve):
            sup = AnimCurve
        else:
            sup = Node

        self = super(Singleton, sup).__call__(mobject, exists)
        self._hashCode = hsh
        self._hexStr = hx
        cls._instances[hx] = self
        return self


@add_metaclass(Singleton)
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

    _Fn = om.MFnDependencyNode

    # Module-level cache of previously created instances of Node
    _Cache = dict()

    def __eq__(self, other):
        """MObject supports this operator explicitly"""

        # On scene-open, an old MObject can reference a new node,
        # most typically the `top` camera node. Therefore, it isn't
        # enough to only compare MObject to MObject

        try:
            # Better to ask forgivness than permission
            return (
                _isalive(self._mobject) and
                _isalive(other._mobject) and
                self._mobject == other._mobject
            )
        except AttributeError:
            return str(self) == str(other)

    def __ne__(self, other):
        try:
            return self._mobject != other._mobject
        except AttributeError:
            return str(self) != str(other)

    def __str__(self):
        return self.name(namespace=True)

    def __repr__(self):
        return self.name(namespace=True)

    def __add__(self, other):
        """Support legacy + '.attr' behavior

        Example:
            >>> node = createNode("transform")
            >>> getAttr(node + ".tx")
            0.0
            >>> delete(node)

        """

        return self[other.strip(".")]

    def __contains__(self, other):
        """Does the attribute `other` exist?"""

        return self.hasAttr(other)

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
                pass

        try:
            plug = self.findPlug(key)
        except RuntimeError:
            raise ExistError("%s.%s" % (self.path(), key))

        return Plug(self, plug, unit=unit, key=key)

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
            >>> try:
            ...    node["myDist"] = Distance()
            ... except Exception as e:
            ...    assert isinstance(e, ExistError)
            ... else:
            ...    assert False
            >>>
            >>> try:
            ...   node["notExist"] = 5
            ... except Exception as f:
            ...   assert isinstance(f, ExistError)
            ... else:
            ...   assert False
            >>>
            >>> delete(node)

        """

        if isinstance(value, Plug):
            value = value.read()

        unit = None
        if isinstance(key, (list, tuple)):
            key, unit = key

            # Convert value to the given unit
            if isinstance(value, (list, tuple, om.MVector)):
                value = list(unit(v) for v in value)
            else:
                value = unit(value)

        # Create a new attribute
        elif isinstance(value, (tuple, list)):
            if isinstance(value[0], type):
                if issubclass(value[0], _AbstractAttribute):
                    Attribute, kwargs = value
                    attr = Attribute(key, **kwargs)

                    try:
                        return self.addAttr(attr.create())

                    except RuntimeError:
                        # NOTE: I can't be sure this is the only occasion
                        # where this exception is thrown. Stay catious.
                        raise ExistError(key)

        plug = self.findPlug(key)
        plug = Plug(self, plug, unit=unit)

        # Else, write it immediately
        plug.write(value)

    def __hash__(self):
        """Support storing in set() and as key in dict()"""
        return hash(self.path())

    def __delitem__(self, key):
        self.deleteAttr(key)

    @withTiming()
    def __init__(self, mobject, exists=True):
        """Initialise Node

        Private members:
            mobject (om.MObject): Wrap this MObject
            fn (om.MFnDependencyNode): The corresponding function set
            destroyed (bool): Has this node been destroyed by Maya?
            state (dict): Optional state for performance

        """

        self._mobject = mobject
        self._destroyed = False
        self._hashCode = None
        self._state = {
            "values": dict(),
            "callbacks": list()
        }

        # There is no humanly possible way of knowing when
        # an MObject is destroyed, other than to listen for
        # it via a callback. Please correct me if I'm wrong,
        # callbacks are death.
        self._state["callbacks"] += [
            # Monitor node deletion, to prevent accidental
            # use of MObject past its lifetime which may
            # result in a fatal crash.
            om.MNodeMessage.addNodeDestroyedCallback(
                mobject,
                self._onDestroyed,  # func
                None  # clientData
            )
        ]

        Stats.NodeInitCount += 1

    def __del__(self):
        """Clean up callbacks on garbage collection

        These may/should clean up themselves alongside node
        destruction, but in case they don't we make extra sure.

        """

        for callback in self._state["callbacks"]:
            try:
                om.MMessage.removeCallback(callback)
            except RuntimeError:
                pass

        self._state["callbacks"].clear()

    def _onDestroyed(self, mobject, _=None):
        self._destroyed = True

    @property
    def _fn(self):
        if SAFE_MODE:
            assert _isalive(self._mobject)

        return self._Fn(self._mobject)

    def plugin(self):
        """Return the user-defined class of the plug-in behind this node"""
        return type(self._fn.userNode())

    def instance(self):
        """Return the current plug-in instance of this node"""
        return self._fn.userNode()

    def object(self):
        """Return MObject of this node"""
        return self._mobject

    def isAlive(self):
        """The node exists somewhere in memory"""
        return not self._destroyed

    @property
    def data(self):
        """Special handling for data stored in the instance

        Normally, the initialisation of data could happen in the __init__,
        but for some reason the postConstructor of a custom plug-in calls
        __init__ twice for every unique hex, which causes any data added
        there to be wiped out once the postConstructor is done.

        """

        return _data[self.hex]

    @property
    def exists(self):
        """The node exists in both memory *and* scene

        Example:
            >>> node = createNode("joint")
            >>> node.exists
            True
            >>> cmds.delete(str(node))
            >>> node.exists
            False
            >>> _ = cmds.file(new=True, force=True)
            >>> node.exists
            False

        """

        return _isalive(self._mobject)

    @property
    def removed(self):
        return not _isalive(self._mobject)

    @property
    def destroyed(self):
        return self._destroyed

    @property
    def hashCode(self):
        """Return MObjectHandle.hashCode of this node

        This a guaranteed-unique integer (long in Python 2)
        similar to the UUID of Maya 2016

        """

        return self._hashCode

    @property
    def hexStr(self):
        """Return unique hashCode as hexadecimal string

        Example:
            >>> node = createNode("transform")
            >>> node.hexStr == format(node.hashCode, "x")
            True

        """

        return self._hexStr

    # Alias
    code = hashCode
    hex = hexStr

    @property
    def typeId(self):
        """Return the native maya.api.MTypeId of this node

        Example:
            >>> node = createNode("transform")
            >>> node.typeId == tTransform
            True

        """

        return self._fn.typeId

    @property
    def typeName(self):
        return self._fn.typeName

    def isA(self, type):
        """Evaluate whether self is of `type`

        Arguments:
            type (MTypeId, str, list, int): any kind of type to check
                - MFn function set constant
                - MTypeId objects
                - nodetype names

        Example:
            >>> node = createNode("transform")
            >>> node.isA(kTransform)
            True
            >>> node.isA(kShape)
            False
            >>> node.isA((kShape, kTransform))
            True

        """
        if isinstance(type, om.MTypeId):
            return type == self._fn.typeId
        elif isinstance(type, string_types):
            return type == self._fn.typeName
        elif isinstance(type, (tuple, list)):
            return any(self.isA(t) for t in type)
        elif isinstance(type, int):
            return self._mobject.hasFn(type)
        cmds.warning("Unsupported argument passed to isA('%s')" % type)
        return False

    def lock(self, value=True):
        self._fn.isLocked = value

    def isLocked(self):
        return self._fn.isLocked

    def isReferenced(self):
        return self._fn.isFromReferencedFile

    @property
    def storable(self):
        """Whether or not to save this node with the file"""

        # How is this value queried?
        return None

    @storable.setter
    def storable(self, value):

        # The original function is a double negative
        self._fn.setDoNotWrite(not bool(value))

    # Module-level branch; evaluated on import
    @withTiming("findPlug() reuse {time:.4f} ns")
    def findPlug(self, name, cached=False, safe=True):
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
            cached (bool, optional): (DEPRECATED) Return cached plug, or
                throw an exception. Default to False, which
                means it will run Maya's findPlug() and cache
                the result.
            safe (bool, optional): (DEPRECATED) Always find the plug through
                Maya's API, defaults to True. This will not perform
                any caching and is intended for use during debugging
                to spot whether caching is causing trouble.

        Example:
            >>> node = createNode("transform")
            >>> plug1 = node.findPlug("translateX")
            >>> isinstance(plug1, om.MPlug)
            True
            >>> plug1 == node.findPlug("translateX")
            True

        """

        assert isinstance(name, string_types), "%s was not string" % name

        # `findPlug` has a tendency of bringing Maya down with it.
        # Let's not give it the satisfaction.
        if not _isalive(self._mobject):
            raise ExistError

        try:
            # We always want a non-networked plug. It's safer and as-fast.
            # https://forums.autodesk.com/t5/maya-programming/maya-api-what-is-a-networked-plug-and-do-i-want-it-or-not/td-p/7182472
            want_networked_plug = False
            plug = self._fn.findPlug(name, want_networked_plug)

        except RuntimeError:
            raise ExistError("%s.%s" % (self.path(), name))

        return plug

    def update(self, attrs):
        """Apply a series of attributes all at once

        This operates similar to a Python dictionary.

        Arguments:
            attrs (dict): Key/value pairs of name and attribute

        Examples:
            >>> node = createNode("transform")
            >>> node.update({"tx": 5.0, ("ry", Degrees): 30.0})
            >>> node["tx"]
            5.0

        """

        for key, value in attrs.items():
            self[key] = value

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

        self._state["values"].clear()

    @protected
    def name(self, namespace=False):
        """Return the name of this node

        Arguments:
            namespace (bool, optional): Return with namespace,
                defaults to False

        Example:
            >>> node = createNode("transform", name="myName")
            >>> node.name() == 'myName'
            True

        """

        if namespace:
            return self._fn.name()
        else:
            return self._fn.name().rsplit(":", 1)[-1]

    def namespace(self):
        """Get namespace of node

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> node = createNode("transform", name="myNode")
            >>> node.namespace() == ""
            True
            >>> _ = cmds.namespace(add=":A")
            >>> _ = cmds.namespace(add=":A:B")
            >>> node = createNode("transform", name=":A:B:myNode")
            >>> node.namespace() == 'A:B'
            True

        """

        name = self._fn.name()

        if ":" in name:
            # Else it will return name as-is, as namespace
            # E.g. Ryan_:leftHand -> Ryan_, but :leftHand -> leftHand
            return name.rsplit(":", 1)[0]

        return type(name)()

    # Alias
    def path(self):
        return self.name(namespace=True)

    shortestPath = path

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

    def dump(self, ignore_error=True, preserve_order=False):
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

        attrs = collections.OrderedDict() if preserve_order else {}
        count = self._fn.attributeCount()
        for index in range(count):
            obj = self._fn.attribute(index)
            plug = self._fn.findPlug(obj, False)

            try:
                value = Plug(self, plug).read()
            except (RuntimeError, TypeError):
                # TODO: Support more types of attributes,
                # such that this doesn't need to happen.
                value = None

                if not ignore_error:
                    raise

            attrs[plug.name()] = value

        return attrs

    def dumps(self, indent=4, sort_keys=True, preserve_order=False):
        """Return a JSON compatible dictionary of all attributes"""
        return json.dumps(
            self.dump(preserve_order),
            indent=indent,
            sort_keys=sort_keys
        )

    def index(self, plug):
        """ Find index of `attr` in its owning node
         _____________
        |             |
        |    Friction o -> 126
        |        Mass o -> 127
        |     Color R o -> 128
        |     Color G o -> 129
        |     Color B o -> 130
        |             |
        |_____________|

        # TODO: This is really slow

        """

        assert isinstance(plug, Plug), "%r was not a cmdx.Plug" % plug

        node = plug.node()

        for i in range(node._fn.attributeCount()):
            attr = node._fn.attribute(i)
            fn = om.MFnAttribute(attr)

            if fn.shortName == plug.name(long=False):
                return i

        # Can happen if asking for an index of a plug from another node
        raise ValueError("Index of '%s' not found" % plug.name())

    def type(self):
        """Return type name

        Example:
            >>> node = createNode("choice")
            >>> node.type() == 'choice'
            True

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

        if isinstance(attr, str):
            node, attr = attr.rsplit(".", 1)
            node = encode(node)
            attr = node[attr]

        mobj = attr

        xattr = None
        if isinstance(mobj, _AbstractAttribute):
            xattr = mobj
            mobj = attr.create()

        assert isinstance(mobj, om.MObject)

        try:
            self._fn.addAttribute(mobj)

        except RuntimeError:
            # Maya doesn't tell you *why* it fails,
            # so let's do some investigating

            # But we can only do that if we've
            # got something to work with.
            if xattr is not None:
                # fn = om.MFnAttribute(mobj)
                if xattr["shortName"] in self:
                    raise ExistError(
                        "%s['%s'] already exists!"
                        % (self.name(), xattr["shortName"])
                    )

                if xattr["name"] in self:
                    raise ExistError(
                        "%s['%s'] already exists!"
                        % (self.name(), xattr["name"])
                    )

            # We didn't find anything wrong, proceed with generic error
            raise

        # These don't natively support defaults by Maya
        # They aren't being saved with the file, unless
        # we explicitly set it after creation.
        if isinstance(attr, String) and attr["default"]:
            self[attr["name"]] = attr["default"]

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

    def connections(self,
                    type=None,
                    unit=None,
                    plugs=False,
                    source=True,
                    destination=True,
                    connections=False):
        """Yield plugs of node with a connection to any other plug

        Arguments:
            unit (int, optional): Return plug in this unit,
                e.g. Meters or Radians
            type (str, optional): Restrict output to nodes of this type,
                e.g. "transform" or "mesh"
            plugs (bool, optional): Return plugs, rather than nodes
            source (bool, optional): Return inputs only
            destination (bool, optional): Return outputs only
            connections (bool, optional): Return tuples of the connected plugs

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
            plug = Plug(self, plug, unit)
            for connection in plug.connections(type=type,
                                               unit=unit,
                                               plugs=plugs,
                                               source=source,
                                               destination=destination):
                if connections:
                    yield connection, plug if plugs else self
                else:
                    yield connection

    def connection(self,
                   type=None,
                   unit=None,
                   plug=False,
                   source=True,
                   destination=True,
                   connection=False):
        """Singular version of :func:`connections()`"""
        return next(
            self.connections(type=type,
                             unit=unit,
                             plugs=plug,
                             source=source,
                             destination=destination,
                             connections=connection), None)

    def inputs(self,
               type=None,
               unit=None,
               plugs=False,
               connections=False):
        """Return input connections from :func:`connections()`"""
        return self.connections(type=type,
                                unit=unit,
                                plugs=plugs,
                                source=True,
                                destination=False,
                                connections=connections)

    def input(self,
              type=None,
              unit=None,
              plug=None,
              connection=False):
        """Return first input connection from :func:`connections()`"""
        return next(
            self.connections(type=type,
                             unit=unit,
                             plugs=plug,
                             source=True,
                             destination=False,
                             connections=connection), None)

    def outputs(self,
                type=None,
                plugs=False,
                unit=None,
                connections=False):
        """Return output connections from :func:`connections()`"""
        return self.connections(type=type,
                                unit=unit,
                                plugs=plugs,
                                source=False,
                                destination=True,
                                connections=connections)

    def output(self,
               type=None,
               plug=False,
               unit=None,
               connection=False):
        """Return first output connection from :func:`connections()`"""
        return next(
            self.connections(type=type,
                             unit=unit,
                             plugs=plug,
                             source=False,
                             destination=True,
                             connections=connection), None)

    def rename(self, name):
        mod = om.MDGModifier()
        mod.renameNode(self._mobject, name)
        mod.doIt()

    if ENABLE_PEP8:
        is_alive = isAlive
        hex_str = hexStr
        hash_code = hashCode
        type_id = typeId
        type_name = typeName
        is_a = isA
        is_locked = isLocked
        is_referenced = isReferenced
        find_plug = findPlug
        add_attr = addAttr
        has_attr = hasAttr
        delete_attr = deleteAttr
        shortest_path = shortestPath


if __maya_version__ >= 2017:
    class ContainerNode(Node):
        """A.k.a. "asset"

        These are special. Published names aren't your average plug. They can't
        be found via the MFnDependencyNode.findPlug call. Instead, they are
        so-called "published names" and reside elsewhere.

        This class wraps that interface to align with regular attribute access,
        for an as-transparent-as-possible experience.

        Examples:
            >> from maya import cmds
            >> _ = cmds.file(new=True, force=True)

            # Establish a published plug
            >> con = cmds.container(name="myContainer")
            >> con = encode(con)
            >> con.isA(kDagNode)
            False
            >> isinstance(con, ContainerNode)
            True

            >> from maya import cmds
            >> _ = cmds.file(new=True, force=True)

            # Establish a published plug
            >> node = cmds.createNode("transform")
            >> con = cmds.container(name="myContainer",
            ..                      addNode=[node],
            ..                      type="dagContainer")
            >> plug = cmds.container(con,
            ..                       edit=True,
            ..                       publishName="inputTranslate")
            >> binding = ("%s.tx" % node, plug)
            >> _ = cmds.container(con, edit=True, bindAttr=binding)

            # Query and connect that published plug
            >> source = createNode("transform")
            >> con = encode(con)
            >> con.isA(kDagNode)
            True
            >> isinstance(con, ContainerNode)
            True
            >> source["tx"] >> con[plug]
            >> source["tx"] = 5.0
            >> con["inputTranslate"].read()
            5.0

        """

        _Fn = om.MFnContainerNode

        def __getitem__(self, key):
            try:
                return super(ContainerNode, self).__getitem__(key)
            except ExistError:
                pass

            # It may be a published name rather than a traditional attribute
            mplugs, keys = self._fn.getPublishedPlugs()

            if key not in keys:
                raise ExistError(
                    "'%s' was not an attribute, nor a "
                    "published name for this container" % key
                )

            mplug = mplugs[keys.index(key)]
            return Plug(self, mplug,
                        unit=None,
                        key=key)


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

    @property
    def _tfn(self):
        if SAFE_MODE:
            assert _isalive(self._mobject)

        # Convert self._tfn to om.MFnTransform(self.dagPath())
        # if you want to use its functions which require sWorld
        return om.MFnTransform(self._mobject)

    @protected
    def path(self):
        """Return full path to node

        Example:
            >>> parent = createNode("transform", "myParent")
            >>> child = createNode("transform", "myChild", parent=parent)
            >>> child.name() == 'myChild'
            True
            >>> child.path() == '|myParent|myChild'
            True

        """

        return self._fn.fullPathName()

    @protected
    def dagPath(self):
        """Return a om.MDagPath for this node

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> parent = createNode("transform", name="Parent")
            >>> child = createNode("transform", name="Child", parent=parent)
            >>> path = child.dagPath()
            >>> str(path)
            'Child'
            >>> str(path.pop())
            'Parent'

        """

        return om.MDagPath.getAPathTo(self._mobject)

    @protected
    def shortestPath(self):
        """Return shortest unique path to node

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> parent = createNode("transform", name="myParent")
            >>> child = createNode("transform", name="myChild", parent=parent)
            >>> child.shortestPath() == "myChild"
            True
            >>> child = createNode("transform", name="myChild")
            >>> # Now `myChild` could refer to more than a single node
            >>> child.shortestPath() == '|myChild'
            True

        """

        return self._fn.partialPathName()

    @property
    def level(self):
        """Return the number of parents this DAG node has

        Example:
            >>> parent = createNode("transform")
            >>> child = createNode("transform", parent=parent)
            >>> child.level
            1
            >>> parent.level
            0

        """

        return self.path().count("|") - 1

    @property
    def boundingBox(self):
        """Return a cmdx.BoundingBox of this DAG node"""
        return BoundingBox(self._fn.boundingBox)

    def hide(self):
        """Set visibility to False"""
        self["visibility"] = False

    def show(self):
        """Set visibility to True"""
        self["visibility"] = True

    def childCount(self, type=None):
        """Return number of children of a given optional type

        Compared to `MFnDagNode.childCount`, this function actually returns
        children, not shapes, along with filtering by an optional type.

        Arguments:
            type (str): Same as to .children(type=)

        """

        return len(list(self.children(type=type)))

    def addChild(self, child, index=Last, safe=True):
        """Add `child` to self

        Arguments:
            child (Node): Child to add
            index (int, optional): Physical location in hierarchy,
                defaults to cmdx.Last
            safe (bool): Prevents crash when the node to reparent was formerly
                a descendent of the new parent. Costs 6µs/call

        Example:
            >>> parent = createNode("transform")
            >>> child = createNode("transform")
            >>> parent.addChild(child)

        """

        mobject = child._mobject
        if safe:
            parent = child.parent()
            if parent is not None:
                parent._fn.removeChild(mobject)
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

    def transform(self, space=sObject, time=None):
        """Return TransformationMatrix"""
        plug = self["worldMatrix"][0] if space == sWorld else self["matrix"]
        return TransformationMatrix(plug.asMatrix(time))

    def transformation(self):
        return TransformationMatrix(self._tfn.transformation())

    def translation(self, space=sObject, time=None):
        """Convenience method for transform(space).translation()

        Example:
            >>> node = createNode("transform")
            >>> node["translateX"] = 5.0
            >>> node.translation().x
            5.0

        """

        return self.transform(space, time).translation()

    def rotation(self, space=sObject, time=None):
        """Convenience method for transform(space).rotation()

        Example:
            >>> node = createNode("transform")
            >>> node["rotateX"] = radians(90)
            >>> round(degrees(node.rotation().x), 1)
            90.0

        """

        return self.transform(space, time).rotation()

    def scale(self, space=sObject, time=None):
        """Convenience method for transform(space).scale()

        Example:
            >>> node = createNode("transform")
            >>> node["scaleX"] = 5.0
            >>> node.scale().x
            5.0

        """

        return self.transform(space, time).scale()

    def mapFrom(self, other, time=None):
        """Return TransformationMatrix of `other` relative self

        Example:
            >>> a = createNode("transform")
            >>> b = createNode("transform")
            >>> a["translate"] = (0, 5, 0)
            >>> b["translate"] = (0, -5, 0)
            >>> delta = a.mapFrom(b)
            >>> delta.translation()[1]
            10.0
            >>> a = createNode("transform")
            >>> b = createNode("transform")
            >>> a["translate"] = (0, 5, 0)
            >>> b["translate"] = (0, -15, 0)
            >>> delta = a.mapFrom(b)
            >>> delta.translation()[1]
            20.0

        """

        a = self["worldMatrix"][0].asMatrix(time)
        b = other["worldInverseMatrix"][0].asMatrix(time)
        delta = a * b
        return TransformationMatrix(delta)

    def mapTo(self, other, time=None):
        """Return TransformationMatrix of self relative `other`

        See :func:`mapFrom` for examples.

        """

        return other.mapFrom(self, time)

    # Alias
    root = assembly

    def parent(self, type=None, filter=None):
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
            >>> child.parent(filter=om.MFn.kTransform) == parent
            True
            >>> child.parent(filter=om.MFn.kJoint) is None
            True

        Returns:
            parent (Node): If any, else None

        """

        mobject = self._fn.parent(0)

        if mobject.apiType() == om.MFn.kWorld:
            return

        cls = self.__class__

        if filter is not None and not mobject.hasFn(filter):
            return None

        if not type or type == self._fn.__class__(mobject).typeName:
            return cls(mobject)

    @protected
    def lineage(self, type=None, filter=None):
        """Yield parents all the way up a hierarchy

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> a = createNode("transform", name="a")
            >>> b = createNode("transform", name="b", parent=a)
            >>> c = createNode("transform", name="c", parent=b)
            >>> d = createNode("transform", name="d", parent=c)
            >>> lineage = d.lineage()
            >>> next(lineage) == c
            True
            >>> next(lineage) == b
            True
            >>> next(lineage) == a
            True

        """

        parent = self.parent(type)
        while parent is not None:
            yield parent
            parent = parent.parent(type, filter)

    # Alias
    parenthood = lineage

    @protected
    def children(self,
                 type=None,
                 filter=om.MFn.kTransform,
                 query=None,
                 contains=None):
        """Return children of node

        All returned children are transform nodes, as specified by the
        `filter` argument. For shapes, use the :func:`shapes` method.
        The `contains` argument only returns transform nodes containing
        a shape of the type provided.

        Arguments:
            type (str, optional): Return only children that match this type
            filter (int, optional): Return only children with this function set
            contains (str, optional): Child must have a shape of this type
            query (dict, optional): Limit output to nodes with these attributes

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
            >>> a.child() == b
            True
            >>> a.child(contains="mesh") == c
            True
            >>> a.child(contains="nurbsCurve") is None
            True
            >>> b["myAttr"] = Double(default=5)
            >>> a.child(query=["myAttr"]) == b
            True
            >>> a.child(query=["noExist"]) is None
            True
            >>> a.child(query={"myAttr": 5}) == b
            True
            >>> a.child(query={"myAttr": 1}) is None
            True

        """

        # Shapes have no children
        if self.isA(kShape):
            return

        Fn = self._fn.__class__
        op = operator.eq
        if isinstance(type, (tuple, list)):
            op = operator.contains

        other = "typeId" if isinstance(type, om.MTypeId) else "typeName"

        assert self._fn.hasObj(self._mobject), "This is a Maya bug"

        try:
            count = int(self._fn.childCount())
        except OverflowError:
            # Maya does this sometimes and you'd be lucky if
            # Python catches onto it. More likely it will
            # fatal crash your Maya, as it likely accesses
            # a bad memory address.
            raise

        for index in range(count):
            try:
                mobject = self._fn.child(index)

            except RuntimeError:
                # TODO: Unsure of exactly when this happens
                log.warning(
                    "Child %d of %s not found, this is a bug" % (index, self)
                )
                raise

            if filter is not None and not mobject.hasFn(filter):
                continue

            if not type or op(type, getattr(Fn(mobject), other)):
                node = DagNode(mobject)

                if not contains or node.shape(type=contains):
                    if query is None:
                        yield node

                    elif isinstance(query, dict):
                        try:
                            if all(node[key] == value
                                   for key, value in query.items()):
                                yield node
                        except ExistError:
                            continue

                    else:
                        if all(key in node for key in query):
                            yield node

    def child(self,
              type=None,
              filter=om.MFn.kTransform,
              query=None,
              contains=None):
        return next(self.children(type, filter, query, contains), None)

    def shapes(self, type=None, query=None):
        return self.children(type, kShape, query)

    def shape(self, type=None):
        return next(self.shapes(type), None)

    def siblings(self, type=None, filter=om.MFn.kTransform):
        parent = self.parent()

        if parent is not None:
            for child in parent.children(type=type, filter=filter):
                if child != self:
                    yield child

    def sibling(self, type=None, filter=None):
        return next(self.siblings(type, filter), None)

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
                >>> it = grandparent.descendents(type=tMesh)
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
                >>> it = grandparent.descendents(type=tMesh)
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

    def duplicate(self):
        """Return a duplicate of self"""
        return self.__class__(self._fn.duplicate())

    def clone(self, name=None, parent=None, worldspace=False):
        """Return a clone of self

        A "clone" assignes the .outMesh attribute of a mesh node
        to the `.inMesh` of the resulting clone.

        Supports:
            - mesh

        Arguments:
            name (str, optional): Name of newly created clone
            parent (DagNode, optional): Parent to newly cloned node
            worldspace (bool, optional): Translate output to worldspace

        """

        if self.isA(kShape) and self.typeName == "mesh":
            assert parent is not None, "mesh cloning requires parent argument"
            name or parent.name() + "Clone"

            with DagModifier() as mod:
                mesh = mod.createNode("mesh", name, parent)
                mesh["inMesh"] << self["outMesh"]

            return mesh

        else:
            raise TypeError("Unsupported clone target: %s" % self)

    def isLimited(self, typ):
        return self._tfn.isLimited(typ)

    def limitValue(self, typ):
        return self._tfn.limitValue(typ)

    def enableLimit(self, typ, state):
        return self._tfn.enableLimit(typ, state)

    def setLimit(self, typ, value):
        return self._tfn.setLimit(typ, value)

    if ENABLE_PEP8:
        shortest_path = shortestPath
        add_child = addChild
        child_count = childCount
        dag_path = dagPath
        map_from = mapFrom
        map_to = mapTo
        is_limited = isLimited
        limit_value = limitValue
        set_limit = setLimit
        enable_limit = enableLimit
        bounding_box = boundingBox


# MFnTransform Limit Types
kRotateMaxX = 13
kRotateMaxY = 15
kRotateMaxZ = 17
kRotateMinX = 12
kRotateMinY = 14
kRotateMinZ = 16
kScaleMaxX = 1
kScaleMaxY = 3
kScaleMaxZ = 5
kScaleMinX = 0
kScaleMinY = 2
kScaleMinZ = 4
kShearMaxXY = 7
kShearMaxXZ = 9
kShearMaxYZ = 11
kShearMinXY = 6
kShearMinXZ = 8
kShearMinYZ = 10
kTranslateMaxX = 19
kTranslateMaxY = 21
kTranslateMaxZ = 23
kTranslateMinX = 18
kTranslateMinY = 20
kTranslateMinZ = 22


class ObjectSet(Node):
    """Support set-type operations on Maya sets

    Caveats
        1. MFnSet was introduced in Maya 2016, this class backports
            that behaviour for Maya 2015 SP3

        2. Adding a DAG node as a DG node persists its function set
            such that when you query it, it'll return the name rather
            than the path.

            Therefore, when adding a node to an object set, it's important
            that it is added either a DAG or DG node depending on what it it.

            This class manages this automatically.

    """

    @protected
    def shortestPath(self):
        return self.name(namespace=True)

    def __iter__(self):
        for member in self.members():
            yield member

    def add(self, member):
        """Add single `member` to set

        Arguments:
            member (cmdx.Node): Node to add

        """

        return self.update([member])

    def remove(self, members):
        mobj = _encode1(self.name(namespace=True))
        selectionList = om1.MSelectionList()

        if not isinstance(members, (tuple, list)):
            selectionList.add(members.path())

        else:
            for member in members:
                selectionList.add(member.path())

        fn = om1.MFnSet(mobj)
        fn.removeMembers(selectionList)

    def update(self, members):
        """Add several `members` to set

        Arguments:
            members (list): Series of cmdx.Node instances

        """

        cmds.sets(list(map(str, members)), forceElement=self.path())

    def clear(self):
        """Remove all members from set"""
        mobj = _encode1(self.name(namespace=True))
        fn = om1.MFnSet(mobj)
        fn.clear()

    def sort(self, key=lambda o: (o.typeName, o.path())):
        """Sort members of set by `key`

        Arguments:
            key (lambda): See built-in `sorted(key)` for reference

        """

        members = sorted(
            self.members(),
            key=key
        )

        self.clear()
        self.update(members)

    def descendent(self, type=None):
        """Return the first descendent"""
        return next(self.descendents(type), None)

    def descendents(self, type=None):
        """Return hierarchy of objects in set"""
        for member in self.members(type=type):
            yield member

            try:
                for child in member.descendents(type=type):
                    yield child

            except AttributeError:
                continue

    def flatten(self, type=None):
        """Return members, converting nested object sets into its members

        Example:
            >>> from maya import cmds
            >>> _ = cmds.file(new=True, force=True)
            >>> a = cmds.createNode("transform", name="a")
            >>> b = cmds.createNode("transform", name="b")
            >>> c = cmds.createNode("transform", name="c")
            >>> cmds.select(a)
            >>> gc = cmds.sets([a], name="grandchild")
            >>> cc = cmds.sets([gc, b], name="child")
            >>> parent = cmds.sets([cc, c], name="parent")
            >>> mainset = encode(parent)
            >>> sorted(mainset.flatten(), key=lambda n: n.name())
            [|a, |b, |c]

        """

        members = set()

        def recurse(objset):
            for member in objset:
                if member.isA(om.MFn.kSet):
                    recurse(member)
                elif type is not None:
                    if type == member.typeName:
                        members.add(member)
                else:
                    members.add(member)

        recurse(self)

        return list(members)

    def member(self, type=None):
        """Return the first member"""

        return next(self.members(type), None)

    def members(self, type=None):
        op = operator.eq
        other = "typeId"

        if isinstance(type, string_types):
            other = "typeName"

        if isinstance(type, (tuple, list)):
            op = operator.contains

        for node in cmds.sets(self.name(namespace=True), query=True) or []:
            node = encode(node)

            if not type or op(type, getattr(node._fn, other)):
                yield node


class AnimCurve(Node):
    if __maya_version__ >= 2016:
        def __init__(self, mobj, exists=True):
            super(AnimCurve, self).__init__(mobj, exists)
            self._fna = oma.MFnAnimCurve(mobj)

        def key(self, time, value, interpolation=Linear):
            if isinstance(time, (float, int)):
                time = Seconds(time)

            index = self._fna.find(time)

            if index:
                self._fna.setValue(index, value)
            else:
                self._fna.addKey(time, value, interpolation, interpolation)

        def keys(self, times, values, interpolation=Linear, change=None):
            times = list(map(
                lambda t: Seconds(t) if isinstance(t, (float, int)) else t,
                times
            ))

            try:
                keepExistingKeys = False  # Default
                args = [
                    times,
                    values,
                    oma.MFnAnimCurve.kTangentGlobal,
                    oma.MFnAnimCurve.kTangentGlobal,
                    keepExistingKeys,
                ]

                if change is not None:
                    args += [change]

                self._fna.addKeys(*args)

            except RuntimeError:
                # The error provided by Maya aren't very descriptive,
                # help a brother out by look for common problems.

                if not times:
                    log.error("No times were provided: %s" % str(times))

                if not values:
                    log.error("No values were provided: %s" % str(values))

                if len(values) != len(times):
                    log.error(
                        "Count mismatch; len(times)=%d, len(values)=%d" % (
                            len(times), len(values)
                        )
                    )

                raise


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

    def __round__(self, digits=2):
        return round(self.read(), digits)

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

    def __lt__(self, other):
        """Is plug less than `other`?

        Examples:
            >>> node = createNode("transform")
            >>> node["scaleX"] < node["translateX"]
            False

        """

        if isinstance(other, Plug):
            other = other.read()
        return self.read() < other

    def __gt__(self, other):
        """Is plug greater than `other`?

        Examples:
            >>> node = createNode("transform")
            >>> node["scaleX"] > node["translateX"]
            True

        """

        if isinstance(other, Plug):
            other = other.read()
        return self.read() > other

    def __neg__(self):
        """Negate unary operator

        Example:
            >>> node = createNode("transform")
            >>> node["visibility"] = 1
            >>> -node["visibility"]
            -1

        """

        return -self.read()

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
                return self._node[self.name(long=False) + other]
            except ExistError:
                # E.g. node["translate"] + "X"
                return self._node[self.name(long=True) + other]

        raise TypeError(
            "unsupported operand type(s) for +: 'Plug' and '%s'"
            % type(other)
        )

    def __iadd__(self, other):
        """Support += operator, for .append()

        Example:
            >>> node = createNode("transform")
            >>> node["myArray"] = Double(array=True)
            >>> node["myArray"].append(1.0)
            >>> node["myArray"].extend([2.0, 3.0])
            >>> node["myArray"] += 5.1
            >>> node["myArray"] += [1.1, 2.3, 999.0]
            >>> node["myArray"][0]
            1.0
            >>> node["myArray"][6]
            999.0
            >>> node["myArray"][-1]
            999.0

        """

        if isinstance(other, (tuple, list)):
            for entry in other:
                self.append(entry)
        else:
            self.append(other)

        return self

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

    def __floordiv__(self, other):
        """Disconnect attribute via A // B

        Example:
            >>> nodeA = createNode("transform")
            >>> nodeB = createNode("transform")
            >>> nodeA["tx"] >> nodeB["tx"]
            >>> nodeA["tx"] = 5
            >>> nodeB["tx"] == 5
            True
            >>> nodeA["tx"] // nodeB["tx"]
            >>> nodeA["tx"] = 0
            >>> nodeB["tx"] == 5
            True

        """

        self.disconnect(other)

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
            >>> for single in node["visibility"]:
            ...   print(single)
            ...
            True
            >>> node = createNode("wtAddMatrix")
            >>> node["wtMatrix"][0]["weightIn"] = 1.0

        """

        if self._mplug.isArray:
            # getExisting... returns indices currently in use, which is
            # important if the given array is *sparse*. That is, if
            # indexes 5, 7 and 8 are used. If we simply call
            # `evaluateNumElements` then it'll return a single number
            # we could use to `range()` from, but that would only work
            # if the indices were contiguous.
            for index in self._mplug.getExistingArrayAttributeIndices():
                yield self[index]

        elif self._mplug.isCompound:
            for index in range(self._mplug.numChildren()):
                yield self[index]

        else:
            values = self.read()

            # Facilitate single-value attributes
            values = values if isinstance(values, (tuple, list)) else [values]

            for value in values:
                yield value

    def __getitem__(self, logicalIndex):
        """Read from child of array or compound plug

        Arguments:
            logicalIndex (int): Logical index of plug (NOT physical, make note)

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> node = createNode("transform", name="mynode")
            >>> node["translate"][0].read()
            0.0
            >>> node["visibility"][0]
            Traceback (most recent call last):
            ...
            TypeError: |mynode.visibility does not support indexing
            >>> node["translate"][2] = 5.1
            >>> node["translate"][2].read()
            5.1

            # Elements are accessed by logical index, rather than physical
            >>> tm = createNode("transform")
            >>> mult = createNode("multMatrix")
            >>> plug = mult["matrixIn"]
            >>> plug[0] << tm["matrix"]
            >>> plug[1] << tm["parentMatrix"][0]
            >>> plug[2] << tm["worldMatrix"][0]

            >>> plug[2].connection(plug=True) == tm["worldMatrix"][0]
            True

            # Notice how index 2 remains index 2 even on disconnect
            # The physical index moves to 1.
            >>> plug[1].disconnect()
            >>> plug[2].connection(plug=True) == tm["worldMatrix"][0]
            True

        """

        cls = self.__class__

        if isinstance(logicalIndex, int):
            # Support backwards-indexing
            if logicalIndex < 0:
                logicalIndex = self.count() - abs(logicalIndex)

            if self._mplug.isArray:
                # Preserve behavior from MEL
                #
                # NOTE: Physical index makes a lot more sense for
                # programmatic use, but it isn't reliable when
                # accessing native Maya array attributes like worldMatrix
                # In that case, there is no index-0, even though a logical
                # index 0 most definitely always (?) exists.
                item = self._mplug.elementByLogicalIndex(logicalIndex)
                return cls(self._node, item, self._unit)

            elif self._mplug.isCompound:
                item = self._mplug.child(logicalIndex)
                return cls(self._node, item, self._unit)

            else:
                raise TypeError(
                    "%s does not support indexing" % self.path()
                )

        elif isinstance(logicalIndex, string_types):
            # Compound attributes have no equivalent
            # to "MDependencyNode.findPlug()" and must
            # be searched by hand.
            if self._mplug.isCompound:
                for child in range(self._mplug.numChildren()):
                    child = self._mplug.child(child)
                    _, name = child.name().rsplit(".", 1)

                    if logicalIndex == name:
                        return cls(self._node, child)

            else:
                raise TypeError("'%s' is not a compound attribute"
                                % self.path())

            raise ExistError("'%s' was not found" % logicalIndex)

    def __setitem__(self, index, value):
        """Write to child of array or compound plug

        Example:
            >>> node = createNode("transform")
            >>> node["translate"][0] = 5
            >>> node["tx"]
            5.0

        """

        self[index].write(value)

    def __hash__(self):
        """Support storing in set() and as key in dict()"""
        return hash(self.path())

    def __init__(self, node, mplug, unit=None, key=None):
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

    def clone(self, name, shortName=None, niceName=None):
        """Return `AbstractAttribute` of this exact plug

        This can be used to replicate one plug on another node,
        including default values, min/max values, hidden and keyable
        states etc.

        Examples:
            >>> parent = createNode("transform")
            >>> cam = createNode("camera", parent=parent)
            >>> original = cam["focalLength"]
            >>> clone = original.clone("focalClone")

            # Original setup is preserved
            >>> clone["min"]
            2.5
            >>> clone["max"]
            100000.0

            >>> cam.addAttr(clone)
            >>> cam["focalClone"].read()
            35.0

            # Also works with modifiers
            >>> with DagModifier() as mod:
            ...   clone = cam["fStop"].clone("fClone")
            ...   _ = mod.addAttr(cam, clone)
            ...
            >>> cam["fClone"].read()
            5.6

        """

        assert isinstance(self, Plug)

        if self.isArray:
            raise TypeError("Array plugs are unsupported")

        if self.isCompound:
            raise TypeError("Compound plugs are unsupported")

        if niceName is False:
            niceName = None
        else:
            niceName = niceName or self.niceName

        # There is no way to tell whether the niceName of
        # a plug is automatically generated by Maya or if
        # it is overridden by the user (if there is, please let me know!)
        # So we'll wing it, and assume the user has not given
        # the same nice name as would have been generated from
        # the long name.
        if niceName == _camel_to_title(name):
            niceName = None

        cls = self.typeClass()
        fn = self.fn()
        attr = cls(
            name,
            default=self.default,
            label=niceName,
            shortName=shortName,
            writable=fn.writable,
            readable=fn.readable,
            cached=fn.cached,
            storable=fn.storable,
            keyable=fn.keyable,
            hidden=fn.hidden,
            channelBox=fn.channelBox,
            affectsAppearance=fn.affectsAppearance,
            affectsWorldSpace=fn.affectsWorldSpace,
            array=fn.array,
            indexMatters=fn.indexMatters,
            connectable=fn.connectable,
            disconnectBehavior=fn.disconnectBehavior,
        )

        if hasattr(fn, "getMin") and fn.hasMin():
            attr["min"] = fn.getMin()

        if hasattr(fn, "getMax") and fn.hasMax():
            attr["max"] = fn.getMax()

        return attr

    def plug(self):
        """Return the MPlug of this cmdx.Plug"""
        return self._mplug

    def attribute(self):
        """Return the attribute MObject of this cmdx.Plug"""
        return self._mplug.attribute()

    @property
    def isArray(self):
        return self._mplug.isArray

    @property
    def arrayIndices(self):
        if not self._mplug.isArray:
            raise TypeError("{} is not an array".format(self.path()))

        # Convert from `p_OpenMaya_py2.rItemNot3Strs` to list
        return list(self._mplug.getExistingArrayAttributeIndices())

    @property
    def isCompound(self):
        return self._mplug.isCompound

    def nextAvailableIndex(self, startIndex=0):
        """Find the next unconnected element in an array plug

        Array plugs have both a "logical" and "physical" index.
        Accessing any array plug via index means to access it's
        logical element.

        [0]<---- plug1
        [.]
        [.]
        [3]<---- plug2
        [4]<---- plug3
        [5]<---- plug4
        [.]
        [7]<---- plug5

        In the above scenario, 5 plugs are connected by 5 physical
        indices, and yet the last index is 7. 7 is a logical index.

        This function walks each element from the `startIndex` in search
        of the first available index, in this case [1].

        Examples:
            >>> transform = createNode("transform")
            >>> mult = createNode("multMatrix")
            >>> mult["matrixIn"][0] << transform["matrix"]
            >>> mult["matrixIn"][1] << transform["matrix"]
            >>> mult["matrixIn"][2] << transform["matrix"]

            # 3 logical indices are occupied
            >>> mult["matrixIn"].count()
            3

            # Disconnecting affects the physical count
            >>> mult["matrixIn"][1].disconnect()
            >>> mult["matrixIn"].count()
            2

            # But the last logical index is still 2
            >>> mult["matrixIn"].arrayIndices
            [0, 2]

            # Finally, let's find the next available index
            >>> mult["matrixIn"].nextAvailableIndex()
            1

        """

        # Assume a max of 10 million connections
        max_index = 1e7

        while startIndex < max_index:
            if self[startIndex].connection() is None:
                return startIndex
            startIndex += 1

        # No connections means the first index is available
        return 0

    def pull(self):
        """Pull on a plug, without seriasing any value. For performance"""
        self._mplug.asMObject()

    def append(self, value, autofill=False):
        """Add `value` to end of self, which is an array

        Arguments:
            value (object): If value, create a new entry and append it.
                If cmdx.Plug, create a new entry and connect it.
            autofill (bool): Append to the next available index. This performs
                a search for the first *unconnected* value of an array to
                reuse potentially disconnected plugs and optimise space.

        Example:
            >>> _ = cmds.file(new=True, force=True)
            >>> node = createNode("transform", name="appendTest")
            >>> node["myArray"] = Double(array=True)
            >>> node["myArray"].append(1.0)
            >>> node["notArray"] = Double()
            >>> node["notArray"].append(2.0)
            Traceback (most recent call last):
            ...
            TypeError: "|appendTest.notArray" was not an array attribute
            >>> node["myArray"][0] << node["tx"]
            >>> node["myArray"][1] << node["ty"]
            >>> node["myArray"][2] << node["tz"]
            >>> node["myArray"].count()
            3
            >>> # Disconnect doesn't change count
            >>> node["myArray"][1].disconnect()
            >>> node["myArray"].count()
            3
            >>> node["myArray"].append(node["ty"])
            >>> node["myArray"].count()
            4
            >>> # Reuse disconnected slot with autofill=True
            >>> node["myArray"].append(node["rx"], autofill=True)
            >>> node["myArray"].count()
            4

        """

        if not self._mplug.isArray:
            raise TypeError("\"%s\" was not an array attribute" % self.path())

        if autofill:
            index = self.nextAvailableIndex()
        else:
            index = self.count()

        if isinstance(value, Plug):
            self[index] << value
        else:
            self[index].write(value)

    def extend(self, values):
        """Append multiple values to the end of an array

        Arguments:
            values (tuple): If values, create a new entry and append it.
                If cmdx.Plug's, create a new entry and connect it.

        Example:
            >>> node = createNode("transform")
            >>> node["myArray"] = Double(array=True)
            >>> node["myArray"].extend([1.0, 2.0, 3.0])
            >>> node["myArray"][0]
            1.0
            >>> node["myArray"][-1]
            3.0

        """

        for value in values:
            self.append(value)

    def count(self):
        return self._mplug.evaluateNumElements()

    def asDouble(self, time=None):
        """Return plug as double (Python float)

        Example:
            >>> node = createNode("transform")
            >>> node["translateX"] = 5.0
            >>> node["translateX"].asDouble()
            5.0

        """

        if time is not None:
            return self._mplug.asDouble(DGContext(time=time))
        return self._mplug.asDouble()

    def asMatrix(self, time=None):
        """Return plug as MatrixType

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

        if time is not None:
            context = DGContext(time=time)
            obj = self._mplug.asMObject(context)
        else:
            obj = self._mplug.asMObject()

        return MatrixType(om.MFnMatrixData(obj).matrix())

    def asTransformationMatrix(self, time=None):
        """Return plug as TransformationMatrix

        Example:
            >>> node = createNode("transform")
            >>> node["translateY"] = 12
            >>> node["rotate"] = 1
            >>> tm = node["matrix"].asTransform()
            >>> [round(v, 1) for v in tm.rotation()]
            [1.0, 1.0, 1.0]
            >>> list(tm.translation())
            [0.0, 12.0, 0.0]

        """

        return TransformationMatrix(self.asMatrix(time))

    # Alias
    asTm = asTransformationMatrix
    asTransform = asTransformationMatrix

    def asEulerRotation(self, order=kXYZ, time=None):
        value = self.read(time=time)
        return Euler(om.MEulerRotation(value, order))

    asEuler = asEulerRotation

    def asQuaternion(self, time=None):
        value = self.read(time=time)
        value = Euler(value).asQuaternion()
        return Quaternion(value)

    def asVector(self, time=None):
        assert self.isArray or self.isCompound, "'%s' not an array" % self
        return Vector(self.read(time=time))

    def asPoint(self, time=None):
        assert self.isArray or self.isCompound, "'%s' not an array" % self
        return Point(self.read(time=time))

    def asTime(self, time=None):
        attr = self._mplug.attribute()
        type = attr.apiType()

        if type != om.MFn.kTimeAttribute:
            raise TypeError("%s is not a time attribute" % self.path())

        kwargs = {}
        if time is not None:
            kwargs["context"] = DGContext(time=time)

        return self._mplug.asMTime(**kwargs)

    @property
    def connected(self):
        """Return whether or not this attribute has an input connection

        Examples:
            >>> node = createNode("transform")
            >>> node["tx"] >> node["ty"]

            # ty is connected, tx is not
            >>> node["tx"].connected
            False

            >>> node["ty"].connected
            True

        """

        return self.connection(destination=False) is not None

    def animated(self, recursive=True):
        """Return whether this attribute is connected to an animCurve

        Arguments:
            recursive (bool, optional): Should I travel to connected
                attributes in search of an animCurve, or only look to
                the immediate connection?

        """

        other = self.connection(destination=False, plug=True)
        while other is not None:

            node = other.node()
            if node.object().hasFn(om.MFn.kAnimCurve):
                return True

            if not recursive:
                break

            other = other.connection(destination=False, plug=True)

        return False

    def lock(self):
        """Convenience function for plug.locked = True

        Examples:
            # Static attributes work just fine
            >>> _new()
            >>> node1 = createNode("transform", name="node1")
            >>> node1["translateX"].locked
            False
            >>> node1["translateX"].locked = True
            >>> _save()
            >>> _load()
            >>> node1 = encode("node1")
            >>> node1["translateX"].locked
            True

            # Dynamic attributes work too
            >>> _new()
            >>> node1 = createNode("transform", name="node1")
            >>> node1["dynamicAttr"] = Double()
            >>> node1["dynamicAttr"].locked
            False
            >>> node1["dynamicAttr"].locked = True
            >>> _save()
            >>> _load()
            >>> node1 = encode("node1")
            >>> node1["dynamicAttr"].locked
            True

        """

        self.locked = True

    def unlock(self):
        """Convenience function for plug.locked = False"""
        self.locked = False

    @property
    def locked(self):
        return self._mplug.isLocked

    @locked.setter
    def locked(self, value):
        """Lock attribute"""

        elements = (
            self
            if self.isArray or self.isCompound
            else [self]
        )

        for el in elements:
            # Use setAttr in place of MPlug.isLocked = False, as that
            # doesn't persist the scene on save if the attribute is dynamic.
            if el._mplug.isDynamic:
                cmds.setAttr(el.path(), lock=value)

            else:
                el._mplug.isLocked = value

    def _channelBoxTest(self, value=None):
        """@properties aren't tested

        Examples:
            # Static attributes work just fine
            >>> _new()
            >>> node1 = createNode("transform", name="node1")
            >>> node1["translateX"].channelBox
            False
            >>> node1["translateX"].channelBox = True
            >>> _save()
            >>> _load()
            >>> node1 = encode("node1")
            >>> node1["translateX"].channelBox
            True

            # Dynamic attributes work too
            >>> _new()
            >>> node1 = createNode("transform", name="node1")
            >>> node1["dynamicAttr"] = Double()
            >>> node1["dynamicAttr"].channelBox
            False
            >>> node1["dynamicAttr"].channelBox = True
            >>> _save()
            >>> _load()
            >>> node1 = encode("node1")
            >>> node1["dynamicAttr"].channelBox
            True

        """

    @property
    def channelBox(self):
        """Is the attribute visible in the Channel Box?"""
        if self.isArray or self.isCompound:
            return all(
                plug._mplug.isChannelBox
                for plug in self
            )
        else:
            return self._mplug.isChannelBox

    @channelBox.setter
    def channelBox(self, value):
        """Make a non-keyable attribute visible in the channel box"""

        elements = (
            self
            if self.isArray or self.isCompound
            else [self]
        )

        for el in elements:
            if el._mplug.isDynamic:
                # Use setAttr as isChannelBox doesn't
                # persist on scene save for dynamic attributes.
                cmds.setAttr(el.path(), keyable=value, channelBox=value)
            else:
                el._mplug.isChannelBox = value

    def _keyableTest(self, value=None):
        """@properties aren't tested

        Examples:
            # Static attributes work just fine
            >>> _new()
            >>> node1 = createNode("transform", name="node1")
            >>> node1["translateX"].keyable
            True
            >>> node1["translateX"].keyable = False
            >>> _save()
            >>> _load()
            >>> node1 = encode("node1")
            >>> node1["translateX"].keyable
            False

            # Dynamic attributes work too
            >>> _new()
            >>> node1 = createNode("transform", name="node1")
            >>> node1["dynamicAttr"] = Double(keyable=True)
            >>> node1["dynamicAttr"].keyable
            True
            >>> node1["dynamicAttr"].keyable = False
            >>> _save()
            >>> _load()
            >>> node1 = encode("node1")
            >>> node1["dynamicAttr"].keyable
            False

        """

    @property
    def keyable(self):
        """Is the attribute keyable?"""
        if self.isArray or self.isCompound:
            return all(
                plug._mplug.isKeyable
                for plug in self
            )
        else:
            return self._mplug.isKeyable

    @keyable.setter
    def keyable(self, value):

        # Facilitate passing e.g. `0` or `None`
        value = bool(value)

        elements = (
            self
            if self.isArray or self.isCompound
            else [self]
        )

        for el in elements:
            if el._mplug.isDynamic:
                # Use setAttr as isKeyable doesn't
                # persist on scene save for dynamic attributes.
                cmds.setAttr(el.path(), keyable=value)
            else:
                el._mplug.isKeyable = value

    @property
    def hidden(self):
        return om.MFnAttribute(self._mplug.attribute()).hidden

    @hidden.setter
    def hidden(self, value):
        pass

    def hide(self):
        """Hide attribute from channel box

        Note: An attribute cannot be hidden from the channel box
        and keyable at the same time. Therefore, this method
        also makes the attribute non-keyable.

        Supports array and compound attributes too.

        """

        self.keyable = False
        self.channelBox = False

    def lockAndHide(self):
        self.lock()
        self.hide()

    @property
    def niceName(self):
        """The nice name of this plug, visible in e.g. Channel Box

        Examples:
            >>> _new()
            >>> node = createNode("transform", name="myTransform")

            # Return pairs of nice names for compound attributes
            >>> node["scale"].niceName == ("Scale X", "Scale Y", "Scale Z")
            True

            >>> assert node["translateY"].niceName == "Translate Y"
            >>> node["translateY"].niceName = "New Name"
            >>> assert node["translateY"].niceName == "New Name"

            # The nice name is preserved on scene open
            >>> _save()
            >>> _load()
            >>> node = encode("myTransform")
            >>> assert node["translateY"].niceName == "New Name"

        """

        # No way of retrieving this information via the API?

        if self.isArray or self.isCompound:
            return tuple(
                cmds.attributeName(plug.path(), nice=True)
                for plug in self
            )
        else:
            return cmds.attributeName(self.path(), nice=True)

    @niceName.setter
    def niceName(self, value):
        elements = (
            self
            if self.isArray or self.isCompound
            else [self]
        )

        for el in elements:
            if el._mplug.isDynamic:
                # Use setAttr as isKeyable doesn't
                # persist on scene save for dynamic attributes.
                cmds.addAttr(el.path(), edit=True, niceName=value)
            else:
                fn = om.MFnAttribute(el._mplug.attribute())
                fn.setNiceNameOverride(value)

    @property
    def default(self):
        """Return default value of plug"""
        return _plug_to_default(self._mplug)

    def fn(self):
        """Return the correct function set for the plug attribute MObject"""

        attr = self._mplug.attribute()
        typ = attr.apiType()

        if typ == om.MFn.kNumericAttribute:
            fn = om.MFnNumericAttribute(attr)

        elif typ == om.MFn.kUnitAttribute:
            fn = om.MFnUnitAttribute(attr)

        elif typ in (om.MFn.kDoubleLinearAttribute,
                     om.MFn.kFloatLinearAttribute,
                     om.MFn.kDoubleAngleAttribute,
                     om.MFn.kFloatAngleAttribute):
            return om.MFnUnitAttribute(attr)

        elif typ == om.MFn.kTypedAttribute:
            fn = om.MFnTypedAttribute(attr)

        elif typ in (om.MFn.kMatrixAttribute,
                     om.MFn.kFloatMatrixAttribute):
            fn = om.MFnMatrixAttribute(attr)

        elif typ == om.MFn.kMessageAttribute:
            fn = om.MFnMessageAttribute(attr)

        else:
            raise TypeError(
                "Couldn't figure out function set for '%s.%s'" % (
                    self.path(), attr.apiTypeStr
                )
            )

        return fn

    def reset(self):
        """Restore plug to default value"""

        if self.writable:
            self.write(self.default)
        else:
            raise TypeError(
                "Cannot reset non-writable attribute '%s'" % self.path()
            )

    @property
    def writable(self):
        """Can the user write to this attribute?

        Convenience for combined call to `plug.connected`
        and `plug.locked`.

        Example:
            >> if node["translateX"].writable:
            ..   node["translateX"] = 5

        """

        return not any([self.connected, self.locked])

    def show(self):
        """Show attribute in channel box

        Note: An attribute can be both visible in the channel box
        and non-keyable, therefore, unlike :func:`hide()`, this
        method does not alter the keyable state of the attribute.

        """

        self.channelBox = True

    @property
    def editable(self):
        return self._mplug.isFreeToChange() == om.MPlug.kFreeToChange

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

    def typeClass(self):
        """Retrieve cmdx Attribute class of plug, e.g. Double

        This reverse-engineers the plug attribute into the
        attribute class used to originally create it. It'll
        work on attributes not created with cmdx as well, but
        won't catch'em'all (see below)

        Examples:
            >>> victim = createNode("transform")
            >>> victim["enumAttr"] = Enum()
            >>> victim["stringAttr"] = String()
            >>> victim["messageAttr"] = Message()
            >>> victim["matrixAttr"] = Matrix()
            >>> victim["longAttr"] = Long()
            >>> victim["doubleAttr"] = Double()
            >>> victim["floatAttr"] = Float()
            >>> victim["double3Attr"] = Double3()
            >>> victim["booleanAttr"] = Boolean()
            >>> victim["angleAttr"] = Angle()
            >>> victim["timeAttr"] = Time()
            >>> victim["distanceAttr"] = Distance()
            >>> victim["compoundAttr"] = Compound(children=[Double("Temp")])

            >>> assert victim["enumAttr"].typeClass() == Enum
            >>> assert victim["stringAttr"].typeClass() == String
            >>> assert victim["messageAttr"].typeClass() == Message
            >>> assert victim["matrixAttr"].typeClass() == Matrix
            >>> assert victim["longAttr"].typeClass() == Long
            >>> assert victim["doubleAttr"].typeClass() == Double
            >>> assert victim["floatAttr"].typeClass() == Float
            >>> assert victim["double3Attr"].typeClass() == Double3
            >>> assert victim["booleanAttr"].typeClass() == Boolean
            >>> assert victim["angleAttr"].typeClass() == Angle
            >>> assert victim["timeAttr"].typeClass() == Time
            >>> assert victim["distanceAttr"].typeClass() == Distance
            >>> assert victim["compoundAttr"].typeClass() == Compound

            # Unsupported
            # >>> victim["dividerAttr"] = Divider()
            # >>> victim["double2Attr"] = Double2()
            # >>> victim["double4Attr"] = Double4()
            # >>> victim["angle2Attr"] = Angle2()
            # >>> victim["angle3Attr"] = Angle3()
            # >>> victim["distance2Attr"] = Distance2()
            # >>> victim["distance3Attr"] = Distance3()
            # >>> victim["distance4Attr"] = Distance4()

        """

        attr = self._mplug.attribute()
        typ = attr.apiType()

        if typ == om.MFn.kAttribute3Double:
            return Double3

        elif typ == om.MFn.kNumericAttribute:
            typ = om.MFnNumericAttribute(attr).numericType()
            if typ == om.MFnNumericData.kBoolean:
                return Boolean

            elif typ in (om.MFnNumericData.kLong,
                         om.MFnNumericData.kInt):
                return Long

            elif typ == om.MFnNumericData.kDouble:
                return Double

            elif typ == om.MFnNumericData.kFloat:
                return Float

        elif typ in (om.MFn.kDoubleAngleAttribute,
                     om.MFn.kFloatAngleAttribute):
            return Angle

        elif typ in (om.MFn.kDoubleLinearAttribute,
                     om.MFn.kFloatLinearAttribute):
            return Distance

        elif typ == om.MFn.kTimeAttribute:
            return Time

        elif typ == om.MFn.kEnumAttribute:
            return Enum

        elif typ == om.MFn.kUnitAttribute:
            typ = om.MFnUnitAttribute(attr).unitType()
            if typ == om.MFnUnitAttribute.kAngle:
                return Angle

            elif typ == om.MFnUnitAttribute.kDistance:
                return Distance

            elif typ == om.MFnUnitAttribute.kTime:
                return Time

        elif typ == om.MFn.kTypedAttribute:
            typ = om.MFnTypedAttribute(attr).attrType()
            if typ == om.MFnData.kString:
                return String

            elif typ == om.MFnData.kMatrix:
                return Matrix

        elif typ == om.MFn.kCompoundAttribute:
            return Compound

        elif typ in (om.MFn.kMatrixAttribute,
                     om.MFn.kFloatMatrixAttribute):
            return Matrix

        elif typ == om.MFn.kMessageAttribute:
            return Message

        apitype = self._mplug.attribute().apiTypeStr
        raise TypeError('%s is not implemented' % apitype)

    def path(self, full=False):
        """Return path to attribute, including node path

            Examples:
                >>> persp = encode("persp")
                >>> persp["translate"].path()
                '|persp.translate'
                >>> persp["translateX"].path()
                '|persp.translateX'
                >>> persp["translateX"].path(full=True)
                '|persp.translate.translateX'

            """

        return "{}.{}".format(
            self._node.path(), self._mplug.partialName(
                includeNodeName=False,
                useLongNames=True,
                useFullAttributePath=full
            )
        )

    def name(self, long=True, full=False):
        """Return name part of an attribute

        Examples:
            >>> persp = encode("persp")
            >>> persp["translateX"].name()
            'translateX'
            >>> persp["tx"].name()
            'translateX'
            >>> persp["tx"].name(long=False)
            'tx'
            >>> persp["tx"].name(full=True)
            'translate.translateX'
            >>> persp["tx"].name(long=False, full=True)
            't.tx'

        """

        return "{}".format(
            self._mplug.partialName(
                includeNodeName=False,
                useLongNames=long,
                useFullAttributePath=full
            )
        )

    def read(self, unit=None, time=None):
        """Read attribute value

        Arguments:
            unit (int, optional): Unit with which to read plug
            time (float, optional): Time at which to read plug

        Example:
            >>> node = createNode("transform")
            >>> node["ty"] = 100.0
            >>> node["ty"].read()
            100.0
            >>> node["ty"].read(unit=Meters)
            1.0

        """

        unit = unit if unit is not None else self._unit
        context = None if time is None else DGContext(time=time)

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

    if __maya_version__ > 2015:
        def animate(self, values, interpolation=None):
            """Treat values as time:value pairs and animate this attribute

            Example:
                >>> _ = cmds.file(new=True, force=True)
                >>> node = createNode("transform")
                >>> node["tx"] = {1: 0.0, 5: 1.0, 10: 0.0}
                >>> node["rx"] = {1: 0.0, 5: 1.0, 10: 0.0}
                >>> node["sx"] = {1: 0.0, 5: 1.0, 10: 0.0}
                >>> node["v"] = {1: True, 5: False, 10: True}

                # Direct function call
                >>> node["ry"].animate({1: 0.0, 5: 1.0, 10: 0.0})

                # Interpolation
                >>> node["rz"].animate({1: 0.0, 5: 1.0, 10: 0.0}, Smooth)

            """

            times, values = list(map(UiUnit(), values.keys())), values.values()
            typ = _find_curve_type(self)
            anim = self.input(type=typ)

            if not anim:
                anim = createNode(typ)
                anim["output"] >> self

            anim.keys(times, values, interpolation=Linear)

    def write(self, value):
        if isinstance(value, dict) and __maya_version__ > 2015:
            return self.animate(value)

        try:
            _python_to_plug(value, self)
            self._cached = value

        except RuntimeError:
            raise

        except TypeError:
            log.error("'%s': failed to write attribute" % self.path())
            raise

    def connect(self, other, force=True):
        mod = om.MDGModifier()

        if force:
            # Disconnect any plug connected to `other`
            for plug in other._mplug.connectedTo(True, False):
                mod.disconnect(plug, other._mplug)

        mod.connect(self._mplug, other._mplug)
        mod.doIt()

    def disconnect(self, other=None, source=True, destination=True):
        """Disconnect self from `other`

        Arguments:
            other (Plug, optional): If none is provided, disconnect everything

        Example:
            >>> node1 = createNode("transform")
            >>> node2 = createNode("transform")
            >>> node2["tx"].connection() is None
            True
            >>> node2["ty"].connection() is None
            True
            >>>
            >>> node2["tx"] << node1["tx"]
            >>> node2["ty"] << node1["ty"]
            >>> node2["ty"].connection() is None
            False
            >>> node2["tx"].connection() is None
            False
            >>>
            >>> node2["tx"].disconnect(node1["tx"])
            >>> node2["ty"].disconnect()
            >>> node2["tx"].connection() is None
            True
            >>> node2["ty"].connection() is None
            True

        """

        other = getattr(other, "_mplug", None)

        mod = DGModifier()
        mod.disconnect(self._mplug, other, source, destination)
        mod.doIt()

    def connections(self,
                    type=None,
                    source=True,
                    destination=True,
                    plugs=False,
                    unit=None):
        """Yield plugs connected to self

        Arguments:
            type (int, optional): Only return nodes of this type
            source (bool, optional): Return source plugs,
                default is True
            destination (bool, optional): Return destination plugs,
                default is True
            plugs (bool, optional): Return connected plugs instead of nodes
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
            >>> b["arrayAttr"] = Long(array=True)
            >>> b["arrayAttr"][0] >> a["ihi"]
            >>> b["arrayAttr"][1] >> a["visibility"]
            >>> a["ihi"].connection() == b
            True
            >>> a["ihi"].connection(plug=True) == b["arrayAttr"][0]
            True
            >>> a["visibility"].connection(plug=True) == b["arrayAttr"][1]
            True
            >>> b["arrayAttr"][1].connection(plug=True) == a["visibility"]
            True

        """

        for plug in self._mplug.connectedTo(source, destination):
            mobject = plug.node()
            node = Node(mobject)

            if type is None or node.isA(type):
                if plugs:
                    if SAFE_MODE:
                        assert not plug.isNull

                    # For some reason mplug.connectedTo returns networked plugs
                    # sometimes, we have to convert them before using them.
                    # https://forums.autodesk.com/t5/maya-programming/maya-api-what-is-a-networked-plug-and-do-i-want-it-or-not/td-p/7182472
                    if plug.isNetworked:

                        if plug.isElement:
                            # Name would be e.g. 'myArrayAttr[0]'
                            # raise TypeError(plug.partialName() + "\n")
                            name = plug.partialName()

                            if name.endswith("]"):
                                name, index = name.rsplit("[", 1)
                                index = int(index.rstrip("]"))

                            else:
                                # E.g. worldMatrix[0] -> wm
                                index = 0

                            plug = node.findPlug(name)

                            # The index returned is *logical*, not physical.
                            plug = plug.elementByLogicalIndex(index)

                        else:
                            plug = node.findPlug(plug.partialName())

                    yield Plug(node, plug, unit)
                else:
                    yield node

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

    def input(self,
              type=None,
              plug=False,
              unit=None):
        """Return input connection from :func:`connections()`"""
        return next(self.connections(type=type,
                                     source=True,
                                     destination=False,
                                     plugs=plug,
                                     unit=unit), None)

    def outputs(self,
                type=None,
                plugs=False,
                unit=None):
        """Return output connections from :func:`connections()`"""
        return self.connections(type=type,
                                source=False,
                                destination=True,
                                plugs=plugs,
                                unit=unit)

    def output(self,
               type=None,
               plug=False,
               unit=None):
        """Return first output connection from :func:`connections()`"""
        return next(self.connections(type=type,
                                     source=False,
                                     destination=True,
                                     plugs=plug,
                                     unit=unit), None)

    def source(self, unit=None):
        cls = self.__class__
        plug = self._mplug.source()
        node = Node(plug.node())

        if not plug.isNull:
            return cls(node, plug, unit)

    def node(self):
        return self._node

    if ENABLE_PEP8:
        as_double = asDouble
        as_matrix = asMatrix
        as_transformation_matrix = asTransformationMatrix
        as_transform = asTransform
        as_euler_rotation = asEulerRotation
        as_euler = asEuler
        as_quaternion = asQuaternion
        as_vector = asVector
        as_point = asPoint
        as_time = asTime
        channel_box = channelBox
        lock_and_hide = lockAndHide
        array_indices = arrayIndices
        type_class = typeClass
        next_available_index = nextAvailableIndex


class TransformationMatrix(om.MTransformationMatrix):
    """A more readable version of Maya's MTransformationMatrix

    Added:
        - Takes tuples/lists in place of MVector and other native types
        - Support for multiplication
        - Support for getting individual axes
        - Support for direct access to the quaternion

    Arguments:
        matrix (Matrix, TransformationMatrix, optional): Original constructor
        translate (tuple, Vector, optional): Initial translate value
        rotate (tuple, Vector, optional): Initial rotate value
        scale (tuple, Vector, optional): Initial scale value

    """

    def __repr__(self):
        return (
            "MTransformationMatrix(\n"
            "  translate: {t}\n"
            "  rotate: {r}\n"
            "  scale: {s}\n"
            "  rotatePivot: {rp}\n"
            "  rotatePivotTranslation: {rpt}\n"
            "  scalePivot: {sp}\n"
            "  scalePivotTranslation: {spt}\n"
            ")"
        ).format(
            t=self.translation(),
            r="(%.2f, %.2f, %.2f)" % tuple(
                degrees(v) for v in self.rotation()),
            s=self.scale(),
            rp=self.rotatePivot(),
            rpt=self.rotatePivotTranslation(),
            sp=self.scalePivot(),
            spt=self.scalePivotTranslation(),
        )

    def __init__(self, matrix=None, translate=None, rotate=None, scale=None):

        # It doesn't like being handed `None`
        args = [matrix] if matrix is not None else []

        super(TransformationMatrix, self).__init__(*args)

        if translate is not None:
            self.setTranslation(translate)

        if rotate is not None:
            self.setRotation(rotate)

        if scale is not None:
            self.setScale(scale)

    def __mul__(self, other):
        if isinstance(other, (tuple, list)):
            other = Vector(*other)

        if isinstance(other, om.MVector):
            p = self.translation()
            q = self.quaternion()
            return p + q * other

        elif isinstance(other, om.MMatrix):
            return type(self)(self.asMatrix() * other)

        elif isinstance(other, om.MTransformationMatrix):
            return type(self)(self.asMatrix() * other.asMatrix())

        else:
            raise TypeError(
                "unsupported operand type(s) for *: '%s' and '%s'"
                % (type(self).__name__, type(other).__name__)
            )

    @property
    def xAxis(self):
        return self.quaternion() * Vector(1, 0, 0)

    @property
    def yAxis(self):
        return self.quaternion() * Vector(0, 1, 0)

    @property
    def zAxis(self):
        return self.quaternion() * Vector(0, 0, 1)

    def translateBy(self, vec, space=None):
        space = space or sTransform
        if isinstance(vec, (tuple, list)):
            vec = Vector(vec)
        return super(TransformationMatrix, self).translateBy(vec, space)

    def rotateBy(self, rot, space=None):
        """Handle arguments conveniently

        - Allow for optional `space` argument
        - Automatically convert tuple to Vector

        Arguments:
            rot (Vector, Quaternion): Rotation to add

        """

        space = space or sTransform
        if isinstance(rot, (tuple, list)):
            rot = Vector(rot)

        if isinstance(rot, om.MVector):
            rot = EulerRotation(rot)

        return super(TransformationMatrix, self).rotateBy(rot, space)

    def scale(self, space=None):
        """Make space into an optional argument"""
        space = space or sTransform
        return Vector(super(TransformationMatrix, self).scale(space))

    def quaternion(self):
        """Return transformation matrix as a Quaternion"""
        return Quaternion(self.rotation(asQuaternion=True))

    def rotatePivot(self, space=None):
        """This method does not typically support optional arguments"""
        space = space or sTransform
        return Vector(super(TransformationMatrix, self).rotatePivot(space))

    def setRotatePivot(self, pivot, space=sTransform, balance=False):
        pivot = pivot if isinstance(pivot, om.MPoint) else om.MPoint(pivot)
        return super(TransformationMatrix, self).setRotatePivot(
            pivot, space, balance)

    def rotatePivotTranslation(self, space=None):
        """This method does not typically support optional arguments"""
        space = space or sTransform
        return Vector(
            super(TransformationMatrix, self).rotatePivotTranslation(space)
        )

    def scalePivot(self, space=None):
        """This method does not typically support optional arguments"""
        space = space or sTransform
        return Vector(super(TransformationMatrix, self).scalePivot(space))

    def scalePivotTranslation(self, space=None):
        """This method does not typically support optional arguments"""
        space = space or sTransform
        return Vector(
            super(TransformationMatrix, self).scalePivotTranslation(space)
        )

    def translation(self, space=None):  # type: (om.MSpace) -> om.MVector
        """This method does not typically support optional arguments"""
        space = space or sTransform
        return Vector(super(TransformationMatrix, self).translation(space))

    def setTranslation(self, trans, space=None):
        if isinstance(trans, Plug):
            trans = trans.as_vector()

        if isinstance(trans, (tuple, list)):
            trans = Vector(*trans)

        space = space or sTransform
        return super(TransformationMatrix, self).setTranslation(trans, space)

    def scaleBy(self, space=None):
        """This method does not typically support optional arguments"""
        space = space or sTransform
        return Vector(super(TransformationMatrix, self).scale(space))

    def setScale(self, seq, space=None):
        """This method does not typically support optional arguments"""
        if isinstance(seq, Plug):
            seq = seq.as_vector()

        if isinstance(seq, (tuple, list)):
            seq = Vector(*seq)

        space = space or sTransform
        return super(TransformationMatrix, self).setScale(seq, space)

    def rotation(self, asQuaternion=False):
        rotation = super(TransformationMatrix, self).rotation(asQuaternion)
        return Quaternion(rotation) if asQuaternion else Euler(rotation)

    def setRotation(self, rot):
        """Interpret three values as an euler rotation"""
        if isinstance(rot, Plug):
            rot = rot.as_vector()

        if isinstance(rot, (tuple, list)):
            try:
                rot = Vector(rot)
            except ValueError:
                traceback.print_exc()
                raise ValueError(
                    "I tried automatically converting your "
                    "tuple to a Vector, but couldn't.."
                )

        if isinstance(rot, Vector):
            rot = EulerRotation(rot)

        return super(TransformationMatrix, self).setRotation(rot)

    def asMatrix(self):  # type: () -> MatrixType
        return MatrixType(super(TransformationMatrix, self).asMatrix())

    def asMatrixInverse(self):  # type: () -> MatrixType
        return MatrixType(super(TransformationMatrix, self).asMatrixInverse())

    if ENABLE_PEP8:
        x_axis = xAxis
        y_axis = yAxis
        z_axis = zAxis
        translate_by = translateBy
        rotate_by = rotateBy
        set_translation = setTranslation
        set_rotation = setRotation
        set_scale = setScale
        as_matrix = asMatrix
        as_matrix_inverse = asMatrixInverse


class MatrixType(om.MMatrix):
    def __str__(self):
        fmt = (
            "%.2f %.2f %.2f %.2f\n"
            "%.2f %.2f %.2f %.2f\n"
            "%.2f %.2f %.2f %.2f\n"
            "%.2f %.2f %.2f %.2f"
        )

        return fmt % (
            self(0, 0), self(0, 1), self(0, 2), self(0, 3),
            self(1, 0), self(1, 1), self(1, 2), self(1, 3),
            self(2, 0), self(2, 1), self(2, 2), self(2, 3),
            self(3, 0), self(3, 1), self(3, 2), self(3, 3),
        )

    def __repr__(self):
        value = "\n".join("  " + line for line in str(self).split("\n"))
        return "%s.Matrix4(\n%s\n)" % (__name__, value)

    def __call__(self, *item):
        """Native API 2.0 MMatrix does not support indexing

        API 1.0 however *does*, except only for elements
        and not rows. Screw both of those, indexing isn't hard.

        Arguments:
            item (int, tuple): 1 integer for row, 2 for element

        Identity/default matrix:
            [[1.0, 0.0, 0.0, 0.0]]
            [[0.0, 1.0, 0.0, 0.0]]
            [[0.0, 0.0, 1.0, 0.0]]
            [[0.0, 0.0, 0.0, 1.0]]

        Example:
            >>> m = MatrixType()
            >>> m(0, 0)
            1.0
            >>> m(0, 1)
            0.0
            >>> m(1, 1)
            1.0
            >>> m(2, 1)
            0.0
            >>> m(3, 3)
            1.0
            >>>
            >>> m(0)
            (1.0, 0.0, 0.0, 0.0)

        """

        if len(item) == 1:
            return self.row(*item)

        elif len(item) == 2:
            return self.element(*item)

        else:
            raise ValueError(
                "Must provide either 1 or 2 coordinates, "
                "for row and element respectively"
            )

    def __mul__(self, other):
        return type(self)(super(MatrixType, self).__mul__(other))

    def __div__(self, other):
        return type(self)(super(MatrixType, self).__div__(other))

    def inverse(self):
        return type(self)(super(MatrixType, self).inverse())

    def row(self, index):
        values = tuple(self)
        return (
            values[index * 4 + 0],
            values[index * 4 + 1],
            values[index * 4 + 2],
            values[index * 4 + 3]
        )

    def element(self, row, col):
        values = tuple(self)
        return values[row * 4 + col % 4]


# Alias
Transformation = TransformationMatrix
Tm = TransformationMatrix
Mat = MatrixType
Mat4 = MatrixType
Matrix4 = MatrixType


class Vector(om.MVector):
    """Maya's MVector

    Example:
        >>> vec = Vector(1, 0, 0)
        >>> vec * Vector(0, 1, 0)  # Dot product
        0.0
        >>> vec ^ Vector(0, 1, 0)  # Cross product
        maya.api.OpenMaya.MVector(0, 0, 1)

    """

    def __add__(self, value):
        if isinstance(value, (int, float)):
            return type(self)(
                self.x + value,
                self.y + value,
                self.z + value,
            )

        return Vector(super(Vector, self).__add__(value))

    def __iadd__(self, value):
        if isinstance(value, (int, float)):
            return type(self)(
                self.x + value,
                self.y + value,
                self.z + value,
            )

        return Vector(super(Vector, self).__iadd__(value))

    def dot(self, value):
        return Vector(super(Vector, self).__mul__(value))

    def cross(self, value):
        return Vector(super(Vector, self).__xor__(value))

    def isEquivalent(self, other, tolerance=om.MVector.kTolerance):
        return super(Vector, self).isEquivalent(other, tolerance)

    if ENABLE_PEP8:
        is_equivalent = isEquivalent


# Alias, it can't take anything other than values
# and yet it isn't explicit in its name.
Vector3 = Vector


def multiply_vectors(vec1, vec2):
    """Piecewise multiplication of two vectors"""

    return Vector(
        vec1[0] * vec2[0],
        vec1[1] * vec2[1],
        vec1[2] * vec2[2]
    )


def divide_vectors(vec1, vec2):
    """Piecewise division of two vectors"""

    return Vector(
        vec1[0] / vec2[0],
        vec1[1] / vec2[1],
        vec1[2] / vec2[2]
    )


class Point(om.MPoint):
    """Maya's MPoint"""


class Color(om.MColor):
    """Maya's MColor"""


class BoundingBox(om.MBoundingBox):
    """Maya's MBoundingBox"""

    def volume(self):
        return self.width * self.height * self.depth


class Quaternion(om.MQuaternion):
    """Maya's MQuaternion

    Example:
        >>> q = Quaternion(0, 0, 0, 1)
        >>> v = Vector(1, 2, 3)
        >>> isinstance(q * v, Vector)
        True

    """

    def __mul__(self, other):
        if isinstance(other, (tuple, list)):
            other = Vector(*other)

        if isinstance(other, om.MVector):
            return Vector(other.rotateBy(self))

        else:
            return Quaternion(super(Quaternion, self).__mul__(other))

    def lengthSquared(self):
        return (
            self.x * self.x +
            self.y * self.y +
            self.z * self.z +
            self.w * self.w
        )

    def length(self):
        return math.sqrt(self.lengthSquared())

    def isNormalised(self, tol=0.0001):
        return abs(self.length() - 1.0) < tol

    def asEulerRotation(self):
        return Euler(super(Quaternion, self).asEulerRotation())

    def inverse(self):
        return Quaternion(super(Quaternion, self).inverse())

    def asMatrix(self):
        return Matrix4(super(Quaternion, self).asMatrix())

    if ENABLE_PEP8:
        as_matrix = asMatrix
        is_normalised = isNormalised
        length_squared = lengthSquared
        as_euler_rotation = asEulerRotation
        as_euler = asEulerRotation


# Alias
Quat = Quaternion


def twistSwingToQuaternion(ts):
    """Convert twist/swing1/swing2 rotation in a Vector into a quaternion

    Arguments:
        ts (Vector): Twist, swing1 and swing2

    """

    t = tan(ts.x * 0.25)
    s1 = tan(ts.y * 0.25)
    s2 = tan(ts.z * 0.25)

    b = 2.0 / (1.0 + s1 * s1 + s2 * s2)
    c = 2.0 / (1.0 + t * t)

    quat = Quaternion()
    quat.w = (b - 1.0) * (c - 1.0)
    quat.x = -t * (b - 1.0) * c
    quat.y = -b * (c * t * s1 + (c - 1.0) * s2)
    quat.z = -b * (c * t * s2 - (c - 1.0) * s1)

    assert quat.isNormalised()
    return quat


class EulerRotation(om.MEulerRotation):
    def asQuaternion(self):
        return Quaternion(super(EulerRotation, self).asQuaternion())

    def asMatrix(self):
        return Matrix4(super(EulerRotation, self).asMatrix())

    def isEquivalent(self, other, tolerance=om.MEulerRotation.kTolerance):
        return super(EulerRotation, self).isEquivalent(other, tolerance)

    if ENABLE_PEP8:
        is_equivalent = isEquivalent

    strToOrder = {
        'xyz': kXYZ,
        'xzy': kXZY,
        'yxz': kYXZ,
        'yzx': kYZX,
        'zxy': kZXY,
        'zyx': kZYX
    }

    orderToStr = {
        kXYZ: 'xyz',
        kXZY: 'xzy',
        kYXZ: 'yxz',
        kYZX: 'yzx',
        kZXY: 'zxy',
        kZYX: 'zyx'
    }

    enumToOrder = [
        kXYZ,
        kXZY,
        kYXZ,
        kYZX,
        kZXY,
        kZYX
    ]

    if ENABLE_PEP8:
        as_quaternion = asQuaternion
        as_matrix = asMatrix


# Alias
Euler = EulerRotation


def NurbsCurveData(points, degree=1, form=om1.MFnNurbsCurve.kOpen):
    """Tuple of points to MObject suitable for nurbsCurve-typed data

    Arguments:
        points (tuple): (x, y, z) tuples per point
        degree (int, optional): Defaults to 1 for linear
        form (int, optional): Defaults to MFnNurbsCurve.kOpen,
            also available kClosed

    Example:
        Create a new nurbs curve like this.

        >>> data = NurbsCurveData(
        ...     points=(
        ...         (0, 0, 0),
        ...         (0, 1, 0),
        ...         (0, 2, 0),
        ...     ))
        ...
        >>> parent = createNode("transform")
        >>> shape = createNode("nurbsCurve", parent=parent)
        >>> shape["cached"] = data

    """

    degree = min(3, max(1, degree))

    cvs = om1.MPointArray()
    curveFn = om1.MFnNurbsCurve()
    data = om1.MFnNurbsCurveData()
    mobj = data.create()

    for point in points:
        cvs.append(om1.MPoint(*point))

    curveFn.createWithEditPoints(cvs,
                                 degree,
                                 form,
                                 False,
                                 False,
                                 True,
                                 mobj)

    return mobj


class CachedPlug(Plug):
    """Returned in place of an actual plug"""

    def __init__(self, value):
        self._value = value

    def read(self):
        return self._value


def _plug_to_default(mplug):
    """Find default value from mplug, regardless of attribute type"""

    if mplug.isArray:
        raise TypeError("Array plugs are unsupported")

    if mplug.isCompound:
        raise TypeError("Compound plugs are unsupported")

    attr = mplug.attribute()
    type = attr.apiType()

    if type == om.MFn.kTypedAttribute:
        return om.MFnTypedAttribute(attr).default

    elif type in (om.MFn.kDoubleLinearAttribute,
                  om.MFn.kFloatLinearAttribute,
                  om.MFn.kDoubleAngleAttribute,
                  om.MFn.kFloatAngleAttribute):
        return om.MFnUnitAttribute(attr).default

    elif type == om.MFn.kNumericAttribute:
        return om.MFnNumericAttribute(attr).default

    elif type == om.MFn.kEnumAttribute:
        return om.MFnEnumAttribute(attr).default

    else:
        raise TypeError("Attribute type '%s' unsupported" % type)


def _plug_to_python(plug, unit=None, context=None):
    """Convert native `plug` to Python type

    Arguments:
        plug (om.MPlug): Native Maya plug
        unit (int, optional): Return value in this unit, e.g. Meters
        context (om.MDGContext, optional): Return value in this context

    Examples:
        >>> from maya import cmds
        >>> cmds.currentTime(1)
        1.0
        >>> time = encode("time1")
        >>> TimeUiUnit()  # 24 fps
        6
        >>> "%.3f" % time["outTime"]  # Seconds
        '0.042'
        >>> "%.1f" % time["outTime", TimeUiUnit()]
        '1.0'

    """

    assert isinstance(plug, om.MPlug), "'%r' was not an MPlug" % plug
    assert not plug.isNull, "'%s' was null" % plug

    kwargs = dict()

    if context is not None:
        kwargs["context"] = context

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
                om.MFnMatrixData(plug.asMObject(**kwargs)).matrix()
            )

        elif innerType == om.MFnData.kString:
            return plug.asString(**kwargs)

        elif innerType == om.MFnData.kNurbsCurve:
            return om.MFnNurbsCurveData(plug.asMObject(**kwargs))

        elif innerType == om.MFnData.kComponentList:
            return None

        elif innerType == om.MFnData.kInvalid:
            # E.g. time1.timewarpIn_Hidden
            # Unsure of why some attributes are invalid
            return None

        else:
            log.debug("Unsupported kTypedAttribute: %s" % innerType)
            return None

    elif type == om.MFn.kMatrixAttribute:
        return tuple(om.MFnMatrixData(plug.asMObject(**kwargs)).matrix())

    elif type == om.MFnData.kDoubleArray:
        raise TypeError("%s: kDoubleArray is not supported" % plug)

    elif type in (om.MFn.kDoubleLinearAttribute,
                  om.MFn.kFloatLinearAttribute):

        if unit is None:
            return plug.asMDistance(**kwargs).asUnits(Centimeters)
        elif unit == Millimeters:
            return plug.asMDistance(**kwargs).asMillimeters()
        elif unit == Centimeters:
            return plug.asMDistance(**kwargs).asCentimeters()
        elif unit == Meters:
            return plug.asMDistance(**kwargs).asMeters()
        elif unit == Kilometers:
            return plug.asMDistance(**kwargs).asKilometers()
        elif unit == Inches:
            return plug.asMDistance(**kwargs).asInches()
        elif unit == Feet:
            return plug.asMDistance(**kwargs).asFeet()
        elif unit == Miles:
            return plug.asMDistance(**kwargs).asMiles()
        elif unit == Yards:
            return plug.asMDistance(**kwargs).asYards()
        else:
            raise TypeError("Unsupported unit '%d'" % unit)

    elif type in (om.MFn.kDoubleAngleAttribute,
                  om.MFn.kFloatAngleAttribute):
        if unit is None:
            return plug.asMAngle(**kwargs).asUnits(Radians)
        elif unit == Degrees:
            return plug.asMAngle(**kwargs).asDegrees()
        elif unit == Radians:
            return plug.asMAngle(**kwargs).asRadians()
        elif unit == AngularSeconds:
            return plug.asMAngle(**kwargs).asAngSeconds()
        elif unit == AngularMinutes:
            return plug.asMAngle(**kwargs).asAngMinutes()
        else:
            raise TypeError("Unsupported unit '%d'" % unit)

    # Number
    elif type == om.MFn.kNumericAttribute:
        innerType = om.MFnNumericAttribute(attr).numericType()

        if innerType == om.MFnNumericData.kBoolean:
            return plug.asBool(**kwargs)

        elif innerType in (om.MFnNumericData.kShort,
                           om.MFnNumericData.kInt,
                           om.MFnNumericData.kLong,
                           om.MFnNumericData.kByte):
            return plug.asInt(**kwargs)

        elif innerType in (om.MFnNumericData.kFloat,
                           om.MFnNumericData.kDouble,
                           om.MFnNumericData.kAddr):
            return plug.asDouble(**kwargs)

        else:
            raise TypeError("Unsupported numeric type: %s"
                            % innerType)

    # Enum
    elif type == om.MFn.kEnumAttribute:
        return plug.asShort(**kwargs)

    elif type == om.MFn.kMessageAttribute:
        # In order to comply with `if plug:`
        return True

    elif type == om.MFn.kTimeAttribute:
        # MTime.value returns in UI units, which is inconsistent
        # with e.g. angular and linear attributes, which both return
        # UI-independent units.
        return plug.asMTime(**kwargs).asUnits(unit or Seconds)

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
        if plug.type() == "kMatrixAttribute":
            assert len(value) == 16, "Value didn't appear to be a valid matrix"
            return _python_to_plug(Matrix4(value), plug)

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

    elif isinstance(value, om1.MObject):
        node = _encode1(plug._node.path())
        shapeFn = om1.MFnDagNode(node)
        plug = shapeFn.findPlug(plug.name())
        plug.setMObject(value)

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

    elif isinstance(value, om.MQuaternion):
        _python_to_plug(value.asEulerRotation(), plug)

    elif isinstance(value, om.MVector):
        for index, value in enumerate(value):
            _python_to_plug(value, plug[index])

    elif isinstance(value, om.MColor):
        _python_to_plug(value[0], plug[0])
        _python_to_plug(value[1], plug[1])
        _python_to_plug(value[2], plug[2])

    elif isinstance(value, om.MPoint):
        for index, value in enumerate(value):
            _python_to_plug(value, plug[index])

    elif isinstance(value, om.MMatrix):
        matrixData = om.MFnMatrixData()
        matobj = matrixData.create(value)
        plug._mplug.setMObject(matobj)

    elif plug._mplug.isCompound:
        count = plug._mplug.numChildren()
        return _python_to_plug([value] * count, plug)

    # Native Python types

    elif isinstance(value, string_types):
        plug._mplug.setString(value)

    elif isinstance(value, int):
        plug._mplug.setInt(value)

    elif isinstance(value, float):
        plug._mplug.setDouble(value)

    elif isinstance(value, bool):
        plug._mplug.setBool(value)

    else:
        raise TypeError("Unsupported Python type '%s'" % value.__class__)


def _find_curve_type(plug):
    """Find which type of curve to associate with a given `plug`

    For example, translate channels have a linear curve type,
    whereas rotate channels have an angular one.

    """

    attr = plug._mplug.attribute()
    type = attr.apiType()

    if type in (om.MFn.kDoubleLinearAttribute,
                om.MFn.kFloatLinearAttribute):
        return "animCurveTL"

    elif type in (om.MFn.kDoubleAngleAttribute,
                  om.MFn.kFloatAngleAttribute):
        return "animCurveTA"

    elif type == om.MFn.kNumericAttribute:
        innerType = om.MFnNumericAttribute(attr).numericType()

        if innerType == om.MFnNumericData.kBoolean:
            return "animCurveTU"

        elif innerType in (om.MFnNumericData.kShort,
                           om.MFnNumericData.kInt,
                           om.MFnNumericData.kLong,
                           om.MFnNumericData.kByte,
                           om.MFnNumericData.kFloat,
                           om.MFnNumericData.kDouble,
                           om.MFnNumericData.kAddr):
            return "animCurveTL"

    elif type == om.MFn.kTimeAttribute:
        return "animCurveTT"

    # Unitless, could be anything
    return "animCurveTU"


def _python_to_mod(value, plug, mod):
    """Convert `value` into a suitable equivalent for om.MDGModifier

    Arguments:
        value (object): Value of any type to write into modifier
        plug (Plug): Plug within which to write value
        mod (om.MDGModifier): Modifier to use for writing it

    Example:
        >>> mod = DagModifier()
        >>> node = mod.createNode("transform")
        >>> mod.set_attr(node["tx"], 5.0)
        >>> mod.doIt()
        >>> int(node["tx"].read())
        5

        # Support for applying a single value across compound children
        >>> mod.set_attr(node["translate"], 10)
        >>> mod.doIt()
        >>> int(node["ty"].read())
        10

    """

    if isinstance(value, dict) and __maya_version__ > 2015:
        times, values = map(UiUnit(), value.keys()), value.values()
        curve_typ = _find_curve_type(plug)
        curve = plug.input(type=curve_typ)

        if not curve:
            if isinstance(mod, DGModifier):
                curve = mod.createNode(curve_typ)
            else:
                # The DagModifier can't create DG nodes
                with DGModifier() as dgmod:
                    curve = dgmod.createNode(curve_typ)

            mod.connect(curve["output"]._mplug, plug._mplug)

        change = oma.MAnimCurveChange()
        curve.keys(times, values, change=change)

        return change

    mplug = plug._mplug

    if plug.isCompound and isinstance(value, (int, float)):
        value = [value] * mplug.numChildren()

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

            _python_to_mod(value, plug[index], mod)

    elif isinstance(value, om.MVector):
        for index, value in enumerate(value):
            _python_to_mod(value, plug[index], mod)

    elif isinstance(value, om.MColor):
        _python_to_mod(value[0], plug[0], mod)
        _python_to_mod(value[1], plug[1], mod)
        _python_to_mod(value[2], plug[2], mod)

    elif isinstance(value, string_types):
        mod.newPlugValueString(mplug, value)

    elif isinstance(value, int):
        mod.newPlugValueInt(mplug, value)

    elif isinstance(value, float):
        mod.newPlugValueFloat(mplug, value)

    elif isinstance(value, bool):
        mod.newPlugValueBool(mplug, value)

    elif isinstance(value, om.MAngle):
        mod.newPlugValueMAngle(mplug, value)

    elif isinstance(value, om.MDistance):
        mod.newPlugValueMDistance(mplug, value)

    elif isinstance(value, om.MTime):
        mod.newPlugValueMTime(mplug, value)

    elif isinstance(value, om.MMatrix):
        obj = om.MFnMatrixData().create(value)
        mod.newPlugValue(mplug, obj)

    elif isinstance(value, om.MEulerRotation):
        for index, value in enumerate(value):
            value = om.MAngle(value, om.MAngle.kRadians)
            _python_to_mod(value, plug[index], mod)

    elif isinstance(value, om.MQuaternion):
        _python_to_mod(value.asEulerRotation(), plug, mod)

    else:
        raise TypeError(
            "Unsupported plug type for modifier: %s" % type(value)
        )
        return False
    return True


def exists(path, strict=True):
    """Return whether any node at `path` exists

    This will return True for nodes that are *about to* be
    created via a DG or Dag modifier.

    Arguments:
        path (str): Full or partial path to node
        strict (bool, optional): Error if the path isn't a full match,
            including namespace.

    Examples:
        >>> _new()
        >>> exists("uniqueName", strict=False)
        False
        >>> _ = createNode("transform", name="uniqueName")
        >>> exists("uniqueName", strict=False)
        True

        # Note that even to-be-created nodes also register as existing
        >>> exists("uniqueName2", strict=False)
        False
        >>> with DagModifier() as mod:
        ...    _ = mod.createNode("transform", name="uniqueName2")
        ...    assert exists("uniqueName2", strict=False)
        ...
        >>> exists("uniqueName2", strict=False)
        True

    """

    try:
        node = encode(path)
    except RuntimeError:
        return False

    if strict:
        return node.path() == path

    return True


def encode(path):  # type: (str) -> Node
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
        raise ExistError("'%s' does not exist" % path)

    mobj = selectionList.getDependNode(0)

    # Deleted nodes can still get picked up, unless
    # they are also destroyed. But we don't care for
    # removed-but-not-destroyed nodes
    return Node(mobj)


def find(path, default=None):
    """Find node at `path` or return `default`"""
    try:
        return encode(path)
    except ExistError:
        return default


def fromHash(code, default=None):
    """Get existing node from MObjectHandle.hashCode()"""
    try:
        return Singleton._instances["%x" % code]
    except KeyError:
        return default


def fromHex(hex, default=None, safe=True):
    """Get existing node from Node.hex"""
    node = Singleton._instances.get(hex, default)
    if safe and node and node.exists:
        return node
    else:
        return node


def toHash(mobj):
    """Cache the given `mobj` and return its hashCode

    This enables pre-caching of one or more nodes in situations where
    intend to access it later, at a more performance-critical moment.

    Ignores nodes that have already been cached.

    """

    node = Node(mobj)
    return node.hashCode


def toHex(mobj):
    """Cache the given `mobj` and return its hex value

    See :func:`toHash` for docstring.

    """

    node = Node(mobj)
    return node.hex


def asHash(mobj):
    """Return a given hashCode for `mobj`, without caching it

    This can be helpful in case you wish to synchronise `cmdx`
    with a third-party library or tool and wish to guarantee
    that an identical algorithm is used.

    """

    handle = om.MObjectHandle(mobj)
    return handle.hashCode()


def asHex(mobj):
    """Return a given hex string for `mobj`, without caching it

    See docstring for :func:`asHash` for details

    """

    return "%x" % asHash(mobj)


if ENABLE_PEP8:
    from_hash = fromHash
    from_hex = fromHex
    to_hash = toHash
    to_hex = toHex
    as_hash = asHash
    as_hex = asHex


# Helpful for euler rotations
degrees = math.degrees
radians = math.radians
sin = math.sin
cos = math.cos
tan = math.tan
pi = math.pi


def meters(cm):
    """Centimeters (Maya's default unit) to Meters

    Example:
        >>> meters(100)
        1.0

    """

    return cm * 0.01


def clear():
    """Clear all memory used by cmdx, including undo"""

    Singleton._instances.clear()

    if ENABLE_UNDO:

        # Traces left in here can trick Maya into thinking
        # nodes still exists that cannot be unloaded.
        self.shared.undoId = None
        self.shared.redoId = None
        self.shared.undos = {}
        self.shared.redos = {}

        cmds.flushUndo()

    # Also ensure Python does its job
    import gc
    gc.collect()


def _encode1(path):
    """Convert `path` to Maya API 1.0 MObject

    Arguments:
        path (str): Absolute or relative path to DAG or DG node

    Raises:
        ExistError on `path` not existing

    """

    selectionList = om1.MSelectionList()

    try:
        selectionList.add(path)
    except RuntimeError:
        raise ExistError("'%s' does not exist" % path)

    mobject = om1.MObject()
    selectionList.getDependNode(0, mobject)
    return mobject


def _encodedagpath1(path):
    """Convert `path` to Maya API 1.0 MObject

    Arguments:
        path (str): Absolute or relative path to DAG or DG node

    Raises:
        ExistError on `path` not existing

    """

    selectionList = om1.MSelectionList()

    try:
        selectionList.add(path)
    except RuntimeError:
        raise ExistError("'%s' does not exist" % path)

    dagpath = om1.MDagPath()
    selectionList.getDagPath(0, dagpath)
    return dagpath


def decode(node):
    """Convert cmdx Node to shortest unique path

    This is the same as `node.shortestPath()`
    To get an absolute path, use `node.path()`

    """

    try:
        return node.shortestPath()
    except AttributeError:
        return node.name(namespace=True)


def record_history(func):
    if SAFE_MODE:
        # Getting of `node.path()` involves use of a function
        # set. But if an MObject is no valid, we'd better not
        # try and query it.
        return func

    @wraps(func)
    def decorator(self, *args, **kwargs):
        _kwargs = kwargs.copy()
        _args = list(args)

        # Don't store actual objects,
        # to facilitate garbage collection.
        for index, arg in enumerate(args):
            if isinstance(arg, (Node, Plug)):
                _args[index] = arg.path()
            else:
                _args[index] = repr(arg)

        for key, value in kwargs.items():
            if isinstance(value, (Node, Plug)):
                _kwargs[key] = value.path()
            else:
                _kwargs[key] = repr(value)

        self._history.append((func.__name__, _args, _kwargs))

        return func(self, *args, **kwargs)

    return decorator


class _BaseModifier(object):
    """Interactively edit an existing scenegraph with support for undo/redo

    Arguments:
        undoable (bool, optional): For contexts, put undoIt on the undo queue
        interesting (bool, optional): New nodes should appear
            in the channelbox
        debug (bool, optional): Include additional debug data,
            at the expense of performance
        atomic (bool, optional): Automatically rollback changes on failure
        template (str, optional): Automatically name new nodes using
            this template

    """

    Type = om.MDGModifier

    def __enter__(self):
        """Support use as a context manager

        Examples:
            >>> with DagModifier() as mod:
            ...    node = mod.createNode("transform")
            ...    mod.set_attr(node["translateX"], 5.0)
            ...
            >>>

        """

        if self._opts["undoable"]:
            # Given that we perform lots of operations in a single context,
            # let's establish our own chunk for it. We'll use the unique
            # memory address of this particular instance as a name,
            # such that we can identify it amongst the possible-nested
            # modifiers once it exits.
            cmds.undoInfo(chunkName="%x" % id(self), openChunk=True)

        self.isContext = True

        return self

    def __exit__(self, exc_type, exc_value, tb):
        if exc_type:
            # Let our internal calls to `assert` prevent the
            # modifier from proceeding, given it's half-baked
            return

        try:
            self.redoIt()

            if self._opts["undoable"]:
                # Make our commit within the current undo chunk,
                # but *before* we call any maya.cmds as it may
                # otherwise confuse the chunk
                def undoit():
                    for change in self._animChanges:
                        change.undoIt()

                    self._modifier.undoIt()

                def redoit():
                    self._modifier.doIt()

                    for change in self._animChanges:
                        change.redoIt()

                commit(undoit, redoit)

            # These all involve calling on cmds,
            # which manages undo on its own.
            self._doKeyableAttrs()
            self._doNiceNames()
            self._doLockAttrs()

        finally:

            # Ensure we close the undo chunk no matter what
            if self._opts["undoable"]:
                cmds.undoInfo(chunkName="%x" % id(self), closeChunk=True)

    def __init__(self,
                 undoable=True,
                 interesting=True,
                 debug=True,
                 atomic=False,
                 template=None):
        super(_BaseModifier, self).__init__()
        self.isContext = False

        self._modifier = self.Type()
        self._history = list()
        self._index = 1
        self._opts = {
            "undoable": undoable,
            "interesting": interesting,
            "debug": debug,
            "atomic": atomic,
            "template": template,
        }

        self._attributesBeingAdded = []

        # Extras
        self._lockAttrs = []
        self._keyableAttrs = []
        self._niceNames = []
        self._animChanges = []

        # Undo
        self._doneLockAttrs = []
        self._doneKeyableAttrs = []
        self._doneNiceNames = []

        self._attributesBeingAdded = []

    @record_history
    def setNiceName(self, plug, value=True):
        """Set a new nice name for a plug

        The modifier doesn't natively support this, so we
        stow away the request and call it at the tail end
        of call to `doIt`.

        Examples:
            # Only works with dynamic attributes
            >>> with DagModifier() as mod:
            ...    node = mod.createNode("transform")
            ...    _ = mod.addAttr(node, Double("myDynamic"))
            ...
            >>> assert node["myDynamic"].niceName == "My Dynamic"

            >>> with DagModifier() as mod:
            ...    mod.setNiceName(node["myDynamic"], "Your Dynamic")
            ...
            >>> assert node["myDynamic"].niceName == "Your Dynamic"

        """

        if isinstance(plug, om.MPlug):
            plug = Plug(Node(plug.node()), plug)

        assert isinstance(plug, Plug), "%s was not a plug" % plug
        self._niceNames.append((plug, value))

    @record_history
    def setLocked(self, plug, value=True):
        """Lock a plug

        The modifier doesn't natively support this, so we
        stow away the request and call it at the tail end
        of call to `doIt`.

        Examples:
            >>> node = createNode("transform")
            >>> with DagModifier() as mod:
            ...    mod.setLocked(node["translateX"])
            ...    mod.setLocked(node["rotateY"])
            ...
            >>> assert node["translateX"].locked
            >>> assert node["rotateY"].locked

            # Must be undoable
            >>> from maya import cmds
            >>> cmds.undo()
            >>> assert not node["translateX"].locked
            >>> assert not node["rotateY"].locked

            # Also works with dynamic attributes
            >>> with DagModifier() as mod:
            ...    node = mod.createNode("transform")
            ...    _ = mod.addAttr(node, Double("myDynamic"))
            ...
            >>> assert not node["myDynamic"].locked

            >>> with DagModifier() as mod:
            ...    mod.setLocked(node["myDynamic"])
            ...
            >>> assert node["myDynamic"].locked
            >>> cmds.undo()
            >>> assert not node["myDynamic"].locked

        """

        if isinstance(plug, om.MPlug):
            plug = Plug(Node(plug.node()), plug)

        assert isinstance(plug, Plug), "%s was not a plug" % plug
        self._lockAttrs.append((plug, value))

    @record_history
    def setKeyable(self, plug, value=True):
        """Make a plug keyable

        The modifier doesn't natively support this, so we
        stow away the request and call it at the tail end
        of call to `doIt`.

        Examples:
            >>> with DagModifier() as mod:
            ...    node = mod.createNode("transform")
            ...    mod.setKeyable(node["rotatePivotX"])
            ...    mod.setKeyable(node["translateX"], False)
            ...
            >>> node["rotatePivotX"].keyable
            True
            >>> node["translateX"].keyable
            False

            # Also works with dynamic attributes
            >>> with DagModifier() as mod:
            ...    node = mod.createNode("transform")
            ...    _ = mod.addAttr(node, Double("myDynamic"))
            ...
            >>> node["myDynamic"].keyable
            False
            >>> with DagModifier() as mod:
            ...    mod.setKeyable(node["myDynamic"])
            ...
            >>> node["myDynamic"].keyable
            True

        """

        if isinstance(plug, om.MPlug):
            plug = Plug(Node(plug.node()), plug)

        assert isinstance(plug, Plug), "%s was not a plug" % plug
        self._keyableAttrs.append((plug, value))

    def _doLockAttrs(self):
        while self._lockAttrs:
            plug, value = self._lockAttrs.pop(0)
            elements = plug if plug.isArray or plug.isCompound else [plug]

            for el in elements:
                cmds.setAttr(el.path(), lock=value)

    def _doKeyableAttrs(self):
        while self._keyableAttrs:
            plug, value = self._keyableAttrs.pop(0)
            elements = plug if plug.isArray or plug.isCompound else [plug]

            for el in elements:
                cmds.setAttr(el.path(), keyable=value)

    def _doNiceNames(self):
        while self._niceNames:
            plug, value = self._niceNames.pop(0)
            elements = plug if plug.isArray or plug.isCompound else [plug]

            for el in elements:
                if el._mplug.isDynamic:
                    # Use setAttr as isKeyable doesn't
                    # persist on scene save for dynamic attributes.
                    cmds.addAttr(el.path(), edit=True, niceName=value)
                else:
                    fn = om.MFnAttribute(el._mplug.attribute())
                    fn.setNiceNameOverride(value)

    def doIt(self):
        try:
            self._modifier.doIt()

        except RuntimeError:

            # Rollback changes
            if self._opts["atomic"]:
                self._modifier.undoIt()

            traceback.print_exc()
            raise ModifierError(self._history)

        else:
            # Facilitate multiple calls to doIt, whereby only
            # the latest, actually-performed actions are reported
            self._history[:] = []

        self._attributesBeingAdded[:] = []

    def undoIt(self):
        self._modifier.undoIt()

    def redoIt(self):
        self.doIt()

    @record_history
    def createNode(self, type, name=None):
        try:
            mobj = self._modifier.createNode(type)
        except TypeError:
            raise TypeError("'%s' is not a valid node type" % type)

        template = self._opts["template"]
        if name or template:
            name = (template or "{name}").format(
                name=name or "",
                type=type,
                index=self._index,
            )
            self._modifier.renameNode(mobj, name)

        # Create every node immediately, to allow for
        # calls to MObjectHandle.isAlive()
        self._modifier.doIt()

        node = Node(mobj, exists=False)

        if not self._opts["interesting"]:
            plug = node["isHistoricallyInteresting"]
            _python_to_mod(False, plug, self._modifier)

        self._index += 1
        return node

    @record_history
    def deleteNode(self, node):
        """Delete a node

        Examples:
            >>> _new()
            >>> with DGModifier() as mod:
            ...   node = mod.createNode("multMatrix", name="specialName")
            ...
            >>> "specialName" in cmds.ls()
            True
            >>> with DGModifier() as mod:
            ...   mod.deleteNode(node)
            ...
            >>> "specialName" in cmds.ls()
            False

            # It does not automatically delete empty parent transforms
            >>> with DagModifier() as mod:
            ...   transform = mod.createNode("transform",
            ...                              name="specialTransform")
            ...   shape = mod.createNode("mesh",
            ...                          name="specialShape",
            ...                          parent=transform)
            ...
            >>> "specialTransform" in cmds.ls()
            True
            >>> "specialShape" in cmds.ls()
            True
            >>> with DGModifier() as mod:
            ...   mod.deleteNode(shape)
            ...
            >>> "specialTransform" in cmds.ls()
            True
            >>> "specialShape" in cmds.ls()
            False

        """

        # This is one picky s-o-b, let's not give it the
        # satisfaction of ever erroring out on us. Performance
        # is of less importance here, as deletion is not time-cricital
        mobj = node._mobject
        if not _isalive(mobj):
            raise ExistError

        self._modifier.deleteNode(mobj)

        # This appears to happen regardless of calling doIt yourself,
        # and the documentation recommends you do it always. Let's do it.
        self._modifier.doIt()

    @record_history
    def renameNode(self, node, name):
        if SAFE_MODE:
            assert _isalive(node._mobject)

        return self._modifier.renameNode(node._mobject, name)

    @record_history
    def addAttr(self, node, attr):
        """Add new `attr` to `node`

        Examples:
            >>> _new()
            >>> with DagModifier() as mod:
            ...   node = mod.createNode("transform", name="myNode")
            ...   attr = mod.addAttr(node, Double("newAttr", default=5.0))
            ...
            >>> node["newAttr"].read()
            5.0
            >>> cmds.undo()
            >>> node.hasAttr("newAttr")
            False

            # Protect against adding an attribute twice
            >>> try:
            ...   with DagModifier() as mod:
            ...     node = mod.createNode("transform")
            ...     attr1 = mod.addAttr(node, Boolean("sameAttr"))
            ...     attr2 = mod.addAttr(node, Double("sameAttr"))
            ... except Exception as e:
            ...   assert isinstance(e, ExistError)
            ... else:
            ...   assert False
            >>>

            # But allow the same attributes to be added to different nodes
            >>> with DagModifier() as mod:
            ...   node1 = mod.createNode("transform")
            ...   node2 = mod.createNode("transform")
            ...   attr1 = mod.addAttr(node1, Boolean("sameAttr"))
            ...   attr2 = mod.addAttr(node2, Double("sameAttr"))
            ...
            >>>

        """

        assert isinstance(node, Node), "%s was not a cmdx.Node"

        if SAFE_MODE:
            assert _isalive(node._mobject)

        mobj = attr

        if isinstance(attr, _AbstractAttribute):
            mobj = attr.create()

        this_name = om.MFnAttribute(mobj).name
        if node.hasAttr(this_name):
            raise ExistError(
                "Attribute already exists: %s" % node[this_name].path()
            )

        # Ensure it isn't in the process of being added
        for _node, _mattr in self._attributesBeingAdded:
            name_being_added = om.MFnAttribute(_mattr).name
            if node == _node and this_name == name_being_added:
                raise ExistError(
                    "Same attribute added twice: %s.%s" % (
                        node.path(), name_being_added)
                )

        status = self._modifier.addAttribute(node._mobject, mobj)

        if not status:
            raise ValueError(
                "Could not add the attribute: %s.%s" % (node, attr)
            )

        if isinstance(attr, String) and attr["default"]:
            log.warning("Strings don't support default values with modifier")

        # Protect against user error
        # This one is especially pesky; Maya will go ahead and create
        # the same attribute name multiple times, only to complain when
        # you try and undo. Bad, Maya, bad!
        self._attributesBeingAdded += [(node, mobj)]

        if SAFE_MODE:
            self._modifier.doIt()

        return mobj

    @record_history
    def deleteAttr(self, plug):
        assert isinstance(plug, Plug), "%s was not a cmdx.Plug" % plug
        assert not plug._mplug.isNull

        node = plug.node()

        if SAFE_MODE:
            assert _isalive(node._mobject)

        # Erase cached values, they're no longer valid
        node.clear()

        result = self._modifier.removeAttribute(
            node._mobject, plug._mplug.attribute()
        )

        if SAFE_MODE:
            self._modifier.doIt()

        return result

    @record_history
    def setAttr(self, plug, value):
        if isinstance(plug, om.MPlug):
            assert not plug.isNull
            plug = Plug(plug.node(), plug)

        assert not plug._mplug.isNull
        if not plug.editable:
            raise LockedError("%s was locked or connected" % plug.path())

        # Support passing a cmdx.Plug as value
        if isinstance(value, Plug):
            value = value.read()

        # Support passing an MPlug as value
        if isinstance(value, om.MPlug):
            value = Plug(value.node(), value).read()

        result = _python_to_mod(value, plug, self._modifier)

        if isinstance(result, oma.MAnimCurveChange):
            self._animChanges += [result]

        if SAFE_MODE:
            self._modifier.doIt()

    def smartSetAttr(self, plug, value):
        """Convenience method for setAttr

        If the plug being set is driven by another attribute,
        attempt to set *its* value instead.

        This is intended for semi-proxy attributes, which take
        the place of an attribute elsewhere. When actual proxy
        attributes are not possible (as they are garbage).

        """

        if plug.editable:
            # No smarts necessary
            return self.set_attr(plug, value)

        if plug.locked:
            # No amount of smarts is going to save us from this one
            raise LockedError("%s was locked" % plug.path())

        # Let's try and set the attribute on the connected plug instead
        connection = plug.connection(plug=True,
                                     source=True,
                                     destination=False)

        assert connection is not None, (
            "Attribute was not locked, but also not connected? "
            "Then what is it? This case isn't handled and is a bug."
        )

        return self.set_attr(connection, value)

    def trySetAttr(self, plug, value):
        try:
            self.setAttr(plug, value)
        except Exception:
            pass

    def forceSetAttr(self, plug, value):
        if plug._mplug.isLocked:
            raise LockedError("%s is locked and cannot be forced." % plug)

        if plug.connected:
            # Disconnect anything connecting to this plug
            self.disconnect(plug, destination=False)
            self.doIt()

        self.setAttr(plug, value)

    def resetAttr(self, plug):
        self.setAttr(plug, plug.default)

    @record_history
    def connect(self, src, dst, force=True):
        """Connect one attribute to another, with undo

        Examples:
            >>> _new()
            >>> tm = createNode("transform", name="myTransform")
            >>> with DagModifier() as mod:
            ...   mod.connect(tm["rx"], tm["ry"])
            ...
            >>> tx = createNode("animCurveTL", name="myAnimCurve")

            # Automatically disconnects any connected attribute
            >>> with DagModifier() as mod:
            ...     mod.connect(tm["sx"], tm["tx"])
            ...
            >>> tm["tx"].connection()
            |myTransform
            >>> cmds.undo()
            >>> tm["tx"].connection() is None
            True

            # Connect without undo
            >>> tm["tx"] << tx["output"]
            >>> tm["tx"].connection()
            myAnimCurve

            # Disconnect without undo
            >>> tm["tx"] // tx["output"]
            >>> tm["tx"].connection() is None
            True

        """

        if isinstance(src, Plug):
            src = src._mplug

        if isinstance(dst, Plug):
            dst = dst._mplug

        assert isinstance(src, om.MPlug), "%s must be of type MPlug" % src
        assert isinstance(dst, om.MPlug), "%s must be of type MPlug" % dst

        assert not src.isNull
        assert not dst.isNull

        if dst.isLocked:
            # Modifier can't perform this connect, but wouldn't
            # tell you about it until you `doIt()`. Bad.
            path = dst.partialName(
                includeNodeName=False,
                useLongNames=True,
                useFullAttributePath=False
            )

            raise LockedError("Channel locked, cannot connect '%s'" % path)

        if force:
            # Disconnect any plug connected to `other`
            disconnected = False

            # Ensure we only disconnect incoming attributes,
            # we don't care about whether this attribute connects
            # to something else.
            for plug in dst.connectedTo(True, False):
                self.disconnect(plug, dst)
                disconnected = True

            if disconnected:
                # Connecting after disconnecting breaks undo,
                # unless we do it first.
                #
                # NOTE: This is bad, the user should be in control of when
                # the modifier is actually being called. Especially if we
                # want to avoid calling it altogether in case of an exception
                self._modifier.doIt()

        self._modifier.connect(src, dst)

    def connectAttr(self, srcPlug, dstNode, dstAttr):
        """Connect a plug to an attribute

        This method enables connecting to attributes that hasn't
        yet been created.

        Examples:
            >>> _new()

            # Connect to newly created attributes
            >>> with DagModifier() as mod:
            ...     newNode = mod.createNode("transform", name="newNode")
            ...     newAttr = mod.addAttr(newNode, Double("newAttr"))
            ...     mod.connectAttr(newNode["visibility"], newNode, newAttr)
            ...
            >>> newNode["newAttr"].read()
            1.0

            # Also works with undo
            >>> cmds.undo()
            >>> newNode.hasAttr("newAttr")
            False
            >>> cmds.redo()
            >>> newNode.hasAttr("newAttr")
            True

            >>> with DagModifier() as mod:
            ...     otherNode = mod.createNode("transform", name="otherNode")
            ...     otherAttr = mod.addAttr(otherNode, Message("otherAttr"))
            ...     mod.connectAttr(newNode["newAttr"], otherNode, otherAttr)
            ...
            >>> newNode["newAttr"].connection()
            |otherNode

            >>> cmds.undo()
            >>> newNode["newAttr"].connection()
            |newNode

        """

        assert isinstance(srcPlug, (Plug, om.MPlug)), "%s not a plug" % srcPlug
        assert isinstance(dstNode, (Node, om.MObject)), "%s not node" % dstNode
        assert (
            isinstance(dstAttr, om.MObject) or
            isinstance(dstAttr, string_types)
        ), "%s not an MObject" % dstAttr

        if isinstance(srcPlug, Plug):
            srcPlug = srcPlug._mplug

        assert not srcPlug.isNull
        srcNode = srcPlug.node()
        srcAttr = srcPlug.attribute()

        if isinstance(dstNode, Node):

            assert _isalive(dstNode._mobject)
            dstNode = dstNode.object()

        if SAFE_MODE:
            assert _isalive(srcNode)
            assert _isalive(dstNode)

        self.connectAttrs(srcNode, srcAttr, dstNode, dstAttr)

    def connectAttrs(self, srcNode, srcAttr, dstNode, dstAttr):
        """Connect a new attribute to another new attribute

        This method enables connecting to attributes, neither of
        which hasn't been created yet.

        Examples:
            # Connect to newly created attributes
            >>> with DagModifier() as mod:
            ...     newNode = mod.createNode("transform")
            ...     newAttr = mod.addAttr(newNode, Double("newAttr"))
            ...     mod.connectAttr(newNode["visibility"], newNode, newAttr)
            ...
            >>> newNode["newAttr"].read()
            1.0

            # Support for passing attribute by name
            >>> with DagModifier() as mod:
            ...     newNode = mod.createNode("transform")
            ...     _ = mod.addAttr(newNode, Double("newAttr"))
            ...     mod.doIt()
            ...     mod.connectAttr(newNode["visibility"], newNode, "newAttr")
            ...
            >>> newNode["newAttr"].read()
            1.0

            # Support for passing both attributes by name
            >>> with DagModifier() as mod:
            ...     newNode = mod.createNode("transform")
            ...     _ = mod.addAttr(newNode, Double("newAttr"))
            ...     mod.doIt()
            ...     mod.connectAttrs(newNode, "visibility", newNode, "newAttr")
            ...
            >>> newNode["newAttr"].read()
            1.0

        """

        if SAFE_MODE:
            # Ensure any node or attribute going into this method
            # has actually already been created.
            self._modifier.doIt()

        if isinstance(srcNode, Node):
            srcNode = srcNode.object()

        if isinstance(dstNode, Node):
            dstNode = dstNode.object()

        if isinstance(srcAttr, string_types):
            # Support passing of attributes as string
            name = srcAttr
            srcAttr = om.MFnDependencyNode(dstNode).attribute(name)

            if srcAttr.isNull():
                raise ExistError("Could not find %s.attribute %s" % name)

        if isinstance(dstAttr, string_types):
            name = dstAttr
            dstAttr = om.MFnDependencyNode(dstNode).attribute(name)

            if dstAttr.isNull():
                raise ExistError("Could not find %s.attribute %s" % name)

        if isinstance(srcAttr, Plug):
            # Support passing of attributes as cmdx.Plug
            assert not srcAttr._mplug.isNull
            srcAttr = srcAttr.attribute()

        if isinstance(dstAttr, Plug):
            assert not dstAttr._mplug.isNull
            dstAttr = dstAttr.attribute()

        assert isinstance(srcNode, om.MObject)
        assert isinstance(srcAttr, om.MObject)
        assert isinstance(dstNode, om.MObject)
        assert isinstance(dstAttr, om.MObject)

        assert not srcAttr.isNull()
        assert not dstAttr.isNull()

        if SAFE_MODE:
            assert _isalive(srcNode) and _isalive(dstNode)

        self._modifier.connect(srcNode, srcAttr,
                               dstNode, dstAttr)

        if SAFE_MODE:
            self._modifier.doIt()

    def tryConnect(self, src, dst):
        """Connect and ignore failure

        Convenience method to improve readability of your code.

        Returns:
            success (bool): Whether or not the connection succeeded

        Examples:
            >>> node = createNode("transform")
            >>> node["translateY"].lock()
            >>> mod = DGModifier()
            >>> try:
            ...    mod.connect(node["tx"], node["ty"])
            ... except Exception as e:
            ...    assert isinstance(e, LockedError)
            ... else:
            ...    assert False
            >>>

            # Now let's tryConnect
            >>> with DGModifier() as mod:
            ...    success = mod.tryConnect(node["tx"], node["ty"])
            ...
            >>> success
            False

        """

        try:
            self.connect(src, dst)

        except LockedError:
            return False

        except Exception:
            return False

        else:
            return True

    @record_history
    def disconnect(self, a, b=None, source=True, destination=True):
        """Disconnect `a` from `b`

        Normally, Maya only performs a disconnect if the
        connection is incoming.

        disconnect(A, B) => OK
         __________       _________
        |          |     |         |
        |  nodeA   o---->o  nodeB  |
        |__________|     |_________|

        disconnect(B, A) => NO
         __________       _________
        |          |     |         |
        |  nodeA   o---->o  nodeB  |
        |__________|     |_________|

        Examples:
            >>> tm1 = createNode("transform", name="tm1")
            >>> tm2 = createNode("transform", name="tm2")
            >>> tm3 = createNode("transform", name="tm3")

           # Disconnects of unconnected attributes are ignored
            >>> with DagModifier() as mod:
            ...    _ = mod.disconnect(tm1["rx"], tm1["ry"])
            ...    _ = mod.disconnect(tm1["rx"], tm1["rz"])
            ...    _ = mod.disconnect(tm1["rx"], tm1["sy"])
            ...    _ = mod.disconnect(tm1["rx"], tm1["ty"])
            ...

            # This doesn't throw an error
            >>> cmds.undo() if ENABLE_UNDO else DoNothing

            # Disconnect either source or destination, only
            >>> a, b = tm1["tx"], tm2["ty"]
            >>> a << b
            >>> a.connection() is tm2
            True

            # b is a source, not a destination, so this does nothing
            >>> a.disconnect(b, source=False, destination=True)
            >>> a.connection() is tm2
            True

            # This on the other hand..
            >>> a.disconnect(b, source=True, destination=False)
            >>> a.connection() is tm2
            False
            >>> a.connection() is None
            True

            # Default is to disconnect both
            >>> tm1["tx"] >> tm2["tx"]
            >>> tm2["tx"] >> tm3["tx"]
            >>> tm1["tx"].connection() is tm2
            True
            >>> tm3["tx"].connection() is tm2
            True
            >>> tm2["tx"].disconnect()
            >>> tm1["tx"].connection() is tm2
            False
            >>> tm3["tx"].connection() is tm2
            False

        Arguments:
            a (Plug): Starting point of a connection
            b (Plug, optional): End point of a connection, defaults to all
            source (bool, optional): Disconnect b, if it is a source
            destination (bool, optional): Disconnect b, if it
                is a destination

        Returns:
            count (int): Number of disconnected attributes

        """

        if isinstance(a, Plug):
            a = a._mplug

        if isinstance(b, Plug):
            b = b._mplug

        assert a and not a.isNull
        assert b is None or not b.isNull

        count = 0
        incoming = (True, False)
        outgoing = (False, True)

        if source:
            for other in a.connectedTo(*incoming):

                # Limit disconnects to the attribute provided
                if b is not None and other != b:
                    continue

                assert not other.isNull
                self._modifier.disconnect(other, a)
                count += 1

        if destination:
            for other in a.connectedTo(*outgoing):
                if b is not None and other != b:
                    continue

                assert not other.isNull
                self._modifier.disconnect(a, other)
                count += 1

        return count

    # Aliases
    delete = deleteNode
    rename = renameNode

    if ENABLE_PEP8:
        do_it = doIt
        undo_it = undoIt
        create_node = createNode
        delete_node = deleteNode
        rename_node = renameNode
        add_attr = addAttr
        set_attr = setAttr
        try_set_attr = trySetAttr
        force_set_attr = forceSetAttr
        smart_set_attr = smartSetAttr
        delete_attr = deleteAttr
        reset_attr = resetAttr
        try_connect = tryConnect
        connect_attr = connectAttr
        connect_attrs = connectAttrs
        set_keyable = setKeyable
        set_locked = setLocked
        set_nice_name = setNiceName


class DGModifier(_BaseModifier):
    """Modifier for DG nodes"""

    Type = om.MDGModifier


class DagModifier(_BaseModifier):
    """Modifier for DAG nodes

    Example:
        >>> with DagModifier() as mod:
        ...     node1 = mod.createNode("transform")
        ...     node2 = mod.createNode("transform", parent=node1)
        ...     mod.setAttr(node1["translate"], (1, 2, 3))
        ...     mod.connect(node1 + ".translate", node2 + ".translate")
        ...
        >>> getAttr(node1 + ".translateX")
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

    Example, without context manager:
        >>> mod = DagModifier()
        >>> parent = mod.createNode("transform")
        >>> shape = mod.createNode("transform", parent=parent)
        >>> mod.connect(parent["tz"], shape["tz"])
        >>> mod.setAttr(parent["sx"], 2.0)
        >>> parent["tx"] >> shape["ty"]
        >>> round(shape["ty"], 1)
        0.0
        >>> parent["tx"] = 5.1
        >>> round(shape["ty"], 1)  # Not yet created nor connected
        5.1
        >>> mod.doIt()
        >>> round(shape["ty"], 1)
        5.1
        >>> round(parent["sx"])
        2.0

    Duplicate names are resolved, even though nodes haven't yet been created:
        >>> _ = cmds.file(new=True, force=True)
        >>> with DagModifier() as mod:
        ...     node = mod.createNode("transform", name="NotUnique")
        ...     node1 = mod.createNode("transform", name="NotUnique")
        ...     node2 = mod.createNode("transform", name="NotUnique")
        ...
        >>> node.name() == "NotUnique"
        True
        >>> node1.name() == "NotUnique1"
        True
        >>> node2.name() == "NotUnique2"
        True

    Deletion works too
        >>> _ = cmds.file(new=True, force=True)
        >>> mod = DagModifier()
        >>> parent = mod.createNode("transform", name="myParent")
        >>> child = mod.createNode("transform", name="myChild", parent=parent)
        >>> _ = mod.createNode("transform", name="keepAlive", parent=parent)
        >>> mod.doIt()
        >>> "myParent" in cmds.ls()
        True
        >>> "myChild" in cmds.ls()
        True
        >>> parent.child().name() == 'myChild'
        True
        >>> mod = DagModifier()
        >>> _ = mod.delete(child)
        >>> mod.doIt()
        >>> parent.child().name() == 'keepAlive'
        True
        >>> "myChild" in cmds.ls()
        False

    """

    Type = om.MDagModifier

    @record_history
    def createNode(self, type, name=None, parent=None):
        parent = parent._mobject if parent else om.MObject.kNullObj

        try:
            mobj = self._modifier.createNode(type, parent)
        except TypeError as e:
            if str(e) == "parent is not a transform type":
                raise TypeError("'%s' is not a transform type," % parent)
            else:
                raise TypeError("'%s' is not a valid node type," % type)

        template = self._opts["template"]
        if name or template:
            name = (template or "{name}").format(
                name=name or "",
                type=type,
                index=self._index,
            )
            self._modifier.renameNode(mobj, name)

        self._modifier.doIt()

        return DagNode(mobj, exists=False)

    @record_history
    def parent(self, node, parent=None):
        parent = parent._mobject if parent is not None else om.MObject.kNullObj
        self._modifier.reparentNode(node._mobject, parent)

        if SAFE_MODE:
            self._modifier.doIt()

    reparent = parent
    reparentNode = parent

    if ENABLE_PEP8:
        create_node = createNode


class HashableTime(om.MTime):
    """Use time in a dictionary"""

    def __hash__(self):
        return hash(self.value)


# Convenience functions
def connect(a, b):
    with DagModifier() as mod:
        mod.connect(a, b)


def currentTime(time=None):
    """Set or return current time in MTime format"""
    if time is None:
        return oma.MAnimControl.currentTime()
    else:
        return oma.MAnimControl.setCurrentTime(time)


def animationStartTime(time=None):
    if time is None:
        return oma.MAnimControl.animationStartTime()
    else:
        return oma.MAnimControl.setAnimationStartTime(time)


def animationEndTime(time=None):
    if time is None:
        return oma.MAnimControl.animationEndTime()
    else:
        return oma.MAnimControl.setAnimationEndTime(time)


def minTime(time=None):
    if time is None:
        return oma.MAnimControl.minTime()
    else:
        return oma.MAnimControl.setMinTime(time)


def maxTime(time=None):
    if time is None:
        return oma.MAnimControl.maxTime()
    else:
        return oma.MAnimControl.setMaxTime(time)


class DGContext(om.MDGContext):
    """Context for evaluating the Maya DG

    Extension of MDGContext to also accept time as a float. In Maya 2018
    and above DGContext can also be used as a context manager.

    Arguments:
        time (float, om.MTime, optional): Time at which to evaluate context

    """

    def __init__(self, time=None, unit=None):
        args = []

        if time is not None:
            if not isinstance(time, TimeType):
                unit = unit or Seconds
                time = unit(time)
            args += [time]

        super(DGContext, self).__init__(*args)
        self._previous_context = None

    if __maya_version__ >= 2018:
        def __enter__(self):
            """Support for use as a context manager

            Example:
                >>> tm = createNode("transform")
                >>> tm["tx"] = {1: 0.0, 5: 1.0, 10: 0.0}
                >>> with DGContext(1, UiUnit()):
                ...     assert tm["tx"].read() == 0.0
                ...
                >>> with DGContext(5, UiUnit()):
                ...     assert tm["tx"].read() == 1.0
                ...

            """

            self._previous_context = self.makeCurrent()
            return self

        def __exit__(self, exc_type, exc_value, tb):
            if self._previous_context:
                self._previous_context.makeCurrent()


# Alias
Context = DGContext


def ls(*args, **kwargs):
    return list(map(encode, cmds.ls(*args, **kwargs)))


def selection(*args, **kwargs):
    kwargs["selection"] = True
    return ls(*args, **kwargs)


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
        >>> node = createNode(tTransform)  # Type as ID

        # Shape without transform automatically creates transform
        >>> node = createNode("mesh")
        >>> node.isA(kTransform)
        True

        # DG nodes are also OK
        >>> node = createNode("multMatrix")

        # Parenting is A-OK
        >>> parent = createNode("transform")
        >>> child = createNode("transform", parent=parent)
        >>> child.parent() == parent
        True

        # Custom name is OK
        >>> specialName = createNode("transform", name="specialName")
        >>> specialName.name() == "specialName"
        True

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

    return Node(mobj, exists=False)


def getAttr(attr, type=None, time=None):
    """Read `attr`

    Arguments:
        attr (Plug): Attribute as a cmdx.Plug
        type (str, optional): Unused
        time (float, optional): Time at which to evaluate the attribute

    Example:
        >>> node = createNode("transform")
        >>> getAttr(node + ".translateX")
        0.0

    """

    return attr.read(time=time)


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

    if isinstance(attr, str):
        node, attr = attr.rsplit(".", 1)
        node = encode(node)
        attr = node[attr]

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
            "enum": Enum,
        }[attributeType]

    kwargs = {
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
        >>> listRelatives(str(child), parent=True) == [str(parent)]
        True

    """

    if isinstance(node, str):
        node = encode(node)

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

    if isinstance(src, str):
        node, src = src.rsplit(".", 1)
        node = encode(node)
        src = node[src]

    if isinstance(dst, str):
        node, dst = dst.rsplit(".", 1)
        node = encode(node)
        dst = node[dst]

    src.connect(dst)


def delete(*nodes):
    # Flatten possible sub-lists
    flattened = list()
    for node in nodes:
        if isinstance(node, (tuple, list)):
            flattened += node
        else:
            flattened += [node]

    # Use DAG modifier rather than DG, because
    # DG doesn't understand hierarchy.
    # Do not make undoable, such that it may
    # be used alongside :func:`commit` and within
    # plug-ins that manage undo themselves
    with DagModifier(undoable=False) as mod:
        for node in flattened:
            if isinstance(node, str):
                node, node = node.rsplit(".", 1)
                node = encode(node)
                node = node[node]

            if not node.exists:
                # May have been a child of something
                # deleted earlier
                continue

            mod.delete(node)
            mod.do_it()


def rename(node, name):
    with DGModifier() as mod:
        mod.rename(node, name)


def parent(children, parent, relative=True, absolute=False, safe=True):
    assert isinstance(parent, DagNode), "parent must be DagNode"

    if not isinstance(children, (tuple, list)):
        children = [children]

    for child in children:
        assert isinstance(child, DagNode), "child must be DagNode"
        parent.addChild(child, safe=safe)


def objExists(obj):
    if isinstance(obj, (Node, Plug)):
        obj = obj.path()

    try:
        om.MSelectionList().add(obj)
    except RuntimeError:
        return False
    else:
        return True


# Possible up-axes
Y = "y"
Z = "z"


def upAxis():
    """Get the current up-axis as a Vector

    Examples:
        >>> setUpAxis(Z)
        >>> assert upAxis() == Vector(0, 0, 1)
        >>> setUpAxis(Y)
        >>> assert upAxis() == Vector(0, 1, 0)

    Returns:
        Vector: (0, 1, 0) for Y-up, (0, 0, 1) for Z-up

    """

    if __maya_version__ >= 2019:
        return Vector(om.MGlobal.upAxis())

    else:
        if cmds.optionVar(query="upAxisDirection").lower() == "y":
            return Vector(0, 1, 0)

        else:
            # Maya only supports two axes
            return Vector(0, 0, 1)


def setUpAxis(axis=Y):
    """Set the current up-axis as Y or Z

    Tested in :func:`upAxis`

    """

    if __maya_version__ >= 2019:
        if axis == Y:
            om.MGlobal.setYAxisUp(True)
        else:
            om.MGlobal.setZAxisUp(True)
    else:
        cmds.optionVar(stringValue=("upAxisDirection", axis))
        cmds.warning(
            "Changing up-axis via cmdx in Maya 2019 "
            "or below requires a restart."
        )


if ENABLE_PEP8:
    sl = selection
    create_node = createNode
    get_attr = getAttr
    set_attr = setAttr
    add_attr = addAttr
    list_relatives = listRelatives
    list_connections = listConnections
    connect_attr = connectAttr
    obj_exists = objExists
    current_time = currentTime
    min_time = minTime
    max_time = maxTime
    animation_start_time = animationStartTime
    animation_end_time = animationEndTime
    up_axis = upAxis
    set_up_axis = setUpAxis


# Special-purpose functions

kOpen = om1.MFnNurbsCurve.kOpen
kClosed = om1.MFnNurbsCurve.kClosed
kPeriodic = om1.MFnNurbsCurve.kPeriodic


def editCurve(parent, points, degree=1, form=kOpen):
    assert isinstance(parent, DagNode), (
        "parent must be of type cmdx.DagNode"
    )

    degree = min(3, max(1, degree))

    cvs = om1.MPointArray()
    curveFn = om1.MFnNurbsCurve()

    for point in points:
        cvs.append(om1.MPoint(*point))

    mobj = curveFn.createWithEditPoints(cvs,
                                        degree,
                                        form,
                                        False,
                                        False,
                                        True,
                                        _encode1(parent.path()))

    mod = om1.MDagModifier()
    mod.renameNode(mobj, parent.name(namespace=True) + "Shape")
    mod.doIt()

    def undo():
        mod.deleteNode(mobj)
        mod.doIt()

    def redo():
        mod.undoIt()

    commit(undo, redo)

    shapeFn = om1.MFnDagNode(mobj)
    return encode(shapeFn.fullPathName())


def curve(parent, points, degree=1, form=kOpen):
    """Create a NURBS curve from a series of points

    Arguments:
        parent (DagNode): Parent to resulting shape node
        points (list): One tuples per point, with 3 floats each
        degree (int, optional): Degree of curve, 1 is linear
        form (int, optional): Whether to close the curve or not

    Example:
        >>> parent = createNode("transform")
        >>> shape = curve(parent, [
        ...     (0, 0, 0),
        ...     (0, 1, 0),
        ...     (0, 2, 0),
        ... ])
        ...

    """

    assert isinstance(parent, DagNode), (
        "parent must be of type cmdx.DagNode"
    )

    # Superimpose end knots
    # startpoints = [points[0]] * (degree - 1)
    # endpoints = [points[-1]] * (degree - 1)
    # points = startpoints + list(points) + endpoints

    degree = min(3, max(1, degree))

    cvs = om1.MPointArray()
    knots = om1.MDoubleArray()
    curveFn = om1.MFnNurbsCurve()

    knotcount = len(points) - degree + 2 * degree - 1

    for point in points:
        cvs.append(om1.MPoint(*point))

    for index in range(knotcount):
        knots.append(index)

    mobj = curveFn.create(cvs,
                          knots,
                          degree,
                          form,
                          False,
                          True,
                          _encode1(parent.path()))

    mod = om1.MDagModifier()
    mod.renameNode(mobj, parent.name(namespace=True) + "Shape")
    mod.doIt()

    def undo():
        mod.deleteNode(mobj)
        mod.doIt()

    def redo():
        mod.undoIt()

    commit(undo, redo)

    shapeFn = om1.MFnDagNode(mobj)
    return encode(shapeFn.fullPathName())


def lookAt(origin, center, up=None):
    """Build a (left-handed) look-at matrix

    See glm::glc::matrix_transform::lookAt for reference

             + Z (up)
            /
           /
    (origin) o------ + X (center)
           \
            + Y

    Arguments:
        origin (Vector): Starting position
        center (Vector): Point towards this
        up (Vector, optional): Up facing this way, defaults to Y-up

    Example:
        >>> mat = lookAt(
        ...   (0, 0, 0),  # Relative the origin..
        ...   (1, 0, 0),  # X-axis points towards global X
        ...   (0, 1, 0)   # Z-axis points towards global Y
        ... )
        >>> tm = Tm(mat)
        >>> int(degrees(tm.rotation().x))
        -90

    """

    if isinstance(origin, (tuple, list)):
        origin = Vector(origin)

    if isinstance(center, (tuple, list)):
        center = Vector(center)

    if up is not None and isinstance(up, (tuple, list)):
        up = Vector(up)

    up = up or Vector(0, 1, 0)

    x = (center - origin).normalize()
    y = ((center - origin) ^ (center - up)).normalize()
    z = x ^ y

    return MatrixType((
        x[0], x[1], x[2], 0,
        y[0], y[1], y[2], 0,
        z[0], z[1], z[2], 0,
        0, 0, 0, 0
    ))


if ENABLE_PEP8:
    look_at = lookAt


def first(iterator, default=None):
    """Return first member of an `iterator`

    Example:
        >>> def it():
        ...   yield 1
        ...   yield 2
        ...   yield 3
        ...
        >>> first(it())
        1

    """

    return next(iterator, default)


def last(iterator, default=None):
    """Return last member of an `iterator`

    Example:
        >>> def it():
        ...   yield 1
        ...   yield 2
        ...   yield 3
        ...
        >>> last(it())
        3

    """

    last = default
    for member in iterator:
        last = member
    return last

# --------------------------------------------------------
#
# Attribute Types
#
# --------------------------------------------------------


# Disconnect behaviors
kNothing = om.MFnAttribute.kNothing
kReset = om.MFnAttribute.kReset
kDelete = om.MFnAttribute.kDelete


class _AbstractAttribute(dict):
    Fn = None
    Type = None
    Default = None

    Readable = True
    Writable = True
    Cached = True  # Cache in datablock?
    Storable = True  # Write value to file?
    Hidden = False  # Display in Attribute Editor?

    Array = False
    IndexMatters = True
    Connectable = True

    Keyable = False
    ChannelBox = False
    AffectsAppearance = False
    AffectsWorldSpace = False

    # What should happen when an attribute is disconnected?
    # kNothing | leave the attribute set to its last known value
    # kReset   | reset the attribute to its default value
    # kDelete  | delete the element of the array that was connected
    #          | (only relevant for array attributes)
    DisconnectBehavior = kNothing

    Help = ""

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
        """Support for using name of assignment

        Example:
            node["thisName"] =  cmdx.Double()

        In this example, the attribute isn't given a `name`
        Instead, the name is inferred from where it is assigned.

        """

        if not args:
            return cls, kwargs

        return super(_AbstractAttribute, cls).__new__(cls, *args, **kwargs)

    def __init__(self,
                 name,
                 default=None,
                 label=None,
                 shortName=None,

                 writable=None,
                 readable=None,
                 cached=None,
                 storable=None,
                 keyable=None,
                 hidden=None,
                 min=None,
                 max=None,
                 channelBox=None,
                 affectsAppearance=None,
                 affectsWorldSpace=None,
                 array=False,
                 indexMatters=None,
                 connectable=True,
                 disconnectBehavior=kNothing,
                 help=None):

        self.Fn = type(self).Fn()

        # To avoid repeating the long list of arguments above,
        # store all arguments to this function using "locals"
        args = locals().copy()
        args.pop("self")

        self["name"] = args.pop("name")
        self["label"] = args.pop("label")
        self["default"] = args.pop("default")

        # Exclusive to numeric attributes
        self["min"] = args.pop("min")
        self["max"] = args.pop("max")

        # Filled in on creation
        self["mobject"] = None

        self["shortName"] = (
            args.pop("shortName") or

            # MyName -> myName
            self["name"][0].lower() + self["name"][1:]
        )

        for key, value in args.items():
            default = getattr(self, key[0].upper() + key[1:])
            self[key] = value if value is not None else default

    def dumps(self):
        """Return a block of text representing the config of this attribute"""

        result = ["type: %s" % type(self).__name__]

        for key, value in self.items():
            if key == "disconnectBehavior":
                value = {
                    kNothing: "kNothing",
                    kReset: "kReset",
                    kDelete: "kDelete"
                }[value]

            if key == "label":
                key = "niceName"

            # Internal
            if key == "mobject":
                continue

            result += ["%s: %s" % (key, value)]

        return "\n".join(result)

    def default(self, cls=None):
        """Return one of three available values

        Resolution order:
            1. Argument
            2. Node default (from cls.defaults)
            3. Attribute default

        """

        if self["default"] is not None:
            return self["default"]

        if cls is not None:
            return cls.defaults.get(self["name"], self.Default)

        return self.Default

    def type(self):
        return self.Type

    def create(self, cls=None):
        args = [
            arg
            for arg in (self["name"],
                        self["shortName"],
                        self.type())
            if arg is not None
        ]

        default = self.default(cls)
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
        self.Fn.connectable = self["connectable"]
        self.Fn.hidden = self["hidden"]
        self.Fn.cached = self["cached"]
        self.Fn.keyable = self["keyable"]
        self.Fn.channelBox = self["channelBox"]
        self.Fn.affectsAppearance = self["affectsAppearance"]
        self.Fn.affectsWorldSpace = self["affectsWorldSpace"]
        self.Fn.disconnectBehavior = self["disconnectBehavior"]
        self.Fn.array = self["array"]

        if self["indexMatters"] is False:
            self.Fn.readable = False
            self.Fn.indexMatters = False

        if self["min"] is not None:
            self.Fn.setMin(self["min"])

        if self["max"] is not None:
            self.Fn.setMax(self["max"])

        if self["label"] is not None:
            self.Fn.setNiceNameOverride(self["label"])

        return self["mobject"]

    def read(self, data):
        pass


class Enum(_AbstractAttribute):
    Fn = om.MFnEnumAttribute
    Type = None
    Default = 0

    Keyable = True

    def __init__(self, name, fields=None, default=0, label=None, **kwargs):
        super(Enum, self).__init__(name, default, label, **kwargs)

        self.update({
            "fields": fields or (name,),
        })

    def create(self, cls=None):
        attr = super(Enum, self).create(cls)

        for index in range(len(self["fields"])):
            field = self["fields"][index]

            # Support passing in of arbitrary indexes
            # E.g. fields=((0, "Box"), (3, "Sphere"))
            if isinstance(field, (tuple, list)):
                index, field = field

            self.Fn.addField(field, index)

        return attr

    def read(self, data):
        return data.inputValue(self["mobject"]).asShort()


class Divider(Enum):
    """Visual divider in channel box"""

    ChannelBox = True
    Keyable = False

    def __init__(self, label, **kwargs):
        kwargs.pop("name", None)
        kwargs.pop("fields", None)
        kwargs.pop("label", None)

        # Account for spaces in label
        # E.g. "Hard Pin" -> "hardPin"
        name = label[0].lower() + label[1:].replace(" ", "")

        super(Divider, self).__init__(
            name, fields=(label,), label=" ", **kwargs
        )


class String(_AbstractAttribute):
    Fn = om.MFnTypedAttribute
    Type = om.MFnData.kString
    Default = ""

    def default(self, cls=None):
        default = str(super(String, self).default(cls))
        return om.MFnStringData().create(default)

    def read(self, data):
        return data.inputValue(self["mobject"]).asString()


class Message(_AbstractAttribute):
    Fn = om.MFnMessageAttribute
    Type = None
    Default = None
    Storable = False


class Matrix(_AbstractAttribute):
    Fn = om.MFnMatrixAttribute

    Default = (0.0,) * 4 * 4  # Identity matrix

    Array = False
    Readable = True
    Keyable = False
    Hidden = False

    def default(self, cls=None):
        return None

    def read(self, data):
        return data.inputValue(self["mobject"]).asMatrix()


class Long(_AbstractAttribute):
    Fn = om.MFnNumericAttribute
    Type = om.MFnNumericData.kLong
    Default = 0

    def read(self, data):
        return data.inputValue(self["mobject"]).asLong()


class Double(_AbstractAttribute):
    Fn = om.MFnNumericAttribute
    Type = om.MFnNumericData.kDouble
    Default = 0.0

    def read(self, data):
        return data.inputValue(self["mobject"]).asDouble()


class Float(_AbstractAttribute):
    Fn = om.MFnNumericAttribute
    Type = om.MFnNumericData.kFloat
    Default = 0.0

    def read(self, data):
        return data.inputValue(self["mobject"]).asFloat()


class Double3(_AbstractAttribute):
    Fn = om.MFnNumericAttribute
    Type = None
    Default = (0.0,) * 3

    def default(self, cls=None):
        if self["default"] is not None:
            default = self["default"]

            # Support single-value default
            if not isinstance(default, (tuple, list)):
                default = (default,) * 3

        elif cls is not None:
            default = cls.defaults.get(self["name"], self.Default)

        else:
            default = self.Default

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
    Fn = om.MFnNumericAttribute
    Type = om.MFnNumericData.kBoolean
    Default = True

    def read(self, data):
        return data.inputValue(self["mobject"]).asBool()


class AbstractUnit(_AbstractAttribute):
    Fn = om.MFnUnitAttribute
    Default = 0.0
    Min = None
    Max = None
    SoftMin = None
    SoftMax = None


class Angle(AbstractUnit):
    def default(self, cls=None):
        default = super(Angle, self).default(cls)

        # When no unit was explicitly passed, assume radians
        if not isinstance(default, om.MAngle):
            default = om.MAngle(default, om.MAngle.kRadians)

        return default


class Time(AbstractUnit):
    def default(self, cls=None):
        default = super(Time, self).default(cls)

        # When no unit was explicitly passed, assume seconds
        if not isinstance(default, om.MTime):
            default = om.MTime(default, om.MTime.kSeconds)

        return default


class Distance(AbstractUnit):
    def default(self, cls=None):
        default = super(Distance, self).default(cls)

        # When no unit was explicitly passed, assume centimeters
        if not isinstance(default, om.MDistance):
            default = om.MDistance(default, om.MDistance.kCentimeters)

        return default


class Compound(_AbstractAttribute):
    """One or more nested attributes

    Examples:
        >>> _ = cmds.file(new=True, force=True)
        >>> node = createNode("transform")
        >>> node["compoundAttr"] = Compound(children=[
        ...     Double("child1", default=1.0),
        ...     Double("child2", default=5.0)
        ... ])
        ...
        >>> node["compoundAttr"]["child1"].read()
        1.0
        >>> node["compoundAttr"]["child2"].read()
        5.0

        # Also supports nested attributes
        >>> node.addAttr(
        ...     Compound("parent", children=[
        ...         Compound("child", children=[
        ...             Double("age", default=33),
        ...             Double("height", default=1.87)
        ...         ])
        ...     ])
        ... )
        ...
        >>> node["parent"]["child"]["age"].read()
        33.0
        >>> node["parent"]["child"]["height"].read()
        1.87

    """

    Fn = om.MFnCompoundAttribute
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

    def default(self, cls=None):
        # Compound itself has no defaults, only it's children do
        pass

    def create(self, cls=None):
        mobj = super(Compound, self).create(cls)
        default = super(Compound, self).default(cls)

        for index, child in enumerate(self["children"]):
            # Forward attributes from parent to child
            for attr in ("storable",
                         "readable",
                         "writable",
                         "hidden",
                         "channelBox",
                         "keyable"):
                child[attr] = self[attr]

            if child["default"] is None and default is not None:
                child["default"] = default[index]

            self.Fn.addChild(child.create(cls))

        return mobj

    def read(self, handle):
        """Read from MDataHandle"""
        output = list()

        for child in self["children"]:
            child_handle = handle.child(child["mobject"])
            output.append(child.read(child_handle))

        return tuple(output)


class Double2(Compound):
    Multi = ("XY", Double)


class Double4(Compound):
    Multi = ("XYZW", Double)


class Angle2(Compound):
    Multi = ("XY", Angle)


class Angle3(Compound):
    Multi = ("XYZ", Angle)


class Distance2(Compound):
    Multi = ("XY", Distance)


class Distance3(Compound):
    Multi = ("XYZ", Distance)


class Distance4(Compound):
    Multi = ("XYZW", Distance)


# Convenience aliases, for when it isn't clear e.g. `Matrix()`
# is referring to an attribute rather than the datatype.
EnumAttribute = Enum
DividerAttribute = Divider
StringAttribute = String
MessageAttribute = Message
MatrixAttribute = Matrix
LongAttribute = Long
DoubleAttribute = Double
Double3Attribute = Double3
BooleanAttribute = Boolean
AbstractUnitAttribute = AbstractUnit
AngleAttribute = Angle
TimeAttribute = Time
DistanceAttribute = Distance
CompoundAttribute = Compound
Double2Attribute = Double2
Double4Attribute = Double4
Angle2Attribute = Angle2
Angle3Attribute = Angle3
Distance2Attribute = Distance2
Distance3Attribute = Distance3
Distance4Attribute = Distance4


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


# E.g. cmdx => cmdx_0_6_0_plugin_username0.py
unique_plugin = "cmdx_%s_plugin_%s.py" % (
    __version__.replace(".", "_"),

    # Include username, in case two
    # users occupy the same machine
    getpass.getuser()
)

# Support for multiple co-existing versions of apiundo.
unique_command = "cmdx_%s_command" % __version__.replace(".", "_")

# This module is both a Python module and Maya plug-in.
# Data is shared amongst the two through this "module"
unique_shared = "cmdx_%s_shared" % __version__.replace(".", "_")

if unique_shared not in sys.modules:
    sys.modules[unique_shared] = types.ModuleType(unique_shared)

shared = sys.modules[unique_shared]
shared.undoId = None
shared.redoId = None
shared.undos = {}
shared.redos = {}


def commit(undo, redo=lambda: None):
    """Commit `undo` and `redo` to history

    Arguments:
        undo (func): Call this function on next undo
        redo (func, optional): Like `undo`, for for redo

    """

    if not ENABLE_UNDO:
        return

    if not hasattr(cmds, unique_command):
        install()

    # Precautionary measure.
    # If this doesn't pass, odds are we've got a race condition.
    # NOTE: This assumes calls to `commit` can only be done
    # from a single thread, which should already be the case
    # given that Maya's API is not threadsafe.
    try:
        assert shared.redoId is None
        assert shared.undoId is None
    except AssertionError:
        log.debug("%s has a problem with undo" % __name__)

    # Temporarily store the functions at shared-level,
    # they are later picked up by the command once called.
    shared.undoId = "%x" % id(undo)
    shared.redoId = "%x" % id(redo)
    shared.undos[shared.undoId] = undo
    shared.redos[shared.redoId] = redo

    # Let Maya know that something is undoable
    getattr(cmds, unique_command)()


def install():
    """Load this module as a plug-in

    Inception time! :)

    In order to facilitate undo, we need a custom command registered
    with Maya's native plug-in system. To do that, we need a dedicated
    file. We *could* register ourselves as that file, but what we need
    is a unique instance of said command per distribution of cmdx.

    Per distribution? Yes, because cmdx.py can be vendored with any
    library, and we don't want cmdx.py from one vendor to interfere
    with one from another.

    Maya uses (pollutes) global memory in two ways that
    matter to us here.

    1. Plug-ins are referenced by name, not path. So there can only be
        one "cmdx.py" for example. That's why we can't load this module
        as-is but must instead write a new file somewhere, with a name
        unique to this particular distribution.
    2. Commands are referenced via the native `cmds` module, and there can
        only be 1 command of any given name. So we can't just register e.g.
        `cmdxUndo` if we want to support multiple versions of cmdx being
        registered at once. Instead, we'll generate a unique name per
        distribution of cmdx, like the plug-in itself.

    We can't leverage things like sys.modules[__name__] or even
    the __name__ variable, because the way Maya loads Python modules
    as plug-ins is to copy/paste the text itself and call that. So there
    *is* no __name__. Instead, we'll rely on each version being unique
    and consistent.

    """

    import errno
    import shutil

    # E.g. c:\users\marcus\Documents\maya
    tempdir = os.path.expanduser("~/maya/plug-ins")

    try:
        os.makedirs(tempdir)

    except OSError as e:
        if e.errno == errno.EEXIST:
            # This is fine
            pass

        else:
            # Can't think of a reason why this would ever
            # happen but you can never be too careful..
            log.debug("Could not create %s" % tempdir)

            import tempfile
            tempdir = tempfile.gettempdir()

    tempfname = os.path.join(tempdir, unique_plugin)

    if not os.path.exists(tempfname):
        # We can't know whether we're a .pyc or .py file,
        # but we need to copy the .py file *only*
        fname = os.path.splitext(__file__)[0]

        try:
            shutil.copyfile(fname + ".py", tempfname)

        except OSError:
            # This could never really happen, but you never know.
            # In which case, use the file as-is. This should work
            # for a majority of cases and only really conflict when/if
            # the undo mechanism of cmdx changes, which is exceedingly
            # rare. The actual functionality of cmdx is independent of
            # this plug-in and will still pick up the appropriate
            # vendored module.
            log.debug("Could not generate unique cmdx.py")
            log.debug("Undo may still work, but cmdx may conflict\n"
                      "with other instances of it.")
            tempfname = __file__

    # Now we're guaranteed to not interfere
    # with other versions of cmdx. Win!
    cmds.loadPlugin(tempfname, quiet=True)

    self.installed = True


def uninstall():
    if ENABLE_UNDO and self.installed:

        # Plug-in may exist in undo queue and
        # therefore cannot be unloaded until flushed.
        clear()

        cmds.unloadPlugin(unique_plugin)

    self.installed = False


def maya_useNewAPI():
    pass


class _apiUndo(om.MPxCommand):
    # For debugging, should always be 0 unless there's something to undo
    _aliveCount = 0

    def __init__(self, *args, **kwargs):
        super(_apiUndo, self).__init__(*args, **kwargs)
        _apiUndo._aliveCount += 1

        self.undoId = None
        self.redoId = None

    def __del__(self):
        _apiUndo._aliveCount -= 1

        # Relive whatever was held in memory
        # This *should* always contain the undo ID
        # of the current command instance. If it doesn't,
        # the `shared` module must have been either
        # edited or deleted outside of cmdx, such as
        # if the module was reloaded.

        # However, we can't afford throwing errors here,
        # and errors here isn't a big whop anyway since they
        # would be deleted and cleaned up on unloading
        # of the `cmdx` module along with the `shared`
        # instance from sys.module. E.g. on Maya restart.
        shared.undos.pop(self.undoId, None)
        shared.redos.pop(self.redoId, None)

        self.undoId = None
        self.redoId = None

    def doIt(self, args):

        # Store the last undo/redo commands in this
        # instance of the _apiUndo command.
        self.undoId = shared.undoId
        self.redoId = shared.redoId

        # With that stored, let's avoid storing it elsewhere
        shared.undoId = None
        shared.redoId = None

    def undoIt(self):
        # If the undo ID does not exist, it means
        # we've erased commands still active in the undo
        # queue, which isn't good. E.g. the cmdx module
        # was reloaded.
        shared.undos[self.undoId]()

    def redoIt(self):
        shared.redos[self.redoId]()

    def isUndoable(self):
        # Without this, the above undoIt and redoIt will not be called
        return True


def initializePlugin(plugin):
    om.MFnPlugin(plugin).registerCommand(
        unique_command,
        _apiUndo
    )


def uninitializePlugin(plugin):
    om.MFnPlugin(plugin).deregisterCommand(unique_command)


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


tAddDoubleLinear = om.MTypeId(0x4441444c)
tAddMatrix = om.MTypeId(0x44414d58)
tAngleBetween = om.MTypeId(0x4e414254)
tBlendShape = om.MTypeId(0x46424c53)
tMultMatrix = om.MTypeId(0x444d544d)
tAngleDimension = om.MTypeId(0x4147444e)
tBezierCurve = om.MTypeId(0x42435256)
tCamera = om.MTypeId(0x4443414d)
tChoice = om.MTypeId(0x43484345)
tChooser = om.MTypeId(0x43484f4f)
tCondition = om.MTypeId(0x52434e44)
tMesh = om.MTypeId(0x444d5348)
tNurbsCurve = om.MTypeId(0x4e435256)
tNurbsSurface = om.MTypeId(0x4e535246)
tJoint = om.MTypeId(0x4a4f494e)
tTransform = om.MTypeId(0x5846524d)
tTransformGeometry = om.MTypeId(0x5447454f)
tWtAddMatrix = om.MTypeId(0x4457414d)


# --------------------------------------------------------
#
# Plug-ins
#
# --------------------------------------------------------

InstalledPlugins = dict()
TypeId = om.MTypeId

# Get your unique ID from Autodesk, the below
# should not be trusted for production.
StartId = int(os.getenv("CMDX_BASETYPEID", "0x12b9c0"), 0)


class MetaNode(type):
    def __init__(cls, *args, **kwargs):
        assert isinstance(cls.name, str)
        assert isinstance(cls.defaults, dict)
        assert isinstance(cls.attributes, list)
        assert isinstance(cls.version, tuple)

        if isinstance(cls.typeid, (int, float)):
            cls.typeid = TypeId(cls.typeid)

        # Support Divider plug-in, without name for readability.
        # E.g. Divider("_", "Label") -> Divider("Label")
        index = 1
        for attribute in cls.attributes:
            if isinstance(attribute, Divider):
                attribute["name"] = "_" * index
                attribute["shortName"] = "_" * index
                index += 1

        # Ensure no duplicates
        assert len(set(cls.attributes)) == len(cls.attributes), (
            "One or more attributes in '%s' was found more than once"
            % cls.__name__
        )

        attributes = {attr["name"]: attr for attr in cls.attributes}

        def findAttribute(self, name):
            return attributes.get(name)

        def findMObject(self, name):
            return attributes.get(name)["mobject"]

        def findPlug(self, node, name):
            try:
                mobj = attributes.get(name)["mobject"]
                return om.MPlug(node, mobj)
            except KeyError:
                return None

        cls.findAttribute = findAttribute
        cls.findMObject = findMObject
        cls.findPlug = findPlug

        cls.find_attribute = findAttribute
        cls.find_mobject = findMObject
        cls.find_plug = findPlug

        cls.log = logging.getLogger(cls.__name__)

        return super(MetaNode, cls).__init__(*args, **kwargs)


@add_metaclass(MetaNode)
class DgNode(om.MPxNode):
    """Abstract baseclass for a Maya DG node

    Attributes:
        name (str): Name used in e.g. cmds.createNode
        id (int): Unique ID from Autodesk (see Ids above)
        version (tuple, optional): Optional version number for plug-in node
        attributes (tuple, optional): Attributes of node
        defaults (dict, optional): Dictionary of default values

    """

    typeid = TypeId(StartId)
    name = "defaultNode"
    version = (0, 0)
    attributes = list()
    affects = list()
    ranges = dict()
    defaults = {}

    @classmethod
    def postInitialize(cls):
        pass


@add_metaclass(MetaNode)
class SurfaceShape(om.MPxSurfaceShape):
    """Abstract baseclass for a Maya shape

    Attributes:
        name (str): Name used in e.g. cmds.createNode
        id (int): Unique ID from Autodesk (see Ids above)
        version (tuple, optional): Optional version number for plug-in node
        attributes (tuple, optional): Attributes of node
        defaults (dict, optional): Dictionary of default values

    """

    typeid = TypeId(StartId)
    classification = "drawdb/geometry/custom"
    name = "defaultNode"
    version = (0, 0)
    attributes = list()
    affects = list()
    ranges = dict()
    defaults = {}

    @classmethod
    def postInitialize(cls):
        pass

    @classmethod
    def uiCreator(cls):
        pass


@add_metaclass(MetaNode)
class SurfaceShapeUI(omui.MPxSurfaceShapeUI):
    """Abstract baseclass for a Maya shape

    Attributes:
        name (str): Name used in e.g. cmds.createNode
        id (int): Unique ID from Autodesk (see Ids above)
        version (tuple, optional): Optional version number for plug-in node
        attributes (tuple, optional): Attributes of node
        defaults (dict, optional): Dictionary of default values

    """

    typeid = TypeId(StartId)
    classification = "drawdb/geometry/custom"
    name = "defaultNode"
    version = (0, 0)
    attributes = list()
    affects = list()
    ranges = dict()
    defaults = {}

    @classmethod
    def postInitialize(cls):
        pass


@add_metaclass(MetaNode)
class LocatorNode(omui.MPxLocatorNode):
    """Abstract baseclass for a Maya locator

    Attributes:
        name (str): Name used in e.g. cmds.createNode
        id (int): Unique ID from Autodesk (see Ids above)
        version (tuple, optional): Optional version number for plug-in node
        attributes (tuple, optional): Attributes of node
        defaults (dict, optional): Dictionary of default values

    """

    name = "defaultNode"
    typeid = TypeId(StartId)
    classification = "drawdb/geometry/custom"
    version = (0, 0)
    attributes = list()
    affects = list()
    ranges = dict()
    defaults = {}

    @classmethod
    def postInitialize(cls):
        pass


def initialize2(Plugin):
    def _nodeInit():
        nameToAttr = {}
        for attr in Plugin.attributes:
            mattr = attr.create(Plugin)
            Plugin.addAttribute(mattr)
            nameToAttr[attr["name"]] = mattr

        for src, dst in Plugin.affects:
            log.debug("'%s' affects '%s'" % (src, dst))
            Plugin.attributeAffects(nameToAttr[src], nameToAttr[dst])

    def _nodeCreator():
        return Plugin()

    def initializePlugin(obj):
        version = ".".join(map(str, Plugin.version))
        plugin = om.MFnPlugin(obj, "Cmdx", version, "Any")

        try:
            if issubclass(Plugin, LocatorNode):
                plugin.registerNode(Plugin.name,
                                    Plugin.typeid,
                                    _nodeCreator,
                                    _nodeInit,
                                    om.MPxNode.kLocatorNode,
                                    Plugin.classification)

            elif issubclass(Plugin, DgNode):
                plugin.registerNode(Plugin.name,
                                    Plugin.typeid,
                                    _nodeCreator,
                                    _nodeInit)

            elif issubclass(Plugin, SurfaceShape):
                plugin.registerShape(Plugin.name,
                                     Plugin.typeid,
                                     _nodeCreator,
                                     _nodeInit,
                                     Plugin.uiCreator,
                                     Plugin.classification)

            else:
                raise TypeError("Unsupported subclass: '%s'" % Plugin)

        except Exception:
            raise

        else:
            # Maintain reference to original class
            InstalledPlugins[Plugin.name] = Plugin

            Plugin.postInitialize()

    return initializePlugin


def uninitialize2(Plugin):
    def uninitializePlugin(obj):
        om.MFnPlugin(obj).deregisterNode(Plugin.typeid)

    return uninitializePlugin


# Plugins written with Maya Python API 1.0

class MPxManipContainer1(ompx1.MPxManipContainer):
    name = "defaultManip"
    version = (0, 0)
    ownerid = om1.MTypeId(StartId)
    typeid = om1.MTypeId(StartId)


def initializeManipulator1(Manipulator):
    def _manipulatorCreator():
        return ompx1.asMPxPtr(Manipulator())

    def _manipulatorInit():
        ompx1.MPxManipContainer.addToManipConnectTable(Manipulator.ownerid)
        ompx1.MPxManipContainer.initialize()

    def initializePlugin(obj):
        version = ".".join(map(str, Manipulator.version))
        plugin = ompx1.MFnPlugin(obj, "Cmdx", version, "Any")

        # NOTE(marcus): The name *must* end with Manip
        # See https://download.autodesk.com/us/maya/2011help
        #     /API/class_m_px_manip_container.html
        #     #e95527ff30ae53c8ae0419a1abde8b0c
        assert Manipulator.name.endswith("Manip"), (
            "Manipulator '%s' must have the name of a plug-in, "
            "and end with 'Manip'"
        )

        plugin.registerNode(
            Manipulator.name,
            Manipulator.typeid,
            _manipulatorCreator,
            _manipulatorInit,
            ompx1.MPxNode.kManipContainer
        )

    return initializePlugin


def uninitializeManipulator1(Manipulator):
    def uninitializePlugin(obj):
        ompx1.MFnPlugin(obj).deregisterNode(Manipulator.typeid)

    return uninitializePlugin


def findPlugin(name):
    """Find the original class of a plug-in by `name`"""

    try:
        return InstalledPlugins[name]
    except KeyError:
        raise ExistError("'%s' is not a recognised plug-in" % name)


# --------------------------
#
# Callback Manager
#
# --------------------------


class Callback(object):
    """A Maya callback"""

    log = logging.getLogger("cmdx.Callback")

    def __init__(self, name, installer, args, api=2, help="", parent=None):
        self._id = None
        self._args = args
        self._name = name
        self._installer = installer
        self._help = help

        # Callbacks are all uninstalled using the same function
        # relative either API 1.0 or 2.0
        self._uninstaller = {
            1: om1.MMessage.removeCallback,
            2: om.MMessage.removeCallback
        }[api]

    def __del__(self):
        self.deactivate()

    def name(self):
        return self._name

    def help(self):
        return self._help

    def is_active(self):
        return self._id is not None

    def activate(self):
        self.log.debug("Activating callback '%s'.." % self._name)

        if self.is_active():
            self.log.debug("%s already active, ignoring" % self._name)
            return

        self._id = self._installer(*self._args)

    def deactivate(self):
        self.log.debug("Deactivating callback '%s'.." % self._name)

        if self.is_active():
            self._uninstaller(self._id)

        self._id = None


class CallbackGroup(list):
    """Multiple callbacks rolled into one"""

    def __init__(self, name, callbacks, parent=None):
        self._name = name
        self[:] = callbacks

    def name(self):
        return self._name

    def add(self, name, installer, args, api=2):
        """Convenience method for .append(Callback())"""
        callback = Callback(name, installer, args, api)
        self.append(callback)

    def activate(self):
        for callback in self._callbacks:
            callback.activate()

    def deactivate(self):
        for callback in self._callbacks:
            callback.deactivate()


# ----------------------
#
# Cache Manager
#
# ----------------------

class Cache(object):
    def __init__(self):
        self._values = {}

    def clear(self, node=None):
        pass

    def read(self, node, attr, time):
        pass

    def transform(self, node):
        pass


# Testing utilities
def _new():
    cmds.file(new=True, force=True)


def _tempfile():
    import tempfile
    dirname = tempfile.gettempdir()
    return os.path.join(dirname, "test.ma")


def _save():
    cmds.file(rename=_tempfile())
    cmds.file(save=True, type="mayaAscii")


def _load():
    cmds.file(_tempfile(), open=True, force=True)


# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#    http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
