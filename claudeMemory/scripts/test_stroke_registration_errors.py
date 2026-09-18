# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Exercise stroke failure propagation with native calls replaced by fakes.

Compile the actual function bodies without Blender's import-time registration.
Native registration/geometry behavior is covered by the engine gate separately.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[2] / "sculptcore_addon/stroke.py"
MODULE = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
OPERATOR = next(node for node in MODULE.body
                if isinstance(node, ast.ClassDef) and node.name == "SCULPTCORE_OT_brush_stroke")


def function(name, namespace, method=False):
    nodes = OPERATOR.body if method else MODULE.body
    node = next(node for node in nodes if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace[name]


class StrokeRegistrationErrors(unittest.TestCase):
    def setUp(self):
        self.executor = Mock()
        self.executor.supportsResolved.return_value = False
        self.executor.supportsResolvedProgram.return_value = False
        self.executor.preflightRaw.return_value = True
        self.executor.preflightRawProgram.return_value = True
        self.vector = Mock()
        self.refresh = Mock()
        self.namespace = {
            "engine": Mock(), "_ensure_executor": Mock(return_value=self.executor),
            "_float3": Mock(return_value=self.vector), "_refresh_queries": self.refresh,
            "brush_policy": Mock(), "set_snake_hook_state": Mock(),
        }
        self.session = SimpleNamespace(last_stroke_grids=False, multires_ptr=0, brush_obj=Mock())

    def test_dyntopo_returns_failure_and_releases_vectors_without_refresh(self):
        dab = function("apply_dyntopo_dab", self.namespace)
        self.executor.applyDab.return_value = -1
        self.assertEqual(dab(self.session, Mock(), (0, 0, 0), (0, 0, 1), 1, None, 1), -1)
        self.assertEqual(self.vector.dispose.call_count, 2)
        self.refresh.assert_not_called()
        self.executor.applyDab.return_value = 4
        self.assertEqual(dab(self.session, Mock(), (0, 0, 0), (0, 0, 1), 1, None, 2), 4)
        self.refresh.assert_called_once_with(self.session)

    def test_mesh_program_failure_is_not_a_successful_dab(self):
        dab = function("apply_dab_program", self.namespace)
        self.session.tree = Mock(return_value=Mock())
        self.executor.lastUniformValidationOk.return_value = False
        with patch.dict("sys.modules", {"sculptcore": Mock()}):
            self.assertEqual(dab(self.session, Mock(), (0, 0, 0), (0, 0, 1), 1), -1)
        self.executor.clearIsFirstOfStep.assert_not_called()
        self.refresh.assert_not_called()
        self.assertEqual(self.vector.dispose.call_count, 2)

    def test_scalar_failure_stops_symmetry_images(self):
        for path in ("apply_dyntopo_dab", "apply_dab_program", "apply_dab"):
            with self.subTest(path=path):
                calls = {name: Mock(return_value=-1) for name in
                         ("apply_dyntopo_dab", "apply_dab_program", "apply_dab")}
                self.namespace.update(calls)
                dab = function("_apply_one_image", self.namespace, method=True)
                op = SimpleNamespace(session=self.session, _engine_dead=False, _dab_count=0, _generic=None,
                                     _dyntopo=Mock() if path == "apply_dyntopo_dab" else None,
                                     _program=None if path == "apply_dab" else Mock(), kernel=1)
                dab(op, (0, 0, 0), (0, 0, 1), 1, False)
                self.assertTrue(op._engine_dead)
                dab(op, (0, 0, 0), (0, 0, 1), 1, False)
                calls[path].assert_called_once()
                self.assertEqual(op._dab_count, 1)

    def test_preview_failure_stops_new_snapshots(self):
        self.namespace.update(apply_dab_program=Mock(return_value=-1), apply_dab=Mock())
        dab = function("_preview_apply_image", self.namespace, method=True)
        op = SimpleNamespace(session=self.session, _engine_dead=False, _program=Mock(), kernel=1, _generic=None)
        dab(op, (0, 0, 0), (0, 0, 1), 1, False)
        self.assertTrue(op._engine_dead)
        dab(op, (0, 0, 0), (0, 0, 1), 1, True)
        self.executor.beginPreviewDab.assert_called_once()
        self.executor.extendPreviewDab.assert_not_called()

    def test_modal_failure_cancels_regular_and_rolls_back_preview(self):
        self.namespace["_MOVE_EVENT_TYPES"] = {"MOUSEMOVE", "INBETWEEN_MOUSEMOVE"}
        modal = function("modal", self.namespace, method=True)
        for preview in (False, True):
            with self.subTest(preview=preview):
                op = Mock(_preview_method=preview, _engine_dead=False)
                def fail(*args, **kwargs):
                    op._engine_dead = True
                op._dab_preview.side_effect = fail
                op._dab_at.side_effect = fail
                op._finish.return_value = {'CANCELLED'}
                op._finish_preview.return_value = {'CANCELLED'}
                context = Mock()
                event = SimpleNamespace(type="MOUSEMOVE", pressure=1)
                self.assertEqual(modal(op, context, event), {'CANCELLED'})
                if preview:
                    op._finish_preview.assert_called_once_with(context, commit=False)
                    op._finish.assert_not_called()
                else:
                    op._finish.assert_called_once_with(context, 'CANCELLED')
                    op._finish_preview.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
