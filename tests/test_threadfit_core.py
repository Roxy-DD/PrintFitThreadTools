import math
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "fusion", "PrintFitThreadTools", "lib")
if LIB not in sys.path:
    sys.path.insert(0, LIB)

from threadfit_core import (  # noqa: E402
    build_config,
    calculate_fit_scales,
    clearance_scale_ratio,
    hex_circumradius_from_across_flats,
    parse_key_values,
    side_adjust_scale,
)


class ThreadFitCoreTests(unittest.TestCase):
    def test_clearance_scale_ratio(self):
        self.assertAlmostEqual(clearance_scale_ratio(4.0, 0.2), 1.1)
        self.assertAlmostEqual(clearance_scale_ratio(3.0, 0.2), 1.1333333333)

    def test_clearance_scale_rejects_invalid_values(self):
        with self.assertRaises(ValueError):
            clearance_scale_ratio(0.0, 0.2)
        with self.assertRaises(ValueError):
            clearance_scale_ratio(3.0, -0.1)

    def test_side_adjust_scale_accepts_signed_adjustment(self):
        self.assertAlmostEqual(side_adjust_scale(20.0, 0.5), 1.05)
        self.assertAlmostEqual(side_adjust_scale(20.0, -0.5), 0.95)
        with self.assertRaises(ValueError):
            side_adjust_scale(1.0, -0.6)

    def test_parse_key_values_with_aliases(self):
        params = parse_key_values("preset=M3; gap=0.18; hex_af=6")
        self.assertEqual(params["preset"], "M3")
        self.assertEqual(params["clearance"], "0.18")
        self.assertEqual(params["outer"], "6")

    def test_build_config_from_preset(self):
        config = build_config("preset=M4; clearance=0.2; blank=hex; outer=8; thickness=4.8")
        self.assertEqual(config.name, "M4")
        self.assertEqual(config.operation, "cavity")
        self.assertEqual(config.fit, "thread_xy")
        self.assertEqual(config.blank, "hex")
        self.assertTrue(config.keep_tool)
        self.assertAlmostEqual(config.scale_xy, 1.1)

    def test_hex_circumradius_from_across_flats(self):
        self.assertAlmostEqual(hex_circumradius_from_across_flats(8.0), 8.0 / math.sqrt(3.0))

    def test_box_config(self):
        config = build_config("preset=M3; blank=box; box_x=20; box_y=12; outer=8; thickness=5")
        self.assertEqual(config.blank, "box")
        self.assertEqual(config.box_x_mm, 20)
        self.assertEqual(config.box_y_mm, 12)

    def test_generic_xy_config_defaults_to_bbox_center_and_box_blank(self):
        config = build_config("fit=xy; clearance=0.25")
        self.assertEqual(config.fit, "xy")
        self.assertEqual(config.center, "bbox")
        self.assertEqual(config.blank, "box")
        self.assertAlmostEqual(calculate_fit_scales(config, (20, 10, 5))[0], 1.025)
        self.assertAlmostEqual(calculate_fit_scales(config, (20, 10, 5))[1], 1.05)
        self.assertAlmostEqual(calculate_fit_scales(config, (20, 10, 5))[2], 1.0)

    def test_generic_xyz_config_scales_all_axes(self):
        config = build_config("fit=xyz; clearance=0.5")
        self.assertEqual(calculate_fit_scales(config, (20, 10, 5)), (1.05, 1.1, 1.2))

    def test_part_compensation_uses_signed_fit_adjust(self):
        config = build_config("operation=part; fit=xyz; fit_adjust=-0.1")
        self.assertEqual(config.operation, "part")
        self.assertAlmostEqual(calculate_fit_scales(config, (20, 10, 5))[0], 0.99)
        self.assertAlmostEqual(calculate_fit_scales(config, (20, 10, 5))[1], 0.98)
        self.assertAlmostEqual(calculate_fit_scales(config, (20, 10, 5))[2], 0.96)

    def test_manual_scale_overrides(self):
        config = build_config("operation=part; fit=manual; scale_xy=0.98; scale_z=1.01")
        self.assertEqual(calculate_fit_scales(config, (20, 10, 5)), (0.98, 0.98, 1.01))


if __name__ == "__main__":
    unittest.main()
