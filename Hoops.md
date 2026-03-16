

# Retained Mode
保留所有的Primitive信息，方便做算法优化

只更新变化的部分，画面，几何数据
包围盒系统裁剪，根据：屏幕上可见的、用户指定尺寸限制、需要redraw的重要程度。

# 管线优化
array-based 数据结构，增加缓存命中
线程安全的内存管理和分配，空闲时间的内存回收清理
着色器代码优化

**CPU和GPU VertexBuffer数据镜像，确保显存有余量，不至于驱动使用主存**
> HOOPS Visualize Desktop automatically creates and manages vertex buffers on the graphics card, mirroring the geometry data on the CPU. HOOPS Visualize Desktop works to ensure graphics card memory is not exhausted, which would otherwise cause the graphics driver to page main memory resulting in a catastrophic slowdown.

# 场景优化
### 核心观点：
- GPU上下文切换的成本，会随着场景变大而恶化，
- 只画最关键的数据，而不是所有的数据。
### 提到的技术做法：
- 良好的Scene组织加速Culling
- culling: backplane, view frustum and extent culling
- 设立**Static Model**概念，表示由App创建的原始结构，Scene Graph负责对Static Model的自动优化。

# 固定帧率
- 提供接口，实现根据当前相机参数，按照优先级，绘制整个场景。
- 优先级定义：Object在屏幕中的尺寸，与观察者之间的距离。
- 旋转的时候，减少细节绘制，更多关注在旋转响应上。
- 低帧率如何处理：当一帧时间超过了交互响应帧率时间，就中断渲染过程，立刻开始下一帧绘制，当Navigation停止的时候，继续从中断点继续，完成剩余绘制。
