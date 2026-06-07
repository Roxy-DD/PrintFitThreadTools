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
import dataclasses
import importlib


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import threadfit_core
importlib.reload(threadfit_core)

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

_LANG_DICT = {
    "3D打印标准件适配": "3D Print Fit Adapter",
    "为 McMaster/Fusion 标准件生成带打印公差的刀具、底座或补偿副本。": "Generate print-fit cutters, bases, cavities, or adjusted copies from standard parts.",
    "生成配套底座/孔槽": "Generate Base / Cavity",
    "只生成布尔刀具": "Generate Boolean Cutter Only",
    "生成打印补偿副本": "Generate Print-Adjusted Part",
    "径向缩放 (仅 XY 方向, 需零件直立)": "Radial Scale (XY only, part upright)",
    "等比缩放 (XYZ 方向)": "Uniform Scale (XYZ)",
    "真实面偏移 (法向等距)": "Normal Offset (Precise & slow)",
    "手动指定比例": "Manual Scale",
    "宽松插入 (+0.20mm)": "Loose Fit (+0.20mm)",
    "普通配合 (+0.10mm)": "Normal Fit (+0.10mm)",
    "精准/滑动 (+0.05mm)": "Tight / Sliding (+0.05mm)",
    "无公差 (0.00mm)": "No Clearance (0.00mm)",
    "过盈/热熔 (-0.15mm)": "Interference / Heat-set (-0.15mm)",
    "自定义": "Custom",
    "矩形底座": "Rectangular Base",
    "圆形底座": "Cylindrical Base",
    "六角螺母": "Hex Nut Base",
    "不生成底座": "No Base",
    "智能：基于点选圆提取 (推荐)": "Smart: Extract from Circle (Rec.)",
    "自动：包围盒中心 (适合对称体)": "Auto: Bounding Box Center",
    "原点：全局坐标系原点": "Origin: Global Origin",
    "<b>3D 打印标准件适配</b><br/>选择实体，设置公差和底座形状，然后自动生成配套底座、布尔刀具或打印补偿副本。": "<b>3D Print Fit Adapter</b><br/>Select bodies, set clearance and base shape, then automatically generate matching bases, boolean cutters, or compensated print copies.",
    "操作实体": "Source Bodies",
    "选择一个或多个实体 Body": "Select one or more solid bodies",
    "零件与公差": "Part & Clearance",
    "底座边界": "Base Bounds",
    "专家模式": "Expert Mode",
    "操作类型": "Operation Type",
    "选择要生成的结果类型": "Select the result type to generate",
    "【配套底座/孔槽】：直接在外围生成带公差的孔槽底座。适用场景：为零件制作专属的安装底座，或快速打印公差配合测试件。\n【生成刀具体】：提取放大后的零件本体（不含底座）。适用场景：将其作为“刻刀”，在您设计的复杂机械外壳上，使用布尔运算精准挖出安装孔。\n【打印补偿副本】：对原零件本身进行尺寸补偿。适用场景：直接 3D 打印该零件时，预先抵消塑料热收缩误差（如缩小0.15mm），确保打印成品能顺利装配。": "[Generate Base / Cavity]: Make dedicated bases or quick test fits.\n[Generate Boolean Cutter]: Use as a boolean tool to cut precise holes in enclosures.\n[Generate Print-Adjusted Part]: Offset 3D printing shrinkage directly on the part.",
    "适配策略": "Fit Strategy",
    "选择间隙生成的计算底层原理": "Choose the underlying calculation for clearance",
    "【径向缩放 (仅 XY 方向, 需零件直立)】：底部Z轴保持不变，专为螺丝/螺纹设计，保护螺距不被破坏。注意：必须确保零件在绝对坐标系中竖直向上放置 (Z-up)，否则由于 Fusion 360 缩放轴向限制，会导致变形！\n【等比缩放 (XYZ 方向)】：全方向均匀放大，速度极快，适合大部分对称零件。\n【真实面偏移】：沿法线严格推覆，极其精准但面数多时极其耗时。": "[Radial Scale (XY only)]: Z-axis remains unchanged, designed for threads to protect pitch. NOTE: part must be vertical (Z-up)!\n[Uniform Scale (XYZ)]: Quick uniform scaling.\n[Normal Offset]: Strict surface pushing along normal. Precise but slow.",
    "螺纹规格": "Thread Spec",
    "快速选择标准件的外径尺寸": "Quickly select outer diameter for standard parts",
    "圆柱参考/定心点 (可选)": "Cylinder Ref / Center (Optional)",
    "选择圆柱面/圆边提取直径和圆心。或者单独选择一个顶点/草图点来强制指定圆心（此时需手动输入直径）。": "Select a cylindrical face or edge to extract diameter and center. Or select a point/vertex to force a center.",
    "智能提取圆心与直径": "Smart Extract Center & Diameter",
    "如果您不知道模型直径，请点选屏幕上的圆环边缘或圆柱面，系统会自动提取其真实的直径并填入下方，同时全参数化绑定该几何中心。\n如果您只想自定义缩放中心而不修改直径，请直接选择屏幕上的某个点（顶点、草图点等）。": "Select a circular edge or cylindrical face to extract diameter and parametrically bind the center.\nIf you just want to set the center, click a point.",
    "自定义直径": "Custom Diameter",
    "公差预设": "Clearance Preset",
    "快速设置常见的 3D 打印公差": "Quick settings for common 3D printing tolerances",
    "宽松插入：适合需要顺滑插入、经常拔插的零件。\n精准/滑动：适合要求严丝合缝的卡扣或滑动件。\n过盈/热熔：用于强行压入或用电烙铁加热植入铜花母（热熔嵌件）。": "Loose Fit: For smooth, frequent insertion.\nTight/Sliding: For precise snaps or sliders.\nInterference/Heat-set: For forced press-fits or heat-set inserts.",
    "单边公差": "Radial Clearance",
    "零件四周预留的装配空隙": "Assembly gap left around the part",
    "通常 3D 打印推荐设置在 0.15mm - 0.25mm 之间。此数值将生成为全局参数，可随时修改。": "Typically recommended between 0.15mm - 0.25mm for 3D printing. Generated as a global parameter.",
    "开启封头 (填平坑洞并突破)": "Enable Cap (Fill holes & punch)",
    "将坑洞完全填平为实心，并可向外延伸": "Fills holes to make a solid cap, and can extend outwards",
    "勾选后，插件会自动填满您选择的平面或坑底，并可以往外挤出一段距离，形成一个无缝的完美打孔刀具。": "Check to automatically fill the selected face/pit and extrude outwards, creating a seamless hole-punch tool.",
    "封头起点面 (必选)": "Cap Start Face (Required)",
    "请点选螺丝顶面或内六角坑的底面。插件将从该高度开始填平并向外突破。": "Select the screw top face or the bottom of the hex socket. The add-in will fill from here and extend out.",
    "向外突破长度": "Punch-through Length",
    "封头高出螺丝顶部的额外贯穿距离": "Extra protrusion distance past the screw top",
    "确保刀具有足够的长度刺穿外壳。如果您只想要填平坑洞而不冒出头，可以设为 0 mm。": "Ensures the cutter is long enough to pierce the shell. Set to 0 if you only want to fill the hole.",
    "底座/毛坯设置": "Base / Blank Settings",
    "底座生成方式": "Base Generation Mode",
    "底面参考 (可选)": "Bottom Ref (Optional)",
    "选择模型表面、顶点作为底座底面": "Select a face or vertex as the base bottom",
    "拉伸底座的起始边界": "Starting boundary for base extrusion",
    "点击模型表面或顶点，底座将以此为起点。\n如果不选，系统将自动使用包围盒计算。": "Click a face/vertex to start the base from there.\nIf empty, bounding box is used.",
    "顶面参考 (可选)": "Top Ref (Optional)",
    "选择模型表面、顶点作为底座顶面": "Select a face or vertex as the base top",
    "拉伸底座的终止边界": "Ending boundary for base extrusion",
    "点击模型表面或顶点，底座将刚好贴合至该处。\n如果不选，系统将自动使用包围盒计算。": "Click a face/vertex to end the base there.\nIf empty, bounding box is used.",
    "外径/六角对边": "Outer Dia / Hex AF",
    "矩形 X 尺寸": "Box X Size",
    "矩形 Y 尺寸": "Box Y Size",
    "厚度": "Thickness",
    "底面 Z": "Bottom Z",
    "自动边距": "Auto Margin",
    "X 单边公差": "X Clearance",
    "Y 单边公差": "Y Clearance",
    "Z 单边公差": "Z Clearance",
    "零件每边补偿": "Part Offset Per Side",
    "缩放中心": "Scale Center",
    "手动 X 比例": "Manual X Scale",
    "手动 Y 比例": "Manual Y Scale",
    "手动 Z 比例": "Manual Z Scale",
    "执行布尔切割": "Execute Boolean Cut",
    "保留刀具": "Keep Cutter Bodies",
    "<i>适用场景：为零件制作专属的安装底座，或快速打印公差配合测试件。</i>": "<i>Use case: Make dedicated bases or quick test fits.</i>",
    "<i>适用场景：将其作为“刻刀”，在您设计的复杂外壳上，使用布尔运算精准挖出安装孔。</i>": "<i>Use case: Use as a boolean tool to cut precise holes.</i>",
    "<i>适用场景：直接 3D 打印该零件时，预先抵消塑料热收缩误差，确保打印成品能顺利装配。</i>": "<i>Use case: Offset 3D printing shrinkage directly on the part.</i>",
    "请先打开 Fusion 360 Design 文件。": "Please open a Fusion 360 Design file first.",
    "请至少选择一个实体 Body。": "Please select at least one Solid Body.",
    "正在分析几何体...": "Analyzing geometry...",
    "正在提取并分析选定实体...": "Extracting and analyzing selected bodies...",
    "正在计算实体布尔和缩放操作...": "Calculating boolean and scale operations...",
    "创建命令面板失败": "Failed to create command panel",
    "执行失败": "Execution failed",
    "预览失败": "Preview failed",
    "验证输入失败": "Validation failed",
    "更新面板状态失败": "Failed to update panel visibility",
    "选择要适配的实体（Solid Body）": "Select solid bodies",
    "没有可处理的实体。": "No processable bodies.",
    "开启封头时，必须选择一个【封头起点面】。请点选需要填平的坑底面或螺丝顶面。": "When Cap is enabled, you must select a [Cap Start Face].",
    "面偏移计算失败。": "Surface offset calculation failed.",
    "设置非均匀缩放失败。": "Failed to set non-uniform scale.",
    "毛坯草图没有形成封闭轮廓。": "Blank sketch did not form a closed profile.",
    "毛坯厚度必须大于 0。": "Blank thickness must be greater than 0.",
    "毛坯拉伸失败。": "Blank extrusion failed.",
    "封头圆柱创建失败。": "Failed to create seal cap cylinder.",
    "布尔切割失败，请确认毛坯与放大刀具相交。": "Boolean cut failed, ensure blank intersects with tools.",
    "不能计算空实体集合的包围盒。": "Cannot compute bounding box for empty bodies.",
    "生成完成。": "Generation complete.",
    "输入实体数量: %s": "Input bodies count: %s",
    "操作: %s": "Operation: %s",
    "适配策略: %s": "Fit Strategy: %s",
    "缩放: X %.6f / Y %.6f / Z %.6f": "Scale: X %.6f / Y %.6f / Z %.6f",
    "中心: %s": "Center: %s",
    "打印补偿副本: %s": "Adjusted Print Copies: %s",
    "刀具体: %s": "Cutter Bodies: %s",
    "底座/毛坯: %s": "Base / Blank: %s",
    "布尔特征: %s": "Boolean Feature: %s",
    "已创建封头圆柱，注意它可能改变头部挖槽形状。": "Cap cylinder created.",
    "警告:": "Warnings:",
    "带 DO_NOT_PRINT 的刀具仅用于布尔切割，不要打印。": "Cutter bodies with DO_NOT_PRINT are only for boolean cuts."
}

_IS_ENGLISH = None

def _is_english_mode():
    global _IS_ENGLISH
    if _IS_ENGLISH is not None:
        return _IS_ENGLISH
    _IS_ENGLISH = False
    try:
        if adsk is not None:
            app = adsk.core.Application.get()
            lang = app.preferences.generalPreferences.userLanguage
            if lang not in (adsk.core.UserLanguages.ChinesePRCLanguage, getattr(adsk.core.UserLanguages, "ChineseTaiwanLanguage", -1)):
                _IS_ENGLISH = True
    except:
        pass
    return _IS_ENGLISH

def _TR(text: str) -> str:
    if _is_english_mode():
        return _LANG_DICT.get(text, text)
    return text

def _tr_dict(d: dict) -> dict:
    return {_TR(k): v for k, v in d.items()}

OPERATION_OPTIONS = {
    "生成配套底座/孔槽": "cavity",
    "只生成布尔刀具": "tool",
    "生成打印补偿副本": "part",
}
FIT_OPTIONS = {
    "径向缩放 (仅 XY 方向, 需零件直立)": "thread",
    "等比缩放 (XYZ 方向)": "xyz",
    "真实面偏移 (法向等距)": "universal",
    "手动指定比例": "manual",
}
FIT_PROFILES = {
    "宽松插入 (+0.20mm)": "0.20 mm",
    "普通配合 (+0.10mm)": "0.10 mm",
    "精准/滑动 (+0.05mm)": "0.05 mm",
    "无公差 (0.00mm)": "0.00 mm",
    "过盈/热熔 (-0.15mm)": "-0.15 mm",
    "自定义": ""
}
BLANK_OPTIONS = {
    "矩形底座": "box",
    "圆形底座": "cylinder",
    "六角螺母": "hex",
    "不生成底座": "none",
}
CENTER_OPTIONS = {
    "智能：基于点选圆提取 (推荐)": "smart",
    "自动：包围盒中心 (适合对称体)": "bbox",
    "原点：全局坐标系原点": "origin",
}
PRESET_OPTIONS = ("M2", "M2.5", "M3", "M4", "M5", "M6", "M8", "M10", "自定义")

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
            execute_preview_handler = ExecutePreviewHandler()
            validate_handler = ValidateInputsHandler()
            input_changed_handler = InputChangedHandler()
            activate_handler = ActivateHandler()
            destroy_handler = DestroyHandler()

            command.execute.add(execute_handler)
            command.executePreview.add(execute_preview_handler)
            command.validateInputs.add(validate_handler)
            command.inputChanged.add(input_changed_handler)
            command.activate.add(activate_handler)
            command.destroy.add(destroy_handler)

            _handlers.extend([
                execute_handler,
                execute_preview_handler,
                validate_handler,
                input_changed_handler,
                activate_handler,
                destroy_handler,
            ])
        except Exception:
            _log_error(_TR("创建命令面板失败"), traceback.format_exc(), show_message_box=True)


class ExecuteHandler(_handler_base("CommandEventHandler")):
    def notify(self, args):
        try:
            result = _run_execution_pipeline(args.command.commandInputs, is_preview=False)
            if result is not None:
                config, res_dict = result
                _ui.messageBox(_format_result_message(config, res_dict))
        except Exception:
            _log_error(_TR("执行失败"), traceback.format_exc(), show_message_box=True)


class ExecutePreviewHandler(_handler_base("CommandEventHandler")):
    def notify(self, args):
        try:
            _run_execution_pipeline(args.command.commandInputs, is_preview=True)
            args.isValidResult = True
        except Exception as e:
            err = traceback.format_exc()
            try:
                with open(r"d:\项目文件\code\3d打印标准件\fusion\PrintFitThreadTools\debug_error.log", "w", encoding="utf-8") as f:
                    f.write(err)
            except:
                pass
            _log_error(_TR("预览失败"), err, show_message_box=False)


class ValidateInputsHandler(_handler_base("ValidateInputsEventHandler")):
    def notify(self, args):
        try:
            inputs = args.inputs
            selection_input = inputs.itemById("source_bodies")
            args.areInputsValid = bool(selection_input and selection_input.selectionCount > 0)
        except Exception:
            args.areInputsValid = False
            _log_error(_TR("验证输入失败"), traceback.format_exc(), show_message_box=False)

def _run_execution_pipeline(inputs, is_preview: bool):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        if not is_preview and _ui:
            _ui.messageBox(_TR("请先打开 Fusion 360 Design 文件。"))
        return None

    progress = None
    if not is_preview and _ui:
        progress = _ui.createProgressDialog()
        progress.cancelButtonText = "Cancel"
        progress.isBackgroundDependent = False
        progress.isCancelButtonShown = False
        progress.show(_TR("3D打印标准件适配"), _TR("正在分析几何体..."), 0, 100, 0)

    try:
        if progress:
            progress.message = _TR("正在提取并分析选定实体...")
            progress.progressValue = 10
            adsk.doEvents()

        bodies = _bodies_from_selection_input(inputs.itemById("source_bodies"))
        if not bodies:
            if not is_preview and _ui:
                _ui.messageBox(_TR("请至少选择一个实体 Body。"))
            return None

        config_dict = _config_dict_from_inputs(inputs)
        config = build_config(config_dict)
        
        center_entity = None
        if config.center == "smart":
            dia_ref = inputs.itemById("diameter_ref")
            if dia_ref and dia_ref.selectionCount > 0:
                center_entity = dia_ref.selection(0).entity
        
        bottom_ref_input = inputs.itemById("bottom_ref")
        bottom_entity = bottom_ref_input.selection(0).entity if bottom_ref_input and bottom_ref_input.selectionCount > 0 else None
        
        top_ref_input = inputs.itemById("top_ref")
        top_entity = top_ref_input.selection(0).entity if top_ref_input and top_ref_input.selectionCount > 0 else None
        
        seal_ref_input = inputs.itemById("seal_ref")
        seal_entity = seal_ref_input.selection(0).entity if seal_ref_input and seal_ref_input.selectionCount > 0 else None
        
        if progress:
            progress.message = _TR("正在计算实体布尔和缩放操作...")
            progress.progressValue = 40
            adsk.doEvents()
            
        result = create_print_fit_adapter(design.rootComponent, bodies, config, top_entity, bottom_entity, center_entity, seal_entity=seal_entity, is_preview=is_preview, progress=progress)
        
        if progress:
            progress.progressValue = 100
            progress.hide()
            
        return config, result
        
    except Exception as e:
        if progress:
            progress.hide()
        raise e


class InputChangedHandler(_handler_base("InputChangedEventHandler")):
    def notify(self, args):
        try:
            changed_id = args.input.id if args.input else ""
            _sync_dialog_visibility(args.inputs, changed_id)
            
            if changed_id == "diameter_ref":
                dia_ref = args.inputs.itemById("diameter_ref")
                if dia_ref and dia_ref.selectionCount > 0:
                    entity = dia_ref.selection(0).entity
                    radius_cm = None
                    if entity.objectType in (adsk.fusion.BRepEdge.classType(), "adsk::fusion::BRepEdgeProxy") and (entity.geometry.objectType == adsk.core.Circle3D.classType() or entity.geometry.objectType == adsk.core.Arc3D.classType()):
                        radius_cm = entity.geometry.radius
                    elif entity.objectType in (adsk.fusion.BRepFace.classType(), "adsk::fusion::BRepFaceProxy") and entity.geometry.objectType == adsk.core.Cylinder.classType():
                        radius_cm = entity.geometry.radius
                    
                    if radius_cm is not None:
                        dia_mm = cm_to_mm(radius_cm * 2.0)
                        preset = args.inputs.itemById("preset")
                        if preset:
                            _select_dropdown_label(preset, _TR("自定义"))
                        dia_input = args.inputs.itemById("diameter")
                        if dia_input:
                            dia_input.expression = "%.3f mm" % dia_mm
            
            elif changed_id == "fit_profile":
                profile = args.inputs.itemById("fit_profile")
                if profile and profile.selectedItem.name != _TR("自定义"):
                    val_str = _tr_dict(FIT_PROFILES).get(profile.selectedItem.name)
                    if val_str:
                        for cid in ("clearance", "clearance_x", "clearance_y"):
                            inp = args.inputs.itemById(cid)
                            if inp:
                                inp.expression = val_str
            
            elif changed_id in ("clearance", "clearance_x", "clearance_y", "clearance_z"):
                profile = args.inputs.itemById("fit_profile")
                if profile:
                    _select_dropdown_label(profile, _TR("自定义"))
                            
        except Exception:
            _log_error(_TR("更新面板状态失败"), traceback.format_exc(), show_message_box=False)


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

def _log_error(title, trace, show_message_box=False):
    message = f"[{title}]\n{trace}"
    print(message)
    try:
        app = adsk.core.Application.get()
        text_palette = app.userInterface.palettes.itemById('TextCommands')
        if text_palette:
            text_palette.writeText(message)
    except:
        pass
    if show_message_box and _ui:
        _ui.messageBox(message)


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
                _TR(CMD_NAME),
                _TR(CMD_DESCRIPTION),
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
        ui.messageBox(_TR("加载 3D 打印标准件适配 Add-In 失败：\n\n%s") % traceback.format_exc())


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
            ui.messageBox(_TR("卸载 3D 打印标准件适配 Add-In 失败：\n\n%s") % traceback.format_exc())


def _build_command_dialog(inputs):
    overview = inputs.addTextBoxCommandInput(
        "overview",
        "",
        _TR("<b>3D 打印标准件适配</b><br/>选择实体，设置公差和底座形状，然后自动生成配套底座、布尔刀具或打印补偿副本。"),
        3,
        True,
    )
    overview.isFullWidth = True

    selection_input = inputs.addSelectionInput("source_bodies", _TR("操作实体"), _TR("选择一个或多个实体 Body"))
    selection_input.addSelectionFilter("SolidBodies")
    selection_input.setSelectionLimits(1, 0)

    tab_core = inputs.addTabCommandInput("tab_core", _TR("零件与公差"))
    tab_geom = inputs.addTabCommandInput("tab_geom", _TR("底座边界"))
    tab_adv = inputs.addTabCommandInput("tab_adv", _TR("专家模式"))

    # 标签页 1：零件与公差
    core_inputs = tab_core.children
    op_input = _add_dropdown(core_inputs, "operation", _TR("操作类型"), _tr_dict(OPERATION_OPTIONS), _TR("生成配套底座/孔槽"))
    op_input.tooltip = _TR("选择要生成的结果类型")
    op_input.tooltipDescription = _TR("【配套底座/孔槽】：直接在外围生成带公差的孔槽底座。适用场景：为零件制作专属的安装底座，或快速打印公差配合测试件。\n【生成刀具体】：提取放大后的零件本体（不含底座）。适用场景：将其作为“刻刀”，在您设计的复杂机械外壳上，使用布尔运算精准挖出安装孔。\n【打印补偿副本】：对原零件本身进行尺寸补偿。适用场景：直接 3D 打印该零件时，预先抵消塑料热收缩误差（如缩小0.15mm），确保打印成品能顺利装配。")
    op_desc = core_inputs.addTextBoxCommandInput("op_desc", "", "", 2, True)
    op_desc.isFullWidth = True

    fit_input = _add_dropdown(core_inputs, "fit", _TR("适配策略"), _tr_dict(FIT_OPTIONS), _TR("径向缩放 (仅 XY 方向, 需零件直立)"))
    fit_input.tooltip = _TR("选择间隙生成的计算底层原理")
    fit_input.tooltipDescription = _TR("【径向缩放 (仅 XY 方向, 需零件直立)】：底部Z轴保持不变，专为螺丝/螺纹设计，保护螺距不被破坏。注意：必须确保零件在绝对坐标系中竖直向上放置 (Z-up)，否则由于 Fusion 360 缩放轴向限制，会导致变形！\n【等比缩放 (XYZ 方向)】：全方向均匀放大，速度极快，适合大部分对称零件。\n【真实面偏移】：沿法线严格推覆，极其精准但面数多时极其耗时。")

    preset_input = _add_dropdown(core_inputs, "preset", _TR("螺纹规格"), _tr_dict({name: name for name in PRESET_OPTIONS}), _TR("M4"))
    preset_input.tooltip = _TR("快速选择标准件的外径尺寸")

    dia_ref = core_inputs.addSelectionInput("diameter_ref", _TR("圆柱参考/定心点 (可选)"), _TR("选择圆柱面/圆边提取直径和圆心。或者单独选择一个顶点/草图点来强制指定圆心（此时需手动输入直径）。"))
    dia_ref.addSelectionFilter("CircularEdges")
    dia_ref.addSelectionFilter("CylindricalFaces")
    dia_ref.addSelectionFilter("Vertices")
    dia_ref.addSelectionFilter("SketchPoints")
    dia_ref.addSelectionFilter("ConstructionPoints")
    dia_ref.setSelectionLimits(0, 1)
    dia_ref.tooltip = _TR("智能提取圆心与直径")
    dia_ref.tooltipDescription = _TR("如果您不知道模型直径，请点选屏幕上的圆环边缘或圆柱面，系统会自动提取其真实的直径并填入下方，同时全参数化绑定该几何中心。\n如果您只想自定义缩放中心而不修改直径，请直接选择屏幕上的某个点（顶点、草图点等）。")

    _add_value(core_inputs, "diameter", _TR("自定义直径"), "4.0 mm")

    fit_prof = _add_dropdown(core_inputs, "fit_profile", _TR("公差预设"), _tr_dict({k: k for k in FIT_PROFILES}), _TR("宽松插入 (+0.20mm)"))
    fit_prof.tooltip = _TR("快速设置常见的 3D 打印公差")
    fit_prof.tooltipDescription = _TR("宽松插入：适合需要顺滑插入、经常拔插的零件。\n精准/滑动：适合要求严丝合缝的卡扣或滑动件。\n过盈/热熔：用于强行压入或用电烙铁加热植入铜花母（热熔嵌件）。")

    clear_input = _add_value(core_inputs, "clearance", _TR("单边公差"), "0.20 mm")
    clear_input.tooltip = _TR("零件四周预留的装配空隙")
    clear_input.tooltipDescription = _TR("通常 3D 打印推荐设置在 0.15mm - 0.25mm 之间。此数值将生成为全局参数，可随时修改。")

    seal_enable = core_inputs.addBoolValueInput("seal_enable", _TR("开启封头 (填平坑洞并突破)"), True, "", False)
    seal_enable.tooltip = _TR("将坑洞完全填平为实心，并可向外延伸")
    seal_enable.tooltipDescription = _TR("勾选后，插件会自动填满您选择的平面或坑底，并可以往外挤出一段距离，形成一个无缝的完美打孔刀具。")
    
    seal_ref = core_inputs.addSelectionInput("seal_ref", _TR("封头起点面 (必选)"), _TR("请点选螺丝顶面或内六角坑的底面。插件将从该高度开始填平并向外突破。"))
    seal_ref.addSelectionFilter("PlanarFaces")
    seal_ref.addSelectionFilter("CircularEdges")
    seal_ref.setSelectionLimits(0, 1)
    
    seal_length = _add_value(core_inputs, "seal_length", _TR("向外突破长度"), "2 mm")
    seal_length.tooltip = _TR("封头高出螺丝顶部的额外贯穿距离")
    seal_length.tooltipDescription = _TR("确保刀具有足够的长度刺穿外壳。如果您只想要填平坑洞而不冒出头，可以设为 0 mm。")

    # 标签页 2：底座边界
    geom_inputs = tab_geom.children

    blank_group = geom_inputs.addGroupCommandInput("blank_group", _TR("底座/毛坯设置"))
    blank_group.isExpanded = True
    blank_inputs = blank_group.children
    _add_dropdown(blank_inputs, "blank", _TR("底座生成方式"), _tr_dict(BLANK_OPTIONS), _TR("矩形底座"))
    
    bottom_ref = blank_inputs.addSelectionInput("bottom_ref", _TR("底面参考 (可选)"), _TR("选择模型表面、顶点作为底座底面"))
    bottom_ref.addSelectionFilter("SolidFaces")
    bottom_ref.addSelectionFilter("ConstructionPlanes")
    bottom_ref.addSelectionFilter("Vertices")
    bottom_ref.addSelectionFilter("SketchPoints")
    bottom_ref.setSelectionLimits(0, 1)
    bottom_ref.tooltip = _TR("拉伸底座的起始边界")
    bottom_ref.tooltipDescription = _TR("点击模型表面或顶点，底座将以此为起点。\n如果不选，系统将自动使用包围盒计算。")
    
    top_ref = blank_inputs.addSelectionInput("top_ref", _TR("顶面参考 (可选)"), _TR("选择模型表面、顶点作为底座顶面"))
    top_ref.addSelectionFilter("SolidFaces")
    top_ref.addSelectionFilter("ConstructionPlanes")
    top_ref.addSelectionFilter("Vertices")
    top_ref.addSelectionFilter("SketchPoints")
    top_ref.setSelectionLimits(0, 1)
    top_ref.tooltip = _TR("拉伸底座的终止边界")
    top_ref.tooltipDescription = _TR("点击模型表面或顶点，底座将刚好贴合至该处。\n如果不选，系统将自动使用包围盒计算。")
    
    _add_value(blank_inputs, "outer", _TR("外径/六角对边"), "8.0 mm")
    _add_value(blank_inputs, "box_x", _TR("矩形 X 尺寸"), "0 mm")
    _add_value(blank_inputs, "box_y", _TR("矩形 Y 尺寸"), "0 mm")
    _add_value(blank_inputs, "thickness", _TR("厚度"), "4.8 mm")
    _add_value(blank_inputs, "z_start", _TR("底面 Z"), "0 mm")
    _add_value(blank_inputs, "margin", _TR("自动边距"), "2.0 mm")

    # 标签页 3：专家模式
    adv_inputs = tab_adv.children
    _add_value(adv_inputs, "clearance_x", _TR("X 单边公差"), "0.20 mm")
    _add_value(adv_inputs, "clearance_y", _TR("Y 单边公差"), "0.20 mm")
    _add_value(adv_inputs, "clearance_z", _TR("Z 单边公差"), "0.00 mm")
    _add_value(adv_inputs, "fit_adjust", _TR("零件每边补偿"), "-0.10 mm")
    
    _add_dropdown(adv_inputs, "center", _TR("缩放中心"), _tr_dict(CENTER_OPTIONS), _TR("原点：适合螺纹轴心在原点"))
    adv_inputs.addStringValueInput("scale_x", _TR("手动 X 比例"), "")
    adv_inputs.addStringValueInput("scale_y", _TR("手动 Y 比例"), "")
    adv_inputs.addStringValueInput("scale_z", _TR("手动 Z 比例"), "")
    adv_inputs.addBoolValueInput("cut", _TR("执行布尔切割"), True, "", True)
    adv_inputs.addBoolValueInput("keep_tool", _TR("保留刀具"), True, "", True)

    _sync_dialog_visibility(inputs)


def _add_dropdown(inputs, input_id, label, options, selected_label):
    dropdown = inputs.addDropDownCommandInput(input_id, label, adsk.core.DropDownStyles.TextListDropDownStyle)
    for label_text in options:
        dropdown.listItems.add(label_text, label_text == selected_label)
    return dropdown


def _add_value(inputs, input_id, label, expression):
    return inputs.addValueInput(input_id, label, "mm", adsk.core.ValueInput.createByString(expression))


def _sync_dialog_visibility(inputs, changed_id=""):
    fit = _selected_value(inputs.itemById("fit"), _tr_dict(FIT_OPTIONS))
    operation = _selected_value(inputs.itemById("operation"), _tr_dict(OPERATION_OPTIONS))
    blank = _selected_value(inputs.itemById("blank"), _tr_dict(BLANK_OPTIONS))

    is_thread = fit == "thread"
    is_manual = fit == "manual"
    is_part = operation == "part"
    has_blank = operation == "cavity" and blank != "none"

    _set_visible(inputs, ("preset", "diameter"), is_thread)
    _set_visible(inputs, ("diameter_ref",), True)
    _set_visible(inputs, ("fit_profile",), not is_part and not is_manual)
    _set_visible(inputs, ("clearance",), not is_part and not is_manual)
    _set_visible(inputs, ("clearance_x", "clearance_y", "clearance_z"), not is_thread and not is_manual and not is_part)
    _set_visible(inputs, ("fit_adjust",), is_part and not is_manual)
    _set_visible(inputs, ("blank_group",), operation == "cavity")
    _set_visible(inputs, ("outer",), has_blank and blank in {"hex", "cylinder"})
    _set_visible(inputs, ("box_x", "box_y"), has_blank and blank == "box")
    _set_visible(inputs, ("thickness", "z_start", "margin"), has_blank)
    _set_visible(inputs, ("scale_x", "scale_y", "scale_z"), is_manual)
    _set_visible(inputs, ("cut",), operation == "cavity")
    _set_visible(inputs, ("keep_tool",), operation != "part")
    
    seal_enable_input = inputs.itemById("seal_enable")
    is_seal = seal_enable_input and seal_enable_input.value
    _set_visible(inputs, ("seal_enable",), operation == "tool")
    _set_visible(inputs, ("seal_ref", "seal_length"), operation == "tool" and is_seal)

    op_desc = inputs.itemById("op_desc")
    if op_desc:
        if operation == "cavity":
            op_desc.text = _TR("<i>适用场景：为零件制作专属的安装底座，或快速打印公差配合测试件。</i>")
        elif operation == "tool":
            op_desc.text = _TR("<i>适用场景：将其作为“刻刀”，在您设计的复杂外壳上，使用布尔运算精准挖出安装孔。</i>")
        elif operation == "part":
            op_desc.text = _TR("<i>适用场景：直接 3D 打印该零件时，预先抵消塑料热收缩误差，确保打印成品能顺利装配。</i>")
        else:
            op_desc.text = ""

    center_input = inputs.itemById("center")
    if center_input and changed_id == "fit" and fit != "thread":
        _select_dropdown_label(center_input, _TR("自动：包围盒中心 (适合对称体)"))
    elif center_input and changed_id == "fit":
        _select_dropdown_label(center_input, _TR("智能：基于点选圆提取 (推荐)"))

    blank_input = inputs.itemById("blank")
    if blank_input and operation == "tool":
        _select_dropdown_label(blank_input, _TR("不生成底座"))
    elif blank_input and changed_id in {"fit", "operation"} and is_thread and operation == "cavity":
        _select_dropdown_label(blank_input, _TR("六角螺母"))
    elif blank_input and changed_id in {"fit", "operation"} and operation == "cavity" and not is_thread and _selected_value(blank_input, _tr_dict(BLANK_OPTIONS)) == "hex":
        _select_dropdown_label(blank_input, _TR("矩形底座"))


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


def _config_dict_from_inputs(inputs):
    operation = _selected_value(inputs.itemById("operation"), _tr_dict(OPERATION_OPTIONS))
    fit = _selected_value(inputs.itemById("fit"), _tr_dict(FIT_OPTIONS))
    blank = _selected_value(inputs.itemById("blank"), _tr_dict(BLANK_OPTIONS))
    center = _selected_value(inputs.itemById("center"), _tr_dict(CENTER_OPTIONS))
    seal_enable_input = inputs.itemById("seal_enable")
    seal = "cylinder" if (seal_enable_input and seal_enable_input.value) else "none"

    params = {
        "operation": operation,
        "fit": fit,
        "preset": _selected_value(inputs.itemById("preset"), _tr_dict({name: name for name in PRESET_OPTIONS})),
        "diameter": str(_mm_value(inputs.itemById("diameter"))),
        "clearance": str(_mm_value(inputs.itemById("clearance"))),
        "clearance_x": str(_mm_value(inputs.itemById("clearance_x"))),
        "clearance_y": str(_mm_value(inputs.itemById("clearance_y"))),
        "clearance_z": str(_mm_value(inputs.itemById("clearance_z"))),
        "fit_adjust": str(_mm_value(inputs.itemById("fit_adjust"))),
        "blank": blank,
        "center": center,
        "margin": str(_mm_value(inputs.itemById("margin"))),
        "cut": str(bool(inputs.itemById("cut").value)).lower(),
        "keep_tool": str(bool(inputs.itemById("keep_tool").value)).lower(),
        "seal": seal,
        "seal_length": str(_mm_value(inputs.itemById("seal_length"))) if inputs.itemById("seal_length") else "2.0",
    }

    for input_id, key in (("outer", "outer"), ("box_x", "box_x"), ("box_y", "box_y"), ("thickness", "thickness"), ("z_start", "z_start")):
        value = _optional_positive_mm(inputs, input_id) if input_id in {"outer", "box_x", "box_y", "thickness"} else "%g" % _mm_value(inputs.itemById(input_id))
        if value != "":
            params[key] = value

    for input_id, key in (("scale_x", "scale_x"), ("scale_y", "scale_y"), ("scale_z", "scale_z")):
        value = inputs.itemById(input_id).value.strip()
        if value:
            params[key] = value

    return params


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


def _find_smart_center_from_bodies(bodies):
    best_origin = None
    max_radius = -1.0
    face_count = 0
    edge_count = 0
    for body in bodies:
        for face in body.faces:
            face_count += 1
            if face_count > 2000:
                break
            geom = face.geometry
            if geom.objectType == adsk.core.Cylinder.classType():
                if abs(geom.axis.z) > 0.99:
                    if geom.radius > max_radius:
                        max_radius = geom.radius
                        best_origin = geom.origin
        for edge in body.edges:
            edge_count += 1
            if edge_count > 3000:
                break
            geom = edge.geometry
            if geom.objectType in (adsk.core.Circle3D.classType(), adsk.core.Arc3D.classType()):
                if abs(geom.normal.z) > 0.99:
                    if geom.radius > max_radius:
                        max_radius = geom.radius
                        best_origin = geom.center
    return best_origin


def create_print_fit_adapter(root, source_bodies, config: AdapterConfig, top_entity=None, bottom_entity=None, center_entity=None, seal_entity=None, is_preview=False, progress=None):
    source_bodies = list(source_bodies)
    if not source_bodies:
        raise RuntimeError(_TR("没有可处理的实体。"))
        
    seal_z_cm = None
    if seal_entity:
        if hasattr(seal_entity, 'geometry') and hasattr(seal_entity.geometry, 'origin'):
            seal_z_cm = seal_entity.geometry.origin.z
        elif hasattr(seal_entity, 'pointOnFace'):
            seal_z_cm = seal_entity.pointOnFace.z
        elif hasattr(seal_entity, 'center'):
            seal_z_cm = seal_entity.center.z
        elif hasattr(seal_entity, 'boundingBox'):
            seal_z_cm = seal_entity.boundingBox.minPoint.z
            
    if config.seal == "cylinder" and seal_z_cm is None:
        raise RuntimeError(_TR("开启封头时，必须选择一个【封头起点面】。请点选需要填平的坑底面或螺丝顶面。"))

    safe_name = _safe_name(config.name)
    source_box = _union_bounding_box(source_bodies)
    source_size = _box_size_mm(source_box)
    scales = calculate_fit_scales(config, source_size)
    
    design = adsk.fusion.Design.cast(root.parentDesign)
    scale_exprs = None
    if design and config.fit != "manual" and not is_preview:
        base_prefix = "PF_" + safe_name.replace("-", "_").replace(" ", "_")
        user_params = design.userParameters
        
        safe_prefix = base_prefix
        idx = 1
        while user_params.itemByName(f"{safe_prefix}_Clear") or user_params.itemByName(f"{safe_prefix}_Dia") or user_params.itemByName(f"{safe_prefix}_Clear_X"):
            safe_prefix = f"{base_prefix}_{idx}"
            idx += 1
        
        def _get_or_create(name, expr, units):
            param = user_params.itemByName(name)
            if param:
                param.expression = expr
            else:
                param = user_params.add(name, adsk.core.ValueInput.createByString(expr), units, "Print-Fit Adapter")
            return param

        if config.fit == "universal":
            _get_or_create(f"{safe_prefix}_Clear", f"{config.clearance_mm} mm", "mm")
            offset_expr = f"{safe_prefix}_Clear"
        elif config.fit == "thread_xy":
            _get_or_create(f"{safe_prefix}_Dia", f"{config.nominal_diameter_mm} mm", "mm")
            _get_or_create(f"{safe_prefix}_Clear", f"{config.clearance_mm} mm", "mm")
            expr_xy = f"({safe_prefix}_Dia + 2 * {safe_prefix}_Clear) / {safe_prefix}_Dia"
            scale_exprs = (expr_xy, expr_xy, "1.0")
        else:
            _get_or_create(f"{safe_prefix}_SizeX", f"{source_size[0]} mm", "mm")
            _get_or_create(f"{safe_prefix}_ClearX", f"{config.clearance_x_mm} mm", "mm")
            _get_or_create(f"{safe_prefix}_SizeY", f"{source_size[1]} mm", "mm")
            _get_or_create(f"{safe_prefix}_ClearY", f"{config.clearance_y_mm} mm", "mm")
            expr_x = f"({safe_prefix}_SizeX + 2 * {safe_prefix}_ClearX) / {safe_prefix}_SizeX"
            expr_y = f"({safe_prefix}_SizeY + 2 * {safe_prefix}_ClearY) / {safe_prefix}_SizeY"
            if config.fit == "xyz":
                _get_or_create(f"{safe_prefix}_SizeZ", f"{source_size[2]} mm", "mm")
                _get_or_create(f"{safe_prefix}_ClearZ", f"{config.clearance_z_mm} mm", "mm")
                expr_z = f"({safe_prefix}_SizeZ + 2 * {safe_prefix}_ClearZ) / {safe_prefix}_SizeZ"
            else:
                expr_z = "1.0"
    else:
        scale_exprs = None
        if config.fit == "universal":
            offset_expr = f"{config.clearance_mm} mm"
        elif config.fit == "thread_xy":
            scale_exprs = (f"{scales[0]}", f"{scales[1]}", "1.0")
        elif config.fit == "xyz":
            scale_exprs = (f"{scales[0]}", f"{scales[1]}", f"{scales[2]}")
        elif config.fit == "xy":
            scale_exprs = (f"{scales[0]}", f"{scales[1]}", "1.0")
        else:
            scale_exprs = None

    center_point = root.originConstructionPoint
    if config.center == "bbox":
        center_point = _create_scale_point(root, _box_center(source_box), "%s scale center" % safe_name)
    elif config.center == "smart":
        if center_entity is not None:
            if center_entity.objectType == adsk.fusion.BRepVertex.classType():
                center_point = center_entity
            elif center_entity.objectType == adsk.fusion.SketchPoint.classType():
                center_point = center_entity
            elif center_entity.objectType == adsk.fusion.ConstructionPoint.classType():
                center_point = center_entity
            elif center_entity.objectType in (adsk.fusion.BRepFace.classType(), adsk.fusion.BRepEdge.classType(), "adsk::fusion::BRepFaceProxy", "adsk::fusion::BRepEdgeProxy"):
                # Extract Point3D robustly instead of using setByCenter which can fail
                geom = center_entity.geometry
                pt = None
                if center_entity.objectType in (adsk.fusion.BRepEdge.classType(), "adsk::fusion::BRepEdgeProxy") and geom.objectType in (adsk.core.Circle3D.classType(), adsk.core.Arc3D.classType()):
                    pt = geom.center
                elif center_entity.objectType in (adsk.fusion.BRepFace.classType(), "adsk::fusion::BRepFaceProxy") and geom.objectType == adsk.core.Cylinder.classType():
                    pt = geom.origin
                
                if pt is not None:
                    # Keep Z coordinate of the original center box, but use XY from the selected entity
                    center_box = _box_center(source_box)
                    smart_pt = adsk.core.Point3D.create(pt.x, pt.y, center_box.z)
                    center_point = _create_scale_point(root, smart_pt, "%s param center" % safe_name)
                else:
                    center_point = _create_scale_point(root, _box_center(source_box), "%s fallback center" % safe_name)
        elif config.center_point is not None:
            smart_pt = adsk.core.Point3D.create(mm_to_cm(config.center_point[0]), mm_to_cm(config.center_point[1]), mm_to_cm(config.center_point[2]))
            center_point = _create_scale_point(root, smart_pt, "%s smart center" % safe_name)
        else:
            smart_origin = _find_smart_center_from_bodies(source_bodies)
            if smart_origin is not None:
                center_box = _box_center(source_box)
                smart_pt = adsk.core.Point3D.create(smart_origin.x, smart_origin.y, center_box.z)
                center_point = _create_scale_point(root, smart_pt, "%s smart auto center" % safe_name)
            else:
                center_point = _create_scale_point(root, _box_center(source_box), "%s fallback center" % safe_name)

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
            
        if config.fit == "universal":
            total_faces = sum(b.faces.count for b in working_bodies if b and b.isValid)
            if is_preview and total_faces > 50:
                _scale_bodies(root, working_bodies, center_point, scales, "Print compensation scale (preview fallback)", scale_exprs)
            else:
                if progress:
                    progress.message = _TR("正在进行真实面偏移计算 ({total_faces} 个曲面)，极耗时请耐心等待...").replace("{total_faces}", str(total_faces))
                    adsk.doEvents()
                try:
                    feature, offset_bodies = _offset_body_faces(root, working_bodies, offset_expr, "Print compensation offset")
                    for body in working_bodies:
                        try:
                            body.deleteMe()
                        except:
                            body.isLightBulbOn = False
                    working_bodies = offset_bodies
                except Exception as e:
                    print("Offset failed, fallback to scale: %s" % e)
                    _scale_bodies(root, working_bodies, center_point, scales, "Print compensation scale (fallback)", scale_exprs)
        else:
            _scale_bodies(root, working_bodies, center_point, scales, "Print compensation scale", scale_exprs)
            
        result["part_names"] = [body.name for body in working_bodies if body and body.isValid]
        return result

    for index, body in enumerate(working_bodies, start=1):
        body.name = "%s_clearance_cutter_DO_NOT_PRINT_%02d" % (safe_name, index)
        
    if config.fit == "universal":
        total_faces = sum(b.faces.count for b in working_bodies if b and b.isValid)
        if is_preview and total_faces > 50:
            _scale_bodies(root, working_bodies, center_point, scales, "Print-fit cutter scale (preview fallback)", scale_exprs)
        else:
            if progress:
                progress.message = _TR("正在进行真实面偏移计算 ({total_faces} 个曲面)，极耗时请耐心等待...").replace("{total_faces}", str(total_faces))
                adsk.doEvents()
            try:
                feature, offset_bodies = _offset_body_faces(root, working_bodies, offset_expr, "Print-fit cutter offset")
                for body in working_bodies:
                    try:
                        body.deleteMe()
                    except:
                        body.isLightBulbOn = False
                working_bodies = offset_bodies
                for index, body in enumerate(working_bodies, start=1):
                    body.name = "%s_clearance_cutter_DO_NOT_PRINT_%02d" % (safe_name, index)
            except Exception as e:
                print("Offset failed, fallback to scale: %s" % e)
                _scale_bodies(root, working_bodies, center_point, scales, "Print-fit cutter scale (fallback)", scale_exprs)
    else:
        _scale_bodies(root, working_bodies, center_point, scales, "Print-fit cutter scale", scale_exprs)

    tool_bodies = list(working_bodies)
    tool_box = _union_bounding_box(tool_bodies)

    if config.seal == "cylinder":
        cap_body = _create_cylindrical_seal_cap(root, tool_box, center_point, seal_z_cm, config)
        if cap_body and cap_body.isValid:
            if len(tool_bodies) > 0:
                tools = adsk.core.ObjectCollection.create()
                tools.add(cap_body)
                combine_input = root.features.combineFeatures.createInput(tool_bodies[0], tools)
                combine_input.operation = adsk.fusion.FeatureOperations.JoinFeatureOperation
                combine_input.isKeepToolBodies = False
                combine_input.isNewComponent = False
                try:
                    combine_feature = root.features.combineFeatures.add(combine_input)
                    if not combine_feature.bodies.count > 0:
                        tool_bodies.append(cap_body)
                except:
                    tool_bodies.append(cap_body)
            else:
                tool_bodies.append(cap_body)
            result["cap_created"] = True

    result["tool_names"] = [body.name for body in tool_bodies if body and body.isValid]

    blank_body = None
    if config.blank != "none":
        blank_body = _create_blank(root, config, _union_bounding_box(tool_bodies), safe_name, top_entity, bottom_entity)
        blank_body.name = "%s_%s_blank" % (safe_name, config.blank)
        result["blank_name"] = blank_body.name

    if config.operation == "cavity" and config.cut and blank_body:
        tool_faces = sum(b.faces.count for b in tool_bodies if b and b.isValid)
        if is_preview and tool_faces > 200:
            blank_body.opacity = 0.3
            blank_body.name = "%s_print_fit_%s (Preview)" % (safe_name, config.blank)
            result["blank_name"] = blank_body.name
        else:
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
        selection = ui.selectEntity(_TR("选择要适配的实体（Solid Body）"), "SolidBodies")
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
            raise RuntimeError(_TR("复制实体失败：%s") % (body.name or "(unnamed body)"))
        copies.append(copied)
    return copies


def _offset_body_faces(root, bodies, offset_expr_str, feature_name):
    faces = adsk.core.ObjectCollection.create()
    for body in bodies:
        for face in body.faces:
            faces.add(face)
            
    offset_features = root.features.offsetFeatures
    offset_input = offset_features.createInput(
        faces,
        adsk.core.ValueInput.createByString(offset_expr_str),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation
    )
    feature = offset_features.add(offset_input)
    if not feature or feature.bodies.count < len(bodies):
        raise RuntimeError(_TR("面偏移计算失败。"))
        
    new_bodies = []
    for i in range(feature.bodies.count):
        new_bodies.append(feature.bodies.item(i))
        
    feature.name = feature_name
    return feature, new_bodies


def _scale_bodies(root, bodies, scale_point, scales, feature_name, scale_exprs=None):
    collection = adsk.core.ObjectCollection.create()
    for body in bodies:
        collection.add(body)

    scale_features = root.features.scaleFeatures
    scale_input = scale_features.createInput(
        collection,
        scale_point,
        adsk.core.ValueInput.createByReal(1.0),
    )
    if scale_exprs:
        ok = scale_input.setToNonUniform(
            adsk.core.ValueInput.createByString(scale_exprs[0]),
            adsk.core.ValueInput.createByString(scale_exprs[1]),
            adsk.core.ValueInput.createByString(scale_exprs[2]),
        )
    else:
        ok = scale_input.setToNonUniform(
            adsk.core.ValueInput.createByReal(scales[0]),
            adsk.core.ValueInput.createByReal(scales[1]),
            adsk.core.ValueInput.createByReal(scales[2]),
        )
    if not ok:
        raise RuntimeError(_TR("设置非均匀缩放失败。"))
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
        raise RuntimeError(_TR("创建偏移平面失败: %s") % name)
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


def _create_blank(root, config: AdapterConfig, tool_box, safe_name, top_entity=None, bottom_entity=None):
    min_x, min_y, min_z, max_x, max_y, max_z = _box_values_mm(tool_box)
    size_x, size_y, size_z = _box_size_mm(tool_box)
    center_x_cm = (tool_box.minPoint.x + tool_box.maxPoint.x) / 2.0
    center_y_cm = (tool_box.minPoint.y + tool_box.maxPoint.y) / 2.0

    design = adsk.fusion.Design.cast(root.parentDesign)
    safe_prefix = "PF_" + safe_name.replace("-", "_").replace(" ", "_")
    user_params = design.userParameters
    def _get_or_create(name, expr, units):
        param = user_params.itemByName(name)
        if param:
            param.expression = expr
        else:
            param = user_params.add(name, adsk.core.ValueInput.createByString(expr), units, "Print-Fit Adapter")
        return param

    sketch = root.sketches.add(root.xYConstructionPlane)
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
        raise RuntimeError(_TR("毛坯草图没有形成封闭轮廓。"))

    extrude_input = root.features.extrudeFeatures.createInput(sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    
    if bottom_entity:
        start_def = adsk.fusion.FromEntityStartDefinition.create(bottom_entity, adsk.core.ValueInput.createByReal(0))
        extrude_input.startExtent = start_def
    else:
        z_start_mm = config.z_start_mm if config.z_start_mm is not None else min_z - config.margin_z_mm
        _get_or_create(f"{safe_prefix}_Blank_Z", f"{z_start_mm} mm", "mm")
        offset_val = adsk.core.ValueInput.createByString(f"{safe_prefix}_Blank_Z")
        start_def = adsk.fusion.OffsetStartDefinition.create(offset_val)
        extrude_input.startExtent = start_def

    if top_entity:
        extent_def = adsk.fusion.ToEntityExtentDefinition.create(top_entity, False)
        extrude_input.setOneSideExtent(extent_def, adsk.fusion.ExtentDirections.PositiveExtentDirection)
    else:
        thickness_mm = config.thickness_mm if config.thickness_mm is not None else size_z + 2.0 * config.margin_z_mm
        if thickness_mm <= 0:
            raise RuntimeError(_TR("毛坯厚度必须大于 0。"))
        _get_or_create(f"{safe_prefix}_Blank_Thick", f"{thickness_mm} mm", "mm")
        extent_def = adsk.fusion.DistanceExtentDefinition.create(adsk.core.ValueInput.createByString(f"{safe_prefix}_Blank_Thick"))
        extrude_input.setOneSideExtent(extent_def, adsk.fusion.ExtentDirections.PositiveExtentDirection)

    extrude = root.features.extrudeFeatures.add(extrude_input)
    sketch.isVisible = False
    if not extrude or extrude.bodies.count < 1:
        raise RuntimeError(_TR("毛坯拉伸失败。"))
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


def _create_cylindrical_seal_cap(root, tool_box, center_point, seal_z_cm, config: AdapterConfig):
    min_x, min_y, min_z, max_x, max_y, max_z = _box_values_mm(tool_box)
    
    if hasattr(center_point, 'geometry'):
        geom = center_point.geometry
        center_x_cm = geom.x
        center_y_cm = geom.y
    elif hasattr(center_point, 'x'):
        center_x_cm = center_point.x
        center_y_cm = center_point.y
    else:
        center_x_cm = (tool_box.minPoint.x + tool_box.maxPoint.x) / 2.0
        center_y_cm = (tool_box.minPoint.y + tool_box.maxPoint.y) / 2.0

    half_x_cm = (tool_box.maxPoint.x - tool_box.minPoint.x) / 2.0
    half_y_cm = (tool_box.maxPoint.y - tool_box.minPoint.y) / 2.0
    radius_cm = max(half_x_cm, half_y_cm) * config.seal_oversize
    extra_mm = 0.05

    start_z_mm = seal_z_cm * 10.0
    
    # 智能判断螺丝朝向 (离 max_z 近还是离 min_z 近)
    dist_to_max = abs(max_z - start_z_mm)
    dist_to_min = abs(start_z_mm - min_z)
    
    if dist_to_max < dist_to_min:
        # 螺丝头朝上 (+Z方向突破)
        distance_mm = max_z - start_z_mm + config.seal_length_mm + extra_mm
        if distance_mm < 1.0: distance_mm = 1.0
        extrude_dist = distance_mm
    else:
        # 螺丝头朝下 (-Z方向突破)
        distance_mm = start_z_mm - min_z + config.seal_length_mm + extra_mm
        if distance_mm < 1.0: distance_mm = 1.0
        # 对于向下突破，偏移平面设为 min_z - seal_length，然后往 +Z 拉伸到 start_z_mm
        extrude_dist = distance_mm
        start_z_mm = start_z_mm - distance_mm

    plane = _create_offset_xy_plane(root, start_z_mm, "%s seal cap plane" % config.name)
    sketch = root.sketches.add(plane)
    sketch.name = "%s seal cap sketch" % config.name
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(center_x_cm, center_y_cm, 0),
        radius_cm,
    )

    extrude = root.features.extrudeFeatures.addSimple(
        sketch.profiles.item(0),
        adsk.core.ValueInput.createByString("%g mm" % extrude_dist),
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
    )
    sketch.isVisible = False
    plane.isLightBulbOn = False
    if not extrude or extrude.bodies.count < 1:
        raise RuntimeError(_TR("封头圆柱创建失败。"))
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
        raise RuntimeError(_TR("布尔切割失败，请确认毛坯与放大刀具相交。"))
    feature.name = "Cut print-fit cavity"
    return feature


def _union_bounding_box(bodies):
    if not bodies:
        raise RuntimeError(_TR("不能计算空实体集合的包围盒。"))
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
        _TR("生成完成。"),
        "",
        _TR("输入实体数量: %s") % result["source_count"],
        _TR("操作: %s") % result["operation"],
        _TR("适配策略: %s") % result["fit"],
        _TR("缩放: X %.6f / Y %.6f / Z %.6f") % (scales[0], scales[1], scales[2]),
        _TR("中心: %s") % config.center,
    ]
    if result["part_names"]:
        lines.append(_TR("打印补偿副本: %s") % ", ".join(result["part_names"]))
    if result["tool_names"]:
        lines.append(_TR("刀具体: %s") % ", ".join(result["tool_names"]))
    if result["blank_name"]:
        lines.append(_TR("底座/毛坯: %s") % result["blank_name"])
    if result["combine_feature"]:
        lines.append(_TR("布尔特征: %s") % result["combine_feature"])
    if result["cap_created"]:
        lines.append(_TR("已创建封头圆柱，注意它可能改变头部挖槽形状。"))
    if config.warning_messages:
        lines.extend(["", _TR("警告:")])
        lines.extend("- %s" % message for message in config.warning_messages)
    if config.operation in {"tool", "cavity"}:
        lines.extend(["", _TR("带 DO_NOT_PRINT 的刀具仅用于布尔切割，不要打印。")])
    return "\n".join(lines)


def _safe_name(value: str) -> str:
    safe = []
    for char in value:
        if char.isalnum() or char in {"_", "-", "."}:
            safe.append(char)
        else:
            safe.append("_")
    # Truncate to 20 characters to prevent Fusion 360 user parameter name length limit crashes
    return "".join(safe)[:20].strip("_") or "PrintFit"
