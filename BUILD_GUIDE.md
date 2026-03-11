# VulkanSceneGraph Windows 构建指南

> 环境：Windows 10/11，Visual Studio 2022，CMake 3.10+，无系统级 Vulkan SDK

---

## 目录

- [VulkanSceneGraph Windows 构建指南](#vulkanscenegraph-windows-构建指南)
  - [目录](#目录)
  - [1. 设置代理](#1-设置代理)
  - [2. 拉取 VulkanSceneGraph](#2-拉取-vulkanscenegraph)
  - [3. 编译安装 Vulkan Headers](#3-编译安装-vulkan-headers)
  - [4. 编译安装 Vulkan Loader](#4-编译安装-vulkan-loader)
  - [5. 编译安装 glslang（运行时 Shader 编译）](#5-编译安装-glslang运行时-shader-编译)
  - [6. 编译 VulkanSceneGraph（含 glslang）](#6-编译-vulkanscenegraph含-glslang)
  - [7. 安装 VSG 到本地目录](#7-安装-vsg-到本地目录)
  - [8. 编译安装 vsgXchange（格式扩展库）](#8-编译安装-vsgxchange格式扩展库)
  - [9. 拉取并编译 vsgExamples](#9-拉取并编译-vsgexamples)
  - [10. 运行示例与查看模型](#10-运行示例与查看模型)
    - [部分示例一览](#部分示例一览)
  - [目录结构总览](#目录结构总览)

---

## 1. 设置代理

```powershell
# 设置当前会话环境变量
$env:HTTP_PROXY  = "http://127.0.0.1:7897"
$env:HTTPS_PROXY = "http://127.0.0.1:7897"
$env:ALL_PROXY   = "http://127.0.0.1:7897"

# 设置 git 全局代理
git config --global http.proxy  http://127.0.0.1:7897
git config --global https.proxy http://127.0.0.1:7897
```

---

## 2. 拉取 VulkanSceneGraph

```powershell
cd C:\github-repos\vulkanSceneGraph\Github
git clone https://github.com/vsg-dev/VulkanSceneGraph.git
```

---

## 3. 编译安装 Vulkan Headers

系统未安装 Vulkan SDK 时，需从源码编译。

```powershell
cd C:\github-repos\vulkanSceneGraph
git clone --depth 1 https://github.com/KhronosGroup/Vulkan-Headers.git

cd Vulkan-Headers
New-Item -ItemType Directory -Path build -Force | Out-Null
cd build

cmake .. -DCMAKE_INSTALL_PREFIX="C:\github-repos\vulkanSceneGraph\VulkanSDK"
cmake --build . --target install
```

安装后头文件位于 `VulkanSDK\include\vulkan\`。

---

## 4. 编译安装 Vulkan Loader

```powershell
cd C:\github-repos\vulkanSceneGraph
git clone --depth 1 https://github.com/KhronosGroup/Vulkan-Loader.git

cd Vulkan-Loader
New-Item -ItemType Directory -Path build -Force | Out-Null
cd build

cmake .. `
  -G "Visual Studio 17 2022" -A x64 `
  -DCMAKE_INSTALL_PREFIX="C:\github-repos\vulkanSceneGraph\VulkanSDK" `
  -DVulkanHeaders_DIR="C:\github-repos\vulkanSceneGraph\VulkanSDK\share\cmake\VulkanHeaders" `
  -DUPDATE_DEPS=OFF

cmake --build . --config Release -j 8
cmake --install . --config Release
```

安装后产物：
- `VulkanSDK\lib\vulkan-1.lib`
- `VulkanSDK\bin\vulkan-1.dll`

---

## 5. 编译安装 glslang（运行时 Shader 编译）

glslang 使 VSG 支持运行时 GLSL → SPIR-V 编译，**不安装则大多数图形示例无法启动**。

```powershell
cd C:\github-repos\vulkanSceneGraph
git clone --depth 1 https://github.com/KhronosGroup/glslang.git

$GLSLANG = "C:\github-repos\vulkanSceneGraph\glslang"
$GLSLANG_INSTALL = "C:\github-repos\vulkanSceneGraph\glslang-install"

cmake -S $GLSLANG -B "$GLSLANG\build" `
  -G "Visual Studio 17 2022" -A x64 `
  -DCMAKE_INSTALL_PREFIX="$GLSLANG_INSTALL" `
  -DENABLE_OPT=OFF `
  -DENABLE_GLSLANG_BINARIES=ON `
  -DBUILD_SHARED_LIBS=OFF

cmake --build "$GLSLANG\build" --config Release -j 8
cmake --install "$GLSLANG\build" --config Release
```

> `ENABLE_OPT=OFF` 跳过对 SPIRV-Tools 的依赖，无需额外安装。

安装后 CMake 配置位于 `glslang-install\lib\cmake\glslang\`。

---

## 6. 编译 VulkanSceneGraph（含 glslang）

```powershell
$env:VULKAN_SDK = "C:\github-repos\vulkanSceneGraph\VulkanSDK"

cd C:\github-repos\vulkanSceneGraph\Github\VulkanSceneGraph
New-Item -ItemType Directory -Path build -Force | Out-Null

cmake -S . -B build `
  -G "Visual Studio 17 2022" -A x64 `
  -DCMAKE_PREFIX_PATH="C:\github-repos\vulkanSceneGraph\VulkanSDK;C:\github-repos\vulkanSceneGraph\glslang-install" `
  -DVulkan_INCLUDE_DIR="C:\github-repos\vulkanSceneGraph\VulkanSDK\include" `
  -DVulkan_LIBRARY="C:\github-repos\vulkanSceneGraph\VulkanSDK\lib\vulkan-1.lib" `
  -Dglslang_DIR="C:\github-repos\vulkanSceneGraph\glslang-install\lib\cmake\glslang"

cmake --build build --config Release -j 8
```

编译产物：`build\lib\vsg.lib`（~35 MB），CMakeCache 中应有 `VSG_SUPPORTS_ShaderCompiler=ON`。

---

## 7. 安装 VSG 到本地目录

```powershell
cmake --install build --config Release `
  --prefix "C:\github-repos\vulkanSceneGraph\vsg-install"
```

安装后 CMake 配置文件位于 `vsg-install\lib\cmake\vsg\`，供其他项目 `find_package(vsg)` 使用。

---

## 8. 编译安装 vsgXchange（格式扩展库）

vsgXchange 为 vsgviewer 添加 glTF、PNG/JPG、DDS、3D Tiles 等格式的读取支持。

```powershell
cd C:\github-repos\vulkanSceneGraph\Github
git clone --depth 1 https://github.com/vsg-dev/vsgXchange.git

$XDIR    = "C:\github-repos\vulkanSceneGraph\Github\vsgXchange"
$XINSTALL = "C:\github-repos\vulkanSceneGraph\vsgXchange-install"
$PREFIX  = "C:\github-repos\vulkanSceneGraph\vsg-install;" + `
           "C:\github-repos\vulkanSceneGraph\VulkanSDK;" + `
           "C:\github-repos\vulkanSceneGraph\glslang-install"

cmake -S $XDIR -B "$XDIR\build" `
  -G "Visual Studio 17 2022" -A x64 `
  -DCMAKE_INSTALL_PREFIX="$XINSTALL" `
  -DCMAKE_PREFIX_PATH="$PREFIX" `
  -DVulkan_INCLUDE_DIR="C:\github-repos\vulkanSceneGraph\VulkanSDK\include" `
  -DVulkan_LIBRARY="C:\github-repos\vulkanSceneGraph\VulkanSDK\lib\vulkan-1.lib"

cmake --build "$XDIR\build" --config Release -j 8
cmake --install "$XDIR\build" --config Release
```

安装产物：
- `vsgXchange-install\lib\vsgXchange.lib`
- `vsgXchange-install\bin\vsgconv.exe`（格式转换工具）
- `vsgXchange-install\lib\cmake\vsgXchange\`

支持的格式（内置，无额外依赖）：
| 格式 | 说明 |
|---|---|
| `.gltf` / `.glb` | glTF 2.0 三维模型 |
| `.vsgt` / `.vsgb` / `.vsga` | VSG 原生格式 |
| `.png` / `.jpg` / `.bmp` | 图片（stbi） |
| `.dds` | DirectDraw Surface 纹理 |
| `.b3dm` / `.i3dm` / `.cmpt` | 3D Tiles |

---

## 9. 拉取并编译 vsgExamples

```powershell
cd C:\github-repos\vulkanSceneGraph\Github
git clone https://github.com/vsg-dev/vsgExamples.git VulkanSceneGraphExamples
cd VulkanSceneGraphExamples

$PREFIX = "C:\github-repos\vulkanSceneGraph\vsg-install;" + `
          "C:\github-repos\vulkanSceneGraph\VulkanSDK;" + `
          "C:\github-repos\vulkanSceneGraph\glslang-install;" + `
          "C:\github-repos\vulkanSceneGraph\vsgXchange-install"

cmake -S . -B build `
  -G "Visual Studio 17 2022" -A x64 `
  -DCMAKE_PREFIX_PATH="$PREFIX" `
  -DVulkan_INCLUDE_DIR="C:\github-repos\vulkanSceneGraph\VulkanSDK\include" `
  -DVulkan_LIBRARY="C:\github-repos\vulkanSceneGraph\VulkanSDK\lib\vulkan-1.lib" `
  -DvsgXchange_DIR="C:\github-repos\vulkanSceneGraph\vsgXchange-install\lib\cmake\vsgXchange"

cmake --build build --config Release -j 8
```

编译产物：`build\bin\Release\` 下共 **88 个** `.exe` 示例程序。

---

## 10. 运行示例与查看模型

运行前需将各 DLL 所在目录加入 PATH：

```powershell
$env:PATH = "C:\github-repos\vulkanSceneGraph\VulkanSDK\bin;" +
            "C:\github-repos\vulkanSceneGraph\vsg-install\bin;" +
            "C:\github-repos\vulkanSceneGraph\vsgXchange-install\bin;" +
            $env:PATH

cd C:\github-repos\vulkanSceneGraph\Github\VulkanSceneGraphExamples\build\bin\Release

# 直接启动（空场景）
.\vsgviewer.exe

# 打开内置 VSG 格式模型
.\vsgviewer.exe ..\..\..\data\models\teapot.vsgt
.\vsgviewer.exe ..\..\..\data\models\lz.vsgt

# 打开 glTF 文件（需 vsgXchange 支持）
.\vsgviewer.exe C:\path\to\model.glb
```

**vsgviewer 鼠标/键盘操作**

| 操作 | 效果 |
|---|---|
| 左键拖拽 | 旋转视角 |
| 右键拖拽 | 平移场景 |
| 滚轮 | 缩放 |
| `F` | 全屏切换 |
| `Esc` | 退出 |

### 部分示例一览

| 可执行文件 | 功能 |
|---|---|
| `vsgviewer.exe` | 通用场景查看器（支持 vsgt/glb/png 等） |
| `vsganimation.exe` | 动画演示 |
| `vsglights.exe` | 光照演示 |
| `vsgshadow.exe` | 阴影演示 |
| `vsgtext.exe` | 文字渲染 |
| `vsgraytracing.exe` | 光线追踪 |
| `vsgskybox.exe` | 天空盒 |
| `vsgtriangles.exe` | 基础三角形（需 shader 编译支持） |
| `vsgmaths.exe` | 数学库测试（无 GPU 依赖） |

---

## 目录结构总览

```
C:\github-repos\vulkanSceneGraph\
├── Github\
│   ├── VulkanSceneGraph\           # VSG 源码
│   │   └── build\lib\vsg.lib       # 编译产物（静态库，~35 MB）
│   ├── VulkanSceneGraphExamples\   # 示例源码
│   │   ├── build\bin\Release\      # 88 个示例可执行文件
│   │   └── data\models\            # 内置模型（teapot.vsgt、lz.vsgt 等）
│   └── vsgXchange\                 # vsgXchange 源码
├── Vulkan-Headers\                 # Vulkan 头文件源码
├── Vulkan-Loader\                  # Vulkan Loader 源码
├── glslang\                        # glslang 源码
├── VulkanSDK\                      # 本地 Vulkan SDK（头文件 + lib + dll）
│   ├── include\vulkan\
│   ├── lib\vulkan-1.lib
│   └── bin\vulkan-1.dll
├── glslang-install\                # glslang 安装目录
│   ├── lib\                        # glslang.lib、SPIRV.lib 等
│   └── lib\cmake\glslang\
├── vsg-install\                    # VSG 安装目录
│   └── lib\cmake\vsg\              # CMake 配置文件（供 find_package 使用）
└── vsgXchange-install\             # vsgXchange 安装目录
    ├── bin\vsgconv.exe
    ├── lib\vsgXchange.lib
    └── lib\cmake\vsgXchange\
```
