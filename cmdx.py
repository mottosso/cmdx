# -*- coding: utf-8 -*-
from maya.api import OpenMaya as om

NotExistError = type("NotExistError", (Exception,), {})
GlobalModifier = om.MDGModifier()

# TODO: Try om.MFnDependencyNode.setObject to avoid re-instantiating these
GlobalDagNode = om.MFnDagNode()
GlobalDependencyNode = om.MFnDependencyNode()


class Node(object):
    def __eq__(self, other):
        return self.uuid() == other.uuid()

    def __neq__(self, other):
        return self.uuid() != other.uuid()

    def __str__(self):
        return self.path()

    def __repr__(self):
        return self.path()

    def __add__(self, other):
        return self[other.strip(".")]

    def __getitem__(self, attr):
        plug = self._fn.findPlug(attr, False)
        return Plug(plug)

    def __setitem__(self, key, value):
        """Support item assignment of new attributes or values

        Example:
            >>> from maya.api import OpenMaya
            >>> node = Node(OpenMaya.MFnDagNode())
            >>> node.create("transform")
            >>> node["myAttr"] = Double(default=1.0)
            >>> node["myAttr"] == 1.0
            True
            >>> node.pop("myAttr")

        """

        # Create a new attribute
        if isinstance(value, (tuple, list)):
            Attribute, kwargs = value
            return self.addAttr(Attribute(key, **kwargs))

        # Set an existing attribute
        type = None
        if isinstance(value, Plug):
            value = value.read()
            type = value.type

        Plug(self, key).write(value, type)

    def __delitem__(self, key):
        attr = self[key]
        self.deleteAttr(attr)

    def __init__(self, fn, mobject=None):
        self._fn = fn
        self._mobject = mobject

    def create(self, type, name=None, parent=None):
        kwargs = {}

        if name:
            kwargs["name"] = name

        if parent:
            kwargs["parent"] = parent._mobject

        mobject = self._fn.create(type, **kwargs)

        # Update reference
        self._mobject = mobject

        return mobject

    def update(self, attrs):
        """Add `attrs` to self

        Arguments:
            attrs (dict): Key/value pairs of name and attribute

        """

        for key, value in attrs.items():
            self[key] = value

    def pop(self, key):
        del self[key]

    def path(self):
        """Return full path to node"""
        try:
            return self._fn.fullPathName()

        # Only DAG nodes have a path
        except AttributeError:
            return self._fn.name()

    def shortestPath(self):
        """Return shortest unique path to node"""
        try:
            return self._fn.partialPathName()

        # Only DAG nodes have a path
        except AttributeError:
            return self._fn.name()

    def uuid(self):
        return self._fn.uuid()

    def dump(self, detail=0):
        """Return dictionary of all attributes"""

        attrs = {}
        count = self._fn.attributeCount()
        for index in range(count):
            obj = self._fn.attribute(index)
            plug = self._fn.findPlug(obj, False)

            attrs[plug.name()] = Plug(plug).read()

        return attrs

    @property
    def basename(self):
        return self.path().rsplit("|", 1)[-1]

    def root(self):
        Class = self.__class__
        Fn = self._fn.__class__
        mobject = self._fn.dagRoot()
        return Class(Fn(mobject), mobject)

    def parent(self, type=None):
        Class = self.__class__
        Fn = self._fn.__class__
        mobject = self._fn.parent(0)
        return Class(Fn(mobject), mobject)

    def children(self, type=None):
        Class = self.__class__
        Fn = self._fn.__class__

        for index in range(self._fn.childCount()):
            mobject = self._fn.child(index)
            fn = Fn(mobject)

            if not type or fn.typeId == type:
                yield Class(fn, mobject)

    def child(self, type=None):
        return next(self.children(type))

    def shapes(self, type=None):
        pass

    def addAttr(self, attr):
        GlobalModifier.addAttribute(self._mobject, attr.create())

        try:
            GlobalModifier.doIt()
        except RuntimeError as e:
            errorType, message = e.message.split(":")
            errorType = errorType.strip("()")

            if errorType == "kInvalidParameter":
                raise ValueError(message)

            # Unhandled exception
            else:
                raise

    def deleteAttr(self, attr):
        GlobalModifier.removeAttribute(self._mobject, attr)
        GlobalModifier.doIt()


class Plug(om.MPlug):
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

    @property
    def type(self):
        return self.attribute().apiType()

    def read(self, type=None):
        """Passing type = 20% faster"""
        try:
            return plug_to_python(self)

        except RuntimeError:
            raise
            return None

        except TypeError:
            raise
            return None

    def write(self, value, type=None):
        """Passing type = 10% faster"""
        try:
            return python_to_plug(value, self)

        except RuntimeError:
            return None

        except TypeError:
            return None

    def connect(self, other):
        GlobalModifier.connect(self, other)
        GlobalModifier.doIt()


def plug_to_python(plug):
    attr = plug.attribute()
    type = attr.apiType()

    # Typed
    if type == om.MFn.kTypedAttribute:
        innerType = om.MFnTypedAttribute(attr).attrType()

        # Matrix
        if innerType == om.MFnData.kMatrix:
            return om.MFnMatrixData(plug.asMObject()).matrix()

        # String
        elif innerType == om.MFnData.kString:
            return plug.asString()

        elif innerType == om.MFnData.kInvalid:
            # E.g. time1.timewarpIn_Hidden
            # Unsure of why some attributes are invalid
            return None

        else:
            raise TypeError("Unsupported typed type: %s"
                            % innerType)

    # Matrix
    elif type == om.MFn.kMatrixAttribute:
        return om.MFnMatrixData(plug.asMObject()).matrix()

    # Compound
    elif type in (om.MFn.kAttribute3Double,
                  om.MFn.kAttribute3Float,
                  om.MFn.kCompoundAttribute) and plug.isCompound:

        return tuple(
            plug_to_python(plug.child(index))
            for index in range(plug.numChildren())
        )

    # Distance
    elif type in (om.MFn.kDoubleLinearAttribute,
                  om.MFn.kFloatLinearAttribute):
        return plug.asMDistance().asCentimeters()

    # Angle
    elif type in (om.MFn.kDoubleAngleAttribute,
                  om.MFn.kFloatAngleAttribute):
        return plug.asMAngle().asDegrees()

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


def python_to_plug(python, plug):
    if isinstance(python, str):
        plug.setString(python)

    elif isinstance(python, int):
        plug.setInt(python)

    elif isinstance(python, float):
        plug.setDouble(python)

    elif isinstance(python, bool):
        plug.setBool(python)

    else:
        raise TypeError("Unsupported Python type '%s'" % type(python))


def encode(path):
    """Fastest conversion from absolute path to Node"""
    selectionList = om.MSelectionList()
    selectionList.add(path)
    mobj = selectionList.getDependNode(0)

    if mobj.hasFn(om.MFn.kDagNode):
        return Node(om.MFnDagNode(mobj), mobj)
    else:
        return Node(om.MFnDependencyNode(mobj), mobj)


def decode(node):
    """Fastest conversion from DependencyNode to absolute path"""
    return node.path()


def createNode(type, name=None, parent=None):
    kwargs = {}
    fn = GlobalDependencyNode

    if name:
        kwargs["name"] = name

    if parent:
        kwargs["parent"] = parent._mobject
        fn = GlobalDagNode

    mobj = fn.create(type, **kwargs)

    if fn == GlobalDagNode or mobj.hasFn(om.MFn.kDagNode):
        return Node(om.MFnDagNode(mobj), mobj)
    else:
        return Node(om.MFnDependencyNode(mobj), mobj)


def getAttr(attr, type=None):
    return attr.read(type)


def setAttr(attr, value, type=None):
    attr.write(value, type)


def addAttr(node,
            longName,
            attributeType,
            shortName=None,
            enumName=None,
            defaultValue=None):

    if isinstance(attributeType, type):
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


def listRelatives(node, type=None, children=False, allDesdencents=False):
    result = list()

    # Only DAG nodes have relatives
    if not isinstance(node._fn, om.MFnDependencyNode):
        return result

    for child in node.children(type=type):
        result.append(child)

    return result


def connectAttr(plugA, plugB):
    plugA.connect(plugB)


def ls(type=om.MFn.kInvalid):
    nodes = list()

    it = om.MItDependencyNodes(type)
    while not it.isDone():
        mobj = it.thisNode()

        if mobj.hasFn(om.MFn.kDagNode):
            nodes.append(Node(om.MFnDagNode(mobj), mobj))
        else:
            nodes.append(Node(om.MFnDependencyNode(mobj), mobj))

        it.next()

    return nodes


# --------------------------------------------------------
#
# Attribute Types
#
# --------------------------------------------------------

class AbstractAttribute(dict):
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
        return super(AbstractAttribute, cls).__new__(cls, *args, **kwargs)

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


class Enum(AbstractAttribute):
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
    """Visual divider in channel box

    Example:

        Translate X  [ 0.0 ]
        Translate X  [ 0.0 ]
        Translate X  [ 0.0 ]
                     My Divider
        Custom Attr [ True ]

    """

    def __init__(self, label):
        super(Divider, self).__init__("_", fields=(label,), label=" ")


class String(AbstractAttribute):
    Fn = om.MFnTypedAttribute()
    Type = om.MFnData.kString
    Default = ""

    def default(self):
        default = super(String, self).default()
        return om.MFnStringData().create(default)

    def read(self, data):
        return data.inputValue(self["mobject"]).asString()


class Message(AbstractAttribute):
    Fn = om.MFnMessageAttribute()
    Type = None
    Default = None
    Storable = False


class Matrix(AbstractAttribute):
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


class Long(AbstractAttribute):
    Fn = om.MFnNumericAttribute()
    Type = om.MFnNumericData.kLong
    Default = 0

    def read(self, data):
        return data.inputValue(self["mobject"]).asLong()


class Double(AbstractAttribute):
    Fn = om.MFnNumericAttribute()
    Type = om.MFnNumericData.kDouble
    Default = 0.0

    def read(self, data):
        return data.inputValue(self["mobject"]).asDouble()


class Double3(AbstractAttribute):
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


# NOTE: Name clash, "Boolean" is a node type
class Bool(AbstractAttribute):
    Fn = om.MFnNumericAttribute()
    Type = om.MFnNumericData.kBoolean
    Default = True

    def read(self, data):
        return data.inputValue(self["mobject"]).asBool()


# --------------------------------------------------------
#
# Node Types
#
# --------------------------------------------------------


AISEnvFacade = om.MTypeId(0x52454656)
AboutToSetValueTestNode = om.MTypeId(0x4153564e)
AbsOverride = om.MTypeId(0x58000378)
AbsUniqueOverride = om.MTypeId(0x580003a0)
AddDoubleLinear = om.MTypeId(0x4441444c)
AddMatrix = om.MTypeId(0x44414d58)
AdskMaterial = om.MTypeId(0x4144534d)
AimConstraint = om.MTypeId(0x44414d43)
AirField = om.MTypeId(0x59414952)
AirManip = om.MTypeId(0x554d4958)
AlignCurve = om.MTypeId(0x4e414c43)
AlignManip = om.MTypeId(0x554d4144)
AlignSurface = om.MTypeId(0x4e414c53)
AmbientLight = om.MTypeId(0x414d424c)
AngleBetween = om.MTypeId(0x4e414254)
AngleDimension = om.MTypeId(0x4147444e)
AnimBlend = om.MTypeId(0x41424e44)
AnimBlendInOut = om.MTypeId(0x4142494f)
AnimBlendNodeAdditive = om.MTypeId(0x41424e41)
AnimBlendNodeAdditiveDA = om.MTypeId(0x41424141)
AnimBlendNodeAdditiveDL = om.MTypeId(0x4142414c)
AnimBlendNodeAdditiveF = om.MTypeId(0x41424146)
AnimBlendNodeAdditiveFA = om.MTypeId(0x41424641)
AnimBlendNodeAdditiveFL = om.MTypeId(0x4142464c)
AnimBlendNodeAdditiveI16 = om.MTypeId(0x41424153)
AnimBlendNodeAdditiveI32 = om.MTypeId(0x41424149)
AnimBlendNodeAdditiveRotation = om.MTypeId(0x41424e52)
AnimBlendNodeAdditiveScale = om.MTypeId(0x41424e53)
AnimBlendNodeBoolean = om.MTypeId(0x4142424f)
AnimBlendNodeEnum = om.MTypeId(0x41424e45)
AnimBlendNodeTime = om.MTypeId(0x41425449)
AnimClip = om.MTypeId(0x434c504e)
AnimCurveTA = om.MTypeId(0x50435441)
AnimCurveTL = om.MTypeId(0x5043544c)
AnimCurveTT = om.MTypeId(0x50435454)
AnimCurveTU = om.MTypeId(0x50435455)
AnimCurveUA = om.MTypeId(0x50435541)
AnimCurveUL = om.MTypeId(0x5043554c)
AnimCurveUT = om.MTypeId(0x50435554)
AnimCurveUU = om.MTypeId(0x50435555)
AnimLayer = om.MTypeId(0x414e4c52)
Anisotropic = om.MTypeId(0x52414e49)
AnnotationShape = om.MTypeId(0x414e4e53)
AovChildCollection = om.MTypeId(0x5800039c)
AovCollection = om.MTypeId(0x5800039b)
ApplyAbs2FloatsOverride = om.MTypeId(0x58000397)
ApplyAbs3FloatsOverride = om.MTypeId(0x58000381)
ApplyAbsBoolOverride = om.MTypeId(0x5800038a)
ApplyAbsEnumOverride = om.MTypeId(0x5800038c)
ApplyAbsFloatOverride = om.MTypeId(0x5800037d)
ApplyAbsIntOverride = om.MTypeId(0x58000391)
ApplyAbsStringOverride = om.MTypeId(0x58000393)
ApplyConnectionOverride = om.MTypeId(0x58000384)
ApplyRel2FloatsOverride = om.MTypeId(0x58000399)
ApplyRel3FloatsOverride = om.MTypeId(0x58000383)
ApplyRelFloatOverride = om.MTypeId(0x5800037f)
ApplyRelIntOverride = om.MTypeId(0x58000392)
ArcLengthDimension = om.MTypeId(0x41444d4e)
AreaLight = om.MTypeId(0x41524c54)
ArrayMapper = om.MTypeId(0x44414d50)
ArrowManip = om.MTypeId(0x554d4152)
ArubaTessellate = om.MTypeId(0x41544553)
AttachCurve = om.MTypeId(0x4e415443)
AttachSurface = om.MTypeId(0x4e415453)
AttrHierarchyTest = om.MTypeId(0x41544854)
Audio = om.MTypeId(0x41554449)
AvgCurves = om.MTypeId(0x4e414352)
AvgNurbsSurfacePoints = om.MTypeId(0x4e414e50)
AvgSurfacePoints = om.MTypeId(0x4e415350)
BallProjManip = om.MTypeId(0x554d4250)
BarnDoorManip = om.MTypeId(0x554d4c4e)
BaseLattice = om.MTypeId(0x46424153)
BasicSelector = om.MTypeId(0x58000375)
Bevel = om.MTypeId(0x4e42564c)
BevelPlus = om.MTypeId(0x4e425356)
BezierCurve = om.MTypeId(0x42435256)
BezierCurveToNurbs = om.MTypeId(0x42544e52)
BlendColorSets = om.MTypeId(0x50424353)
BlendColors = om.MTypeId(0x52424c32)
BlendDevice = om.MTypeId(0x424c4456)
BlendShape = om.MTypeId(0x46424c53)
BlendTwoAttr = om.MTypeId(0x41424c32)
BlendWeighted = om.MTypeId(0x41424c57)
BlindDataTemplate = om.MTypeId(0x424c4454)
Blinn = om.MTypeId(0x52424c4e)
BoneLattice = om.MTypeId(0x4642554c)
Boolean = om.MTypeId(0x4e424f4c)
Boundary = om.MTypeId(0x4e424e44)
Brownian = om.MTypeId(0x5246424d)
Brush = om.MTypeId(0x42525348)
Bulge = om.MTypeId(0x52544255)
Bump2d = om.MTypeId(0x5242554d)
Bump3d = om.MTypeId(0x52425533)
ButtonManip = om.MTypeId(0x55465054)
CacheBlend = om.MTypeId(0x4354524b)
CacheFile = om.MTypeId(0x43434846)
Camera = om.MTypeId(0x4443414d)
CameraManip = om.MTypeId(0x554d4958)
CameraPlaneManip = om.MTypeId(0x554d4350)
CameraSet = om.MTypeId(0x44525452)
CameraView = om.MTypeId(0x44434156)
CenterManip = om.MTypeId(0x434e4d50)
Character = om.MTypeId(0x43484152)
CharacterMap = om.MTypeId(0x434d4150)
CharacterOffset = om.MTypeId(0x584f4646)
Checker = om.MTypeId(0x52544348)
Choice = om.MTypeId(0x43484345)
Chooser = om.MTypeId(0x43484f4f)
CircleManip = om.MTypeId(0x554d434c)
CircleSweepManip = om.MTypeId(0x5543534d)
Clamp = om.MTypeId(0x52434c33)
ClipGhostShape = om.MTypeId(0x43475348)
ClipLibrary = om.MTypeId(0x434c4950)
ClipScheduler = om.MTypeId(0x43534348)
ClipToGhostData = om.MTypeId(0x43324744)
CloseCurve = om.MTypeId(0x4e434355)
CloseSurface = om.MTypeId(0x4e435355)
ClosestPointOnMesh = om.MTypeId(0x43504f4d)
ClosestPointOnSurface = om.MTypeId(0x4e435053)
Cloth = om.MTypeId(0x5254434c)
Cloud = om.MTypeId(0x52544344)
Cluster = om.MTypeId(0x46434c53)
ClusterFlexorShape = om.MTypeId(0x464a4346)
ClusterHandle = om.MTypeId(0x46434c48)
CoiManip = om.MTypeId(0x55465054)
Collection = om.MTypeId(0x58000373)
CollisionModel = om.MTypeId(0x59434f4c)
ColorManagementGlobals = om.MTypeId(0x434d4742)
ColorProfile = om.MTypeId(0x434f4c50)
CombinationShape = om.MTypeId(0x46434e53)
CompactPlugArrayTest = om.MTypeId(0x43504154)
ComponentManip = om.MTypeId(0x5554544d)
ConcentricProjManip = om.MTypeId(0x554d434f)
Condition = om.MTypeId(0x52434e44)
ConnectionOverride = om.MTypeId(0x58000385)
ConnectionUniqueOverride = om.MTypeId(0x580003a2)
Container = om.MTypeId(0x434f4e54)
ContainerBase = om.MTypeId(0x434f4241)
Contrast = om.MTypeId(0x52434f4e)
Controller = om.MTypeId(0x43475250)
CopyColorSet = om.MTypeId(0x43504353)
CopyUVSet = om.MTypeId(0x43505553)
CpManip = om.MTypeId(0x554d4350)
Crater = om.MTypeId(0x52533430)
CreaseSet = om.MTypeId(0x43524541)
CreateColorSet = om.MTypeId(0x43524353)
CreateUVSet = om.MTypeId(0x43525553)
CubicProjManip = om.MTypeId(0x554d4355)
CurveFromMeshCoM = om.MTypeId(0x4e434d43)
CurveFromMeshEdge = om.MTypeId(0x4e434d45)
CurveFromSubdivEdge = om.MTypeId(0x53435345)
CurveFromSubdivFace = om.MTypeId(0x53435346)
CurveFromSurfaceBnd = om.MTypeId(0x4e435342)
CurveFromSurfaceCoS = om.MTypeId(0x4e435343)
CurveFromSurfaceIso = om.MTypeId(0x4e435349)
CurveInfo = om.MTypeId(0x4e43494e)
CurveIntersect = om.MTypeId(0x4e434349)
CurveNormalizerAngle = om.MTypeId(0x434e5241)
CurveNormalizerLinear = om.MTypeId(0x434e524c)
CurveSegmentManip = om.MTypeId(0x554d5043)
CurveVarGroup = om.MTypeId(0x4e435647)
CylindricalProjManip = om.MTypeId(0x554d4359)
DagContainer = om.MTypeId(0x44414743)
DagPose = om.MTypeId(0x46504f53)
DataBlockTest = om.MTypeId(0x44425453)
DefaultLightList = om.MTypeId(0x4445464c)
DefaultRenderUtilityList = om.MTypeId(0x4452554c)
DefaultRenderingList = om.MTypeId(0x44524e4c)
DefaultShaderList = om.MTypeId(0x5244534c)
DefaultTextureList = om.MTypeId(0x5244544c)
DeformBend = om.MTypeId(0x46444244)
DeformFlare = om.MTypeId(0x4644464c)
DeformSine = om.MTypeId(0x4644534e)
DeformSquash = om.MTypeId(0x46445351)
DeformTwist = om.MTypeId(0x46445457)
DeformWave = om.MTypeId(0x46445756)
DeleteColorSet = om.MTypeId(0x444c4353)
DeleteComponent = om.MTypeId(0x44454354)
DeleteUVSet = om.MTypeId(0x444c4d53)
DeltaMush = om.MTypeId(0x444c544d)
DetachCurve = om.MTypeId(0x4e445443)
DetachSurface = om.MTypeId(0x4e445453)
DirectedDisc = om.MTypeId(0x44445343)
DirectionManip = om.MTypeId(0x55465054)
DirectionalLight = om.MTypeId(0x4449524c)
DiscManip = om.MTypeId(0x5544534d)
DiskCache = om.MTypeId(0x44534b43)
DisplacementShader = om.MTypeId(0x52445348)
DisplayLayer = om.MTypeId(0x4453504c)
DisplayLayerManager = om.MTypeId(0x44504c4d)
DistanceBetween = om.MTypeId(0x44444254)
DistanceDimShape = om.MTypeId(0x44444d4e)
DistanceManip = om.MTypeId(0x554d444d)
Dof = om.MTypeId(0x444f4644)
DofManip = om.MTypeId(0x554d4350)
DoubleShadingSwitch = om.MTypeId(0x53574832)
DpBirailSrf = om.MTypeId(0x4e444253)
DragField = om.MTypeId(0x59445247)
DropoffLocator = om.MTypeId(0x444c4354)
DynAttenuationManip = om.MTypeId(0x554d444d)
DynController = om.MTypeId(0x5943544c)
DynGlobals = om.MTypeId(0x5944474c)
DynHolder = om.MTypeId(0x59484c44)
DynSpreadManip = om.MTypeId(0x554d444d)
DynamicConstraint = om.MTypeId(0x44434f4e)
EditMetadata = om.MTypeId(0x454d5444)
EditsManager = om.MTypeId(0x454d4752)
EmitterManip = om.MTypeId(0x554d4958)
EnableManip = om.MTypeId(0x454e4d50)
EnvBall = om.MTypeId(0x5245424c)
EnvChrome = om.MTypeId(0x52454348)
EnvCube = om.MTypeId(0x52454342)
EnvFacade = om.MTypeId(0x52454643)
EnvFog = om.MTypeId(0x52454647)
EnvSky = om.MTypeId(0x5245534b)
EnvSphere = om.MTypeId(0x52455350)
EnvironmentFog = om.MTypeId(0x454e5646)
ExplodeNurbsShell = om.MTypeId(0x4e455348)
Expression = om.MTypeId(0x44455850)
ExtendCurve = om.MTypeId(0x4e455843)
ExtendSurface = om.MTypeId(0x4e455853)
Extrude = om.MTypeId(0x4e455852)
Facade = om.MTypeId(0x4446434e)
FfBlendSrf = om.MTypeId(0x4e424c54)
FfBlendSrfObsolete = om.MTypeId(0x4e424c53)
FfFilletSrf = om.MTypeId(0x4e464653)
Ffd = om.MTypeId(0x46464644)
FieldManip = om.MTypeId(0x554d4958)
FieldsManip = om.MTypeId(0x554d4958)
File = om.MTypeId(0x52544654)
FilletCurve = om.MTypeId(0x4e464352)
FitBspline = om.MTypeId(0x4e465443)
FlexorShape = om.MTypeId(0x464c5848)
Flow = om.MTypeId(0x464c4f57)
FluidEmitter = om.MTypeId(0x46454d49)
FluidShape = om.MTypeId(0x464c5549)
FluidSliceManip = om.MTypeId(0x46534c4d)
FluidTexture2D = om.MTypeId(0x464c5454)
FluidTexture3D = om.MTypeId(0x464c5458)
Follicle = om.MTypeId(0x48435256)
ForceUpdateManip = om.MTypeId(0x554d4655)
FosterParent = om.MTypeId(0x4650524e)
FourByFourMatrix = om.MTypeId(0x4642464d)
Fractal = om.MTypeId(0x52543246)
FrameCache = om.MTypeId(0x46434348)
FreePointManip = om.MTypeId(0x554d4650)
FreePointTriadManip = om.MTypeId(0x55465054)
GammaCorrect = om.MTypeId(0x5247414d)
GeoConnectable = om.MTypeId(0x5947434f)
GeoConnector = om.MTypeId(0x59474354)
GeomBind = om.MTypeId(0x4742494e)
GeometryConstraint = om.MTypeId(0x44474e43)
GeometryFilter = om.MTypeId(0x44474649)
GeometryOnLineManip = om.MTypeId(0x554d474c)
GeometryVarGroup = om.MTypeId(0x4e475647)
GlobalCacheControl = om.MTypeId(0x4743434c)
GlobalStitch = om.MTypeId(0x4e475354)
Granite = om.MTypeId(0x52544752)
GravityField = om.MTypeId(0x59475241)
GreasePencilSequence = om.MTypeId(0x47505351)
GreasePlane = om.MTypeId(0x4447504c)
GreasePlaneRenderShape = om.MTypeId(0x47505253)
Grid = om.MTypeId(0x52544744)
GroupId = om.MTypeId(0x47504944)
GroupParts = om.MTypeId(0x47525050)
Guide = om.MTypeId(0x46475549)
HairConstraint = om.MTypeId(0x4850494e)
HairSystem = om.MTypeId(0x48535953)
HairTubeShader = om.MTypeId(0x52485442)
HardenPoint = om.MTypeId(0x4e484450)
HardwareRenderGlobals = om.MTypeId(0x48575247)
HardwareRenderingGlobals = om.MTypeId(0x48525247)
HeightField = om.MTypeId(0x4f435050)
HierarchyTestNode1 = om.MTypeId(0x48544e31)
HierarchyTestNode2 = om.MTypeId(0x48544e32)
HierarchyTestNode3 = om.MTypeId(0x48544e33)
HikEffector = om.MTypeId(0x4446494b)
HikFKJoint = om.MTypeId(0x4a54494b)
HikFloorContactMarker = om.MTypeId(0x4846434d)
HikGroundPlane = om.MTypeId(0x48474e44)
HikHandle = om.MTypeId(0x4b484948)
HikIKEffector = om.MTypeId(0x494b4546)
HikSolver = om.MTypeId(0x4b48494b)
HistorySwitch = om.MTypeId(0x48495353)
HoldMatrix = om.MTypeId(0x4450484d)
HsvToRgb = om.MTypeId(0x52483252)
HwReflectionMap = om.MTypeId(0x4857524d)
HwRenderGlobals = om.MTypeId(0x59485244)
HyperGraphInfo = om.MTypeId(0x48595052)
HyperLayout = om.MTypeId(0x4859504c)
HyperView = om.MTypeId(0x44485056)
IkEffector = om.MTypeId(0x4b454646)
IkHandle = om.MTypeId(0x4b48444c)
IkMCsolver = om.MTypeId(0x4b4d4353)
IkPASolver = om.MTypeId(0x4b504153)
IkRPsolver = om.MTypeId(0x4b525053)
IkSCsolver = om.MTypeId(0x4b534353)
IkSplineSolver = om.MTypeId(0x4b535053)
IkSystem = om.MTypeId(0x4b535953)
ImagePlane = om.MTypeId(0x4449504c)
ImplicitBox = om.MTypeId(0x46494258)
ImplicitCone = om.MTypeId(0x4649434f)
ImplicitSphere = om.MTypeId(0x46495350)
IndexManip = om.MTypeId(0x554d4958)
InsertKnotCurve = om.MTypeId(0x4e494b43)
InsertKnotSurface = om.MTypeId(0x4e494b53)
Instancer = om.MTypeId(0x594e5354)
IntersectSurface = om.MTypeId(0x4e495346)
Jiggle = om.MTypeId(0x4a474446)
Joint = om.MTypeId(0x4a4f494e)
JointCluster = om.MTypeId(0x464a434c)
JointFfd = om.MTypeId(0x46464442)
JointLattice = om.MTypeId(0x4642454c)
KeyframeRegionManip = om.MTypeId(0x4b46524d)
KeyingGroup = om.MTypeId(0x4b475250)
Lambert = om.MTypeId(0x524c414d)
Lattice = om.MTypeId(0x464c4154)
LayeredShader = om.MTypeId(0x4c595253)
LayeredTexture = om.MTypeId(0x4c595254)
LeastSquaresModifier = om.MTypeId(0x4e4c534d)
Leather = om.MTypeId(0x52544c45)
LightEditor = om.MTypeId(0x580003e3)
LightFog = om.MTypeId(0x52464f47)
LightGroup = om.MTypeId(0x580003e2)
LightInfo = om.MTypeId(0x524c494e)
LightItem = om.MTypeId(0x580003e1)
LightLinker = om.MTypeId(0x524c4c4b)
LightList = om.MTypeId(0x4c4c5354)
LightManip = om.MTypeId(0x554d4958)
LightsChildCollection = om.MTypeId(0x5800039a)
LightsCollection = om.MTypeId(0x58000394)
LightsCollectionSelector = om.MTypeId(0x580003a4)
LimitManip = om.MTypeId(0x4c544d50)
LineManip = om.MTypeId(0x554d4c4e)
LineModifier = om.MTypeId(0x4c4d4f44)
Locator = om.MTypeId(0x4c4f4354)
LodGroup = om.MTypeId(0x4c4f4447)
LodThresholds = om.MTypeId(0x4c4f4454)
Loft = om.MTypeId(0x4e534b4e)
LookAt = om.MTypeId(0x444c4154)
Luminance = om.MTypeId(0x524c554d)
MakeGroup = om.MTypeId(0x504d4752)
MakeIllustratorCurves = om.MTypeId(0x4e4d4943)
MakeNurbCircle = om.MTypeId(0x4e435243)
MakeNurbCone = om.MTypeId(0x4e434e45)
MakeNurbCube = om.MTypeId(0x4e435542)
MakeNurbCylinder = om.MTypeId(0x4e43594c)
MakeNurbPlane = om.MTypeId(0x4e504c4e)
MakeNurbSphere = om.MTypeId(0x4e535048)
MakeNurbTorus = om.MTypeId(0x4e544f52)
MakeNurbsSquare = om.MTypeId(0x4e535152)
MakeTextCurves = om.MTypeId(0x4e545843)
MakeThreePointCircularArc = om.MTypeId(0x4e334341)
MakeTwoPointCircularArc = om.MTypeId(0x4e324341)
Mandelbrot = om.MTypeId(0x52544d41)
Mandelbrot3D = om.MTypeId(0x52544d33)
Manip2DContainer = om.MTypeId(0x554d3243)
ManipContainer = om.MTypeId(0x554d4343)
Marble = om.MTypeId(0x52544d52)
MarkerManip = om.MTypeId(0x554d4d41)
MaterialFacade = om.MTypeId(0x524d4643)
MaterialInfo = om.MTypeId(0x444d5449)
MaterialOverride = om.MTypeId(0x58000387)
Membrane = om.MTypeId(0x4d454d42)
Mesh = om.MTypeId(0x444d5348)
MeshVarGroup = om.MTypeId(0x4e4d5647)
MotionPath = om.MTypeId(0x4d505448)
MotionPathManip = om.MTypeId(0x554d4d41)
MotionTrail = om.MTypeId(0x4d4f5452)
MotionTrailShape = om.MTypeId(0x4d4f5348)
Mountain = om.MTypeId(0x52544d54)
MoveVertexManip = om.MTypeId(0x554d4650)
Movie = om.MTypeId(0x52544d56)
MpBirailSrf = om.MTypeId(0x4e4d4253)
MultDoubleLinear = om.MTypeId(0x444d444c)
MultMatrix = om.MTypeId(0x444d544d)
MultilisterLight = om.MTypeId(0x4d554c4c)
MultiplyDivide = om.MTypeId(0x524d4449)
Mute = om.MTypeId(0x4d555445)
NCloth = om.MTypeId(0x4e434c4f)
NComponent = om.MTypeId(0x4e434d50)
NParticle = om.MTypeId(0x4e504152)
NRigid = om.MTypeId(0x4e524744)
NearestPointOnCurve = om.MTypeId(0x4e504f43)
Network = om.MTypeId(0x4e54574b)
NewtonField = om.MTypeId(0x594e4557)
NewtonManip = om.MTypeId(0x554d4958)
Noise = om.MTypeId(0x52544e33)
NonLinear = om.MTypeId(0x464e4c44)
NormalConstraint = om.MTypeId(0x444e4332)
Nucleus = om.MTypeId(0x4e535953)
NurbsCurve = om.MTypeId(0x4e435256)
NurbsCurveToBezier = om.MTypeId(0x4e525442)
NurbsSurface = om.MTypeId(0x4e535246)
NurbsTessellate = om.MTypeId(0x4e544553)
NurbsToSubdiv = om.MTypeId(0x534e5453)
NurbsToSubdivProc = om.MTypeId(0x534e5450)
ObjectAttrFilter = om.MTypeId(0x4f464154)
ObjectBinFilter = om.MTypeId(0x4f4b464c)
ObjectFilter = om.MTypeId(0x4f464c54)
ObjectMultiFilter = om.MTypeId(0x4f4d464c)
ObjectNameFilter = om.MTypeId(0x4f4e464c)
ObjectRenderFilter = om.MTypeId(0x4f52464c)
ObjectScriptFilter = om.MTypeId(0x4f53464c)
ObjectSet = om.MTypeId(0x4f425354)
ObjectTypeFilter = om.MTypeId(0x4f54464c)
Ocean = om.MTypeId(0x52544f43)
OceanShader = om.MTypeId(0x524f5053)
OffsetCos = om.MTypeId(0x4e4f4353)
OffsetCurve = om.MTypeId(0x4e4f4355)
OffsetSurface = om.MTypeId(0x4e4f5355)
OldBlindDataBase = om.MTypeId(0x42444454)
OldGeometryConstraint = om.MTypeId(0x44474d43)
OldNormalConstraint = om.MTypeId(0x444e5243)
OldTangentConstraint = om.MTypeId(0x44544e43)
OpticalFX = om.MTypeId(0x4f504658)
OrientConstraint = om.MTypeId(0x444f5243)
OrientationMarker = om.MTypeId(0x4f52544d)
PairBlend = om.MTypeId(0x4150424c)
ParamDimension = om.MTypeId(0x52444d4e)
ParentConstraint = om.MTypeId(0x44504152)
Particle = om.MTypeId(0x59504152)
ParticleAgeMapper = om.MTypeId(0x50414d41)
ParticleCloud = om.MTypeId(0x50434c44)
ParticleColorMapper = om.MTypeId(0x50434d41)
ParticleIncandMapper = om.MTypeId(0x50494d41)
ParticleSamplerInfo = om.MTypeId(0x5053494e)
ParticleTranspMapper = om.MTypeId(0x50544d41)
Partition = om.MTypeId(0x5052544e)
PassContributionMap = om.MTypeId(0x5053434d)
PassMatrix = om.MTypeId(0x4450534d)
PfxHair = om.MTypeId(0x50464841)
PfxToon = om.MTypeId(0x5046544f)
Phong = om.MTypeId(0x5250484f)
PhongE = om.MTypeId(0x52504845)
PivotAndOrientManip = om.MTypeId(0x50414f4d)
Place2dTexture = om.MTypeId(0x52504c32)
Place3dTexture = om.MTypeId(0x52504c44)
PlanarProjManip = om.MTypeId(0x554d5050)
PlanarTrimSurface = om.MTypeId(0x4e504c54)
PlusMinusAverage = om.MTypeId(0x52504d41)
PointConstraint = om.MTypeId(0x44505443)
PointEmitter = om.MTypeId(0x59454d49)
PointLight = om.MTypeId(0x504f4954)
PointMatrixMult = om.MTypeId(0x44504d4d)
PointOnCurveInfo = om.MTypeId(0x4e504349)
PointOnCurveManip = om.MTypeId(0x554d5043)
PointOnLineManip = om.MTypeId(0x554d504c)
PointOnPolyConstraint = om.MTypeId(0x44505043)
PointOnSurfManip = om.MTypeId(0x554d5353)
PointOnSurfaceInfo = om.MTypeId(0x4e505349)
PointOnSurfaceManip = om.MTypeId(0x554d5053)
PoleVectorConstraint = om.MTypeId(0x44505643)
PolyAppend = om.MTypeId(0x50415050)
PolyAppendVertex = om.MTypeId(0x50415056)
PolyAutoProj = om.MTypeId(0x50415550)
PolyAverageVertex = om.MTypeId(0x50415656)
PolyBevel = om.MTypeId(0x5042564c)
PolyBevel2 = om.MTypeId(0x50425632)
PolyBevel3 = om.MTypeId(0x50425633)
PolyBlindData = om.MTypeId(0x4d424454)
PolyBoolOp = om.MTypeId(0x50424f50)
PolyBridgeEdge = om.MTypeId(0x50425245)
PolyCBoolOp = om.MTypeId(0x50435642)
PolyChipOff = om.MTypeId(0x50434849)
PolyCircularize = om.MTypeId(0x50435243)
PolyClean = om.MTypeId(0x504c434c)
PolyCloseBorder = om.MTypeId(0x50434c4f)
PolyCollapseEdge = om.MTypeId(0x50434f45)
PolyCollapseF = om.MTypeId(0x50434f46)
PolyColorDel = om.MTypeId(0x5043444c)
PolyColorMod = om.MTypeId(0x50434d4f)
PolyColorPerVertex = om.MTypeId(0x50435056)
PolyCone = om.MTypeId(0x50434f4e)
PolyConnectComponents = om.MTypeId(0x50434353)
PolyContourProj = om.MTypeId(0x50434e50)
PolyCopyUV = om.MTypeId(0x50435556)
PolyCrease = om.MTypeId(0x50435253)
PolyCreaseEdge = om.MTypeId(0x50435345)
PolyCreateFace = om.MTypeId(0x50435245)
PolyCube = om.MTypeId(0x50435542)
PolyCut = om.MTypeId(0x50504354)
PolyCylProj = om.MTypeId(0x50435950)
PolyCylinder = om.MTypeId(0x5043594c)
PolyDelEdge = om.MTypeId(0x50444545)
PolyDelFacet = om.MTypeId(0x50444546)
PolyDelVertex = om.MTypeId(0x50444556)
PolyDuplicateEdge = om.MTypeId(0x50445545)
PolyEdgeToCurve = om.MTypeId(0x50544356)
PolyEditEdgeFlow = om.MTypeId(0x50534546)
PolyExtrudeEdge = om.MTypeId(0x50455845)
PolyExtrudeFace = om.MTypeId(0x50455846)
PolyExtrudeVertex = om.MTypeId(0x50455856)
PolyFlipEdge = om.MTypeId(0x50464c45)
PolyFlipUV = om.MTypeId(0x50465556)
PolyHelix = om.MTypeId(0x48454c49)
PolyHoleFace = om.MTypeId(0x50484645)
PolyLayoutUV = om.MTypeId(0x504c5556)
PolyMapCut = om.MTypeId(0x504d4143)
PolyMapDel = om.MTypeId(0x504d4144)
PolyMapSew = om.MTypeId(0x504d4153)
PolyMapSewMove = om.MTypeId(0x5053454d)
PolyMergeEdge = om.MTypeId(0x504d4545)
PolyMergeFace = om.MTypeId(0x504d4546)
PolyMergeUV = om.MTypeId(0x504d4755)
PolyMergeVert = om.MTypeId(0x504d5645)
PolyMirror = om.MTypeId(0x504d4952)
PolyMoveEdge = om.MTypeId(0x504d4f45)
PolyMoveFace = om.MTypeId(0x504d4f46)
PolyMoveFacetUV = om.MTypeId(0x504d4655)
PolyMoveUV = om.MTypeId(0x504d5556)
PolyMoveVertex = om.MTypeId(0x504d4f56)
PolyNormal = om.MTypeId(0x504e4f52)
PolyNormalPerVertex = om.MTypeId(0x504e5056)
PolyNormalizeUV = om.MTypeId(0x504e5556)
PolyOptUvs = om.MTypeId(0x504f5556)
PolyPassThru = om.MTypeId(0x50595054)
PolyPinUV = om.MTypeId(0x50505556)
PolyPipe = om.MTypeId(0x50504950)
PolyPlanarProj = om.MTypeId(0x50504c50)
PolyPlane = om.MTypeId(0x504d4553)
PolyPlatonicSolid = om.MTypeId(0x534f4c49)
PolyPoke = om.MTypeId(0x5050504b)
PolyPrimitiveMisc = om.MTypeId(0x4d495343)
PolyPrism = om.MTypeId(0x50505249)
PolyProj = om.MTypeId(0x5050524f)
PolyProjectCurve = om.MTypeId(0x50504356)
PolyPyramid = om.MTypeId(0x50505952)
PolyQuad = om.MTypeId(0x50515541)
PolyReduce = om.MTypeId(0x50524544)
PolyRemesh = om.MTypeId(0x50524d48)
PolyRetopo = om.MTypeId(0x5052464d)
PolySeparate = om.MTypeId(0x50534550)
PolySewEdge = om.MTypeId(0x50535745)
PolySmooth = om.MTypeId(0x50534d54)
PolySmoothFace = om.MTypeId(0x50534d46)
PolySmoothProxy = om.MTypeId(0x50534d50)
PolySoftEdge = om.MTypeId(0x50534f45)
PolySphProj = om.MTypeId(0x50535050)
PolySphere = om.MTypeId(0x50535048)
PolySpinEdge = om.MTypeId(0x50535051)
PolySplit = om.MTypeId(0x5053504c)
PolySplitEdge = om.MTypeId(0x50534544)
PolySplitRing = om.MTypeId(0x50535052)
PolySplitVert = om.MTypeId(0x50535645)
PolyStraightenUVBorder = om.MTypeId(0x50535442)
PolySubdEdge = om.MTypeId(0x50535545)
PolySubdFace = om.MTypeId(0x50535546)
PolyToSubdiv = om.MTypeId(0x50534453)
PolyTorus = om.MTypeId(0x50544f52)
PolyTransfer = om.MTypeId(0x50544652)
PolyTriangulate = om.MTypeId(0x50545249)
PolyTweak = om.MTypeId(0x5054574b)
PolyTweakUV = om.MTypeId(0x50545556)
PolyUVRectangle = om.MTypeId(0x50555652)
PolyUnite = om.MTypeId(0x50554e49)
PolyWedgeFace = om.MTypeId(0x50574643)
PoseInterpolatorManager = om.MTypeId(0x5053444d)
PositionMarker = om.MTypeId(0x504f534d)
PostProcessList = om.MTypeId(0x50505354)
ProjectCurve = om.MTypeId(0x4e504352)
ProjectTangent = om.MTypeId(0x4e50544e)
Projection = om.MTypeId(0x5250524a)
ProjectionManip = om.MTypeId(0x554d4354)
PropModManip = om.MTypeId(0x554d4354)
PropMoveTriadManip = om.MTypeId(0x554d5054)
ProxyManager = om.MTypeId(0x50584d47)
PsdFileTex = om.MTypeId(0x50534454)
QuadPtOnLineManip = om.MTypeId(0x554d504c)
QuadShadingSwitch = om.MTypeId(0x53574834)
RadialField = om.MTypeId(0x59524144)
Ramp = om.MTypeId(0x52545241)
RampShader = om.MTypeId(0x52525053)
RbfSrf = om.MTypeId(0x4e524246)
RebuildCurve = om.MTypeId(0x4e524243)
RebuildSurface = om.MTypeId(0x4e524253)
Record = om.MTypeId(0x52454344)
Reference = om.MTypeId(0x5245464e)
RelOverride = om.MTypeId(0x5800037a)
RelUniqueOverride = om.MTypeId(0x580003a1)
RemapColor = om.MTypeId(0x524d434c)
RemapHsv = om.MTypeId(0x524d4853)
RemapValue = om.MTypeId(0x524d564c)
RenderBox = om.MTypeId(0x524e4258)
RenderCone = om.MTypeId(0x524e434f)
RenderGlobals = om.MTypeId(0x52474c42)
RenderGlobalsList = om.MTypeId(0x5244474c)
RenderLayer = om.MTypeId(0x524e444c)
RenderLayerManager = om.MTypeId(0x524e4c4d)
RenderPass = om.MTypeId(0x524e5053)
RenderPassSet = om.MTypeId(0x52505353)
RenderQuality = om.MTypeId(0x52515541)
RenderRect = om.MTypeId(0x52524354)
RenderSettingsChildCollection = om.MTypeId(0x580003a3)
RenderSettingsCollection = om.MTypeId(0x58000395)
RenderSetup = om.MTypeId(0x58000371)
RenderSetupLayer = om.MTypeId(0x58000372)
RenderSphere = om.MTypeId(0x524e5350)
RenderTarget = om.MTypeId(0x524e5447)
RenderedImageSource = om.MTypeId(0x52434953)
ReorderUVSet = om.MTypeId(0x524f5553)
Resolution = om.MTypeId(0x524c544e)
ResultCurveTimeToAngular = om.MTypeId(0x52435441)
ResultCurveTimeToLinear = om.MTypeId(0x5243544c)
ResultCurveTimeToTime = om.MTypeId(0x52435454)
ResultCurveTimeToUnitless = om.MTypeId(0x52435455)
Reverse = om.MTypeId(0x52525653)
ReverseCurve = om.MTypeId(0x4e525643)
ReverseSurface = om.MTypeId(0x4e525653)
Revolve = om.MTypeId(0x4e52564c)
RgbToHsv = om.MTypeId(0x52523248)
RigidBody = om.MTypeId(0x59524744)
RigidConstraint = om.MTypeId(0x59435354)
RigidSolver = om.MTypeId(0x59534c56)
Rock = om.MTypeId(0x5254524b)
RotateLimitsManip = om.MTypeId(0x554d524c)
RotateManip = om.MTypeId(0x554d5241)
RotateUV2dManip = om.MTypeId(0x5532524f)
RoundConstantRadius = om.MTypeId(0x4e524352)
Sampler = om.MTypeId(0x46534d50)
SamplerInfo = om.MTypeId(0x5253494e)
ScaleConstraint = om.MTypeId(0x44534343)
ScaleLimitsManip = om.MTypeId(0x4c544d50)
ScaleManip = om.MTypeId(0x554d4650)
ScaleUV2dManip = om.MTypeId(0x55325343)
ScreenAlignedCircleManip = om.MTypeId(0x5341434d)
Script = om.MTypeId(0x53435250)
ScriptManip = om.MTypeId(0x554d5343)
Sculpt = om.MTypeId(0x46534350)
SelectionListOperator = om.MTypeId(0x534c4f50)
SequenceManager = om.MTypeId(0x53514d47)
Sequencer = om.MTypeId(0x53514e43)
SetRange = om.MTypeId(0x52524e47)
ShaderGlow = om.MTypeId(0x5348474c)
ShaderOverride = om.MTypeId(0x58000386)
ShadingEngine = om.MTypeId(0x53484144)
ShadingMap = om.MTypeId(0x53444d50)
ShapeEditorManager = om.MTypeId(0x53444d4c)
ShellTessellate = om.MTypeId(0x53544553)
Shot = om.MTypeId(0x53484f54)
ShrinkWrap = om.MTypeId(0x53575250)
SimpleSelector = om.MTypeId(0x5800039e)
SimpleTestNode = om.MTypeId(0x53544e44)
SimpleVolumeShader = om.MTypeId(0x53565348)
SingleShadingSwitch = om.MTypeId(0x53574831)
SketchPlane = om.MTypeId(0x534b504e)
SkinBinding = om.MTypeId(0x534b4244)
SkinCluster = om.MTypeId(0x4653434c)
SmoothCurve = om.MTypeId(0x4e534d43)
SmoothTangentSrf = om.MTypeId(0x4e53544e)
SnapUV2dManip = om.MTypeId(0x5532534e)
Snapshot = om.MTypeId(0x534e5054)
SnapshotShape = om.MTypeId(0x53534841)
Snow = om.MTypeId(0x5254534e)
SoftMod = om.MTypeId(0x4653534c)
SoftModHandle = om.MTypeId(0x46535348)
SolidFractal = om.MTypeId(0x52544633)
SpBirailSrf = om.MTypeId(0x4e534253)
SphericalProjManip = om.MTypeId(0x554d5350)
SpotCylinderManip = om.MTypeId(0x53434d50)
SpotLight = om.MTypeId(0x5350544c)
SpotManip = om.MTypeId(0x554d4958)
Spring = om.MTypeId(0x59535052)
SquareSrf = om.MTypeId(0x4e535153)
Stencil = om.MTypeId(0x52545354)
StereoRigCamera = om.MTypeId(0x53524341)
StitchAsNurbsShell = om.MTypeId(0x4e535348)
StitchSrf = om.MTypeId(0x4e535453)
Stroke = om.MTypeId(0x5354524b)
StrokeGlobals = om.MTypeId(0x53544b47)
Stucco = om.MTypeId(0x52533630)
StyleCurve = om.MTypeId(0x4e535443)
SubCurve = om.MTypeId(0x4e534243)
SubSurface = om.MTypeId(0x4e535352)
SubdAddTopology = om.MTypeId(0x53415459)
SubdAutoProj = om.MTypeId(0x53415550)
SubdBlindData = om.MTypeId(0x53424454)
SubdCleanTopology = om.MTypeId(0x53435459)
SubdHierBlind = om.MTypeId(0x53485242)
SubdLayoutUV = om.MTypeId(0x534c5556)
SubdMapCut = om.MTypeId(0x534d4143)
SubdMapSewMove = om.MTypeId(0x5353454d)
SubdPlanarProj = om.MTypeId(0x53504c50)
SubdTweak = om.MTypeId(0x5354574b)
SubdTweakUV = om.MTypeId(0x53545556)
Subdiv = om.MTypeId(0x53445353)
SubdivCollapse = om.MTypeId(0x53434c50)
SubdivComponentId = om.MTypeId(0x53534944)
SubdivReverseFaces = om.MTypeId(0x53525646)
SubdivSurfaceVarGroup = om.MTypeId(0x53535647)
SubdivToNurbs = om.MTypeId(0x5344534e)
SubdivToPoly = om.MTypeId(0x53445350)
SurfaceInfo = om.MTypeId(0x4e53494e)
SurfaceLuminance = om.MTypeId(0x52534c55)
SurfaceShader = om.MTypeId(0x52535348)
SurfaceVarGroup = om.MTypeId(0x4e535647)
SymmetryConstraint = om.MTypeId(0x44534d43)
TangentConstraint = om.MTypeId(0x44544332)
Tension = om.MTypeId(0x54454e53)
TextButtonManip = om.MTypeId(0x554d5442)
Texture3dManip = om.MTypeId(0x554d5458)
TextureBakeSet = om.MTypeId(0x5442414b)
TextureDeformer = om.MTypeId(0x54584446)
TextureDeformerHandle = om.MTypeId(0x54444844)
TextureToGeom = om.MTypeId(0x5454474f)
Time = om.MTypeId(0x54494d45)
TimeEditor = om.MTypeId(0x544d4544)
TimeEditorAnimSource = om.MTypeId(0x54454153)
TimeEditorClip = om.MTypeId(0x41434c43)
TimeEditorClipBase = om.MTypeId(0x414c434c)
TimeEditorClipEvaluator = om.MTypeId(0x4143524f)
TimeEditorInterpolator = om.MTypeId(0x54454950)
TimeEditorTracks = om.MTypeId(0x5445544b)
TimeFunction = om.MTypeId(0x7466786e)
TimeToUnitConversion = om.MTypeId(0x44544d55)
TimeWarp = om.MTypeId(0x54495741)
ToggleManip = om.MTypeId(0x554d5447)
ToggleOnLineManip = om.MTypeId(0x55544f4c)
ToolDrawManip = om.MTypeId(0x5454444d)
ToolDrawManip2D = om.MTypeId(0x54444d32)
ToonLineAttributes = om.MTypeId(0x544c4154)
TrackInfoManager = om.MTypeId(0x54494d47)
TransUV2dManip = om.MTypeId(0x55325452)
TransferAttributes = om.MTypeId(0x54524154)
Transform = om.MTypeId(0x5846524d)
TransformGeometry = om.MTypeId(0x5447454f)
TranslateLimitsManip = om.MTypeId(0x434e4d50)
TranslateManip = om.MTypeId(0x554d4650)
TranslateUVManip = om.MTypeId(0x554d5556)
Trim = om.MTypeId(0x4e54524d)
TrimWithBoundaries = om.MTypeId(0x4e545742)
TriplanarProjManip = om.MTypeId(0x554d5452)
TripleShadingSwitch = om.MTypeId(0x53574833)
TrsInsertManip = om.MTypeId(0x554d4354)
TrsManip = om.MTypeId(0x5554544d)
TurbulenceField = om.MTypeId(0x59545552)
TurbulenceManip = om.MTypeId(0x554d4958)
Tweak = om.MTypeId(0x464d5054)
UniformField = om.MTypeId(0x59554e49)
UnitConversion = om.MTypeId(0x44554e54)
UnitToTimeConversion = om.MTypeId(0x4455544d)
Unknown = om.MTypeId(0x554e4b4e)
UnknownDag = om.MTypeId(0x554e4b44)
UnknownTransform = om.MTypeId(0x554e4b54)
Untrim = om.MTypeId(0x4e555452)
UseBackground = om.MTypeId(0x55534247)
Uv2dManip = om.MTypeId(0x5556324d)
UvChooser = om.MTypeId(0x55564348)
VectorProduct = om.MTypeId(0x52564543)
VertexBakeSet = om.MTypeId(0x5642414b)
ViewColorManager = om.MTypeId(0x5657434d)
VolumeAxisField = om.MTypeId(0x59565846)
VolumeFog = om.MTypeId(0x52564647)
VolumeLight = om.MTypeId(0x564f4c4c)
VolumeNoise = om.MTypeId(0x52545633)
VolumeShader = om.MTypeId(0x52565348)
VortexField = om.MTypeId(0x59564f52)
Water = om.MTypeId(0x52545741)
WeightGeometryFilter = om.MTypeId(0x44574746)
Wire = om.MTypeId(0x46574952)
Wood = om.MTypeId(0x52545744)
Wrap = om.MTypeId(0x46575250)
WtAddMatrix = om.MTypeId(0x4457414d)
