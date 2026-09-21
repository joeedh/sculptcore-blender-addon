## sculptcore engine
[ ]: split engine/source/brush/compiler/emit_cpp.cc into smaller files
[ ]: split engine/source/subdiv/multires.cc into smaller files
[ ]: split engine/tests/test_grid_stroke.cc into smaller files if possible

## blender add-on todos

[ ]: expose the feature align smooth brush in the blender addon
  - make sure to expose options in brush ui
[ ]: sculptcore strokes don't update all 3d viewports on stroke end, only the active one
[ ]: right-clicking on a brush asset icon in sculptcore mode crashes, check recent 
     crash dumps.
[ ]: there are two automasking panels in sculptcore mode, the more complete one 
     should be retained make sure it maps properly to sculptcore properties.
[ ]: the change object mode pie menu shows a 'custom' as well as a 'sculptcore' mode.
     this appears to be duplicative.

## shift smooth panel 
[ ]: create a new panel in the properties editor for shift-smooth properties
[ ]: shift-smooth properties should use proper generic brush properties in unified mode 
     by default.
[ ]: add an option to enable dyntopo in shift-smooth 
[ ]: add an option to control whether smooth uses normal smooth or feature align smooth
     - make sure to add options in ui for feature align if it's enabled for shift smooth
	 - note: when we implement vertex paint smear we'll also allow the user to control 
	         blur shift smooth vs smear.
[ ]: add property to control shift-smooth strength.  it should have a maximum of 4.

