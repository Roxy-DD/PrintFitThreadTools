# PrintFitThreadTools

![版本](https://img.shields.io/badge/version-1.1.3-blue)
![平台](https://img.shields.io/badge/platform-Fusion%20360-orange)

## 1. 简介 (Introduction)
**PrintFitThreadTools** 是一款为 Fusion 360 开发的辅助插件。主要用于处理 McMaster-Carr 或其他渠道导入的标准件模型（如螺栓、螺母、轴承、齿轮等）。该插件能够根据设定的 3D 打印公差，自动生成相应的容纳底座、布尔切割刀具或补偿副本。

**PrintFitThreadTools** is an add-in for Fusion 360. It is mainly used to process standard part models (e.g., bolts, nuts, bearings, gears) imported from McMaster-Carr or other sources. The add-in automatically generates corresponding bases, boolean cutters, or compensated copies based on specified 3D printing tolerances.

![总览 (Overview)](docs/images/overview.png)

## 2. 功能特性 (Features)

### 2.1 公差适配策略 (Tolerance Strategies)
系统提供三种计算策略以适应不同的几何类型：
The system provides three strategies to accommodate different geometry types:
- **径向缩放 / Radial Scaling (XY 方向/XY Only)**：保持 Z 轴尺寸固定，仅在 XY 轴平面进行缩放。适用于螺纹等需要保持轴向间距（螺距）不变的部件。
  Keeps the Z-axis dimension fixed and scales only in the XY plane. Ideal for threaded parts where axial pitch must remain unchanged.
- **等比缩放 / Uniform Scaling (XYZ 方向/XYZ All)**：在 XYZ 三维方向进行均匀的比例放大。
  Scales uniformly across all X, Y, and Z axes.
- **面偏移 / Normal Offset (法向等距/Normal)**：通过拓扑计算使零件表面沿法线方向向外偏移，适用于非对称或不规则形状的零件。
  Offsets the part surface outward along the normal direction using topology computation. Ideal for asymmetrical or irregular shapes.

### 2.2 圆心基准提取 (Center Point Extraction)
系统提供不完整几何体的特征圆心提取功能：
Extracts feature center points from incomplete geometries:
- **自动提取 / Auto Extraction**：用户选中部分圆柱曲面时，系统自动提取该圆柱的几何中心作为缩放基准点。
  Automatically extracts the geometric center of a selected partial cylindrical face as the base point.
- **手动指定 / Manual Selection**：支持通过点选圆弧边缘或顶点特征来手动设定中心基准。
  Allows manual selection of circular edges or vertex features as the center point.

![圆心基准提取 (Center Point Extraction)](docs/images/smart_center.png)

### 2.3 封头与单向延伸 (Cap & Unidirectional Extension)
系统支持针对内六角或带有复杂倒角的螺丝头部生成延伸实体：
Generates extended bodies for socket heads or screw heads with complex chamfers:
- **特征获取 / Feature Recognition**：用户点选参照面后，系统获取螺丝头部的最大外接圆直径。
  Obtains the maximum circumscribed circle diameter of the screw head after selecting a reference face.
- **实体生成 / Body Generation**：沿指定方向生成包含倒角的实心圆柱体延伸，并与刀具实体进行布尔合并。
  Generates a solid cylindrical extension that includes the chamfer along the specified direction, then combines it with the cutter body.

### 2.4 参数作用域与性能控制 (Parameter Scoping & Performance)
- **参数隔离 / Parameter Isolation**：多次操作同一零件时，系统会自动生成带数字后缀的独立用户参数（例如 `PF_M4_1_Clear`），防止不同操作之间的参数冲突。
  Automatically generates independent user parameters with numeric suffixes (e.g., `PF_M4_1_Clear`) for multiple operations on the same part to prevent conflicts.
- **预览降级 / Preview Degradation**：在参数调整阶段，系统对高面数模型跳过布尔运算，生成的底座显示为 30% 半透明状态；确认操作后执行最终布尔切除计算。
  Skips heavy boolean operations on high-poly models during parameter adjustments, displaying the base at 30% opacity. Final boolean cut is executed only upon confirmation.

## 3. 安装步骤 (Installation)

1. 将本仓库克隆或下载至本地计算机。 (Clone or download this repository to your local machine.)
2. 启动 Fusion 360。 (Open Fusion 360.)
3. 依次点击顶部菜单栏：`实用程序 (Utilities)` -> `附加模块 (Add-ins)`。 (Navigate to `Utilities` -> `Add-ins` in the top menu.)
4. 在弹出的对话框中，选择 `插件 (Add-ins)` 选项卡。 (Select the `Add-ins` tab in the dialog.)
5. 点击绿色的 `+` 按钮，定位并选择本仓库下的 `PrintFitThreadTools` 文件夹。 (Click the green `+` button and select the `PrintFitThreadTools` folder.)
6. 在加载项列表中选中 `PrintFitThreadTools`，勾选 `启动时运行 (Run on Startup)`，然后点击 `运行 (Run)`。 (Check `Run on Startup` and click `Run`.)

![安装说明 (Installation Guide)](docs/images/install_guide.png)

## 4. 操作说明 (Instructions)

1. **选择对象 / Select Objects**：在工作区视图中，选中需要处理的导入实体模型。 (Select the imported solid bodies.)
2. **启动插件 / Launch Add-in**：通过工具栏入口调出插件面板。 (Open the add-in panel from the toolbar.)
3. **选择策略 / Select Strategy**：根据当前选中的模型类型，在面板中选择相应的适配策略（径向、等比或面偏移）。 (Choose the fitting strategy based on the model.)
4. **设置公差 / Set Clearance**：在公差设置项中输入所需的补偿数值，或选择系统预设值。 (Input clearance values or select a preset.)
5. **配置底座 / Configure Base**：选择外部底座的几何形状（如方块、六角、圆柱等），并输入所需的边距参数。 (Choose the base shape and enter margins.)
6. **执行操作 / Execute**：点击确定按钮，系统将以参数化特征的形式在时间轴中生成结果。 (Click OK to generate parametric features in the timeline.)

![操作界面 (UI Panel)](docs/images/ui_panel.png)

## 5. 高级配置 / 专家模式 (Advanced Configuration / Expert Mode)

在插件面板的“专家模式”选项卡下，支持以下配置：
The "Expert Mode" tab supports the following configurations:
- 支持为 X、Y、Z 三个轴向分别输入独立的公差补偿数值。
  Independent clearance inputs for X, Y, and Z axes.
- 支持禁用底座生成与布尔运算，仅输出计算后的实体刀具模型。
  Disable base generation and booleans to output only the cutter bodies.
- 支持手动输入数值以覆盖全局的缩放比例或高度参数。
  Manually override global scale factors or height parameters.

## 6. 版本记录 (Release Notes)

### v1.1.3
- 国际化支持：对 README 进行了全面的中英文双语适配。 (Bilingual documentation update.)

### v1.1.2
- CI/CD：修复 GitHub Actions 自动打包发布时缺失 `write` 权限的问题。 (Fixed GitHub Actions missing `write` permissions.)

### v1.1.1
- 增加自动化构建：接入 GitHub Actions 自动发布流程。 (Added GitHub Actions CI/CD.)
- 文档更新：重构说明书，更新界面截图与功能描述。 (Refactored manual, updated screenshots and features.)

### v1.1.0
- 功能优化：重构封头功能操作流程，移除深度与方向的手动选择步骤。 (Optimized cap generation, removed manual depth/direction selection.)
- 操作变更：支持通过点选参考面并输入延伸长度，自动生成封头延伸实体。 (Auto cap generation by selecting reference face and length.)
- 逻辑新增：增加模型朝向的自动判定功能。 (Added auto-detection for screw orientation.)
- 特征处理：封头实体生成后自动与主模型执行布尔合并。 (Auto-combine cap body with the main tool body.)

### v1.0.0
- 初始版本：发布全参数化公差生成基础功能。 (Initial release: Parametric tolerance generation.)
- 核心功能：加入几何定心算法、参数作用域隔离与预览期布尔运算降级机制。 (Added center detection, parameter scoping, and preview performance optimization.)
