
# SceneGraph
## vsglights.cpp 的 SceneGraph 节点图

```text
CommandGraph
`-- RenderGraph
    `-- View
        `-- scene : Group
            |-- original scene : Group
            |   |-- Box
            |   |-- Sphere
            |   |-- Cylinder
            |   |-- Capsule
            |   `-- Quad
            |-- AmbientLight
            |-- DirectionalLight
            |-- CullGroup
            |   `-- PointLight
            `-- CullGroup
                `-- SpotLight
```

说明：
- 上面这棵树对应 `vsglights.cpp` 的默认完整结构，也就是未传入 `--headlight` / `--no-lights` 时的节点组成。
- 如果命令行传入模型文件，那么 `original scene : Group -> Box/Sphere/Cylinder/Capsule/Quad` 这一段，会替换成读入的单个 `model : Node`。

1. 场景图结构建立， vsgt->反序列化 scene 

//.vsgt文件树结构

// CommandGraph
// `-- RenderGraph
//     `-- View
//         |-- Headlight
//         `-- vsg_scene
//             |-- Node                 (single input file returning vsg::Node)
//             `-- Group                (multiple inputs)
//                 |-- Node
//                 `-- TextureQuad      (image input converted from vsg::Data)

CullNode
    |
    MatrixTransform
        |
        Group
            |StateGroup
                |VertexIndexDraw
// Scene结构
    Camera, view, window,...
    RenderGraph, CommandGraph  ->如何组装成RecordAndSubmitTask 与 Presentation

## CommandGraph
vulkan命令组织的顶层SceneGraph节点，负责把一帧内，子图翻译成vulkan command buffer
> CommandGraph is a group node that sits at the top of the scene graph and manages the recording of its subgraph to Vulkan command buffers.

2. compile: 把场景图里的几何、状态、着色器、描述符编译成 Vulkan 资源。
Viewer::compile 遍历 CommandGraph 里的内容，收集资源需求，并把场景图编译成 Vulkan 对象
就是构建GPU Scene，填充SceneGraph的GPU资源部分

3. 渲染循环 acquire、record、submit、present

RecordAndSubmitTask 负责把它持有的那组 CommandGraph 录制成 CommandBuffer，然后把这些 CommandBuffer 提交到对应的 Vulkan Queue。

## class View
Camera、Light、Scene 组织成一个可渲染视图
本次渲染所需的相机和场景上下文

## RenderGraph
渲染过程节点的控制，协调RenderPass
作用：Framebuffer绘制一堆render pass，并遍历 View
vkCmdBeginRenderPass -> RenderGraph -> vkCmdEndRenderPass

## CommandGraph
作用：创建或复用 CommandPool/CommandBuffer，录制整条命令图。
关键实现见 CommandGraph.cpp#L47。
Vulkan 对应：vkCreateCommandPool、vkAllocateCommandBuffers、vkBeginCommandBuffer、vkEndCommandBuffer。

##  RecordAndSubmitTask
作用：每帧轮转 fence，收集 wait/signal semaphores，提交已录好的命令缓冲。
关键实现见 RecordAndSubmitTask.cpp#L83。
Vulkan 对应：vkWaitForFences、vkResetFences、vkQueueSubmit。

##  Presentation
作用：用窗口当前 imageIndex 做 present。
关键实现见 Presentation.cpp#L17。
Vulkan 对应：vkQueuePresentKHR。

##  VertexIndexDraw
作用：代表一次 indexed draw，里面有顶点数组、索引数组、drawIndexed 参数。
关键实现见 VertexIndexDraw.cpp#L137。
Vulkan 对应：vkCmdBindVertexBuffers、vkCmdBindIndexBuffer、vkCmdDrawIndexed。

## RenderLoop
advanceToNextFrame
见 Viewer.cpp#L155
它会先 poll event，然后对所有 window 调用 acquireNextImage。

update
见 Viewer.cpp#L791
这一步主要做动画、分页资源更新、场景更新，本身不直接对应单个核心 Vulkan 调用。

recordAndSubmit
见 Viewer.cpp#L814
这一步内部会走 RecordAndSubmitTask::submit。

present
见 Viewer.cpp#L848
最后调用 Presentation::present。


# Vulkan 一些性能优化相关的基本概念

## CommandBuffer
in-flight frame
命令提交模式为： vulkan api录制进CommandBuffer, 一次性提交给vkQueue

每一帧基本调用
```
vkBeginCommandBuffer
vkCmdBeginRenderPass
vkCmdSetViewport
vkCmdSetScissor
vkCmdBindDescriptorSets
vkCmdBindPipeline
vkCmdBindVertexBuffers
vkCmdBindIndexBuffer
vkCmdDrawIndexed
vkCmdEndRenderPass
vkEndCommandBuffer
vkQueueSubmit

```

优点
- 降低驱动即时解析开销，因为如果直接提交draw call，驱动每收到一条命令就要立刻做校验、转译、调度，CPU-GPU 开销很高
- 多线程构建Command 缓冲队列，主线程统一提交
- 显式同步每一批Command， 把CPU-GPU同步点从立即提交模式中的draw call变成了Command队列批次。


