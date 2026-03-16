#----------------------------------------------------------------
# Generated CMake target import file for configuration "Debug".
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "vsgXchange::vsgXchange" for configuration "Debug"
set_property(TARGET vsgXchange::vsgXchange APPEND PROPERTY IMPORTED_CONFIGURATIONS DEBUG)
set_target_properties(vsgXchange::vsgXchange PROPERTIES
  IMPORTED_LINK_INTERFACE_LANGUAGES_DEBUG "CXX"
  IMPORTED_LOCATION_DEBUG "${_IMPORT_PREFIX}/lib/vsgXchanged.lib"
  )

list(APPEND _cmake_import_check_targets vsgXchange::vsgXchange )
list(APPEND _cmake_import_check_files_for_vsgXchange::vsgXchange "${_IMPORT_PREFIX}/lib/vsgXchanged.lib" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
