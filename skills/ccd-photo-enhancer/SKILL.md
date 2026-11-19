---
name: ccd-photo-enhancer
description: Edits an existing photo or photo folder into a repeatable CCD / early compact digital camera look, 复古, 千禧/Y2K, or ink painting (水墨/国画/工笔). Routes CCD to a local deterministic script; not for screenshots or film-stock simulation.
whenToUse: "对已有照片做 CCD、卡片机、千禧/Y2K、复古、数码相机风格增强，或水墨、国画、工笔等风格转换；不用于截图、胶片仿真或老照片修复（除非用户明确要求）。"
user-invocable: true
agent_created: true
---

# CCD Photo Enhancer

对用户提供的照片做可控风格增强。默认是“早期便携数码相机观感”的**风格近似**，不是某款 CCD 传感器的物理仿真。水墨画等媒介转换属于独立路线，绝不把它与 CCD 滤镜混为一谈。

## English quick guide

For an existing photo, route CCD looks to the local deterministic Pillow/NumPy script when it is available; use an authorized generative editor only for semantic or medium-changing edits such as ink painting; otherwise return a prompt and state that no image was changed. Keep the original file, strip EXIF/GPS by default, and never claim the preview is a saved edit. Detailed routing and safeguards follow in Chinese.

## 必须遵守

- 先识别并尊重用户给的原图和编辑目标；不得把编辑任务偷换成从零生成。
- 默认保留人物身份、人数、姿势、场景、构图、画幅和可读文字。只处理用户指定的风格属性。
- 本地脚本是 L2 确定性像素处理：它不重绘、不移动像素位置、不识别人脸，也不创造真实闪光阴影；它**保证不做几何变换或语义重绘**，但风格效果只是数码观感近似。
- 生成式编辑是 L1 概率性处理：保真要求只是提示与复核约束，不能声称保证身份、人数或背景未变。
- 无合适后端时走 L3：仅给可复制提示词。绝不声称图片已生成或已编辑。
- 不调用未获授权的外部服务上传照片。不得猜测拍摄日期、地点、设备型号或 EXIF 内容。
- 默认剥离 EXIF/GPS 等元数据；按新文件输出，绝不覆盖原图。ICC 色彩配置按参考文档处理。
- 用户要求日期戳或文字时，必须使用其提供或明确确认的精确文本；说明这是后加的图形叠字，不是相机原始数据。L2 脚本不负责加字，需走支持文字编辑的 L1，或在用户同意后使用单独明确的叠字流程。

## 能力探测与路由（必须执行）

先确认输入是本地可读照片，并判断它是否适合照片增强。截图、带界面的图像、已明显重度滤镜化的图像，不默认套 CCD；先说明叠加效果可能造成的退化或询问用户目标。用户说“胶片 / 胶卷 / 某款胶片”时进入独立胶片风格路线或先澄清，不能默认为 CCD。

1. **L2：本地确定性像素管线，CCD 首选。** 检查是否能调用本 skill 的 `scripts/apply_ccd.py`，并有 Python、Pillow、NumPy。支持格式和处理限制见 `references/image-pipeline.md`。只处理明确支持的静态照片；不安装依赖、不联网、不外发。
2. **L1：生成式图像编辑。** 仅当有可用且获授权的图像编辑后端、且请求确实需要局部语义重绘或媒介转换（如水墨画）时使用。先调用可用性明确的工具；不得假设工具存在。需要保留项写成约束，编辑后做语义复核。
3. **L3：仅提示词。** 没有可运行 L2、也没有合适 L1 时，输出提示词但不处理图像。说明用户可把提示词用于其图像工具。

任何路线都不得只凭“能调用 Python”就对任意类型或超大图片强行执行。遇到不支持的编码/色彩配置/文件格式时，安全失败并给出可行替代方案。

## L2 用法

调用 `scripts/apply_ccd.py`，将原图作为输入，明确选择配方、主强度和 seed；如用户未指定强度，默认为 50。基本参数、预设及子效果覆盖见 `references/ccd-presets.md`。现有四个预设是三轴上的离散组合，当前不支持任意轴插值；组合不匹配时诚实说明并走 L1/L3。默认输出为输入同目录的 `<原名>_ccd-<预设>-<强度>.<扩展名>`；若名称已存在，使用不冲突的序号，不得覆盖。

调用前只问确实影响结果的问题。对“复古一点”可直接使用 `daylight-aged` / `strength=50`；用户希望第一眼看出 CCD 风格、或用于快速上手演示时，使用 `strength=75` 并复核肤色和暗部。对明确的室内闪光、白天、夜景意图分别选择对应预设。若用户要求不同子效果强度，可用 grain / color / vignette / sharpness 覆盖值，而非增加五个必答问题。用户想先查看指标时可加 `--preview`；它只计算内存结果，不写文件，报告的剪切指标在 JPEG 编码前统计，不等于最终 JPEG 像素。预览不得称为已处理图片，且不能与 `--out` 一起使用。

整组照片使用 `<输入目录> --batch --out <另一个已存在目录>`。只处理输入目录第一层，不递归；输出目录不得等于输入目录，避免生成图回流为输入。逐张沿用相同预设、强度和显式 seed。批次状态只有四种：`processed`（全部成功，退出码 0）、`processed_with_skips`（只有显式跳过、没有失败，退出码 0）、`partially_processed`（至少一张失败，退出码 1）、`nothing_processed`（没有生成任何图片，退出码 2）。当前环境无法解码的文件（HEIC/HEIF）默认记为失败；加 `--skip-unsupported` 后记为 `skipped` 并写 `reason`，不计入失败、但也不等于成功，必须原样报告 `skipped_files`。不支持批量 `--preview`，先用一张代表照片预览。不得把部分成功或含跳过的批次称为整组已完成。

## 输出状态契约（每次回复必须包含）

```text
处理状态：已处理 / 已处理（含明确跳过）/ 部分已处理 / 仅预览（未写文件）/ 未处理（有错误原因）/ 未处理（无任何输出）
能力层级：L1 生成式编辑 / L2 本地像素处理 / L2 预览指标 / L3 仅提示词
输出文件：<绝对路径或批处理输出目录> / 无
```

L2 处理完成时交付文件或可点击路径；批处理还要给出输出目录、成功/失败数量，部分失败时列出对应文件及原因。L2 preview 只报告指标、输出文件写“无”，图片没有实际修改；L3 时说明图片未改变并提供提示词。脚本失败时状态必须是“未处理”，保留错误原因，不得把 preview、部分批处理成功或 L3 提示词描述成全部处理完成。

六个状态与脚本字段一一对应：`processed` → 已处理；`processed_with_skips` → 已处理（含明确跳过），必须同时报出 `skipped_files` 的数量与原因；`partially_processed` → 部分已处理，必须列出失败文件及原因；`nothing_processed` → 未处理（无任何输出），不得写成“部分完成”或“已跳过即完成”；单张 `skipped` 或不支持格式 → 未处理（有错误原因）。

## 质量检查

### 可程序断言（L2）

确认输入输出显示方向正确、显示尺寸及宽高比未意外改变、输出不是输入文件、无覆盖、seed/预设/强度可追溯、输出文件可重新解码。检查高光死白/阴影死黑比例，并与处理前比较；这些统计是警报而非审美判决。若存在可信的人像掩膜才统计肤色偏移；没有掩膜就标为未测，不能用 RGB 阈值冒充肤色识别。

### 语义/人工检查（L1 或人工复核）

复核人物身份、人数、姿势、构图、文字和意外新增/删除内容；人像还要检查肤色是否偏橙/偏色，必要时降低 `--color-strength`。L2 没有人脸/肤色掩膜，不得宣称自动保护肤色。另问：“并排看是否能辨认出目标 CCD 观感，而不是普通调色滤镜？”不通过时只调整失败的轴/子效果。L2 不产生语义重绘，但仍须检查局部像素效果、文件解码和强度是否过度。

详细轴定义、格式/色彩处理、失败边界及艺术风格分支分别加载。以下所有相对路径都以**当前这份 `SKILL.md` 所在目录**为根，不以工作目录为根；若 skill 根目录未知，先从已安装的 `ccd-photo-enhancer/SKILL.md` 定位 bundle，再读取其旁边的 `references/` 文件，绝不凭当前工作目录猜路径：
- `references/ccd-presets.md` — CCD 三轴与预设参数
- `references/image-pipeline.md` — CLI、格式、ICC、EXIF、性能与验证
- `references/artistic-styles.md` — 水墨画等 L1/L3 独立分支
- `references/test-plan.md` — 回归用例与验收条件
