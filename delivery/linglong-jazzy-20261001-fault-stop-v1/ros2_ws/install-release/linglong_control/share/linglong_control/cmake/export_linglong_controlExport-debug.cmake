#----------------------------------------------------------------
# Generated CMake target import file for configuration "Debug".
#----------------------------------------------------------------

# Commands may need to know the format version.
set(CMAKE_IMPORT_FILE_VERSION 1)

# Import target "linglong_control::linglong_sim_system" for configuration "Debug"
set_property(TARGET linglong_control::linglong_sim_system APPEND PROPERTY IMPORTED_CONFIGURATIONS DEBUG)
set_target_properties(linglong_control::linglong_sim_system PROPERTIES
  IMPORTED_LOCATION_DEBUG "${_IMPORT_PREFIX}/lib/liblinglong_sim_system.so"
  IMPORTED_SONAME_DEBUG "liblinglong_sim_system.so"
  )

list(APPEND _cmake_import_check_targets linglong_control::linglong_sim_system )
list(APPEND _cmake_import_check_files_for_linglong_control::linglong_sim_system "${_IMPORT_PREFIX}/lib/liblinglong_sim_system.so" )

# Commands beyond this point should not need to know the version.
set(CMAKE_IMPORT_FILE_VERSION)
