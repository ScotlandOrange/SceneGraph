# CAD 渲染性能优化技术

> 目标：提升 CAD/工程可视化场景的实时渲染帧率。
> 参考引擎：HOOPS Visualize、OpenCASCADE (OCCT)、OpenSceneGraph (OSG)、Autodesk APS Viewer、VTK、ParaView、Pixyz。

> 关于引用：本文中“某引擎支持/提供/默认开启”等**引擎特定结论**，尽量给出官方文档/源码链接作为出处；未给出出处的段落默认视为**通用图形学优化方法**（不指向某个特定引擎的既定实现）。

---

## 1. 保留模式场景图（Retained Mode Scene Graph）

### 问题
即时模式（Immediate Mode）每帧由应用程序重新提交所有几何数据，导致 CPU→GPU 总线饱和、CPU 占用过高。

### 原理
保留模式将几何数据持久化存储在引擎的“图形数据库/场景图”结构中（通常保留于系统内存，并由引擎/驱动按需维护 GPU 侧缓冲区镜像）。应用程序声明场景结构一次，后续帧仅在数据发生变化时才触发必要的更新/上传。引擎通常维护“脏标记”（dirty flag），仅对被修改的节点触发增量更新。

**HOOPS Visualize 实现：**
- HOOPS Visualize Desktop 的架构核心是“graphics database / scene graph”，其节点称为 *segments*，并支持层级结构与属性继承。
- 在 Performance 章节中，HOOPS 将 retained mode 的收益总结为：Selective Traversal（避免不必要重绘）、Incremental Updates（增量更新）、View-dependent drawing and culling（基于包围体/屏幕重要性做视图相关绘制与裁剪）、以及更快的 Selection（无需应用重发全部图元做 hit test）。
- **SDK samples（可复现的用法证据）**：多个样例在“导入完成 → 首次显示”阶段，会显式将模型段标记为 *Static Model*，并在 UI（进度条/对话框）仍显示时做一次 `UpdateWithNotifier(...).Wait()` 的初始更新。
    - WPF：样例在导入后调用 `GetPerformanceControl().SetStaticModel(HPS.Performance.StaticModel.Attribute)`，并有注释 *“Enable static model for better performance”*，随后 `UpdateWithNotifier(HPS.Window.UpdateType.Exhaustive).Wait()`（见 `samples/wpf_sandbox/source/ProgressBar/ProgressBar.xaml.cs`）。
    - MFC：样例在 `PerformInitialUpdate()` 中设置 `SetStaticModel(...)`，并注释指出“first update … building the static model”，随后 `UpdateWithNotifier(HPS::Window::UpdateType::Exhaustive).Wait()`（见 `samples/mfc_ooc_sandbox/CProgressDialog.cpp`）。

**OCCT 实现：**
- OCCT 的 presentable object（如 `AIS_InteractiveObject`）在首次显示时会创建 `Graphic3d_Structure` 作为图形表达，并保留该结构以供后续显示与视图操作使用。

### 性能收益
对于静态 CAD 装配体（摄像机移动，模型不变），每帧仅更新 MVP 矩阵，几何数据不产生任何 PCIe 传输开销。实践中通常可显著降低 CPU 侧提交与重复遍历成本（具体幅度取决于场景组织、材质数量与驱动开销）。

### References
- HOOPS Visualize Desktop Technical Overview（Architecture/Segments/Performance）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/technical_overview.html
- OCCT Visualization User Guide（Presentable object / `Graphic3d_Structure`）：https://dev.opencascade.org/doc/overview/html/occt_user_guides__visualization.html

---

## 2. 视锥体剔除（Frustum Culling）

### 问题
相机视锥体外的物体参与渲染管线完全是浪费。大型装配体中，典型视角下有 60–75% 的零件在视锥体之外。

### 原理
为场景中每个对象维护轴对齐包围盒（AABB）。每帧根据相机矩阵计算 6 个裁剪平面，利用分离轴定理（SAT）对每个 AABB 进行平面测试，完全在视锥体外的对象跳过 draw call 生成。

**CPU 端实现（正顶点法）：**
```cpp
bool IsAABBInFrustum(const Frustum& f, const AABB& box) {
    for (int i = 0; i < 6; i++) {
        // 找到在平面法线方向上最远的顶点（正顶点）
        glm::vec3 pv;
        pv.x = (f.planes[i].n.x > 0) ? box.max.x : box.min.x;
        pv.y = (f.planes[i].n.y > 0) ? box.max.y : box.min.y;
        pv.z = (f.planes[i].n.z > 0) ? box.max.z : box.min.z;
        if (glm::dot(f.planes[i].n, pv) + f.planes[i].d < 0)
            return false; // 包围盒在此平面外侧
    }
    return true;
}
```

**GPU 驱动剔除（Compute Shader）：**
```glsl
layout(local_size_x = 64) in;
layout(std430, binding = 0) buffer BoundsBuffer { vec4 bounds[]; }; // xyz=center, w=radius
layout(std430, binding = 1) buffer DrawBuffer   { DrawCommand draws[]; };
layout(std430, binding = 2) buffer CountBuffer  { uint drawCount; };
uniform vec4 frustumPlanes[6];

void main() {
    uint id = gl_GlobalInvocationID.x;
    if (sphereInFrustum(bounds[id], frustumPlanes)) {
        uint idx = atomicAdd(drawCount, 1);
        draws[idx] = buildDrawCommand(id);
    }
}
```
输出的 draw 命令直接供 `glMultiDrawElementsIndirect` 消费，CPU 仅提交一次 dispatch，GPU 完成所有剔除和绘制。

**层级加速（BVH 辅助）：**
实践中常用 BVH/层级包围体来加速场景遍历：视锥体裁剪从根节点开始，完全在外的子树整体跳过，无需逐对象测试。OCCT 的可视化文档描述了 CPU-side frustum culling 默认开启，并通过加速结构辅助剔除；HOOPS 则在 retained mode 的收益中明确提到 view-dependent drawing / bounding volumes / size limit。

**HOOPS（SDK samples 侧可观察到的 API）：**
- WPF SegmentBrowser 将 culling 作为可调属性暴露出来，基于 `HPS.SegmentKey.ShowCulling(out HPS.CullingKit)` 并通过 `kit.SetFrustum(...)`、`kit.SetExtent(...)`、`kit.SetDeferralExtent(...)`、`kit.SetDistance(...)` 等方法启用/配置裁剪（见 `samples/wpf_sandbox/source/SegmentBrowser/Properties.cs`）。
- VR 样例在 view 段上直接设置 `GetCullingControl().SetFrustum(true).SetExtent(0)`（见 `samples/vr_shared/vr.cpp`）。

### 性能收益
典型 CAD 等轴测视角下可消除 60–75% 的几何提交，对 10,000 零件场景节省数千次 draw call。

### References
- HOOPS Visualize Desktop Performance（View-dependent drawing and culling）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/technical_overview.html#performance
- OCCT Visualization User Guide（View frustum culling / `V3d_View::SetFrustumCulling()`）：https://dev.opencascade.org/doc/overview/html/occt_user_guides__visualization.html

---

## 3. 遮挡剔除（Occlusion Culling）

### 问题
发动机舱内的线束、机身内部的结构件等对用户不可见，但若不剔除则全部进入渲染管线，浪费大量 GPU 资源。典型机械装配体中内部遮挡率达 40–80%。

### 原理 A：硬件遮挡查询（HOQ）+ CHC++ 算法
1. 以包围盒替代真实几何体，关闭颜色和深度写入，提交渲染。
2. `glBeginQuery(GL_SAMPLES_PASSED)` 统计通过深度测试的片元数。
3. 若结果为 0，该对象完全被遮挡，跳过真实几何渲染。
4. **CHC++（Coherent Hierarchical Culling++）** 利用时间相干性：上帧可见 → 本帧先渲染；上帧遮挡 → 本帧仅发包围盒查询。避免 1–2 帧的查询延迟导致错误结果。

说明：遮挡剔除属于通用技术路线；不同引擎是否采用 HOQ/CHC++/Hi-Z 及其具体实现细节，通常不在公开文档中完整披露。

### 原理 B：Hi-Z 层级深度缓冲（GPU 驱动）
**构建 Hi-Z 金字塔：**
对前一帧深度缓冲生成 mip 链，每层取 2×2 区域的最大深度值。

**测试阶段（Compute Shader）：**
```glsl
float testOcclusion(vec2 screenMin, vec2 screenMax, float nearestZ) {
    vec2 size = screenMax - screenMin;
    int mip = int(ceil(log2(max(size.x * vpW, size.y * vpH))));
    float maxDepth = textureLod(hiZSampler, (screenMin + screenMax) * 0.5, mip).r;
    return nearestZ > maxDepth ? 0.0 : 1.0; // 0=遮挡，1=可见
}
```

**两趟算法：**
1. 仅渲染大遮挡体（外壳、地板）→ 写入深度缓冲。
2. 生成 Hi-Z 金字塔。
3. Compute Shader 测试所有小物体的包围盒 → 输出可见列表。
4. 渲染可见列表中的真实几何。

### 性能收益
- HOQ / Hi-Z 等遮挡剔除思路通常能显著减少“完全被挡住”的几何提交与片元开销；实际收益强依赖遮挡率、查询/Compute 成本、以及引擎/驱动实现。

---

## 4. 背面剔除（Backface Culling）

### 问题
封闭实体的背面三角面（法线朝向摄像机反方向）在光栅化后不可见，但若不剔除仍消耗片元着色器资源。

### 原理
在光栅化阶段，GPU 计算三角面屏幕空间投影的有符号面积（两条边向量的叉积）。面积为负（顺时针绕序代表背面）的三角面直接丢弃，不进入片元着色阶段。

```cpp
// OpenGL 启用背面剔除
glEnable(GL_CULL_FACE);
glCullFace(GL_BACK);
glFrontFace(GL_CCW); // 逆时针为正面
```

（若需要绑定到具体引擎 API，请以各引擎的渲染状态/材质/可见性接口为准；本文不强行给出未经引用校验的特定 SDK 调用示例。）

**HOOPS（SDK samples 侧可观察到的 API）：**
- WPF SegmentBrowser 的 `HPS.CullingKit` 暴露了 `SetBackFace(bool)` 以及 `SetFace(HPS.Culling.Face)` 等设置（见 `samples/wpf_sandbox/source/SegmentBrowser/Properties.cs`）。

### References
- OCCT Visualization User Guide（Automatic back face culling 默认开启、`V3d_View::SetBackFacingModel()`）：https://dev.opencascade.org/doc/overview/html/occt_user_guides__visualization.html

### 注意事项
- 仅对封闭流形（Closed Manifold）有效，CAD 的实体 B-rep 几何均满足。
- 薄壁件（钣金件）若模型为双面薄片，需关闭背面剔除或使用双面材质。
- 截面剖切视图需特殊处理：剖切面会暴露原本为内部的背面。

### 性能收益
封闭实体场景中，背面剔除将片元着色工作量削减约 50%，对片元密集（overdraw 高）的场景收益显著。

---

## 5. 小物体剔除（Small Object Culling）

### 问题
距摄像机极远的零件在屏幕上仅占 1–2 个像素，正常渲染它们的收益几乎为零，但仍会产生 draw call 和顶点处理开销。

### 原理
计算对象包围盒在屏幕空间的投影面积（像素数）或立体角。若低于阈值则跳过渲染或替换为更简化的表示（包围盒线框、Billboard 贴片）。

**屏幕空间误差公式：**
```
screenPixels = (aabbDiameter / distanceToCamera) × focalLengthPixels
if screenPixels < threshold: cull or replace with billboard
```

**HOOPS（概念层面）：**
HOOPS 在 retained mode 的性能收益中明确提到：可利用包围体判断“是否在屏幕上”以及“是否低于用户指定的尺寸限制”，从而只重绘可见或视觉重要的图元集合。

**VTK 中的 Culler：**
`vtkFrustumCoverageCuller` 根据每个 Actor 的屏幕覆盖面积分配渲染时间预算，覆盖面积极小的 Actor 直接赋予最低 LOD 或跳过。

**HOOPS（SDK samples 侧可观察到的 API）：**
- WPF SegmentBrowser 的 `HPS.CullingKit` 暴露了 `SetExtent(bool state, uint pixels)` 与 `SetDeferralExtent(bool state, uint pixels)`（见 `samples/wpf_sandbox/source/SegmentBrowser/Properties.cs`）。这些接口与“以屏幕像素阈值为条件跳过/延后绘制”这一类 small-object 策略在目标上是一致的（具体行为以对应版本 SDK 文档为准）。

### References
- HOOPS Visualize Desktop Performance（bounding volumes、size limit 与 view-dependent drawing/culling）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/technical_overview.html#performance
- VTK `vtkFrustumCoverageCuller`：https://vtk.org/doc/nightly/html/classvtkFrustumCoverageCuller.html

### 性能收益
对包含数千紧固件（螺栓、螺母）的大型装配体，远距离下可剔除 50–80% 的 draw call，配合 LOD 一起使用时效果更佳。

---

## 6. 多层次细节（Level of Detail, LOD）

### 问题
无论物体距摄像机远近，始终渲染相同精度的网格是浪费：远处物体的高精度三角面在屏幕上已无法分辨，却消耗大量顶点和片元资源。

### 原理
为每个对象预备 3–5 个精度递减的网格表示，根据对象在屏幕上的投影大小动态切换。

**基于弦高差的 LOD 生成（CAD 专用）：**

| LOD 等级 | 弦高差 | 面数比例 | 适用距离 |
|---------|--------|---------|---------|
| LOD 0   | 0.001 mm | 100%  | 近景     |
| LOD 1   | 0.01 mm  | ~10%  | 中景     |
| LOD 2   | 0.1 mm   | ~1%   | 远景     |
| LOD 3   | -        | 0%（包围盒）| 极远景 |

**弦高差自适应细分算法：**
```
TessellateEdge(p0, p1, curve, chord_dev):
    mid = curve.evaluate(midParam)
    error = distance(mid, lerp(p0, p1, 0.5))
    if error < chord_dev:
        return [p0, p1]   // 无需细分
    else:
        return TessellateEdge(p0, mid) + TessellateEdge(mid, p1)
```

**屏幕空间误差切换准则：**
```
screenError = (chordDeviation / cameraDistance) × focalLengthPixels
if screenError < 0.5: 切换到更粗糙的 LOD
```
保证屏幕上低于半像素的几何细节被粗糙 LOD 替代，视觉无损失。

**各引擎实现：**
- HOOPS：官方文档在 Performance 中强调 retained mode 支持 view-dependent drawing/culling（基于包围体/屏幕重要性做“只画重要的”），并在 Fixed Framerate 中描述了按 screen size 与 proximity 设定绘制优先级、在时间预算耗尽时中断并在交互停止后续绘；这些机制与“按屏幕重要性选择更粗 LOD/跳过绘制”的目标一致。点云章节还明确提到 vertex decimation / dynamic LOD（在点云数据上做 LOD 的具体例子）。
- OSG：`osg::LOD` 是一个按距离（或按屏幕像素大小）在子节点间切换的层级节点；每个子节点关联一个可见范围（min/max），范围可重叠且允许同时显示多个子节点（典型 LOD 场景图做法）。
- VTK：`vtkLODActor` 提供多表示（不同复杂度）的 LOD Actor，渲染时可在不同表示之间切换以满足交互帧率目标（具体策略以 VTK 版本与使用方式为准）。
- 离线工具链：批量生成 3–5 级 LOD，并导出为中间格式（如 FBX/glTF/USD）供实时引擎消费（是否以及如何实现取决于具体工具的公开能力与流水线）。

**HOOPS（SDK samples：Fixed Framerate 的具体 API 用法）**
- WPF：`Canvas.SetFrameRate(20.0f)` 用于开启固定帧率模式，`SetFrameRate(0)` 用于关闭，并在 UI 上提示与 HiddenLine 模式存在互斥关系（见 `samples/wpf_sandbox/source/Commands/DemoModeCommands.cs`）。
- Qt：同样通过 `canvas.SetFrameRate(20.0f)`/`canvas.SetFrameRate(0)` 切换固定帧率模式，并在开启帧率模式时切回平滑渲染（Phong）（见 `samples/qt_sandbox/HPSWidget.cpp`）。

### References
- HOOPS Visualize Desktop Performance（View-dependent drawing/culling、Fixed Framerate）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/technical_overview.html#performance
- HOOPS Visualize Desktop Point Clouds（vertex decimation / dynamic LOD）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/technical_overview.html#point-clouds
- OpenSceneGraph `osg::LOD`（Range/Distance/Pixel-size LOD）：https://github.com/openscenegraph/OpenSceneGraph/blob/5e0b3dacc6b95eb7eab44f714edc3d8abf020156/include/osg/LOD
- VTK `vtkLODActor`：https://vtk.org/doc/nightly/html/classvtkLODActor.html

### 性能收益
示例：中距视角下三角面数可能从“千万级”降至“百万/十万级”（量级下降），GPU 顶点处理和光栅化压力同步降低，交互帧率显著提升（具体幅度与模型/硬件/材质相关）。

---

## 7. GPU 实例化（GPU Instancing）

### 问题
工业装配体中大量重复零件（紧固件、轴承、标准件）在朴素渲染下产生 N 个独立 draw call，CPU 驱动开销成为瓶颈。重复件数量上千时，CPU 侧提交与状态切换常会先于 GPU 成为瓶颈。

### 原理
实例化将相同几何体上传一次，通过单次 draw call 并附带每实例数据缓冲区（变换矩阵、颜色、材质 ID）完成所有实例的渲染。

**OpenGL 实现：**
```glsl
// 顶点着色器
layout(location = 0) in vec3 position;
layout(location = 2) in mat4 instanceMatrix;  // 每实例，divisor=1
layout(location = 6) in vec4 instanceColor;   // 每实例，divisor=1

void main() {
    gl_Position = proj * view * instanceMatrix * vec4(position, 1.0);
    vColor = instanceColor;
}
```
```cpp
// CPU 端提交
glVertexAttribDivisor(2, 1); // mat4 占用 location 2,3,4,5
glDrawElementsInstanced(GL_TRIANGLES, indexCount, GL_UNSIGNED_INT, 0, instanceCount);
```

**Vulkan 实现：**
```cpp
// 顶点输入绑定：binding=1 为实例数据，inputRate 为 INSTANCE
VkVertexInputBindingDescription instanceBinding{};
instanceBinding.binding   = 1;
instanceBinding.stride    = sizeof(InstanceData);
instanceBinding.inputRate = VK_VERTEX_INPUT_RATE_INSTANCE;

vkCmdDrawIndexed(cmd, indexCount, instanceCount, 0, 0, 0);
```

**HOOPS（更稳妥的表述）：**
在 retained mode 场景图中复用子树/共享几何（例如通过 include/引用的方式组织重复部件）可以显著降低内存与更新成本。至于是否在底层进一步转化为 GPU instancing draw call、以及触发条件如何，属于实现与版本差异点，应以对应版本的 SDK 文档为准。

**OCCT（复用/“实例”对象的层面）：**
OCCT 可通过 `AIS_ConnectedInteractive` / `AIS_MultipleConnectedInteractive` 复用同一个可呈现对象（Presentation），在交互层面表达多个“连接/重复”的对象实例；这类机制与实例化减少重复数据与更新开销的目标一致。

### References
- HOOPS Visualize Desktop Technical Overview（Architecture/Segments/Performance）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/technical_overview.html
- OCCT Visualization User Guide（`AIS_ConnectedInteractive` / `AIS_MultipleConnectedInteractive`）：https://dev.opencascade.org/doc/overview/html/occt_user_guides__visualization.html

### 限制
- 所有实例必须共享同一基础网格，不同形状的零件各自独立。
- 高亮/选中单个实例需额外 Stencil 或 ID Buffer 支持。
- 若实例间材质差异超出实例缓冲区表达能力（如需完整 PBR 材质集切换），需拆分批次。

### 性能收益
示例：1,500 个相同螺栓若可实例化，draw calls 可从 1,500 降至 1（或少量批次），CPU 提交与状态切换开销通常会出现数量级下降，从而更容易命中 60 fps 的帧预算。

---

## 8. 几何批处理与合并（Geometry Batching & Consolidation）

### 问题
即便不存在重复几何体，大量具有相同渲染状态（材质、着色器、混合模式）的小零件仍各自产生独立 draw call，驱动验证开销累积显著。

### 原理
将处于静态状态且共享相同渲染状态的零件几何体，在 CPU 端合并为单一顶点缓冲区，以一次 draw call 提交。合并时顶点坐标变换至世界空间，消除运行时 model matrix 计算。

**静态批处理（Static Batching）：**
- 合并时机：场景冻结或显式触发。
- 合并条件：相同着色器、相同纹理、相同渲染标志、不需要独立运动。
- 结果：`N` 个零件 → `K` 个共享材质的批次（K << N），每批次 1 个 draw call。

**动态批处理（Dynamic Batching）：**
- 适用于顶点数极少（<300）的频繁变化物体，每帧 CPU 合并后提交。
- （通用思路）在 WebGL/浏览器渲染中也常见“把非常小的网格合并到更大的缓冲区里”以减少 draw call；是否以及如何实现取决于具体 Viewer 的公开文档/源码。

**HOOPS（概念层面）：**
HOOPS 的 Performance/Scene Optimization 强调减少 context switching 的成本，并提到对静态模型会构建用于绘制优化的内部结构（internal tree），且不复制几何数据；这与“对静态部分做状态排序/合批/减少切换”的优化目标一致。具体到某个版本是否提供显式的几何合并开关、API 名称与粒度，请以对应版本的 SDK 文档为准。

**HOOPS（SDK samples 侧可观察到的 API）：**
- 多个样例会在模型段上串联调用 `GetPerformanceControl().SetStaticModel(HPS::Performance::StaticModel::Attribute)` 与 `SetDisplayLists(HPS::Performance::DisplayLists::Segment)`（例如 `samples/openvr_sandbox/main.cpp`、`samples/mfc_ooc_sandbox/CProgressDialog.cpp`）。这类开关与“将静态部分编译/缓存为更适合快速重绘的内部表示、减少重复编译与状态切换”的目标一致（具体缓存粒度/触发条件依版本而异）。

**OSG（可引用的优化器能力）：**
OSG 提供 `osgUtil::Optimizer`，支持如 `MERGE_GEOMETRY`、`MERGE_GEODES`、`SHARE_DUPLICATE_STATE`、`FLATTEN_STATIC_TRANSFORMS` 等优化选项，用于合并几何/Geode、共享重复渲染状态、以及在满足条件时压平静态变换层级；这些能力与“减少 draw calls / 降低状态切换 / 优化静态场景结构”的目标一致。

### 与实例化的取舍
| 场景 | 推荐方式 |
|------|---------|
| 相同几何体 N 份 | GPU 实例化 |
| 不同几何体，相同材质，静态 | 几何批处理 |
| 不同几何体，频繁更新 | 动态批处理或放弃批处理 |

### 性能收益
示例：5,000 个静态零件若能按材质/状态合并，draw calls 可能从数千降至几十量级，CPU 驱动提交成本显著下降（具体幅度与材质种类、可合并比例、驱动/平台相关）。

### References
- HOOPS Visualize Desktop Performance（Optimized Draw Pipeline / Scene Optimization）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/technical_overview.html#performance
- OpenSceneGraph `osgUtil::Optimizer`（优化选项：MERGE_GEOMETRY/SHARE_DUPLICATE_STATE 等）：https://github.com/openscenegraph/OpenSceneGraph/blob/bc4f181d4145660eb80b2365ec3ed5e56e3e6e04/src/osgUtil/Optimizer.cpp

---

## 9. 间接多绘（Multi-Draw Indirect, MDI）

### 问题
即便使用实例化和批处理，仍可能剩余数百个批次需要逐一提交。CPU 每帧调用数百次 `glDraw*` 并在 API 层受驱动校验瓶颈制约。

### 原理
MDI 将所有 draw 参数（顶点数、实例数、起始偏移等）预存入 GPU 缓冲区，通过单次 API 调用提交全部绘制命令。GPU 驱动从缓冲区读取参数，不经 CPU 干预。

**OpenGL 4.6：**
```cpp
struct DrawElementsIndirectCommand {
    uint count;         // 索引数
    uint instanceCount; // 实例数
    uint firstIndex;    // 索引起始偏移
    int  baseVertex;    // 顶点基偏移
    uint baseInstance;  // 实例基偏移
};
// 提交 N 个 draw 命令，一次 API 调用
glMultiDrawElementsIndirect(GL_TRIANGLES, GL_UNSIGNED_INT,
                            offsetInBuffer, drawCount, stride);
```

**GPU 驱动渲染（结合 Compute Shader 剔除）：**
```
1. 视锥体剔除 Compute Shader → 写入 DrawCommand 缓冲区
2. Hi-Z 遮挡剔除 Compute Shader → 进一步筛选 DrawCommand 缓冲区
3. glMultiDrawElementsIndirect 消费缓冲区 → GPU 自主执行所有绘制
```
整个流程 CPU 仅提交 1 次 dispatch + 1 次 MDI 调用，无论场景有多少批次。

**Vulkan 等效：**
```cpp
vkCmdDrawIndexedIndirect(cmd, drawBuffer, 0, drawCount, stride);
// 或带 count 参数（VK_KHR_draw_indirect_count）：
vkCmdDrawIndexedIndirectCount(cmd, drawBuffer, 0, countBuffer, 0, maxDraw, stride);
```

### 性能收益
将 CPU 端 draw call 提交成本从 O(N) 降至 O(1)，使 CPU 从“逐 draw 调用开销”中解放出来；在批次数量很大时通常能带来明显的 CPU 帧时间下降（具体幅度与驱动、线程模型、剔除策略相关）。

---

## 10. BVH 空间索引（Bounding Volume Hierarchy）

### 问题
场景遍历（剔除判定）和交互拾取（Ray Casting）若以线性方式遍历所有对象，复杂度为 O(N)，对 10,000+ 零件场景无法实时响应。

### 原理
BVH 是一棵树，每个内部节点存储子节点几何体的 AABB，叶子节点存储实际几何图元。遍历时，与父节点 AABB 不相交的射线/视锥体会跳过整个子树，平均复杂度降至 O(log N)。

**节点布局（32 字节，对齐 Cache Line）：**
```cpp
struct BVHNode {
    float3 aabbMin;   // 12 bytes
    int    leftChild; // 4 bytes  正值=子节点索引，负值=叶子
    float3 aabbMax;   // 12 bytes
    int    rightChild;// 4 bytes
}; // 32 bytes = 1 cache line
```

**SAH 构建（Surface Area Heuristic）：**
选择使以下代价最小的分割平面：
```
cost = C_trav × (SA_left/SA_parent × N_left + SA_right/SA_parent × N_right)
```
SA = 节点包围盒表面积，N = 图元数，C_trav = 遍历代价常数。

**GPU 快速构建（LBVH Morton Code）：**
1. 计算每个对象质心的 Morton 码（XYZ 位交织）。
2. GPU 基数排序（O(N) 并行）。
3. 按最高位差异分裂构建树。
4. 构建耗时通常随图元数线性增长，适合在 GPU 上并行化（具体耗时与实现/硬件相关）。

**CAD 两级 BVH：**
| 层级 | 叶子粒度 | 用途 |
|------|---------|------|
| 顶层 BVH | 每个零件实例 AABB | 视锥体/遮挡剔除，快速拾取初筛 |
| 零件级 BVH | 每个三角面 | 精确射线-三角面求交（精确拾取、碰撞检测） |

**各引擎实现：**
- HOOPS（SDK samples 侧可观察到的 API）：WPF SegmentBrowser 在 `HPS.WindowKey.ShowSelectionOptions(out HPS.SelectionOptionsKit)` 后，提供了 `SetFrustumCullingRespected(bool)`、`SetExtentCullingRespected(bool)`、`SetDeferralExtentCullingRespected(bool)`、`SetVectorCullingRespected(bool)` 等选项（见 `samples/wpf_sandbox/source/SegmentBrowser/Properties.cs`）。这些选项说明“selection 的候选集裁剪”在 API 层是可配置的（具体默认值与效果以 SDK 文档为准）。
- OCCT：可视化文档描述了 selection 的“selection frustum + 3-level BVH traversal”，通过分层加速结构减少需要精确测试的候选数量（更具体的数据结构实现与分叉度属于实现细节，应以版本为准）。
- Intel Embree：面向 CPU 光线追踪的高性能 BVH/射线求交库，在离线渲染/仿真/分析中常用（此处作为通用技术参考，不绑定到某个 CAD 可视化引擎实现）。

### References
- OCCT Visualization User Guide（Selection：selection frustum + 3-level BVH traversal）：https://dev.opencascade.org/doc/overview/html/occt_user_guides__visualization.html

### 性能收益
视锥体裁剪/拾取的候选集规模通常可从“近似线性遍历”降到“只遍历相交子树”。实际耗时强依赖模型与实现；在 10,000+ 零件场景中，剔除与拾取的 CPU 时间往往能从不可用级别降到可交互级别。

---

## 11. CAD 曲面细分优化（Tessellation Optimization）

### 问题
CAD 数据以 B-rep（NURBS、裁剪曲面）精确表示，需细分（Tessellation）为三角网格才能提交 GPU 渲染。细分参数过细导致三角面数爆炸，过粗则视觉质量不可接受。

### 核心参数

| 参数 | 含义 | 典型范围 |
|------|------|---------|
| 弦高差（Chord Deviation） | 三角形边中点到真实曲线的最大距离 | 0.001–0.5 mm |
| 角度偏差（Angular Deviation） | 相邻三角面法线夹角最大值 | 1°–20° |
| 最小边长 | 防止平坦区域过度细分 | 模型相关 |
| 最大边长 | 防止大平面细分不足 | 模型相关 |

**自适应细分（递归）：**
```
TessellateEdge(p0, p1, curve, t0, t1, chord_dev, angle_dev):
    mid = curve.evaluate((t0+t1)/2)
    chordError = distance(mid, lerp(p0, p1, 0.5))
    angleError = angleBetween(normal(p0), normal(p1))
    if chordError < chord_dev AND angleError < angle_dev:
        return [p0, p1]
    midL = TessellateEdge(p0, mid, curve, t0, (t0+t1)/2, ...)
    midR = TessellateEdge(mid, p1, curve, (t0+t1)/2, t1, ...)
    return midL + midR
```

**屏幕自适应细分（Runtime LOD）：**
```
screenSpaceError = (chordDeviation / distanceToCamera) × focalLengthInPixels
if screenSpaceError < 0.5 pixel: 使用更粗糙的细分等级
```
保证低于半像素精度的几何细节不产生多余三角面。

**多分辨率预计算（离线）：**
- 使用离线工具链预先计算多级细分（例如 3 级，对应 LOD 0/1/2）。
- 运行时按摄像机距离切换，避免实时细分开销。

**GPU 细分着色器（补充平滑）：**
`GL_PATCHES` + Domain Shader 用于对预细分的中等精度网格进行屏幕自适应精化，适合补偿近景下的细分不足，但不适合直接用于 NURBS 复杂曲面（几何过于复杂）。

### 性能收益
合理的弦高差设置可在视觉无损的前提下：
- 典型机械零件三角面数减少 50–80%。
- 下游所有管线（顶点处理、光栅化、内存占用）同比下降。
- 配合 LOD 使用，整体显存占用可减少 60–90%。

---

## 12. 隐藏几何体移除（Hidden Geometry Removal）

### 问题
完整 CAD 装配体包含永远不可见的内部结构（密封在外壳内的发动机内件、导管内壁、焊缝填充体），它们占用三角面数和 draw call 配额，却从任何外部视角均不可见。

### 原理
**射线投射法（外部视角可见性分析）：**
1. 在包围球上均匀采样 N 个视点（典型 1,000–10,000 个方向）。
2. 从每个视点向模型发射射线，记录被击中的三角面。
3. 未被任何射线击中的三角面（面） → 永久内部不可见 → 标记删除。
4. 整个子装配体若完全不可见 → 删除整个节点及其 draw call。

**OCCT 中的可见性分析：**
可利用 BVH 加速射线-三角面求交，大幅减少分析计算时间。

**工业工具链（示例）：**
许多离线优化工具支持“隐藏几何移除/内部件剔除”，并提供射线数、精度、方向分布等配置；不同工具的能力与效果以其公开文档与模型特征为准。

### 适用范围
- 密封外壳内的机械装配（发动机、变速箱、液压系统）。
- 建筑内部不可见的基础结构。
- 管道和线束内部不可见的接头。

### 注意事项
- 这是**离线预处理**步骤，不在运行时执行。
- 需保留接近外壳边界的几何体（剖切视图需求）。
- 可与 LOD 生成流水线结合：先移除内部几何体，再对剩余几何体生成 LOD。

### 性能收益
减少内部不可见几何后，三角面数、draw call、内存与显存占用通常会同步下降，从而改善帧率与加载/流式压力（效果取决于“内部件占比”与渲染瓶颈位置）。

---

## 13. 几何流式传输（Geometry Streaming）

### 问题
超大 CAD 装配体（数 GB 几何数据）无法全部加载入 GPU 显存（典型 8–16 GB），需要动态管理显存中的几何内容。同时用户启动应用时不希望等待全量加载完成后才能看到场景。

### 原理
**显存几何缓存（LRU 淘汰）：**
1. 维护固定大小的 GPU 几何缓存池（如 2 GB）。
2. 每帧计算当前应在缓存中的对象集合（可见 + 预测即将可见）。
3. 按 LRU（最近最少使用）策略淘汰低优先级对象。
4. 后台流式传输线程读取磁盘 → CPU 暂存缓冲 → 通过 Staging Buffer 上传 GPU。
5. 上传完成前，用低精度 LOD 或包围盒占位渲染。

**优先级排序：**
```
priority(obj) = (screenSpaceCoverage / distanceToCamera²)
              × inFrustum(obj)
              × (1.0 - cacheResidency(obj))
```
屏幕占比大、在视锥体内、当前不在缓存中的对象优先上传。

**Vulkan 异步传输：**
```
Transfer Queue (DMA):
  vkCmdCopyBuffer(stagingBuffer → deviceLocalBuffer)
  → signal semaphore

Graphics Queue:
  wait semaphore → vkCmdDrawIndexed(...)
```
传输队列与图形队列并行工作，上传几何体与渲染现有几何体同时进行，无相互阻塞。

**格式优化（预处理）：**
- HOOPS HSF（HOOPS Stream File）：HOOPS Visualize Desktop 支持 HSF 的导入/导出，作为一种二进制的场景交换文件格式，可用于离线预处理与更快的加载/分发；具体的组织方式与是否按空间块切分，属于实现与工具链细节，应以实际版本与生成方式为准。
- Autodesk SVF2：APS Model Derivative API 的常见用途是把多种 CAD 格式翻译到 SVF2，以便在浏览器端使用 Viewer SDK 渲染；这类“服务端预转换 + 客户端按需加载”的流程常用于大模型在线浏览。

**渐进渲染（Progressive Rendering）：**
应用启动后尽快显示低精度概览，后台持续细化，用户无需等待全量加载完成后才开始交互。不同引擎/Viewer 的具体实现细节各异，应以公开文档与版本行为为准。

**HOOPS（SDK samples：导入/加载与“首帧可交互”工作流证据）**
- C++：使用 `HPS::Stream::ImportOptionsKit` 指定导入目标段（`SetSegment(...)`）、alternate root、portfolio，然后通过 `HPS::Stream::File::Import(...)` 得到 notifier，并 `notifier.Wait()` 等待导入完成后检查 `notifier.Status()`（见 `samples/openvr_sandbox/main.cpp`）。
- Qt：通过 `HPS::Database::GetEventDispatcher().Subscribe(..., ClassID<HPS::ImportStatusEvent>())` 订阅导入状态事件，将消息映射为 “Stage 1/3 … Stage 2/3 …”，并在导入完成后 UnSubscribe（见 `samples/qt_sandbox/exchangeimportdialog.cpp`）。
- WPF/MFC：样例均在导入完成后执行一次 `UpdateWithNotifier(HPS::Window::UpdateType::Exhaustive).Wait()` 的初始更新，并在样例注释中将其与“building the static model / Performing Initial Update”关联（见 `samples/wpf_sandbox/source/ProgressBar/ProgressBar.xaml.cs`、`samples/mfc_ooc_sandbox/CProgressDialog.cpp`）。
- 取消：样例通过 `notifier.Cancel()` 取消正在进行的导入（见 `samples/qt_sandbox/exchangeimportdialog.cpp`、`samples/wpf_sandbox/source/ProgressBar/ProgressBar.xaml.cs`）。

### References
- HOOPS Visualize Desktop Supported File Formats（HSF = HOOPS Stream File）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/supported_file_formats.html
- APS Model Derivative API Overview（Translate to SVF2）：https://aps.autodesk.com/en/docs/model-derivative/v2/developers_guide/overview/
- APS Viewer SDK Overview（Viewer 需要 SVF/SVF2）：https://aps.autodesk.com/en/docs/viewer/v7/developers_guide/overview/

### 性能收益
- 突破 GPU 显存容量限制，支持理论无限大小的装配体。
- 首帧可交互时间（Time To Interactive）从分钟级降至秒级。
- 流式吞吐量目标：在现代 PCIe/GPU 平台上，分批上传与按需淘汰通常能把“几何上传”从阻塞式成本降为可控的后台成本；可用带宽与实际吞吐强依赖硬件、驱动与数据布局。

---

## 14. 延迟渲染与后处理优化（Deferred Rendering & Post-Processing）

### 问题
前向渲染中，N 个光源 × M 个对象 = N×M 次着色计算。大型 CAD 场景可能有数十个区域光，导致着色计算量爆炸。此外 SSAO、抗锯齿等后处理若实现不当会显著增加帧时间。

### 延迟渲染原理
**几何阶段（G-Buffer Pass）：**
将场景中每个可见像素的几何属性写入多个纹理（G-Buffer）：
- 位置（World Position）
- 法线（Normal）
- 材质 ID / Albedo
- 深度

**光照阶段（Lighting Pass）：**
仅对 G-Buffer 中的可见像素执行光照计算，复杂度从 O(N×M) → O(N+M)。

**CAD 场景中的简化变体：**
大多数 CAD 渲染器采用「不完整延迟」（Semi-deferred）：
- 一趟不透明几何 pass（写深度+法线）。
- SSAO 后处理（采样 G-Buffer 深度和法线）。
- 一趟光照 pass。
- 透明几何前向渲染（独立 pass，深度排序）。

**屏幕空间环境光遮蔽（SSAO）：**
```glsl
// 在深度/法线 G-Buffer 上进行，不依赖原始几何
float ao = 0.0;
for (int i = 0; i < kernelSize; i++) {
    vec3 sample = TBN * kernelSamples[i]; // 半球样本
    sample = fragPos + sample * radius;
    vec4 offset = proj * vec4(sample, 1.0);
    offset.xyz /= offset.w;
    float sampleDepth = texture(gDepth, offset.xy * 0.5 + 0.5).r;
    ao += (sampleDepth >= sample.z + bias ? 1.0 : 0.0);
}
ao /= kernelSize;
```
SSAO 产生接触阴影效果，显著提升 CAD 实体的空间感，代价固定（仅与分辨率相关，与场景复杂度无关）。

**级联阴影贴图（CSM）：**
将视锥体分为 2–4 个级联区间，近处高精度、远处低精度，避免单张大分辨率 Shadow Map 的内存和渲染代价。

**顺序无关透明（OIT）：**
CAD 场景频繁使用半透明显示（隐藏外壳、高亮内部），OIT 可减少或避免对透明对象/三角形做严格的 back-to-front 排序。常见实现包括 depth peeling 或加权混合等近似方法：
```glsl
// 累积颜色和权重（不排序）
accum   += src.rgba * src.a * weight;
reveal  += src.a;
```
最终合成：`finalColor = accum.rgb / max(accum.a, 1e-5)`。

### 性能收益
- 延迟/半延迟：多光源场景着色计算量显著减少，节省的帧时间通常以“数毫秒”为量级（取决于分辨率与光源/材质）。
- SSAO：成本主要与分辨率和采样核相关，通常对“场景几何复杂度”不敏感。
- OIT：可减少透明排序相关的 CPU 成本，但不同 OIT 算法在质量/性能/显存之间权衡不同。

### References
- HOOPS Visualize Desktop Transparency（Depth peeling 等 order-independent 技术）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/technical_overview.html#transparency
- HOOPS Visualize Desktop Visual Quality（Ambient Occlusion 等后处理/效果）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/technical_overview.html#visual-quality

---

## 15. 多线程渲染架构（Multi-threaded Rendering Architecture）

### 问题
单线程渲染架构中，场景遍历、剔除计算、draw call 录制、几何加载均串行执行，CPU 核心利用率低，加载操作阻塞渲染帧。

### 原理
**Update / Render 线程分离：**
- **Update 线程**：处理场景图修改、属性继承计算、剔除测试、LOD 选择、脏标记传播。
- **Render 线程**：GPU 命令录制和提交，与 Update 线程持有各自的帧状态快照（double buffering）。
- 后台线程：网格加载、细分计算、纹理解码，完成后原子性地集成到场景图。

（HOOPS 相关的可引用事实）HOOPS 官方文档明确提到其 C++/C# 接口是 thread-safe 且内部利用多线程；同时在 Optimized Draw Pipeline 中提到使用 dedicated、multi-threaded memory manager，并在 idle time 自动清理内存。这些信息支撑了“通过多线程与后台任务降低交互卡顿”的设计目标，但具体线程模型与加载/集成策略仍需以 SDK 版本与应用架构为准。

**HOOPS（SDK samples：应用侧线程与回调组织方式）**
- VR 样例会在初始化后启动一个 `std::thread` 执行内部循环（`vr_loop_thread = new std::thread(&VR::InternalLoop, this);`），并使用 driver event handler 订阅每帧事件（如 `InitPictureEvent`、`FinishPictureEvent`）（见 `samples/vr_shared/vr.cpp`）。这些用法体现了“将长生命周期循环/每帧回调与 UI 主线程解耦”的应用层架构实践。

### References
- HOOPS Visualize Desktop Technical Overview（Thread-safe interfaces / internal multi-threading）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/technical_overview.html
- HOOPS Visualize Desktop Performance（multi-threaded memory manager / idle time cleanup）：https://docs.techsoft3d.com/hoops/visualize-desktop/general/technical_overview.html#performance

**Vulkan 多线程命令录制：**
```
主线程:
  vkBeginCommandBuffer(primaryCmd)
  for each worker thread:
    launch: RecordSecondaryCommandBuffer(secondaryCmd[i], geometrySubset[i])
  wait all threads
  for each secondary:
    vkCmdExecuteCommands(primaryCmd, secondaryCmd[i])
  vkEndCommandBuffer(primaryCmd)
  vkQueueSubmit(graphicsQueue, primaryCmd)
```
N 个工作线程并行录制次级命令缓冲区，录制完成后合并到主命令缓冲区提交，命令录制时间从单线程 O(draws) → O(draws/N)。

**ParaView 分布式并行渲染：**
利用 IceT（Image Compositing Engine for Tiles）实现 Sort-Last 并行渲染：
- 场景几何按空间分区分配给 N 个 MPI 节点。
- 每个节点渲染各自分区，生成局部帧缓冲。
- IceT 以二叉树 Reduce 方式合成最终图像。
- 支持超出单机 GPU 显存限制的超大数据集（数百亿三角面）。

**异步资源上传（Vulkan Transfer Queue）：**
Transfer Queue 与 Graphics Queue 并行，DMA 引擎独立工作：
- 上传时：`vkCmdCopyBuffer(stagingBuffer, deviceBuffer)` → signal Semaphore。
- 渲染时：`wait Semaphore` → 使用新几何体。
- 有效消除上传对帧时间的影响。

### 性能收益
- Update/Render 分离：消除加载卡顿，渲染帧率稳定在目标帧率。
- 多线程命令录制：在 draw 数量大且录制可并行拆分时，命令录制耗时通常可接近按 CPU 核数缩短（受同步、任务划分与驱动限制）。
- 分布式渲染：线性扩展至数百节点，支持游戏/工业实时渲染中无法承载的超大场景规模。

---

## 附录：帧时间预算示例（60 fps = 16.6 ms/帧）

（经验预算示例：不同硬件/驱动/分辨率会显著偏离；用于指导“时间预算思维”，不是验收指标。）

| 阶段 | 期望耗时 | 主要优化措施 |
|------|---------|------------|
| CPU 剔除 + draw call 构建 | 0.2–0.5 ms | Compute Shader 剔除 + MDI |
| GPU BVH + Hi-Z 剔除 Compute Shader | 0.5–1.0 ms | GPU 驱动渲染 |
| 不透明几何绘制（GPU） | 5–8 ms | LOD + Instancing + Batching |
| 阴影贴图 Pass | 2–3 ms | CSM 级联策略 |
| 后处理（SSAO、抗锯齿、色调映射） | 1–2 ms | 固定分辨率后处理 |
| 透明几何绘制 | 0.5–1 ms | OIT |
| 合计 | **~10–14 ms** | → **60+ fps** |
