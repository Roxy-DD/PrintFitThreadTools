# 原理记录：标准件到 3D 打印装配件的自动适配

## 目标

Fusion 360 可以直接插入 McMaster-Carr 等标准件模型，但这些模型通常按金属加工、采购件或理想 CAD 几何表达。3D 打印的问题是：孔会偏小、外形会偏大、细小运动副间隙不足、布尔挖出的内螺纹太紧。

本工具把这些问题抽象成三个自动化动作：

1. 复制选中实体，生成带打印间隙的布尔刀具。
2. 自动生成底座/毛坯，并用刀具切出可装配的孔、槽、内螺纹或避让空间。
3. 复制原零件，按参数生成打印补偿副本。

## 为什么不能所有模型都用同一种“放大”

不同标准件的功能面不同：

- 螺纹：必须保持 Z 方向螺距，不能均匀缩放。
- 齿轮/轴套/皮带轮：常见需求是 XY 平面间隙，厚度方向不应变化。
- 避让槽/定位座：需要 X/Y/Z 都留装配余量。
- 拖链/铰链/卡扣：可能需要改原零件副本，让运动副的销、孔、卡扣不再过紧。

所以工具不做一个黑盒“万能放大”，而是提供可选策略。

## `fit=thread`

螺纹策略固定：

```text
X scale = Y scale = (D + 2C) / D
Z scale = 1.0
```

其中 `D` 是公称直径或实测大径，`C` 是单边径向间隙。这样牙型沿轴向的位置不变，避免均匀缩放导致螺距变大、外螺纹和内螺纹逐圈错位。

缩放中心固定根组件原点，所以螺丝轴线必须穿过 `(0,0,0)`。

## `fit=xy`

通用二维间隙策略。脚本先取得所选实体的包围盒尺寸：

```text
X scale = (body_x + 2 * clearance_x) / body_x
Y scale = (body_y + 2 * clearance_y) / body_y
Z scale = 1.0
```

缩放中心默认是包围盒中心。它适合齿轮、皮带轮、滑块、轴套、链节的平面装配/避让。优点是自动、不要求模型在原点；缺点是它不是严格的所有表面等距偏移，而是分轴包络放大。

## `fit=xyz`

完整包络策略：

```text
X scale = (body_x + 2 * clearance_x) / body_x
Y scale = (body_y + 2 * clearance_y) / body_y
Z scale = (body_z + 2 * clearance_z) / body_z
```

适合做定位座、收纳座、避让槽、安装槽。对于齿轮和螺纹这类有明确运动/传动功能的零件，不应盲目使用。

## `operation=part`

打印补偿副本不做布尔。脚本复制原实体并从包围盒中心缩放。`fit_adjust` 是每边尺寸调整：

```text
new_size = old_size + 2 * fit_adjust
scale = new_size / old_size
```

例如拖链链节过紧，可以先对单个链节用：

```text
operation=part; fit=xyz; fit_adjust=-0.10
```

这会让每个方向总尺寸缩小 0.20 mm。若只想缩小 X/Y，则使用：

```text
operation=part; fit=manual; scale_xy=0.98; scale_z=1.0
```

## 自动底座

当 `blank=box/cylinder/hex` 且未提供尺寸时，脚本用放大后的刀具体包围盒自动计算底座：

- `box`：长宽为刀具包围盒 X/Y 加 `margin`。
- `cylinder`：直径覆盖刀具包围盒对角线并加 `margin`。
- `hex`：对边尺寸优先用 `outer`，否则按刀具包围盒估算。
- `thickness` 和 `z_start` 不填时，会自动覆盖刀具体 Z 方向并加 `margin_z`。

这满足“只选实体、设公差、设底座形状”的基本流程。

## 封闭头部

带内六角、十字槽、梅花槽的螺丝头部如果参与切割，可能让布尔结果出现不需要的空腔。脚本提供：

```text
seal=cylinder; seal_depth=2; seal_direction=+z
```

它会添加一个圆柱封头作为额外刀具参与切割。它是通用稳定方案，不理解具体头部槽形。

## 标准依据

- ISO 262:2023 定义 ISO 公制普通螺纹的选用直径/螺距组合，并引用 ISO 68-1 的基本/设计牙型。
- ISO 965-2:2024 定义 ISO 公制普通螺纹内外螺纹的尺寸极限和常见公差等级，例如 6H/6g。
- 本工具不是替代 ISO 965 金属螺纹公差，而是在标准件几何基础上增加可调的打印装配间隙。

参考链接：

- [ISO 262:2023](https://www.iso.org/standard/85105.html)
- [ISO 965-2:2024](https://www.iso.org/standard/87890.html)
- [Autodesk Fusion API: ScaleFeatureInput.setToNonUniform](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/ScaleFeatureInput_setToNonUniform.htm)
- [Autodesk Fusion API: CombineFeatures.createInput](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/CombineFeatures_createInput.htm)
- [Autodesk Fusion API: BRepBody.copyToComponent](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/BRepBody_copyToComponent.htm)
- [Autodesk Fusion API: Selection Filters](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/SelectionFilters_UM.htm)
- [Autodesk Fusion API: Understanding Units in Fusion](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/Units_UM.htm)

## 已知限制

- 当前通用策略是包围盒中心分轴缩放，不是真正的任意曲面等距偏移。
- 复杂 BRep、极薄面、导入质量差的 STEP 模型仍可能布尔失败。
- 网格体需要先转换为实体 BRep。
- 多 Body 标准件可以多选，但若是带装配约束的复杂组件，最好先确认每个 Body 是否都需要参与刀具。
- 齿轮实际啮合、轴承滚道、弹性卡扣等功能面需要试印校准，不能只依赖一次自动放大。
