"""Core calculations and parameter parsing for print-fit standard-part adapters."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Dict, Iterable, List, Optional, Tuple


MM_PER_CM = 10.0


METRIC_COARSE_PRESETS: Dict[str, Dict[str, float]] = {
    "M2": {"diameter": 2.0, "pitch": 0.40, "outer": 4.0, "thickness": 2.4},
    "M2.5": {"diameter": 2.5, "pitch": 0.45, "outer": 5.0, "thickness": 3.0},
    "M3": {"diameter": 3.0, "pitch": 0.50, "outer": 6.0, "thickness": 3.6},
    "M4": {"diameter": 4.0, "pitch": 0.70, "outer": 8.0, "thickness": 4.8},
    "M5": {"diameter": 5.0, "pitch": 0.80, "outer": 10.0, "thickness": 6.0},
    "M6": {"diameter": 6.0, "pitch": 1.00, "outer": 12.0, "thickness": 7.2},
    "M8": {"diameter": 8.0, "pitch": 1.25, "outer": 16.0, "thickness": 9.6},
    "M10": {"diameter": 10.0, "pitch": 1.50, "outer": 20.0, "thickness": 12.0},
}


TRUE_VALUES = {"1", "true", "yes", "y", "on", "是", "开"}
FALSE_VALUES = {"0", "false", "no", "n", "off", "否", "关"}

FIT_ALIASES = {
    "thread": "thread_xy",
    "threadxy": "thread_xy",
    "thread_xy": "thread_xy",
    "screw": "thread_xy",
    "bolt": "thread_xy",
    "螺丝": "thread_xy",
    "螺纹": "thread_xy",
    "xy": "xy",
    "radial": "xy",
    "shaft": "xy",
    "gear": "xy",
    "pulley": "xy",
    "sprocket": "xy",
    "齿轮": "xy",
    "轴类": "xy",
    "xyz": "xyz",
    "all": "xyz",
    "generic": "xyz",
    "envelope": "xyz",
    "body": "xyz",
    "通用": "xyz",
    "包络": "xyz",
    "manual": "manual",
    "scale": "manual",
}

OPERATION_ALIASES = {
    "cavity": "cavity",
    "base": "cavity",
    "cut": "cavity",
    "pocket": "cavity",
    "fixture": "cavity",
    "底座": "cavity",
    "挖孔": "cavity",
    "tool": "tool",
    "cutter": "tool",
    "knife": "tool",
    "刀具": "tool",
    "part": "part",
    "copy": "part",
    "compensate": "part",
    "print": "part",
    "零件": "part",
    "补偿": "part",
}


@dataclass(frozen=True)
class AdapterConfig:
    name: str
    operation: str
    fit: str
    nominal_diameter_mm: float
    clearance_mm: float
    clearance_x_mm: float
    clearance_y_mm: float
    clearance_z_mm: float
    fit_adjust_mm: float
    scale_x: Optional[float]
    scale_y: Optional[float]
    scale_z: Optional[float]
    scale_xy: float
    center: str
    blank: str
    outer_mm: Optional[float]
    thickness_mm: Optional[float]
    z_start_mm: Optional[float]
    box_x_mm: Optional[float]
    box_y_mm: Optional[float]
    margin_mm: float
    margin_x_mm: float
    margin_y_mm: float
    margin_z_mm: float
    cut: bool
    keep_tool: bool
    seal: str
    seal_direction: str
    seal_depth_mm: float
    seal_oversize: float
    warning_messages: Tuple[str, ...] = ()


CompanionConfig = AdapterConfig


def mm_to_cm(value_mm: float) -> float:
    return value_mm / MM_PER_CM


def cm_to_mm(value_cm: float) -> float:
    return value_cm * MM_PER_CM


def clearance_scale_ratio(nominal_diameter_mm: float, clearance_mm: float) -> float:
    """Return XY scale needed to add radial clearance without changing Z pitch."""

    if nominal_diameter_mm <= 0:
        raise ValueError("diameter must be greater than 0 mm")
    if clearance_mm < 0:
        raise ValueError("clearance must not be negative")
    return (nominal_diameter_mm + 2.0 * clearance_mm) / nominal_diameter_mm


def side_adjust_scale(size_mm: float, side_adjust_mm: float) -> float:
    """Return scale for adding a signed amount to each side of a bounding span."""

    if size_mm <= 0:
        raise ValueError("body size must be greater than 0 mm")
    adjusted = size_mm + 2.0 * side_adjust_mm
    if adjusted <= 0:
        raise ValueError("side adjustment %.3f mm collapses %.3f mm span" % (side_adjust_mm, size_mm))
    return adjusted / size_mm


def calculate_fit_scales(config: AdapterConfig, size_xyz_mm: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """Calculate non-uniform scales for the selected fit strategy."""

    if config.fit == "thread_xy":
        return (
            config.scale_x if config.scale_x is not None else config.scale_xy,
            config.scale_y if config.scale_y is not None else config.scale_xy,
            config.scale_z if config.scale_z is not None else 1.0,
        )

    size_x, size_y, size_z = size_xyz_mm
    if config.fit == "xy":
        return (
            config.scale_x if config.scale_x is not None else side_adjust_scale(size_x, config.clearance_x_mm),
            config.scale_y if config.scale_y is not None else side_adjust_scale(size_y, config.clearance_y_mm),
            config.scale_z if config.scale_z is not None else 1.0,
        )

    if config.fit == "xyz":
        default_x = config.fit_adjust_mm if config.operation == "part" else config.clearance_x_mm
        default_y = config.fit_adjust_mm if config.operation == "part" else config.clearance_y_mm
        default_z = config.fit_adjust_mm if config.operation == "part" else config.clearance_z_mm
        return (
            config.scale_x if config.scale_x is not None else side_adjust_scale(size_x, default_x),
            config.scale_y if config.scale_y is not None else side_adjust_scale(size_y, default_y),
            config.scale_z if config.scale_z is not None else side_adjust_scale(size_z, default_z),
        )

    if config.fit == "manual":
        return (
            config.scale_x if config.scale_x is not None else 1.0,
            config.scale_y if config.scale_y is not None else 1.0,
            config.scale_z if config.scale_z is not None else 1.0,
        )

    raise ValueError("unknown fit strategy %r" % config.fit)


def hex_circumradius_from_across_flats(across_flats_mm: float) -> float:
    """Fusion sketch radius for a regular hex when the user enters across-flats size."""

    if across_flats_mm <= 0:
        raise ValueError("hex across-flats size must be greater than 0 mm")
    return across_flats_mm / math.sqrt(3.0)


def parse_key_values(text: str) -> Dict[str, str]:
    """Parse 'key=value; key=value' text used by the Fusion input dialog."""

    result: Dict[str, str] = {}
    if not text:
        return result

    for part in re.split(r"[;\n]+", text):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError("invalid parameter segment %r, expected key=value" % part)
        key, value = part.split("=", 1)
        key = normalize_key(key)
        result[key] = value.strip()
    return result


def normalize_key(key: str) -> str:
    aliases = {
        "d": "diameter",
        "dia": "diameter",
        "nominal": "diameter",
        "nominal_diameter": "diameter",
        "gap": "clearance",
        "single_side_gap": "clearance",
        "radial_clearance": "clearance",
        "clearance_xy": "xy_clearance",
        "gap_xy": "xy_clearance",
        "x_gap": "clearance_x",
        "y_gap": "clearance_y",
        "z_gap": "clearance_z",
        "adjust": "fit_adjust",
        "part_adjust": "fit_adjust",
        "shrink": "fit_adjust",
        "workflow": "operation",
        "op": "operation",
        "mode": "fit",
        "strategy": "fit",
        "profile": "fit",
        "kind": "blank",
        "base": "blank",
        "base_shape": "blank",
        "blank_kind": "blank",
        "shape": "blank",
        "size": "outer",
        "outer_size": "outer",
        "hex_af": "outer",
        "across_flats": "outer",
        "height": "thickness",
        "z": "z_start",
        "z0": "z_start",
        "keep": "keep_tool",
        "keep_tools": "keep_tool",
        "cap": "seal",
        "seal_mode": "seal",
        "seal_dir": "seal_direction",
        "cap_dir": "seal_direction",
        "cap_depth": "seal_depth",
    }
    normalized = key.strip().lower().replace("-", "_").replace(" ", "_")
    return aliases.get(normalized, normalized)


def parse_bool(value: str, default: bool = False) -> bool:
    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    if value == "":
        return default
    raise ValueError("invalid boolean value %r" % value)


def _float_from(params: Dict[str, str], key: str, default: float) -> float:
    value = params.get(key, "")
    if value == "":
        return default
    return float(value)


def _optional_float_from(params: Dict[str, str], key: str) -> Optional[float]:
    value = params.get(key, "")
    if value == "":
        return None
    return float(value)


def _str_from(params: Dict[str, str], key: str, default: str) -> str:
    value = params.get(key, "")
    return value.strip() if value != "" else default


def get_preset(name: str) -> Dict[str, float]:
    normalized = name.strip().upper().replace(" ", "")
    if normalized not in METRIC_COARSE_PRESETS:
        raise ValueError("unknown preset %r" % name)
    return METRIC_COARSE_PRESETS[normalized]


def default_parameter_line(preset_name: str = "M4") -> str:
    preset = get_preset(preset_name)
    return (
        "operation=cavity; fit=thread; preset={preset}; clearance=0.20; "
        "blank=hex; outer={outer:g}; thickness={thickness:g}; z_start=0; "
        "cut=true; keep_tool=true; seal=none"
    ).format(
        preset=preset_name,
        outer=preset["outer"],
        thickness=preset["thickness"],
    )


def normalize_fit(value: str) -> str:
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    if key in FIT_ALIASES:
        return FIT_ALIASES[key]
    raise ValueError("fit must be thread, xy, xyz, or manual")


def normalize_operation(value: str) -> str:
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    if key in OPERATION_ALIASES:
        return OPERATION_ALIASES[key]
    raise ValueError("operation must be cavity, tool, or part")


def normalize_blank(value: str) -> str:
    blank = value.strip().lower().replace("-", "_").replace(" ", "_")
    if blank in {"round", "circle", "circular"}:
        blank = "cylinder"
    if blank in {"rect", "rectangle", "plate", "base_plate"}:
        blank = "box"
    if blank in {"none", "off", "false", "no"}:
        blank = "none"
    if blank not in {"hex", "cylinder", "box", "none"}:
        raise ValueError("blank must be hex, cylinder, box, or none")
    return blank


def build_config(text: str) -> AdapterConfig:
    params = parse_key_values(text)

    raw_fit = params.get("fit", "")
    raw_operation = params.get("operation", "")
    operation = normalize_operation(raw_operation) if raw_operation else "cavity"

    if raw_fit:
        lower_fit = raw_fit.strip().lower().replace("-", "_").replace(" ", "_")
        if lower_fit in OPERATION_ALIASES and not raw_operation:
            operation = normalize_operation(lower_fit)
            raw_fit = ""
        elif lower_fit in {"compensate", "print", "part", "copy", "零件", "补偿"}:
            operation = "part"
            raw_fit = "xyz"

    has_thread_hint = "preset" in params or "diameter" in params
    default_fit = "thread_xy" if has_thread_hint else "xy"
    fit = normalize_fit(raw_fit) if raw_fit else default_fit

    preset_name = _str_from(params, "preset", "M4").upper().replace(" ", "")
    preset = get_preset(preset_name)

    diameter = _float_from(params, "diameter", preset["diameter"])
    clearance = _float_from(params, "clearance", 0.20)
    thread_scale = clearance_scale_ratio(diameter, max(clearance, 0.0))

    xy_clearance = _optional_float_from(params, "xy_clearance")
    clearance_x = _float_from(params, "clearance_x", xy_clearance if xy_clearance is not None else clearance)
    clearance_y = _float_from(params, "clearance_y", xy_clearance if xy_clearance is not None else clearance)
    clearance_z_default = clearance if fit == "xyz" else 0.0
    clearance_z = _float_from(params, "clearance_z", clearance_z_default)

    fit_adjust = _float_from(params, "fit_adjust", 0.0)

    scale_xy_override = _optional_float_from(params, "scale_xy")
    scale_x = _optional_float_from(params, "scale_x")
    scale_y = _optional_float_from(params, "scale_y")
    scale_z = _optional_float_from(params, "scale_z")
    if scale_xy_override is not None:
        scale_x = scale_xy_override if scale_x is None else scale_x
        scale_y = scale_xy_override if scale_y is None else scale_y

    center_default = "origin" if fit == "thread_xy" else "bbox"
    center = _str_from(params, "center", center_default).lower().replace(" ", "_")
    if center in {"box", "body", "auto"}:
        center = "bbox"
    if center not in {"origin", "bbox"}:
        raise ValueError("center must be origin or bbox")

    blank_default = "none" if operation in {"tool", "part"} else ("hex" if fit == "thread_xy" else "box")
    blank = normalize_blank(_str_from(params, "blank", blank_default))
    if operation in {"tool", "part"} and "blank" not in params:
        blank = "none"

    has_outer = "outer" in params
    outer = _optional_float_from(params, "outer") if has_outer else (preset["outer"] if fit == "thread_xy" else None)
    thickness = _optional_float_from(params, "thickness")
    if thickness is None and fit == "thread_xy":
        thickness = preset["thickness"]
    z_start = _optional_float_from(params, "z_start")
    box_x = _optional_float_from(params, "box_x")
    box_y = _optional_float_from(params, "box_y")

    margin = _float_from(params, "margin", max(1.0, clearance * 4.0))
    margin_x = _float_from(params, "margin_x", margin)
    margin_y = _float_from(params, "margin_y", margin)
    margin_z = _float_from(params, "margin_z", margin)

    cut = parse_bool(params.get("cut", "true"), True)
    keep_tool = parse_bool(params.get("keep_tool", "true"), True)

    seal = _str_from(params, "seal", "none").lower()
    if seal in {"off", "false", "0"}:
        seal = "none"
    if seal in {"cap", "circular_cap"}:
        seal = "cylinder"
    if seal not in {"none", "cylinder"}:
        raise ValueError("seal must be none or cylinder")

    seal_direction = _str_from(params, "seal_direction", "+z").lower().replace(" ", "")
    if seal_direction not in {"+z", "-z"}:
        raise ValueError("seal_direction must be +z or -z")
    seal_depth = _float_from(params, "seal_depth", 0.0)
    seal_oversize = _float_from(params, "seal_oversize", 1.02)

    if outer is not None and outer <= 0:
        raise ValueError("outer must be greater than 0 mm")
    if outer is not None and fit == "thread_xy" and blank != "none" and outer <= diameter + 2.0 * max(clearance, 0.0):
        raise ValueError("outer must be larger than the enlarged cutter diameter")
    if thickness is not None and thickness <= 0 and blank != "none":
        raise ValueError("thickness must be greater than 0 mm")
    if box_x is not None and box_x <= 0:
        raise ValueError("box_x must be greater than 0 mm")
    if box_y is not None and box_y <= 0:
        raise ValueError("box_y must be greater than 0 mm")
    if seal_depth < 0:
        raise ValueError("seal_depth must not be negative")
    if seal_oversize <= 0:
        raise ValueError("seal_oversize must be greater than 0")

    name = _str_from(params, "name", preset_name if fit == "thread_xy" else "PrintFit")
    warnings: List[str] = []
    if clearance == 0 and fit != "manual":
        warnings.append("clearance is 0, this will not add print-fit allowance")
    if operation == "part" and fit == "manual" and not any(value is not None for value in (scale_x, scale_y, scale_z)):
        warnings.append("operation=part with fit=manual has no scale override, so the copied part will remain unchanged")
    if seal == "cylinder" and seal_depth == 0:
        warnings.append("seal=cylinder was requested but seal_depth is 0, so no cap will be created")
    if fit != "thread_xy" and center == "origin":
        warnings.append("generic fits usually use center=bbox; center=origin can intentionally shift the result if the body is off origin")

    return AdapterConfig(
        name=name,
        operation=operation,
        fit=fit,
        nominal_diameter_mm=diameter,
        clearance_mm=clearance,
        clearance_x_mm=clearance_x,
        clearance_y_mm=clearance_y,
        clearance_z_mm=clearance_z,
        fit_adjust_mm=fit_adjust,
        scale_x=scale_x,
        scale_y=scale_y,
        scale_z=scale_z,
        scale_xy=thread_scale,
        center=center,
        blank=blank,
        outer_mm=outer,
        thickness_mm=thickness,
        z_start_mm=z_start,
        box_x_mm=box_x,
        box_y_mm=box_y,
        margin_mm=margin,
        margin_x_mm=margin_x,
        margin_y_mm=margin_y,
        margin_z_mm=margin_z,
        cut=cut,
        keep_tool=keep_tool,
        seal=seal,
        seal_direction=seal_direction,
        seal_depth_mm=seal_depth,
        seal_oversize=seal_oversize,
        warning_messages=tuple(warnings),
    )


def scale_table(specs: Iterable[str], clearance_mm: float) -> List[Tuple[str, float, float]]:
    rows: List[Tuple[str, float, float]] = []
    for spec in specs:
        preset = get_preset(spec)
        diameter = preset["diameter"]
        rows.append((spec.upper(), diameter, clearance_scale_ratio(diameter, clearance_mm)))
    return rows
