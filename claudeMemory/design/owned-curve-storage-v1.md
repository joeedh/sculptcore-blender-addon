# Owned scalar CurveMapping storage v1

Companion to [the contract](generic-brush-contract-v1.md). This representation
is engine-agnostic. No new IDProperty type is needed. The owning property is
absent until initialization. When present it contains this ordinary group:

```python
{
    "_type": "blender.owned_curve_mapping",
    "_version": 1,
    "clip": [0.0, 0.0, 1.0, 1.0],  # xmin, ymin, xmax, ymax
    "use_clip": 1,
    "extend": "EXTRAPOLATED",
    "default_handle": "AUTO",
    "points": [
        {"x": 0.0, "y": 0.0, "handle": "AUTO"},
        {"x": 1.0, "y": 1.0, "handle": "AUTO"},
    ],
}
```

`points` is an IDP_IDPARRAY of groups, `clip` a double numeric array. Coordinates
are double IDProperties containing exactly float32-representable finite values
(native CurveMapPoint precision). Native writes quantize to float32 before
saving. Version/use_clip are integer scalars; tags/enums are strings. All other
fields are required, including for future readers preserving this version.

Bounds: 2..32767 points (native signed-short count), finite coordinates,
nondecreasing x (equal-x points preserve authored order), clip minima strictly
less than maxima, clip coordinates within native RNA [-100,100]. Handles are
AUTO, AUTO_CLAMPED or VECTOR. Extend is HORIZONTAL or EXTRAPOLATED. use_clip
is 0 or 1. Non-finite/non-representable coordinates, wrong field types, missing
required fields, invalid tags/versions and excess points are access/edit errors.
Validation never deletes stored data. Unknown additional top-level keys are
preserved on ordinary commits, copies and serialization. Point-level extensions
are rejected by v1 access/commit and remain opaque on file resave; there is no
implicit association of unknown metadata with a moved/replaced point. All
extensions recursively contain only ID-free groups, property arrays, numeric
arrays, strings and numeric scalars, with at most 64 nesting levels inside the
definition. ID references are rejected even inside unknown fields. Reset/unset
is the only operation discarding a supported opaque top-level extension.
Validation also materializes native evaluation data and rejects non-finite
tables, ranges or extrapolation vectors. Finite authored points alone are not
sufficient: coincident endpoints and extreme coordinates can overflow native
curve evaluation. Rejection retains the original payload unchanged.

v1 has one scalar channel, mapped to native cm[0]. Native cm[1..3] are empty.
Wrapping, RGB tone and black/white transforms are not part of the scalar API;
attempts to set them away from scalar defaults raise. CUMA_PREMULLED,
changed_timestamp, tables, extents, runtime identity and bwmul are derived,
never serialized. Selection/active point, current view rectangle, preset-menu
selection, frame/sample indicators are runtime presentation state, reset when
the owner runtime is rebuilt. Editing these does not dirty a brush or bump its
evaluation revision. Setting a preset changes the actual saved points and
does notify. Clip changes notify because clipping can move authored points.

Copy serializes only owned definitions. A brush has no Scene/NodeTree reference
through this property. Native API declaration and subtype dispatch are required
to expose this data as CurveMapping: the group alone is not an editable native
CurveMapping and must never be cast to one.

Compatibility gate: preserve this exact payload, including an unknown extra
key, through a pre-change fork and an available stock Blender 5.x binary,
opening/resaving both ordinary files and external brush asset files with no
declaration. Reopen with the new API and compare definitions/evaluation.
Record binary hashes; do not infer support merely from a 5.x version string.
