#----------------------------------------------------------------
# Generated CMake target import file for configuration "Release".
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "vsg::vsg" for configuration "Release"
set_property(TARGET vsg::vsg APPEND PROPERTY IMPORTED_CONFIGURATIONS RELEASE)
set_target_properties(vsg::vsg PROPERTIES
  IMPORTED_LINK_INTERFACE_LANGUAGES_RELEASE "CXX"
  IMPORTED_LOCATION_RELEASE "${_IMPORT_PREFIX}/lib/vsg.lib"
  )

list(APPEND _cmake_import_check_targets vsg::vsg )
list(APPEND _cmake_import_check_files_for_vsg::vsg "${_IMPORT_PREFIX}/lib/vsg.lib" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
