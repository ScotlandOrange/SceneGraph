# VulkanSceneGraph 架构深度分析

> 基于源码 `Github/VulkanSceneGraph/` 与 `Github/VulkanSceneGraphExamples/` 直接阅读，结合运行时行为

---

## 目录

1. [节点体系 — 种类与职责](#1-节点体系--种类与职责)
2. [典型场景图的构建顺序](#2-典型场景图的构建顺序)
3. [场景图遍历的底层机制 — traverse / accept / apply](#3-场景图遍历的底层机制--traverse--accept--apply)
4. [运行时遍历机制 — RecordTraversal](#4-运行时遍历机制--recordtraversal)
5. [State 机器 — 状态栈与 Draw 命令产生](#5-state-机器--状态栈与-draw-命令产生)
6. [完整帧循环时序](#6-完整帧循环时序)
7. [关键设计模式总结](#7-关键设计模式总结)

---

## 1. 节点体系 — 种类与职责

VulkanSceneGraph 的所有节点从 `vsg::Node` 派生，按职责分为以下五个层次。

### 1.1 纯结构节点（Group 家族）

```
Node
└── Group                   // 通用容器，children: vector<ref_ptr<Node>>
    ├── QuadGroup           // 恰好 4 子节点的 Group，内存布局更紧凑
    ├── StateGroup          // Group + stateCommands 列表（状态作用域）
    └── Transform           // 抽象基，提供 transform(dmat4) 接口
        ├── MatrixTransform // matrix: dmat4，最常用的变换节点
        ├── AbsoluteTransform // 世界坐标绝对矩阵，不与父矩阵相乘
        └── CoordinateFrame // 地理/ENU 坐标系节点
```

| 节点 | 核心字段 | 作用 |
|---|---|---|
| `Group` | `children` vector | 纯结构递归 |
| `QuadGroup` | 4 个固定子槽 | 地形四叉树优化 |
| `StateGroup` | `stateCommands: StateCommands` | 定义一个 Vulkan 状态作用域（push/pop） |
| `MatrixTransform` | `matrix: dmat4` | MV 矩阵 = parentMV × localMatrix |
| `AbsoluteTransform` | `matrix: dmat4` | MV 矩阵直接设为 localMatrix（不继承） |

### 1.2 视锥剔除与 LOD 节点

```
Node
├── CullGroup    // Group + bound: dsphere，先测球再遍历子节点
├── CullNode     // 包裹单子节点的球体剔除节点
├── LOD          // 基于屏幕像素高度选择 children[i]（预排序）
├── PagedLOD     // LOD 高细节子节点按需从磁盘异步加载
└── Switch       // 每个子节点附带 Mask，按 traversalMask 过滤
```

LOD 判定公式（代码 `RecordTraversal.cpp`）：

```
lodDistance = dot(frustum.lodScale, sphere.center)
cutoff      = lodDistance × child.minimumScreenHeightRatio
visible     = sphere.radius > cutoff
```

`lodScale` 由投影矩阵和视图矩阵预先计算，把球体映射为屏幕高度。

### 1.3 渲染延迟节点（Bin 机制）

```
Node
├── DepthSorted  // bound + binNumber，按深度值排序后延迟渲染（透明物体）
├── Layer        // binNumber + value，无深度排序的固定层（HUD、背景）
└── Bin          // Bin 的容器，主场景遍历后统一回放
```

### 1.4 叶节点 — 几何绘制

```
Node
├── VertexDraw         // arrays + vkCmdDraw（无索引）
├── VertexIndexDraw    // arrays + indices + vkCmdDrawIndexed
├── Geometry           // arrays + indices + Commands list（最完整）
├── InstanceDraw       // GPU instancing vkCmdDraw
└── InstanceDrawIndexed// GPU instancing vkCmdDrawIndexed
```

叶节点本身只存储 CPU 端数组 (`vsg::Array`) 和索引，调用 `node.record(commandBuffer)` 时写入 Vulkan 命令。

### 1.5 辅助节点

```
Node
├── AmbientLight / DirectionalLight / PointLight / SpotLight
│       // 累积到 ViewDependentState，延迟写入 GPU UBO
├── Text / TextGroup             // 矢量文字渲染
├── AnimationGroup / Joint       // 骨骼动画（Joint 不产生渲染命令）
├── InstanceNode                 // 实例化绘制的数据提供者
├── TileDatabase                 // 地理瓦片数据库
└── RegionOfInterest             // 捕获 MV 矩阵供分析用，不产生渲染命令
```

### 1.6 应用层节点（Viewer 级）

```
Object
├── CommandGraph   // 拥有一个 VkCommandBuffer，是 RecordTraversal 的根
└── View           // Camera + Bins + ViewDependentState（一个 CommandGraph 可含多个 View）
```

---

## 2. 典型场景图的构建顺序

### 2.1 手动构建（Examples 中最常见模式）

以 `vsgmultigpu.cpp`、`vsgdynamictexture_cs.cpp` 等为代表：

```
Step 1: 创建 Vulkan 管线与描述符集
─────────────────────────────────
auto graphicsPipeline    = vsg::GraphicsPipeline::create(...);
auto bindGraphicsPipeline= vsg::BindGraphicsPipeline::create(graphicsPipeline);
auto descriptorSet       = vsg::DescriptorSet::create(layout, descriptors);
auto bindDescriptorSets  = vsg::BindDescriptorSets::create(..., descriptorSet);

Step 2: 创建状态根节点（StateGroup 定义绘制管线作用域）
──────────────────────────────────────────────────────
auto scenegraph = vsg::StateGroup::create();
scenegraph->add(bindGraphicsPipeline);   // slot 0: pipeline
scenegraph->add(bindDescriptorSets);     // slot 1: descriptor sets

Step 3: 创建变换节点
─────────────────────
auto transform = vsg::MatrixTransform::create();
transform->matrix = vsg::translate(x, y, z) * vsg::rotate(...);

Step 4: 创建几何叶节点
───────────────────────
auto vertices = vsg::vec3Array::create({...});
auto indices  = vsg::ushortArray::create({...});
auto geometry = vsg::VertexIndexDraw::create();
geometry->assignArrays({vertices, normals, texcoords});
geometry->assignIndices(indices);
geometry->indexCount = indices->size();

Step 5: 组装层级关系
─────────────────────
scenegraph → transform → geometry
scenegraph->addChild(transform);
transform->addChild(geometry);

Step 6: 可选的剔除节点包裹
────────────────────────────
auto cullNode = vsg::CullNode::create(bound, scenegraph);

Step 7: 连接到 View / CommandGraph
────────────────────────────────────
auto commandGraph = vsg::createCommandGraphForView(window, camera, scenegraph);
viewer->assignRecordAndSubmitTaskAndPresentation({commandGraph});
```

### 2.2 典型场景树结构（ASCII 图）

```
CommandGraph
└── RenderPass (隐含)
    └── View  [Camera: LookAt + Perspective, Bins, ViewDependentState]
        │
        └── [场景根]
            ├── DirectionalLight       ← 光源节点（收集不渲染）
            │
            ├── CullGroup [bound]      ← 视锥剔除作用域
            │   └── StateGroup [BindGraphicsPipeline, BindDescriptorSets]
            │       └── MatrixTransform [matrix]
            │           ├── CullNode [bound]
            │           │   └── LOD [radius, children]
            │           │       ├── VertexIndexDraw   (高精度)
            │           │       └── VertexDraw        (低精度)
            │           └── MatrixTransform [localMatrix]
            │               └── Geometry
            │
            ├── DepthSorted [binNumber=-1]  ← 透明物体（延迟到反向深度排序 Bin）
            │   └── StateGroup [AlphaBlendPipeline]
            │       └── VertexIndexDraw
            │
            └── Layer [binNumber=1]         ← HUD（延迟到最顶层 Bin）
                └── Text
```

### 2.3 GraphicsPipelineConfigurator 快速构建方式

`vsg::GraphicsPipelineConfigurator` 封装了管线配置流程：

```cpp
auto config = vsg::GraphicsPipelineConfigurator::create(shaderSet);
config->assignTexture("diffuseMap", textureData);
config->assignUniform("material", materialData);
config->init();

// 产生的 StateGroup 含完整 BindGraphicsPipeline + BindDescriptorSets
auto stateGroup = vsg::StateGroup::create();
config->copyTo(stateGroup, sharedObjects);
```

---

## 3. 场景图遍历的底层机制 — traverse / accept / apply

场景图是一棵树，遍历依靠三个函数相互调用形成递归。理解这三个函数的分工是读懂 VSG 所有运行时行为的基础。

### 3.1 三函数协作环路

```
         traverse(visitor)
              ↓ 迭代 children
         child->accept(visitor)   ← 虚调用（唯一一次）
              ↓ CRTP static_cast
         visitor.apply(ConcreteType&)  ← 普通重载，编译期解析
              ↓ 若需继续递归
         node.traverse(visitor)   ← 回到起点
```

三个函数各司其职，形成**一虚调用 + 编译期重载**的双层分发，避免了传统双分发 Visitor 模式的两次虚调用开销。

### 3.2 `traverse()` — 向下迭代 children

```cpp
// include/vsg/nodes/Group.h
void Group::traverse(RecordTraversal& visitor) const override
{
    for (auto& child : children)
        child->accept(visitor);   // 对每个子节点发起 accept
}
```

- **叶子节点**（`VertexIndexDraw`、`BindVertexBuffers` 等）不重写 `traverse()`，继承 `Object::traverse() {}` —— 空实现，递归自然终止。
- `Group`、`StateGroup`、`MatrixTransform`、`LOD`、`Switch` 等容器节点各自重写 `traverse`，有些在调用前后插入额外逻辑（如状态 push/pop）。

### 3.3 `accept()` — 类型自报家门（CRTP）

每个节点类通过 `Inherit<Parent, Self>` 继承，**自动生成** `accept` 覆盖：

```cpp
// include/vsg/core/Inherit.h  L78-80
void accept(RecordTraversal& visitor) const override
{
    visitor.apply(static_cast<const Subclass&>(*this));
}
```

关键点：
- `accept` 本身是虚函数（`override`），负责运行时多态 —— 这是**唯一一次**虚调用。
- 内部的 `visitor.apply(...)` **不是**虚调用，`static_cast<const Subclass&>` 在编译期确定类型，触发 `RecordTraversal` 中对应的重载版本。
- 无需手写 `accept`，`Inherit<>` 模板自动生成，新增节点类型零代码接入。

各具体类型示例：

| 类 | Inherit 声明 | 自动生成的 apply 调用 |
|---|---|---|
| `Group` | `Inherit<Node, Group>` | `visitor.apply(const Group&)` |
| `StateGroup` | `Inherit<Group, StateGroup>` | `visitor.apply(const StateGroup&)` |
| `MatrixTransform` | `Inherit<Group, MatrixTransform>` | `visitor.apply(const MatrixTransform&)` |
| `VertexIndexDraw` | `Inherit<Command, VertexIndexDraw>` | `visitor.apply(const VertexIndexDraw&)` |
| `LOD` | `Inherit<Node, LOD>` | `visitor.apply(const LOD&)` |

### 3.4 `apply()` — 做该做的事

`RecordTraversal` 提供 **30+ 个 `apply` 重载**，每个对应一种具体节点类型，决定是否继续递归：

```cpp
// 容器节点：直接递归
void apply(const Group& group)         { group.traverse(*this); }

// 状态节点：push → 递归 → pop
void apply(const StateGroup& sg)
{
    for (auto& sc : sg.stateCommands) sc->accept(*this);   // push
    sg.traverse(*this);                                     // 递归
    for (auto& sc : sg.stateCommands) sc->raccept(*this);  // pop
}

// 剔除节点：条件递归
void apply(const CullGroup& cg)
{
    if (_state->intersect(cg.bound))   // 视锥测试
        cg.traverse(*this);
}

// 叶子节点：产生 Vulkan 命令，不递归
void apply(const VertexIndexDraw& vid)
{
    _state->record();        // 惰性刷新 Pipeline/Descriptor/PushConstants
    vid.record(currentCommandBuffer);   // vkCmdDrawIndexed
}
```

### 3.5 完整递归调用栈示例

以 `CommandGraph → RenderGraph → View → StateGroup → MatrixTransform → VertexIndexDraw` 为例：

```
CommandGraph::traverse(rt)
 └─ RenderGraph::accept(rt)          ← 虚调用 #1
     Inherit<>::accept → rt.apply(const RenderGraph&)
       → vkCmdBeginRenderPass
       → rg.traverse(rt)
           └─ View::accept(rt)       ← 虚调用 #2
               rt.apply(const View&)
                 → setProjectionAndViewMatrix
                 → view.traverse(rt)
                     └─ StateGroup::accept(rt)  ← 虚调用 #3
                         rt.apply(const StateGroup&)
                           → push(BindPipeline, BindDescriptors)
                           → sg.traverse(rt)
                               └─ MatrixTransform::accept(rt)  ← 虚调用 #4
                                   rt.apply(const MatrixTransform&)
                                     → pushMatrix(T)
                                     → mt.traverse(rt)
                                         └─ VertexIndexDraw::accept(rt)  ← 虚调用 #5
                                             rt.apply(const VertexIndexDraw&)
                                               → state->record()   // 惰性写 Vulkan 状态
                                               → vkCmdDrawIndexed  // 真正的绘制命令
                                     → popMatrix
                           → pop(BindPipeline, BindDescriptors)
       → vkCmdEndRenderPass
```

每层虚调用只发生一次，apply 内部的所有逻辑均为非虚调用，性能开销极低。

### 3.6 核心规律总结

| 函数 | 谁调用 | 作用 | 是否虚函数 |
|---|---|---|---|
| `traverse(visitor)` | `apply()` 内部 | 迭代 children，向下推进递归 | 是（各容器节点 override） |
| `accept(visitor)` | `traverse()` 内部 | 以正确的具体类型调用 apply | 是（Inherit<> 自动 override） |
| `apply(ConcreteType&)` | `accept()` 内部 | 执行节点实际语义（状态/剔除/绘制/递归） | 否（普通重载，编译期解析） |

---

## 4. 运行时遍历机制 — RecordTraversal

### 4.1 节点分发机制（非虚 Visitor 模式）

VSG 使用**双层分发**而非虚函数 override 来避免虚调用开销：

```
每帧调用链（详见第 3 节对 traverse/accept/apply 三层机制的说明）：

```
Viewer::recordAndSubmit()
  └── RecordAndSubmitTask::submit()
      └── CommandGraph::record()
          └── traverse(*recordTraversal)
              └── child->accept(*recordTraversal)       ← 虚调用，1次
                  Inherit::accept → static_cast<ConcreteType>
                  recordTraversal.apply(ConcreteType&)  ← 普通重载，编译期解析
```
```

`accept()` 在节点基类中声明为虚函数，但内部的 `visitor.apply(*this)` 调用是非虚的——`this` 的类型在编译期确定，因此 `apply` 被重载解析到正确版本，**没有虚函数间接调用开销**。

### 4.2 各节点类型的 apply 行为

#### Group / QuadGroup
```cpp
void apply(const Group& group) {
    group.traverse(*this);  // 递归遍历所有 children
}
```
无任何状态修改，纯结构递归。

#### StateGroup
```cpp
void apply(const StateGroup& sg) {
    auto begin = sg.stateCommands.begin();
    auto end   = sg.stateCommands.end();

    state->push(begin, end);   // 把每个 StateCommand 压入对应 stateStacks[cmd->slot]
    sg.traverse(*this);         // 遍历子节点（此时状态已激活）
    state->pop(begin, end);    // 弹出，恢复上层状态
}
```

**关键**：`state->dirty = true` 在 push/pop 后被设置，触发下次叶节点命令录制时重新提交状态。

#### MatrixTransform
```cpp
void apply(const MatrixTransform& mt) {
    state->modelviewMatrixStack.push(mt);
    // push 内部: matrixStack.emplace(parentTop × mt.matrix)
    state->dirty = true;

    if (mt.subgraphRequiresLocalFrustum) {
        state->pushFrustum();   // 把视锥变换到 local space
        mt.traverse(*this);
        state->popFrustum();
    } else {
        mt.traverse(*this);     // 子树不需要 local frustum（优化：跳过视锥变换）
    }

    state->modelviewMatrixStack.pop();
    state->dirty = true;
}
```

#### CullGroup / CullNode
```cpp
void apply(const CullGroup& cg) {
    if (state->intersect(cg.bound)) {  // 球体 vs 视锥 5 平面测试
        cg.traverse(*this);
    }
    // 若测试失败，整个子树被剔除（不产生任何命令）
}
```

#### LOD
```cpp
void apply(const LOD& lod) {
    auto lodDistance = state->lodDistance(lod.bound);  // 负值 = 视锥外
    if (lodDistance < 0.0) return;

    for (auto& child : lod.children) {
        auto cutoff = lodDistance * child.minimumScreenHeightRatio;
        if (lod.bound.radius > cutoff) {   // 满足屏幕尺寸阈值
            child.node->accept(*this);      // 只选第一个可见 child
            return;
        }
    }
}
```

#### 叶节点 VertexIndexDraw / Geometry
```cpp
void apply(const VertexIndexDraw& vid) {
    state->record();                    // ← 刷新所有 Vulkan 状态
    vid.record(*state->_commandBuffer); // ← 写入 vkCmdDrawIndexed
}
```

#### DepthSorted / Layer（延迟渲染）
```cpp
void apply(const DepthSorted& ds) {
    if (state->intersect(ds.bound)) {
        // 计算到视点的深度
        auto distance = -(mv * center).z;
        addToBin(ds.binNumber, distance, ds.child);  // 存入 Bin，不立即渲染
    }
}
```
主场景遍历结束后，`View::apply` 统一调用 `bin->accept(*this)` 回放 Bin 中节点（此时 DepthSorted bin 按距离逆序排列，实现正确的透明混合）。

#### Light 节点
```cpp
void apply(const PointLight& light) {
    if (light.intensity >= intensityMinimum && viewDependentState)
        viewDependentState->pointLights.emplace_back(
            state->modelviewMatrixStack.top(), &light);
    // 不写入命令缓冲，累积到 UBO 更新队列
}
```

---

## 5. State 机器 — 状态栈与 Draw 命令产生

### 5.1 State 的内部结构

```cpp
class State {
    StateStacks       stateStacks;          // vector<StateStack<StateCommand>>
                                            // 按 slot 编号索引
    MatrixStack       projectionMatrixStack; // offset=0  → push_constants
    MatrixStack       modelviewMatrixStack;  // offset=64 → push_constants
    FrustumStack      _frustumStack;        // 视锥（CPU only，用于剔除）
    bool              dirty;                // 任何状态变化都置 true
    uint32_t          activeMaxStateSlot;   // 需要刷新的最大 slot
};
```

### 5.2 StateStack 的惰性 record 优化

```cpp
template<class T>
void StateStack<T>::record(CommandBuffer& cb) {
    const T* current = stack[pos];    // 当前栈顶（最近一次 push）
    if (current != stack[0]) {        // stack[0] = 上次已录制到 GPU 的值
        current->record(cb);          // vkCmdBindPipeline / vkCmdBindDescriptorSets
        stack[0] = current;           // 更新"已录制"缓存
    }
    // 若栈顶未变化，完全跳过 Vulkan 调用 → 状态切换最小化
}
```

这是 VSG 性能的关键：**只有状态真正变化时才向 CommandBuffer 写入 Vulkan 绑定命令**。

### 5.3 State::record() 完整流程

叶节点调用 `state->record()` 时执行：

```
state->record()
  │
  ├─ FOR slot = 0..activeMaxStateSlot:
  │    stateStacks[slot].record(commandBuffer)
  │      → 若 top != last_recorded:
  │           current->record(commandBuffer)   // vkCmdBindPipeline
  │                                            // vkCmdBindDescriptorSets
  │                                            // vkCmdSetViewport
  │                                            // 等各类 VkCmd
  │
  ├─ projectionMatrixStack.record(commandBuffer)
  │    → 若 dirty: vkCmdPushConstants(offset=0,  size=64, projMatrix)
  │
  └─ modelviewMatrixStack.record(commandBuffer)
       → 若 dirty: vkCmdPushConstants(offset=64, size=64, mvMatrix)
```

之后叶节点调用 `VertexIndexDraw::record(cb)`：

```cpp
// 来自 VertexIndexDraw::record
vkCmdBindVertexBuffers(commandBuffer, 0, ...);
vkCmdBindIndexBuffer(commandBuffer, indexBuffer, ...);
vkCmdDrawIndexed(commandBuffer, indexCount, instanceCount, ...);
```

### 5.4 slot 编号规则

`StateCommand` 的 `slot` 字段确保不同类型的绑定进入不同的 `stateStacks` 槽位：

| StateCommand 类型 | slot | Vulkan 命令 |
|---|---|---|
| `BindGraphicsPipeline` | 0 | `vkCmdBindPipeline` |
| `BindDescriptorSet` (set=0) | 1 | `vkCmdBindDescriptorSets` |
| `BindDescriptorSet` (set=1) | 2 | `vkCmdBindDescriptorSets` |
| `SetViewport` | view slot | `vkCmdSetViewport` |
| `BindVertexBuffers` | geom slot | `vkCmdBindVertexBuffers` |

---

## 6. 完整帧循环时序

`vsgviewer` 的主循环对应五个明确阶段：

```cpp
while (viewer->advanceToNextFrame() ...)
{
    viewer->handleEvents();    // ① 事件分发
    viewer->update();          // ② CPU 端状态更新
    viewer->recordAndSubmit(); // ③ 场景图遍历 → 录制 GPU 命令
    viewer->present();         // ④ 提交呈现
}
```

### 6.1 `advanceToNextFrame()` — 帧推进与交换链图像获取

```
pollEvents(true)                      ← 向各 Window 轮询 OS 事件，填充 _events 队列
acquireNextFrame()
  └── window->acquireNextImage()      ← vkAcquireNextImageKHR
        若 VK_ERROR_OUT_OF_DATE_KHR   → window->resize() 重建交换链，重试

FrameStamp::create(time, frameCount, simulationTime)   ← 创建新帧标识
RecordAndSubmitTask::advance()        ← 轮转三缓冲槽位索引（0/1/2 循环）
_events.emplace_back(new FrameEvent)  ← 追加帧事件供 handleEvents 使用
```

`acquireNextImage` 拿到本帧要写入的交换链图像索引，后续 `vkCmdBeginRenderPass` 用此索引选取 Framebuffer。

### 6.2 `handleEvents()` — 事件 Visitor 分发

```cpp
for (auto& event : _events)
    for (auto& handler : _eventHandlers)
        event->accept(*handler);   // 同样的 accept/apply Visitor 模式
```

`vsgviewer` 注册的 EventHandler：
- `CloseHandler` → 响应关闭按钮 / ESC
- `Trackball` → 鼠标拖拽修改 `LookAt` 矩阵（只改 CPU 端 Camera 对象）
- `CameraAnimationHandler` → 按路径文件更新相机

### 6.3 `update()` — CPU 端状态更新

```
DatabasePager::updateSceneGraph(_frameStamp)  ← 合并异步加载完成的 PagedLOD 子节点到场景树
UpdateOperations::run()                       ← 执行用户注册的 UpdateOperation（动态纹理等）
AnimationManager::run(_frameStamp)            ← 推进动画，更新 MatrixTransform::matrix
```

### 6.4 `recordAndSubmit()` — 场景图录制（最核心）

```
Viewer::recordAndSubmit()
│
└─ RecordAndSubmitTask::submit(frameStamp)
   │
   ├─ START: fence->wait()
   │    等待 GPU 消费完同一缓冲槽的上一次 vkQueueSubmit
   │    → 三缓冲 CPU/GPU 并行的同步点
   │
   ├─ TransferTask::transferData(BEFORE)
   │    脏数据通过 Staging Buffer 上传 GPU（动态纹理/UBO）
   │    → 产生 dataTransferredSemaphore 供后续 submit 等待
   │
   ├─ CommandGraph::record()
   │   ├─ 获取/复用空闲 CommandBuffer
   │   ├─ vkBeginCommandBuffer
   │   │
   │   └─ traverse(*recordTraversal)     ← 进入 RenderGraph
   │       └─ RenderGraph::accept()
   │           ├─ vkCmdBeginRenderPass   ← 选当前帧 Framebuffer
   │           ├─ traverse(recordTraversal)  ← 进入 View 及场景树
   │           │   └─ apply(View)
   │           │       ├─ state->setProjectionAndViewMatrix(proj, view)
   │           │       │     → projectionMatrixStack.set(proj)
   │           │       │     → modelviewMatrixStack.set(view)
   │           │       │     → pushFrustum()（world space 视锥）
   │           │       │
   │           │       └─ view->traverse(*this)   ← 递归场景图（见第3、4节）
   │           │           ├─ Light   → viewDependentState 收集（不写命令）
   │           │           ├─ CullGroup → intersect() 失败则整棵子树跳过
   │           │           ├─ LOD     → 选唯一一个满足屏幕尺寸的 child
   │           │           ├─ StateGroup → push/pop 状态栈
   │           │           ├─ MatrixTransform → push/pop MV 矩阵
   │           │           ├─ VertexIndexDraw → state->record() + vkCmdDrawIndexed ★
   │           │           └─ DepthSorted/Layer → addToBin()（延迟）
   │           │
   │           ├─ Bin::traverse()       ← 主遍历结束后回放延迟节点
   │           │   DepthSorted(-1): 按深度升序（近→远，透明物正确混合）
   │           │   Layer(+1):       按 value 降序（HUD 最后覆盖）
   │           │
   │           ├─ ViewDependentState::traverse()  ← 打包灯光 UBO → vkCmdBindDescriptorSets
   │           └─ vkCmdEndRenderPass
   │
   │   └─ vkEndCommandBuffer
   │
   └─ FINISH: vkQueueSubmit(
         commandBuffers     = [vk_commandBuffer],
         waitSemaphores     = [imageAvailable, dataTransferred],
         signalSemaphores   = [renderFinished],
         fence              = current_fence
      )
```

### 6.5 `present()` — 呈现到屏幕

```
Presentation::present()
  └─ vkQueuePresentKHR(
       waitSemaphores = [renderFinished],   ← 等 GPU 渲染完成
       swapchains     = [swapchain],
       imageIndices   = [imageIndex]        ← 展示本帧渲染的图像
     )
```

### 6.6 三缓冲时序与 CPU/GPU 并行

```
帧 N-2      帧 N-1      帧 N
─────────────────────────────────────────────────
CPU: [record]→[submit]  [record]→[submit]  [record]→[submit]
GPU:          [render N-2]     [render N-1]     [render N]
Fence:     wait(slot0)      wait(slot1)      wait(slot2)
```

`RecordAndSubmitTask::start()` 中的 `fence->wait()` 是三缓冲的同步点：等待**同一槽位**（3帧前）的 GPU 工作完成才覆写 CommandBuffer，确保 CPU 录制和 GPU 执行之间始终有 1~2 帧的并行裕量。

### 6.7 惰性状态刷新的实际收益

连续渲染 1000 个使用同一管线的 Mesh：

```
Mesh[0]:  StateGroup push(PipelineA) → dirty=true
          VertexIndexDraw → record():
              slot0: A ≠ null(cached) → vkCmdBindPipeline(A)  ✓ 写
              mvStack: dirty           → vkCmdPushConstants    ✓ 写
              vkCmdDrawIndexed                                 ✓ 写

Mesh[1]:  VertexIndexDraw → record():
              slot0: A == A(cached)   → 跳过！                 ✗
              mvStack: dirty(新矩阵)   → vkCmdPushConstants    ✓ 写
              vkCmdDrawIndexed                                 ✓ 写

Mesh[2..999]:  同上，Pipeline 绑定仅 1 次，每帧节省 999 次 vkCmdBindPipeline
```

状态切换最小化在 CPU 录制阶段就完成，不依赖驱动层过滤。

---

## 7. 关键设计模式总结

### 7.1 状态继承与作用域

`StateGroup` 形成嵌套作用域：外层 `StateGroup` 绑定的管线对所有子孙节点有效；内层 `StateGroup` 可覆盖（push 新值）并在退出时自动恢复。这等价于 OpenGL 的 `glPushAttrib/glPopAttrib`，但通过栈数组而非 OpenGL 上下文实现。

```
StateGroup [Pipeline_A, DescSet_A]         ← slot 0 = Pipeline_A
  └── MatrixTransform
      ├── Geometry                          ← record(): slot0=A → vkBindPipeline(A)
      └── StateGroup [Pipeline_B]           ← slot 0 = Pipeline_B（覆盖）
              └── Geometry                  ← record(): slot0=B → vkBindPipeline(B)
      └── Geometry                          ← 退出内层SG后: slot0=A，重新绑定
```

### 7.2 惰性状态刷新

`state->dirty` 标志配合 `StateStack::stack[0]` 缓存，实现两级剪枝：
1. 若 `!dirty`：`state->record()` 整体跳过（零开销）
2. 若 `dirty` 但某 slot 状态未变：该 slot 的 `record()` 跳过（只提交变化部分）

### 7.3 视锥剔除的矩阵传播

`subgraphRequiresLocalFrustum = false`（默认 true）可跳过视锥变换，适用于已知不需要子节点 LOD 测试的纯渲染子树，是常见性能优化点。

### 7.4 Bin 延迟渲染（DepthSorted / Layer）

透明物体和 HUD 不在主遍历中立即绘制，而是注册到 `Bin`，主场景遍历完成后统一排序回放。`Bin` 保存的是 `(State* snapshot, double value, const Node* node)` 三元组，回放时 state 恢复到产生入队时的状态上下文。

### 7.5 光照的两阶段处理

Light 节点在 RecordTraversal 遍历时仅把 `(mvMatrix, lightPtr)` 存入 `viewDependentState`，**不立即写 GPU 命令**；整个场景遍历完成后，`ViewDependentState::traverse()` 统一打包所有灯光数据、更新 UBO 并绑定到命令缓冲。

---

## 附：核心类文件速查

| 类 | 文件 |
|---|---|
| `Object` | `include/vsg/core/Object.h` |
| `Inherit<P,S>` | `include/vsg/core/Inherit.h` |
| `Node` | `include/vsg/core/Node.h` |
| `Group` | `include/vsg/nodes/Group.h` |
| `RecordTraversal` | `include/vsg/app/RecordTraversal.h` / `src/vsg/app/RecordTraversal.cpp` |
| `State` | `include/vsg/vk/State.h` / `src/vsg/vk/State.cpp` |
| `StateGroup` | `include/vsg/nodes/StateGroup.h` |
| `MatrixTransform` | `include/vsg/nodes/MatrixTransform.h` |
| `CullGroup/CullNode` | `include/vsg/nodes/CullGroup.h` |
| `LOD / PagedLOD` | `include/vsg/nodes/LOD.h` |
| `VertexIndexDraw` | `include/vsg/nodes/VertexIndexDraw.h` |
| `View / CommandGraph` | `include/vsg/app/View.h` / `include/vsg/app/CommandGraph.h` |
| `CommandGraph` | `src/vsg/app/CommandGraph.cpp` |
| `RenderGraph` | `include/vsg/app/RenderGraph.h` / `src/vsg/app/RenderGraph.cpp` |
| `RecordAndSubmitTask` | `include/vsg/app/RecordAndSubmitTask.h` / `src/vsg/app/RecordAndSubmitTask.cpp` |
| `Viewer` | `include/vsg/app/Viewer.h` / `src/vsg/app/Viewer.cpp` |
| `Presentation` | `include/vsg/app/Presentation.h` |
