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
  - [5. 编译 VulkanSceneGraph](#5-编译-vulkanscenegraph)
  - [6. 安装 VSG 到本地目录](#6-安装-vsg-到本地目录)
  - [7. 拉取并编译 vsgExamples](#7-拉取并编译-vsgexamples)
  - [8. 运行示例](#8-运行示例)
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

## 5. 编译 VulkanSceneGraph

```powershell
$env:VULKAN_SDK = "C:\github-repos\vulkanSceneGraph\VulkanSDK"

cd C:\github-repos\vulkanSceneGraph\Github\VulkanSceneGraph
New-Item -ItemType Directory -Path build -Force | Out-Null

cmake -S . -B build `
  -G "Visual Studio 17 2022" -A x64 `
  -DCMAKE_PREFIX_PATH="C:\github-repos\vulkanSceneGraph\VulkanSDK" `
  -DVulkan_INCLUDE_DIR="C:\github-repos\vulkanSceneGraph\VulkanSDK\include" `
  -DVulkan_LIBRARY="C:\github-repos\vulkanSceneGraph\VulkanSDK\lib\vulkan-1.lib"

cmake --build build --config Release -j 8
```

编译产物：`build\lib\vsg.lib`（~35 MB）

> **说明**：`glslang` 为可选依赖，未安装时运行时 shader 编译功能禁用，不影响核心库使用。

---

## 6. 安装 VSG 到本地目录

```powershell
cmake --install build --config Release `
  --prefix "C:\github-repos\vulkanSceneGraph\vsg-install"
```

安装后 CMake 配置文件位于 `vsg-install\lib\cmake\vsg\`，供其他项目 `find_package(vsg)` 使用。

---

## 7. 拉取并编译 vsgExamples

```powershell
cd C:\github-repos\vulkanSceneGraph\Github\VulkanSceneGraphExamples
git clone https://github.com/vsg-dev/vsgExamples.git .

cmake -S . -B build `
  -G "Visual Studio 17 2022" -A x64 `
  -DCMAKE_PREFIX_PATH="C:\github-repos\vulkanSceneGraph\vsg-install;C:\github-repos\vulkanSceneGraph\VulkanSDK" `
  -DVulkan_INCLUDE_DIR="C:\github-repos\vulkanSceneGraph\VulkanSDK\include" `
  -DVulkan_LIBRARY="C:\github-repos\vulkanSceneGraph\VulkanSDK\lib\vulkan-1.lib"

cmake --build build --config Release -j 8
```

编译产物：`build\bin\Release\` 下共 **84 个** `.exe` 示例程序。

---

## 8. 运行示例

运行前需将 Vulkan Loader DLL 加入 PATH：

```powershell
$env:PATH += ";C:\github-repos\vulkanSceneGraph\VulkanSDK\bin"

cd C:\github-repos\vulkanSceneGraph\Github\VulkanSceneGraphExamples\build\bin\Release
.\vsgviewer.exe
```

### 部分示例一览

| 可执行文件 | 功能 |
|---|---|
| `vsgviewer.exe` | 通用场景查看器 |
| `vsganimation.exe` | 动画演示 |
| `vsglights.exe` | 光照演示 |
| `vsgshadow.exe` | 阴影演示 |
| `vsgtext.exe` | 文字渲染 |
| `vsgraytracing.exe` | 光线追踪 |
| `vsgskybox.exe` | 天空盒 |

---

## 目录结构总览

```
C:\github-repos\vulkanSceneGraph\
├── Github\
│   ├── VulkanSceneGraph\       # VSG 源码
│   │   └── build\lib\vsg.lib   # 编译产物（静态库）
│   └── VulkanSceneGraphExamples\  # 示例源码
│       └── build\bin\Release\  # 84 个示例可执行文件
├── Vulkan-Headers\             # Vulkan 头文件源码
├── Vulkan-Loader\              # Vulkan Loader 源码
├── VulkanSDK\                  # 本地 Vulkan SDK（头文件 + lib + dll）
│   ├── include\vulkan\
│   ├── lib\vulkan-1.lib
│   └── bin\vulkan-1.dll
└── vsg-install\                # VSG 安装目录
    └── lib\cmake\vsg\          # CMake 配置文件（供 find_package 使用）
```
