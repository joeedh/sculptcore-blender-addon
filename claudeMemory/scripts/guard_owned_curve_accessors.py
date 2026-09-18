# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Install manual accessors so generated native RNA also respects owned curves."""
from pathlib import Path
import runpy

h = runpy.run_path(str(Path(__file__).with_name("finish_owned_curve_rna.py")))
replace, start, color = h["replace"], h["start"], h["color"]
accessors = []
fields = [
    ("CurveMapPoint", "location", "float", 2, "(&data->x)[i]", "(&data->x)[i] = values[i];"),
    ("CurveMapPoint", "handle_type", "int", 0, "int(data->flag) & 6", "data->flag = eCurveMapPoint_Flag((int(data->flag) & ~6) | value);"),
    ("CurveMapPoint", "select", "bool", 0, "(data->flag & CUMA_SELECT) != 0", "SET_FLAG_FROM_TEST(data->flag, value, CUMA_SELECT);"),
    ("CurveMapping", "tone", "int", 0, "int(data->tone)", "data->tone = eCurveMappingTone(value);"),
    ("CurveMapping", "use_clip", "bool", 0, "(data->flag & CUMA_DO_CLIP) != 0", "rna_CurveMapping_clip_set(ptr, value);"),
    ("CurveMapping", "extend", "int", 0, "int(data->flag) & CUMA_EXTEND_EXTRAPOLATE", "SET_FLAG_FROM_TEST(data->flag, value != 0, CUMA_EXTEND_EXTRAPOLATE);"),
    ("CurveMapping", "black_level", "float", 3, "data->black[i]", "rna_CurveMapping_black_level_set(ptr, values);"),
    ("CurveMapping", "white_level", "float", 3, "data->white[i]", "rna_CurveMapping_white_level_set(ptr, values);"),
]
for bound in ("min", "max"):
    for axis in ("x", "y"):
        fields.append(("CurveMapping", "clip_{}_{}".format(bound, axis), "float", 0,
                       "data->clipr.{}{}".format(axis, bound),
                       "float low, high, soft_low, soft_high;\n"
                       "  rna_CurveMapping_clip{}{}_range(ptr, &low, &high, &soft_low, &soft_high);\n"
                       "  data->clipr.{}{} = std::clamp(value, low, high);".format(bound, axis, axis, bound)))

for struct, field, kind, size, getter, setter in fields:
    name = "rna_owned_access_{}_{}".format(struct, field)
    if size:
        get = '''static void {name}_get(PointerRNA *ptr, float *values)
{{
  if (!RNA_owned_curve_validate(*ptr)) {{ std::fill_n(values, {size}, 0.0f); return; }}
  auto *data = static_cast<{struct} *>(ptr->data);
  for (int i = 0; i < {size}; i++) {{ values[i] = {getter}; }}
}}
'''.format(**locals())
        native_set = ("for (int i = 0; i < 2; i++) { " + setter + " }") if size == 2 else setter
        set = '''static void {name}_set(PointerRNA *ptr, const float *values)
{{
  if (ptr->owned_curve) {{
    double numbers[{size}];
    for (int i = 0; i < {size}; i++) {{ numbers[i] = values[i]; }}
    RNA_owned_curve_set(*ptr, *RNA_struct_type_find_property(ptr->type, "{field}"), numbers, {size});
    return;
  }}
  [[maybe_unused]] auto *data = static_cast<{struct} *>(ptr->data);
  {native_set}
}}
'''.format(**locals())
    else:
        get = '''static {kind} {name}_get(PointerRNA *ptr)
{{
  if (!RNA_owned_curve_validate(*ptr)) {{ return {kind}(0); }}
  auto *data = static_cast<{struct} *>(ptr->data);
  return {getter};
}}
'''.format(**locals())
        set = '''static void {name}_set(PointerRNA *ptr, {kind} value)
{{
  if (ptr->owned_curve) {{
    const double number = double(value);
    RNA_owned_curve_set(*ptr, *RNA_struct_type_find_property(ptr->type, "{field}"), &number, 1);
    return;
  }}
  [[maybe_unused]] auto *data = static_cast<{struct} *>(ptr->data);
  {setter}
}}
'''.format(**locals())
    accessors.extend((get, set))
    method = {"float": "float", "int": "enum", "bool": "boolean"}[kind]
    suffix = ', nullptr' if kind in ("float", "int") else ''
    definition = '  RNA_def_property_{}_funcs(prop, "{}_get", "{}_set"{});'.format(method, name, name, suffix)
    # Preserve each custom range callback: the final funcs call must name it too.
    if field.startswith("clip_"):
        definition = definition.replace('nullptr);', '"rna_CurveMapping_clip{}_range");'.format(field[5:].replace('_', '')))
    text = color.read_text()
    block_start = text.index('static void rna_def_{}('.format('curvemappoint' if struct == 'CurveMapPoint' else 'curvemapping'))
    field_start = text.index('  prop = RNA_def_property(srna, "' + field + '",', block_start)
    field_end = min(index for index in (
        text.find('\n  prop = RNA_def_property(', field_start + 1),
        text.find('\n  func = RNA_def_function(', field_start),
        text.find('\n}', field_start),
    ) if index >= 0)
    if definition not in text[field_start:field_end]:
        text = text[:field_end] + '\n' + definition + '\n' + text[field_end:]
        color.write_text(text, newline='\n')

accessors.append(r'''
static int rna_owned_points_length(PointerRNA *ptr)
{
  if (!RNA_owned_curve_validate(*ptr)) { return 0; }
  auto *curve = static_cast<CurveMap *>(ptr->data);
  return curve->curve ? curve->totpoint : 0;
}
static void rna_owned_points_begin(CollectionPropertyIterator *iter, PointerRNA *ptr)
{
  if (!RNA_owned_curve_validate(*ptr)) { iter->valid = false; return; }
  PointerRNA parent = *ptr;
  RNA_owned_curve_pin(parent);
  iter->parent = parent;
  auto *curve = static_cast<CurveMap *>(parent.data);
  rna_iterator_array_begin(iter, &parent, curve->curve, sizeof(CurveMapPoint), curve->totpoint, 0, nullptr);
}
static void rna_owned_array_next(CollectionPropertyIterator *iter)
{
  if (!RNA_owned_curve_validate(iter->parent)) { iter->valid = false; return; }
  rna_iterator_array_next(iter);
}
static PointerRNA rna_owned_points_get(CollectionPropertyIterator *iter)
{
  if (!RNA_owned_curve_validate(iter->parent)) { iter->valid = false; return {}; }
  return RNA_pointer_create_with_parent(iter->parent, RNA_CurveMapPoint, rna_iterator_array_get(iter));
}
static PointerRNA rna_owned_curves_get(CollectionPropertyIterator *iter)
{
  if (!RNA_owned_curve_validate(iter->parent)) { iter->valid = false; return {}; }
  return RNA_pointer_create_with_parent(iter->parent, RNA_CurveMap, rna_iterator_array_get(iter));
}
''')
text = color.read_text()
text = text.replace('"rna_iterator_array_end", "rna_owned_array_get", "rna_owned_points_length"',
                    '"rna_iterator_array_end", "rna_owned_points_get", "rna_owned_points_length"')
text = text.replace('"rna_owned_array_get",', '"rna_owned_curves_get",')
marker = "/* Owned curve accessors also protect direct generated RNA calls. */\n"
end_marker = "/* End owned curve accessors. */\n"
if marker in text:
    first = text.index(marker)
    last = text.index(end_marker, first) + len(end_marker)
    text = text[:first] + text[last:]
text = text.replace("\n}  // namespace blender\n\n#else\n", "\n" + marker + '\n'.join(accessors) + end_marker + "\n}  // namespace blender\n\n#else\n", 1)
color.write_text(text, newline='\n')
replace(color, '  RNA_def_property_collection_sdna(prop, nullptr, "curve", "totpoint");',
        '  RNA_def_property_collection_sdna(prop, nullptr, "curve", "totpoint");\n'
        '  RNA_def_property_collection_funcs(prop, "rna_owned_points_begin", "rna_owned_array_next",\n'
        '    "rna_iterator_array_end", "rna_owned_points_get", "rna_owned_points_length", nullptr, nullptr, nullptr);')
replace(color, '                                    "rna_iterator_array_next",\n'
               '                                    "rna_iterator_array_end",\n'
               '                                    "rna_iterator_array_get",\n'
               '                                    "rna_CurveMapping_curves_length",',
               '                                    "rna_owned_array_next",\n'
               '                                    "rna_iterator_array_end",\n'
               '                                    "rna_owned_curves_get",\n'
               '                                    "rna_CurveMapping_curves_length",')
start(color, "rna_CurveMapping_curves_length", "  if (!RNA_owned_curve_validate(*ptr)) { return 0; }")
start(color, "rna_CurveMapping_curves_begin", "  if (!RNA_owned_curve_validate(*ptr)) { iter->valid = false; return; }\n"
      "  PointerRNA parent = *ptr;\n  RNA_owned_curve_pin(parent);\n  iter->parent = parent;\n  ptr = &parent;")
for name in ("clipminx", "clipminy", "clipmaxx", "clipmaxy"):
    start(color, "rna_CurveMapping_" + name + "_range", "  if (!RNA_owned_curve_validate(*ptr)) { *min = *max = 0; return; }")
