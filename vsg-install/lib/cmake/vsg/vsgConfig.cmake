include(CMakeFindDependencyMacro)

find_package(Vulkan 1.1.70.0 REQUIRED)
find_dependency(Threads)
find_package(glslang CONFIG REQUIRED)
if (OFF)
    find_dependency(SPIRV-Tools-opt)
endif()


include("${CMAKE_CURRENT_LIST_DIR}/vsgTargets.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/vsgMacros.cmake")
