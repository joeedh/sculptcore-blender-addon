bpy_struct
==========

.. currentmodule:: bpy.types


.. class:: bpy_struct

   built-in base class for all classes in bpy.types.

   .. method:: as_pointer()
   
      Returns the memory address which holds a pointer to Blender's internal data
   
      :return: int (memory address).
      :rtype: int
   
      .. note:: This is intended only for advanced script writers who need to
         pass blender data to their own C/Python modules.


   .. method:: curve_mapping_cache_key()
   
      Return a validated, immutable (runtime record identity, definition revision) key.
      Only owned CurveMapping instances support this method. Call it before cache reuse.
      Presentation/no-op edits preserve the key; committed definition edits advance it.
      Keys are process-local and must not be saved or used after an access error.
      New records after copy/load/unset have new identities; re-registration may reuse a record.
   
      :return: Two exact unsigned integer values.
      :rtype: tuple[int, int]


   .. method:: curve_mapping_initialize(property, *, preset='LINEAR')
   
      Initialize an owned scalar curve, staging absent pointer ancestors atomically.
      Existing definitions are returned unchanged. Reading an unset property returns None.
   
      :param property: Declared property path; collections require existing numeric indices.
      :type property: str
      :param preset: Initial preset; currently LINEAR only.
      :type preset: str
      :return: The owned curve.
      :rtype: :class:`CurveMapping`


   .. method:: curve_mapping_sync(property, /)
   
      Validate and publish raw owned-definition edits. Invalid data remains untouched.
      Changed definitions notify their owner and callback; unchanged sync does neither.
   
      :param property: Declared owned-curve path with existing numeric collection indices.
      :type property: str


   .. method:: driver_add(path, index=-1, /)
   
      Adds driver(s) to the given property
   
      :param path: path to the property to drive, analogous to the fcurve's data path.
      :type path: str
      :param index: array index of the property drive. Defaults to -1 for all indices or a single channel if the property is not an array.
      :type index: int
      :return: The driver added or a list of drivers when index is -1.
      :rtype: :class:`bpy.types.FCurve` | list[:class:`bpy.types.FCurve`]


   .. method:: driver_remove(path, index=-1, /)
   
      Remove driver(s) from the given property
   
      :param path: path to the property to drive, analogous to the fcurve's data path.
      :type path: str
      :param index: array index of the property drive. Defaults to -1 for all indices or a single channel if the property is not an array.
      :type index: int
      :return: Success of driver removal.
      :rtype: bool


   .. method:: get(key, default=None, /)
   
      Returns the value of the custom property assigned to key or default
      when not found (matches Python's dictionary function of the same name).
   
      :param key: The key associated with the custom property.
      :type key: str
      :param default: Optional argument for the value to return if
         *key* is not found.
      :type default: Any
      :return: Custom property value or default.
      :rtype: Any
   
      .. note::
   
         Limited to: :ref:`bpy_types-custom_properties`.


   .. method:: id_properties_clear()
   
      Remove the parent group for an RNA struct's custom IDProperties.


   .. method:: id_properties_ensure()
   
      :return: the parent group for an RNA struct's custom IDProperties.
      :rtype: :class:`idprop.types.IDPropertyGroup`


   .. method:: id_properties_ui(key, /)
   
      :param key: String name of the property.
      :type key: str
      :return: An object used to manage an IDProperty's UI data.
      :rtype: :class:`bpy.types.IDPropertyUIManager`


   .. method:: is_property_hidden(property, /)
   
      Check if a property is hidden.
   
      :param property: Property name.
      :type property: str
      :return: True when the property is hidden.
      :rtype: bool


   .. method:: is_property_overridable_library(property, /)
   
      Check if a property is overridable.
   
      :param property: Property name.
      :type property: str
      :return: True when the property is overridable.
      :rtype: bool


   .. method:: is_property_readonly(property, /)
   
      Check if a property is readonly.
   
      :param property: Property name.
      :type property: str
      :return: True when the property is readonly (not writable).
      :rtype: bool


   .. method:: is_property_set(property, /, *, ghost=True)
   
      Check if a property is set, use for testing operator properties.
   
      :param property: Property name.
      :type property: str
      :param ghost: Used for operators that re-run with previous settings.
         In this case the property is not marked as set,
         yet the value from the previous execution is used.
   
         In rare cases you may want to set this option to false.
   
      :type ghost: bool
      :return: True when the property has been set.
      :rtype: bool


      .. note::

         Properties defined at run-time store the values of the properties as custom-properties.

         This method checks if the underlying data exists, causing the property to be considered *set*.

         A common pattern for operators is to calculate a value for the properties
         that have not had their values explicitly set by the caller
         (where the caller could be a key-binding, menu-items or Python script for example).

         In the case of executing operators multiple times, values are re-used from the previous execution.

         For example: subdividing a mesh with a smooth value of 1.0 will keep using
         that value on subsequent calls to subdivision, unless the operator is called with
         that property set to a different value.

         This behavior can be disabled using the ``SKIP_SAVE`` option when the property is declared (see: :mod:`bpy.props`).

         The ``ghost`` argument allows detecting how a value from a previous execution is handled.

         - When true: The property is considered unset even if the value from a previous call is used.
         - When false: The existence of any values causes ``is_property_set`` to return true.

         While this argument should typically be omitted, there are times when
         it's important to know if a value is anything besides the default.

         For example, the previous value may have been scaled by the scene's unit scale.
         In this case scaling the value multiple times would cause problems, so the ``ghost`` argument should be false.


   .. method:: items()
   
      Returns the items of this objects custom properties (matches Python's
      dictionary function of the same name).
   
      :return: custom property key, value pairs.
      :rtype: :class:`idprop.types.IDPropertyGroupViewItems`
   
      .. note::
   
         Limited to: :ref:`bpy_types-custom_properties`.


   .. method:: keyframe_delete(data_path, *, index=-1, frame=None, group="")
   
      Remove a keyframe from this properties fcurve.
   
      :param data_path: path to the property to remove a key, analogous to the fcurve's data path.
      :type data_path: str
      :param index: array index of the property to remove a key. Defaults to -1 removing all indices or a single channel if the property is not an array.
      :type index: int
      :param frame: The frame on which the keyframe is deleted. None (the default) uses ``bpy.context.scene.frame_current``.
      :type frame: float | None
      :param group: The name of the group the F-Curve should be added to if it doesn't exist yet.
      :type group: str
      :return: Success of keyframe deletion.
      :rtype: bool


   .. method:: keyframe_insert(data_path, *, index=-1, frame=None, group="", options=set(), keytype='KEYFRAME')
   
      Insert a keyframe on the property given, adding fcurves and animation data when necessary.
   
      :param data_path: path to the property to key, analogous to the fcurve's data path.
      :type data_path: str
      :param index: array index of the property to key.
         Defaults to -1 which will key all indices or a single channel if the property is not an array.
      :type index: int
      :param frame: The frame on which the keyframe is inserted. None (the default) uses ``bpy.context.scene.frame_current``.
      :type frame: float | None
      :param group: The name of the group the F-Curve should be added to if it doesn't exist yet.
      :type group: str
      :param options: Optional set of flags:
   
         - ``INSERTKEY_NEEDED`` Only insert keyframes where they're needed in the relevant F-Curves.
         - ``INSERTKEY_VISUAL`` Insert keyframes based on 'visual transforms'.
         - ``INSERTKEY_REPLACE`` Only replace already existing keyframes.
         - ``INSERTKEY_AVAILABLE`` Only insert into already existing F-Curves.
         - ``INSERTKEY_CYCLE_AWARE`` Take cyclic extrapolation into account (Cycle-Aware Keying option).
      :type options: set[Literal['INSERTKEY_NEEDED', 'INSERTKEY_VISUAL', 'INSERTKEY_REPLACE', 'INSERTKEY_AVAILABLE', 'INSERTKEY_CYCLE_AWARE']]
      :param keytype: Type of the key.
      :type keytype: Literal['KEYFRAME', 'BREAKDOWN', 'MOVING_HOLD', 'EXTREME', 'JITTER', 'GENERATED']
      :return: Success of keyframe insertion.
      :rtype: bool


      This is the most simple example of inserting a keyframe from Python.

      .. literalinclude:: ../examples/bpy.types.bpy_struct.keyframe_insert.0.py
         :lines: 5-


      Note that when keying data paths which contain nested properties this must be
      done from the :class:`ID` subclass, in this case the :class:`Armature` rather
      than the bone.

      .. literalinclude:: ../examples/bpy.types.bpy_struct.keyframe_insert.1.py
         :lines: 7-


   .. method:: keys()
   
      Returns the keys of this objects custom properties (matches Python's
      dictionary function of the same name).
   
      :return: custom property keys.
      :rtype: :class:`idprop.types.IDPropertyGroupViewKeys`
   
      .. note::
   
         Limited to: :ref:`bpy_types-custom_properties`.


   .. method:: path_from_id(property="", /)
   
      Returns the data path from the ID to this object (string).
   
      :param property: Optional property name which can be used if the path is
         to a property of this object.
      :type property: str
      :return: The path from :class:`bpy.types.bpy_struct.id_data`
         to this struct and property (when given).
      :rtype: str


   .. method:: path_from_module(property="", index=-1, /)
   
      Returns the full data path to this struct (as a string) from the bpy module.
   
      :param property: Optional property name to get the full path from
      :type property: str
      :param index: Optional index of the property.
         "-1" means that the property has no indices.
      :type index: int
      :return: The full path to the data.
      :rtype: str
   
      :raises ValueError:
         if the input data cannot be converted into a full data path.
   
         .. note:: Even if all input data is correct, this function might
            error out because Blender cannot derive a valid path.
            The incomplete path will be printed in the error message.


   .. method:: path_resolve(path, coerce=True, /)
   
      Returns the property from the path, raise an exception when not found.
   
      :param path: path which this property resolves.
      :type path: str
      :param coerce: optional argument, when True, the property will be converted
         into its Python representation.
      :type coerce: bool
      :return: Property value or property object.
      :rtype: Any | :class:`bpy.types.bpy_prop`


   .. method:: pop(key, default=None, /)
   
      Remove and return the value of the custom property assigned to key or default
      when not found (matches Python's dictionary function of the same name).
   
      :param key: The key associated with the custom property.
      :type key: str
      :param default: Optional argument for the value to return if
         *key* is not found.
      :type default: Any
      :return: Custom property value or default.
      :rtype: Any
   
      .. note::
   
         Limited to: :ref:`bpy_types-custom_properties`.


   .. method:: property_overridable_library_set(property, overridable, /)
   
      Define a property as overridable or not (only for custom properties!).
   
      :param property: Property name.
      :type property: str
      :param overridable: Overridable status to set.
      :type overridable: bool
      :return: True when the overridable status of the property was successfully set.
      :rtype: bool


   .. method:: property_unset(property, /)
   
      Unset a property, will use default value afterward.
   
      :param property: Property name.
      :type property: str


   .. method:: rna_ancestors()
   
      Return the chain of data containing this struct, if known.
      The first item is the root (typically an ID), the last one is the immediate parent.
      May be empty.
   
      :return: a list of this object's ancestors.
      :rtype: list[:class:`bpy.types.bpy_struct`]


   .. method:: type_recast()
   
      Return a new instance, this is needed because types
      such as textures can be changed at runtime.
   
      :return: a new instance of this object with the type initialized again.
      :rtype: :class:`bpy.types.bpy_struct`


   .. method:: values()
   
      Returns the values of this objects custom properties (matches Python's
      dictionary function of the same name).
   
      :return: custom property values.
      :rtype: :class:`idprop.types.IDPropertyGroupViewValues`
   
      .. note::
   
         Limited to: :ref:`bpy_types-custom_properties`.


   .. attribute:: id_data

      The :class:`bpy.types.ID` object this data-block is from or None, (not available for all data types) (readonly)
      
      :type: :class:`bpy.types.ID`


   .. details:: Special Methods

      .. method:: __contains__(item)

         :param item: Item to test for membership.
         :type item: object
         :rtype: bool

      .. method:: __eq__(other)

         :param other: The other operand.
         :type other: object
         :rtype: bool

      .. method:: __ge__(other)

         :param other: The other operand.
         :type other: Self
         :rtype: bool

      .. method:: __getitem__(key)

         :param key: Index or key.
         :type key: int
         :rtype: float

      .. method:: __gt__(other)

         :param other: The other operand.
         :type other: Self
         :rtype: bool

      .. method:: __hash__()

         :rtype: int

      .. method:: __le__(other)

         :param other: The other operand.
         :type other: Self
         :rtype: bool

      .. method:: __lt__(other)

         :param other: The other operand.
         :type other: Self
         :rtype: bool

      .. method:: __ne__(other)

         :param other: The other operand.
         :type other: object
         :rtype: bool

      .. method:: __repr__()

         :rtype: str

      .. method:: __setitem__(key, value)

         :param key: Index or key.
         :type key: int
         :param value: Value to assign.
         :type value: object

      .. method:: __str__()

         :rtype: str

