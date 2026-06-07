"""Fusion 360 script: print-fit adapter for imported standard-part bodies.

Workflows:
1. Select one or more solid bodies from Fusion/McMaster-Carr imports.
2. Choose a fit strategy and clearance.
3. Generate an enlarged cutter, a matching base/cavity, or an adjusted printable copy.

The threaded workflow still preserves the original rule: X/Y scale only, Z stays 1.0.
Generic workflows scale around the selected body's bounding-box center by default.
"""

from __future__ import annotations

import math
import os
import sys
import traceback


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from threadfit_core import (  # noqa: E402
    AdapterConfig,
    build_config,
    calculate_fit_scales,
    cm_to_mm,
    default_parameter_line,
    hex_circumradius_from_across_flats,
    mm_to_cm,
)


try:
    import adsk.core
    import adsk.fusion
except ImportError:
    adsk = None


CMD_ID = "PrintFitStandardPartAdapterCommand"
CMD_NAME = "3D打印标准件适配"
CMD_DESCRIPTION = "为 McMaster/Fusion 标准件生成带打印公差的刀具、底座或补偿副本。"
WORKSPACE_ID = "FusionSolidEnvironment"
PANEL_CANDIDATES = ("SolidCreatePanel", "SolidScriptsAddinsPanel")

OPERATION_OPTIONS = {
    "生成配套底座/孔槽": "cavity",
    "只生成布尔刀具": "tool",
    "生成打印补偿副本": "part",
}
FIT_OPTIONS = {
    "螺纹 XY 间隙": "thread",
    "通用 XY 包络": "xy",
    "通用 XYZ 包络": "xyz",
    "手动缩放": "manual",
}
BLANK_OPTIONS = {
    "矩形底座": "box",
    "圆形底座": "cylinder",
    "六角螺母": "hex",
    "不生成底座": "none",
}
CENTER_OPTIONS = {
    "自动：包围盒中心": "bbox",
    "原点：适合螺纹轴心在原点": "origin",
}
PRESET_OPTIONS = ("M2", "M2.5", "M3", "M4", "M5", "M6", "M8", "M10")

_handlers = []
_ui = None


def _handler_base(name):
    if adsk is None:
        return object
    return getattr(adsk.core, name)


class CommandCreatedHandler(_handler_base("CommandCreatedEventHandler")):
    def notify(self, args):
        try:
            command = args.command
            command.isExecutedWhenPreEmpted = False
            inputs = command.commandInputs
            _build_command_dialog(inputs)

            execute_handler = ExecuteHandler()
            validate_handler = ValidateInputsHandler()
            input_changed_handler = InputChangedHandler()
            activate_handler = ActivateHandler()
            destroy_handler = DestroyHandler()

            command.execute.add(execute_handler)
            command.validateInputs.add(validate_handler)
            command.inputChanged.add(input_changed_handler)
            command.activate.add(activate_handler)
            command.destroy.add(destroy_handler)

            _handlers.extend([
                execute_handler,
                validate_handler,
                input_changed_handler,
                activate_handler,
                destroy_handler,
            ])
        except Exception:
            if _ui:
                _ui.messageBox("创建命令面板失败：\n\n%s" % traceback.format_exc())


class ExecuteHandler(_handler_base("CommandEventHandler")):
    def notify(self, args):
        try:
            app = adsk.core.Application.get()
            design = adsk.fusion.Design.cast(app.activeProduct)
            if not design:
                _ui.messageBox("请先打开 Fusion 360 Design 文件。")
                return

            command = args.command
            inputs = command.commandInputs
            bodies = _bodies_from_selection_input(inputs.itemById("source_bodies"))
            if not bodies:
                _ui.messageBox("请至少选择一个实体 Body。")
                return

            config_text = _config_text_from_inputs(inputs)
            config = build_config(config_text)
            result = create_print_fit_adapter(design.rootComponent, bodies, config)
            _ui.messageBox(_format_result_message(config, result))
        except Exception:
            if _ui:
                _ui.messageBox("执行失败：\n\n%s" % traceback.format_exc())


class ValidateInputsHandler(_handler_base("ValidateInputsEventHandler")):
    def notify(self, args):
        try:
            inputs = args.inputs
            selection_input = inputs.itemById("source_bodies")
            args.areInputsValid = bool(selection_input and selection_input.selectionCount > 0)
        except Exception:
            args.areInputsValid = False


class InputChangedHandler(_handler_base("InputChangedEventHandler")):
    def notify(self, args):
        try:
            changed_id = args.input.id if args.input else ""
            _sync_dialog_visibility(args.inputs, changed_id)
        except Exception:
            if _ui:
                _ui.messageBox("更新面板状态失败：\n\n%s" % traceback.format_exc())


class ActivateHandler(_handler_base("CommandEventHandler")):
    def notify(self, args):
        try:
            app = adsk.core.Application.get()
            selections = app.userInterface.activeSelections
            selection_input = args.command.commandInputs.itemById("source_bodies")
            if not selection_input or selection_input.selectionCount > 0:
                return
            for index in range(selections.count):
                body = adsk.fusion.BRepBody.cast(selections.item(index).entity)
                if body and body.isSolid:
                    selection_input.addSelection(body)
        except Exception:
            pass


class DestroyHandler(_handler_base("CommandEventHandler")):
    def notify(self, args):
        pass


def run(context):
    if adsk is None:
        print("This script must run inside Autodesk Fusion 360.")
        return

    global _ui
    app = adsk.core.Application.get()
    ui = app.userInterface
    _ui = ui

    try:
        command_definition = ui.commandDefinitions.itemById(CMD_ID)
        if not command_definition:
            command_definition = ui.commandDefinitions.addButtonDefinition(
                CMD_ID,
                CMD_NAME,
                CMD_DESCRIPTION,
                "",
            )

        on_created = CommandCreatedHandler()
        command_definition.commandCreated.add(on_created)
        _handlers.append(on_created)

        panel = _target_panel(ui)
        if panel and not panel.controls.itemById(CMD_ID):
            control = panel.controls.addCommand(command_definition)
            control.isPromoted = True
            control.isPromotedByDefault = True

        adsk.autoTerminate(False)
    except Exception:
        ui.messageBox("加载 3D 打印标准件适配 Add-In 失败：\n\n%s" % traceback.format_exc())


def stop(context):
    if adsk is None:
        return
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        for panel in _candidate_panels(ui):
            control = panel.controls.itemById(CMD_ID)
            if control:
                control.deleteMe()
        command_definition = ui.commandDefinitions.itemById(CMD_ID)
        if command_definition:
            command_definition.deleteMe()
        _handlers.clear()
    except Exception:
        if ui:
            ui.messageBox("卸载 3D 打印标准件适配 Add-In 失败：\n\n%s" % traceback.format_exc())


def _build_command_dialog(inputs):
    overview = inputs.addTextBoxCommandInput(
        "overview",
        "",
        "<b>3D 打印标准件适配</b><br/>选择实体，设置公差和底座形状，然后自动生成配套底座、布尔刀具或打印补偿副本。",
        2,
        True,
    )
    overview.isFullWidth = True

    selection_input = inputs.addSelectionInput("source_bodies", "操作实体", "选择一个或多个实体 Body")
    selection_input.addSelectionFilter("SolidBodies")
    selection_input.setSelectionLimits(1, 0)

    main_group = inputs.addGroupCommandInput("main_group", "策略")
    main_group.isExpanded = True
    main_inputs = main_group.children
    _add_dropdown(main_inputs, "operation", "操作类型", OPERATION_OPTIONS, "生成配套底座/孔槽")
    _add_dropdown(main_inputs, "fit", "适配策略", FIT_OPTIONS, "螺纹 XY 间隙")
    _add_dropdown(main_inputs, "preset", "螺纹规格", {name: name for name in PRESET_OPTIONS}, "M4")
    _add_value(main_inputs, "diameter", "自定义直径", "4.0 mm")
    _add_value(main_inputs, "clearance", "单边公差", "0.20 mm")
    _add_value(main_inputs, "clearance_x", "X 单边公差", "0.20 mm")
    _add_value(main_inputs, "clearance_y", "Y 单边公差", "0.20 mm")
    _add_value(main_inputs, "clearance_z", "Z 单边公差", "0.00 mm")
    _add_value(main_inputs, "fit_adjust", "零件每边补偿", "-0.10 mm")

    blank_group = inputs.addGroupCommandInput("blank_group", "底座/毛坯")
    blank_group.isExpanded = True
    blank_inputs = blank_group.children
    _add_dropdown(blank_inputs, "blank", "底座形状", BLANK_OPTIONS, "六角螺母")
    _add_value(blank_inputs, "outer", "外径/六角对边", "8.0 mm")
    _add_value(blank_inputs, "box_x", "矩形 X 尺寸", "0 mm")
    _add_value(blank_inputs, "box_y", "矩形 Y 尺寸", "0 mm")
    _add_value(blank_inputs, "thickness", "厚度", "4.8 mm")
    _add_value(blank_inputs, "z_start", "底面 Z", "0 mm")
    _add_value(blank_inputs, "margin", "自动边距", "2.0 mm")

    advanced_group = inputs.addGroupCommandInput("advanced_group", "高级")
    advanced_group.isExpanded = False
    advanced_inputs = advanced_group.children
    _add_dropdown(advanced_inputs, "center", "缩放中心", CENTER_OPTIONS, "原点：适合螺纹轴心在原点")
    advanced_inputs.addStringValueInput("scale_x", "手动 X 比例", "")
    advanced_inputs.addStringValueInput("scale_y", "手动 Y 比例", "")
    advanced_inputs.addStringValueInput("scale_z", "手动 Z 比例", "")
    advanced_inputs.addBoolValueInput("cut", "执行布尔切割", True, "", True)
    advanced_inputs.addBoolValueInput("keep_tool", "保留刀具", True, "", True)
    _add_dropdown(advanced_inputs, "seal", "封头方式", {"不封头": "none", "圆柱封头": "cylinder"}, "不封头")
    _add_value(advanced_inputs, "seal_depth", "封头深度", "0 mm")
    _add_dropdown(advanced_inputs, "seal_direction", "封头方向", {"+Z": "+z", "-Z": "-z"}, "+Z")

    _sync_dialog_visibility(inputs)


def _add_dropdown(inputs, input_id, label, options, selected_label):
    dropdown = inputs.addDropDownCommandInput(input_id, label, adsk.core.DropDownStyles.TextListDropDownStyle)
    for label_text in options:
        dropdown.listItems.add(label_text, label_text == selected_label)
    return dropdown


def _add_value(inputs, input_id, label, expression):
    return inputs.addValueInput(input_id, label, "mm", adsk.core.ValueInput.createByString(expression))


def _sync_dialog_visibility(inputs, changed_id=""):
    fit = _selected_value(inputs.itemById("fit"), FIT_OPTIONS)
    operation = _selected_value(inputs.itemById("operation"), OPERATION_OPTIONS)
    blank = _selected_value(inputs.itemById("blank"), BLANK_OPTIONS)

    is_thread = fit == "thread"
    is_manual = fit == "manual"
    is_part = operation == "part"
    has_blank = operation == "cavity" and blank != "none"

    _set_visible(inputs, ("preset", "diameter"), is_thread)
    _set_visible(inputs, ("clearance",), not is_part and not is_manual)
    _set_visible(inputs, ("clearance_x", "clearance_y", "clearance_z"), not is_thread and not is_manual and not is_part)
    _set_visible(inputs, ("fit_adjust",), is_part and not is_manual)
    _set_visible(inputs, ("blank_group",), operation == "cavity")
    _set_visible(inputs, ("outer",), has_blank and blank in {"hex", "cylinder"})
    _set_visible(inputs, ("box_x", "box_y"), has_blank and blank == "box")
    _set_visible(inputs, ("thickness", "z_start", "margin"), has_blank)
    _set_visible(inputs, ("scale_x", "scale_y", "scale_z"), is_manual)
    _set_visible(inputs, ("cut",), operation == "cavity")
    _set_visible(inputs, ("keep_tool", "seal", "seal_depth", "seal_direction"), operation != "part")

    center_input = inputs.itemById("center")
    if center_input and changed_id == "fit" and fit != "thread":
        _select_dropdown_label(center_input, "自动：包围盒中心")
    elif center_input and changed_id == "fit":
        _select_dropdown_label(center_input, "原点：适合螺纹轴心在原点")

    blank_input = inputs.itemById("blank")
    if blank_input and operation == "tool":
        _select_dropdown_label(blank_input, "不生成底座")
    elif blank_input and changed_id in {"fit", "operation"} and is_thread and operation == "cavity":
        _select_dropdown_label(blank_input, "六角螺母")
    elif blank_input and changed_id in {"fit", "operation"} and operation == "cavity" and not is_thread and _selected_value(blank_input, BLANK_OPTIONS) == "hex":
        _select_dropdown_label(blank_input, "矩形底座")


def _set_visible(inputs, ids, visible):
    for input_id in ids:
        command_input = inputs.itemById(input_id)
        if command_input:
            command_input.isVisible = visible


def _select_dropdown_label(dropdown, label):
    for index in range(dropdown.listItems.count):
        item = dropdown.listItems.item(index)
        item.isSelected = item.name == label


def _selected_value(dropdown, options):
    if not dropdown or not dropdown.selectedItem:
        return next(iter(options.values()))
    return options.get(dropdown.selectedItem.name, dropdown.selectedItem.name)


def _mm_value(value_input):
    return cm_to_mm(value_input.value)


def _optional_positive_mm(inputs, input_id):
    value = _mm_value(inputs.itemById(input_id))
    return "" if abs(value) < 1e-9 else ("%g" % value)


def _config_text_from_inputs(inputs):
    operation = _selected_value(inputs.itemById("operation"), OPERATION_OPTIONS)
    fit = _selected_value(inputs.itemById("fit"), FIT_OPTIONS)
    blank = _selected_value(inputs.itemById("blank"), BLANK_OPTIONS)
    center = _selected_value(inputs.itemById("center"), CENTER_OPTIONS)
    seal = _selected_value(inputs.itemById("seal"), {"不封头": "none", "圆柱封头": "cylinder"})
    seal_direction = _selected_value(inputs.itemById("seal_direction"), {"+Z": "+z", "-Z": "-z"})

    parts = [
        "operation=%s" % operation,
        "fit=%s" % fit,
        "preset=%s" % _selected_value(inputs.itemById("preset"), {name: name for name in PRESET_OPTIONS}),
        "diameter=%g" % _mm_value(inputs.itemById("diameter")),
        "clearance=%g" % _mm_value(inputs.itemById("clearance")),
        "clearance_x=%g" % _mm_value(inputs.itemById("clearance_x")),
        "clearance_y=%g" % _mm_value(inputs.itemById("clearance_y")),
        "clearance_z=%g" % _mm_value(inputs.itemById("clearance_z")),
        "fit_adjust=%g" % _mm_value(inputs.itemById("fit_adjust")),
        "blank=%s" % blank,
        "center=%s" % center,
        "margin=%g" % _mm_value(inputs.itemById("margin")),
        "cut=%s" % str(bool(inputs.itemById("cut").value)).lower(),
        "keep_tool=%s" % str(bool(inputs.itemById("keep_tool").value)).lower(),
        "seal=%s" % seal,
        "seal_depth=%g" % _mm_value(inputs.itemById("seal_depth")),
        "seal_direction=%s" % seal_direction,
    ]

    for input_id, key in (("outer", "outer"), ("box_x", "box_x"), ("box_y", "box_y"), ("thickness", "thickness"), ("z_start", "z_start")):
        value = _optional_positive_mm(inputs, input_id) if input_id in {"outer", "box_x", "box_y", "thickness"} else "%g" % _mm_value(inputs.itemById(input_id))
        if value != "":
            parts.append("%s=%s" % (key, value))

    for input_id, key in (("scale_x", "scale_x"), ("scale_y", "scale_y"), ("scale_z", "scale_z")):
        value = inputs.itemById(input_id).value.strip()
        if value:
            parts.append("%s=%s" % (key, value))

    return "; ".join(parts)


def _bodies_from_selection_input(selection_input):
    bodies = []
    seen = set()
    if not selection_input:
        return bodies
    for index in range(selection_input.selectionCount):
        selection = selection_input.selection(index)
        body = adsk.fusion.BRepBody.cast(selection.entity)
        if body and body.isSolid:
            token = body.entityToken
            if token not in seen:
                bodies.append(body)
                seen.add(token)
    return bodies


def _target_panel(ui):
    panels = _candidate_panels(ui)
    return panels[0] if panels else None


def _candidate_panels(ui):
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    if not workspace:
        return []
    panels = []
    for panel_id in PANEL_CANDIDATES:
        panel = workspace.toolbarPanels.itemById(panel_id)
        if panel:
            panels.append(panel)
    return panels


def create_thread_companion(root, screw_body, config: AdapterConfig):
    return create_print_fit_adapter(root, [screw_body], config)


def create_print_fit_adapter(root, source_bodies, config: AdapterConfig):
    source_bodies = list(source_bodies)
    if not source_bodies:
        raise RuntimeError("没有可处理的实体。")

    safe_name = _safe_name(config.name)
    source_box = _union_bounding_box(source_bodies)
    source_size = _box_size_mm(source_box)
    scales = calculate_fit_scales(config, source_size)
    center_point = root.originConstructionPoint
    if config.center == "bbox":
        center_point = _create_scale_point(root, _box_center(source_box), "%s scale center" % safe_name)

    result = {
        "source_count": len(source_bodies),
        "operation": config.operation,
        "fit": config.fit,
        "scales": scales,
        "tool_names": [],
        "part_names": [],
        "blank_name": "",
        "combine_feature": "",
        "cap_created": False,
    }

    working_bodies = _copy_bodies_to_root(root, source_bodies)
    if config.operation == "part":
        for index, body in enumerate(working_bodies, start=1):
            body.name = "%s_print_adjusted_%02d" % (safe_name, index)
        _scale_bodies(root, working_bodies, center_point, scales, "Print compensation scale")
        result["part_names"] = [body.name for body in working_bodies if body and body.isValid]
        return result

    for index, body in enumerate(working_bodies, start=1):
        body.name = "%s_clearance_cutter_DO_NOT_PRINT_%02d" % (safe_name, index)
    _scale_bodies(root, working_bodies, center_point, scales, "Print-fit cutter scale")

    tool_bodies = list(working_bodies)
    tool_box = _union_bounding_box(tool_bodies)

    if config.seal == "cylinder" and config.seal_depth_mm > 0:
        cap_body = _create_cylindrical_seal_cap(root, tool_box, config)
        tool_bodies.append(cap_body)
        result["cap_created"] = True

    result["tool_names"] = [body.name for body in tool_bodies if body and body.isValid]

    blank_body = None
    if config.blank != "none":
        blank_body = _create_blank(root, config, _union_bounding_box(tool_bodies))
        blank_body.name = "%s_%s_blank" % (safe_name, config.blank)
        result["blank_name"] = blank_body.name

    if config.operation == "cavity" and config.cut and blank_body:
        combine_feature = _cut_blank_with_tools(root, blank_body, tool_bodies, config.keep_tool)
        blank_body.name = "%s_print_fit_%s" % (safe_name, config.blank)
        result["blank_name"] = blank_body.name
        result["combine_feature"] = combine_feature.name if combine_feature else ""

    return result


def _select_source_bodies(ui):
    bodies = []
    seen = set()
    selections = ui.activeSelections
    for index in range(selections.count):
        entity = selections.item(index).entity
        body = adsk.fusion.BRepBody.cast(entity)
        if body and body.isSolid:
            token = body.entityToken
            if token not in seen:
                bodies.append(body)
                seen.add(token)

    if bodies:
        return bodies

    try:
        selection = ui.selectEntity("选择要适配的实体（Solid Body）", "SolidBodies")
    except Exception:
        return []
    if not selection:
        return []
    body = adsk.fusion.BRepBody.cast(selection.entity)
    return [body] if body and body.isSolid else []


def _copy_bodies_to_root(root, bodies):
    copies = []
    for body in bodies:
        copied = body.copyToComponent(root)
        if not copied:
            raise RuntimeError("复制实体失败：%s" % (body.name or "(unnamed body)"))
        copies.append(copied)
    return copies


def _scale_bodies(root, bodies, scale_point, scales, feature_name):
    collection = adsk.core.ObjectCollection.create()
    for body in bodies:
        collection.add(body)

    scale_features = root.features.scaleFeatures
    scale_input = scale_features.createInput(
        collection,
        scale_point,
        adsk.core.ValueInput.createByReal(1.0),
    )
    ok = scale_input.setToNonUniform(
        adsk.core.ValueInput.createByReal(scales[0]),
        adsk.core.ValueInput.createByReal(scales[1]),
        adsk.core.ValueInput.createByReal(scales[2]),
    )
    if not ok:
        raise RuntimeError("设置非均匀缩放失败。")
    feature = scale_features.add(scale_input)
    if feature:
        feature.name = "%s %.6f %.6f %.6f" % (feature_name, scales[0], scales[1], scales[2])
    return feature


def _create_offset_xy_plane(root, z_mm: float, name: str):
    plane_input = root.constructionPlanes.createInput()
    ok = plane_input.setByOffset(
        root.xYConstructionPlane,
        adsk.core.ValueInput.createByString("%g mm" % z_mm),
    )
    if not ok:
        raise RuntimeError("创建偏移平面失败: %s" % name)
    plane = root.constructionPlanes.add(plane_input)
    plane.name = name
    return plane


def _create_scale_point(root, point, name: str):
    plane = _create_offset_xy_plane(root, cm_to_mm(point.z), "%s plane" % name)
    sketch = root.sketches.add(plane)
    sketch.name = "%s sketch" % name
    point_on_sketch = sketch.sketchPoints.add(adsk.core.Point3D.create(point.x, point.y, 0))
    sketch.isVisible = False
    plane.isLightBulbOn = False
    return point_on_sketch


def _create_blank(root, config: AdapterConfig, tool_box):
    min_x, min_y, min_z, max_x, max_y, max_z = _box_values_mm(tool_box)
    size_x, size_y, size_z = _box_size_mm(tool_box)
    center_x_cm = (tool_box.minPoint.x + tool_box.maxPoint.x) / 2.0
    center_y_cm = (tool_box.minPoint.y + tool_box.maxPoint.y) / 2.0

    z_start_mm = config.z_start_mm if config.z_start_mm is not None else min_z - config.margin_z_mm
    thickness_mm = config.thickness_mm if config.thickness_mm is not None else size_z + 2.0 * config.margin_z_mm
    if thickness_mm <= 0:
        raise RuntimeError("毛坯厚度必须大于 0。")

    plane = _create_offset_xy_plane(root, z_start_mm, "%s blank start plane" % config.name)
    sketch = root.sketches.add(plane)
    sketch.name = "%s blank sketch" % config.name

    if config.blank == "hex":
        outer_mm = config.outer_mm if config.outer_mm is not None else max(size_x, size_y) + 2.0 * max(config.margin_x_mm, config.margin_y_mm)
        radius_cm = mm_to_cm(hex_circumradius_from_across_flats(outer_mm))
        _draw_regular_polygon(sketch, center_x_cm, center_y_cm, 6, radius_cm, math.radians(30.0))
    elif config.blank == "cylinder":
        outer_mm = config.outer_mm if config.outer_mm is not None else math.hypot(size_x, size_y) + 2.0 * max(config.margin_x_mm, config.margin_y_mm)
        sketch.sketchCurves.sketchCircles.addByCenterRadius(
            adsk.core.Point3D.create(center_x_cm, center_y_cm, 0),
            mm_to_cm(outer_mm / 2.0),
        )
    elif config.blank == "box":
        width_mm = config.box_x_mm if config.box_x_mm is not None else size_x + 2.0 * config.margin_x_mm
        depth_mm = config.box_y_mm if config.box_y_mm is not None else size_y + 2.0 * config.margin_y_mm
        _draw_centered_box(sketch, center_x_cm, center_y_cm, mm_to_cm(width_mm), mm_to_cm(depth_mm))
    else:
        raise RuntimeError("unsupported blank type %s" % config.blank)

    if sketch.profiles.count < 1:
        raise RuntimeError("毛坯草图没有形成封闭轮廓。")

    extrude = root.features.extrudeFeatures.addSimple(
        sketch.profiles.item(0),
        adsk.core.ValueInput.createByString("%g mm" % thickness_mm),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    )
    sketch.isVisible = False
    plane.isLightBulbOn = False
    if not extrude or extrude.bodies.count < 1:
        raise RuntimeError("毛坯拉伸失败。")
    return extrude.bodies.item(0)


def _draw_centered_box(sketch, center_x_cm, center_y_cm, width_cm, depth_cm):
    half_x = width_cm / 2.0
    half_y = depth_cm / 2.0
    lines = sketch.sketchCurves.sketchLines
    points = [
        adsk.core.Point3D.create(center_x_cm - half_x, center_y_cm - half_y, 0),
        adsk.core.Point3D.create(center_x_cm + half_x, center_y_cm - half_y, 0),
        adsk.core.Point3D.create(center_x_cm + half_x, center_y_cm + half_y, 0),
        adsk.core.Point3D.create(center_x_cm - half_x, center_y_cm + half_y, 0),
    ]
    for index in range(4):
        lines.addByTwoPoints(points[index], points[(index + 1) % 4])


def _draw_regular_polygon(sketch, center_x_cm, center_y_cm, sides: int, radius_cm: float, rotation_rad: float):
    lines = sketch.sketchCurves.sketchLines
    points = []
    for index in range(sides):
        angle = rotation_rad + 2.0 * math.pi * index / sides
        points.append(
            adsk.core.Point3D.create(
                center_x_cm + radius_cm * math.cos(angle),
                center_y_cm + radius_cm * math.sin(angle),
                0,
            )
        )
    for index in range(sides):
        lines.addByTwoPoints(points[index], points[(index + 1) % sides])


def _create_cylindrical_seal_cap(root, tool_box, config: AdapterConfig):
    min_x, min_y, min_z, max_x, max_y, max_z = _box_values_mm(tool_box)
    center_x_cm = (tool_box.minPoint.x + tool_box.maxPoint.x) / 2.0
    center_y_cm = (tool_box.minPoint.y + tool_box.maxPoint.y) / 2.0
    half_x_cm = (tool_box.maxPoint.x - tool_box.minPoint.x) / 2.0
    half_y_cm = (tool_box.maxPoint.y - tool_box.minPoint.y) / 2.0
    radius_cm = max(half_x_cm, half_y_cm) * config.seal_oversize
    extra_mm = 0.05

    if config.seal_direction == "+z":
        start_z_mm = max_z - config.seal_depth_mm
        distance_mm = config.seal_depth_mm + extra_mm
    else:
        start_z_mm = min_z - extra_mm
        distance_mm = config.seal_depth_mm + extra_mm

    plane = _create_offset_xy_plane(root, start_z_mm, "%s seal cap plane" % config.name)
    sketch = root.sketches.add(plane)
    sketch.name = "%s seal cap sketch" % config.name
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(center_x_cm, center_y_cm, 0),
        radius_cm,
    )

    extrude = root.features.extrudeFeatures.addSimple(
        sketch.profiles.item(0),
        adsk.core.ValueInput.createByString("%g mm" % distance_mm),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    )
    sketch.isVisible = False
    plane.isLightBulbOn = False
    if not extrude or extrude.bodies.count < 1:
        raise RuntimeError("封头圆柱创建失败。")
    cap = extrude.bodies.item(0)
    cap.name = "%s_seal_cap_DO_NOT_PRINT" % _safe_name(config.name)
    return cap


def _cut_blank_with_tools(root, blank_body, tool_bodies, keep_tool: bool):
    tools = adsk.core.ObjectCollection.create()
    for body in tool_bodies:
        tools.add(body)
    combine_input = root.features.combineFeatures.createInput(blank_body, tools)
    combine_input.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
    combine_input.isKeepToolBodies = keep_tool
    feature = root.features.combineFeatures.add(combine_input)
    if not feature:
        raise RuntimeError("布尔切割失败，请确认毛坯与放大刀具相交。")
    feature.name = "Cut print-fit cavity"
    return feature


def _union_bounding_box(bodies):
    if not bodies:
        raise RuntimeError("不能计算空实体集合的包围盒。")
    first = bodies[0].boundingBox
    min_x = first.minPoint.x
    min_y = first.minPoint.y
    min_z = first.minPoint.z
    max_x = first.maxPoint.x
    max_y = first.maxPoint.y
    max_z = first.maxPoint.z

    for body in bodies[1:]:
        box = body.boundingBox
        min_x = min(min_x, box.minPoint.x)
        min_y = min(min_y, box.minPoint.y)
        min_z = min(min_z, box.minPoint.z)
        max_x = max(max_x, box.maxPoint.x)
        max_y = max(max_y, box.maxPoint.y)
        max_z = max(max_z, box.maxPoint.z)

    return adsk.core.BoundingBox3D.create(
        adsk.core.Point3D.create(min_x, min_y, min_z),
        adsk.core.Point3D.create(max_x, max_y, max_z),
    )


def _box_center(box):
    return adsk.core.Point3D.create(
        (box.minPoint.x + box.maxPoint.x) / 2.0,
        (box.minPoint.y + box.maxPoint.y) / 2.0,
        (box.minPoint.z + box.maxPoint.z) / 2.0,
    )


def _box_size_mm(box):
    return (
        cm_to_mm(box.maxPoint.x - box.minPoint.x),
        cm_to_mm(box.maxPoint.y - box.minPoint.y),
        cm_to_mm(box.maxPoint.z - box.minPoint.z),
    )


def _box_values_mm(box):
    return (
        cm_to_mm(box.minPoint.x),
        cm_to_mm(box.minPoint.y),
        cm_to_mm(box.minPoint.z),
        cm_to_mm(box.maxPoint.x),
        cm_to_mm(box.maxPoint.y),
        cm_to_mm(box.maxPoint.z),
    )


def _format_result_message(config: AdapterConfig, result) -> str:
    scales = result["scales"]
    lines = [
        "生成完成。",
        "",
        "输入实体数量: %s" % result["source_count"],
        "操作: %s" % result["operation"],
        "适配策略: %s" % result["fit"],
        "缩放: X %.6f / Y %.6f / Z %.6f" % (scales[0], scales[1], scales[2]),
        "中心: %s" % config.center,
    ]
    if result["part_names"]:
        lines.append("打印补偿副本: %s" % ", ".join(result["part_names"]))
    if result["tool_names"]:
        lines.append("刀具体: %s" % ", ".join(result["tool_names"]))
    if result["blank_name"]:
        lines.append("底座/毛坯: %s" % result["blank_name"])
    if result["combine_feature"]:
        lines.append("布尔特征: %s" % result["combine_feature"])
    if result["cap_created"]:
        lines.append("已创建封头圆柱，注意它可能改变头部挖槽形状。")
    if config.warning_messages:
        lines.extend(["", "警告:"])
        lines.extend("- %s" % message for message in config.warning_messages)
    if config.operation in {"tool", "cavity"}:
        lines.extend(["", "带 DO_NOT_PRINT 的刀具仅用于布尔切割，不要打印。"])
    return "\n".join(lines)


def _safe_name(value: str) -> str:
    safe = []
    for char in value:
        if char.isalnum() or char in {"_", "-", "."}:
            safe.append(char)
        else:
            safe.append("_")
    return "".join(safe).strip("_") or "PrintFit"
