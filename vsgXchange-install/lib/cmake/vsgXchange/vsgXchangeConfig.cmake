include(CMakeFindDependencyMacro)

find_dependency(vsg 1.1.13 REQUIRED)

include("${CMAKE_CURRENT_LIST_DIR}/vsgXchangeTargets.cmake")
