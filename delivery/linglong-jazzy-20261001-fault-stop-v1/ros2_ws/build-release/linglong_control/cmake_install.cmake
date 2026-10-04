# Install script for directory: /workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control

# Set the install prefix
if(NOT DEFINED CMAKE_INSTALL_PREFIX)
  set(CMAKE_INSTALL_PREFIX "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/install-release/linglong_control")
endif()
string(REGEX REPLACE "/$" "" CMAKE_INSTALL_PREFIX "${CMAKE_INSTALL_PREFIX}")

# Set the install configuration name.
if(NOT DEFINED CMAKE_INSTALL_CONFIG_NAME)
  if(BUILD_TYPE)
    string(REGEX REPLACE "^[^A-Za-z0-9_]+" ""
           CMAKE_INSTALL_CONFIG_NAME "${BUILD_TYPE}")
  else()
    set(CMAKE_INSTALL_CONFIG_NAME "Debug")
  endif()
  message(STATUS "Install configuration: \"${CMAKE_INSTALL_CONFIG_NAME}\"")
endif()

# Set the component getting installed.
if(NOT CMAKE_INSTALL_COMPONENT)
  if(COMPONENT)
    message(STATUS "Install component: \"${COMPONENT}\"")
    set(CMAKE_INSTALL_COMPONENT "${COMPONENT}")
  else()
    set(CMAKE_INSTALL_COMPONENT)
  endif()
endif()

# Install shared libraries without execute permission?
if(NOT DEFINED CMAKE_INSTALL_SO_NO_EXE)
  set(CMAKE_INSTALL_SO_NO_EXE "1")
endif()

# Is this installation the result of a crosscompile?
if(NOT DEFINED CMAKE_CROSSCOMPILING)
  set(CMAKE_CROSSCOMPILING "FALSE")
endif()

# Set default install directory permissions.
if(NOT DEFINED CMAKE_OBJDUMP)
  set(CMAKE_OBJDUMP "/usr/bin/objdump")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/linglong_hardware.xml")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/liblinglong_sim_system.so" AND
     NOT IS_SYMLINK "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/liblinglong_sim_system.so")
    file(RPATH_CHECK
         FILE "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/liblinglong_sim_system.so"
         RPATH "")
  endif()
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE SHARED_LIBRARY FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/liblinglong_sim_system.so")
  if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/liblinglong_sim_system.so" AND
     NOT IS_SYMLINK "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/liblinglong_sim_system.so")
    file(RPATH_CHANGE
         FILE "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/liblinglong_sim_system.so"
         OLD_RPATH "/opt/ros/jazzy/lib:/opt/ros/jazzy/lib/x86_64-linux-gnu:"
         NEW_RPATH "")
    if(CMAKE_INSTALL_DO_STRIP)
      execute_process(COMMAND "/usr/bin/strip" "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/lib/liblinglong_sim_system.so")
    endif()
  endif()
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include" TYPE DIRECTORY FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/include/")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control" TYPE DIRECTORY FILES
    "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/config"
    "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/launch"
    "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/urdf"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/RELEASE_ID")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/environment" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_environment_hooks/pythonpath.sh")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/environment" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_environment_hooks/pythonpath.dsv")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/python3.12/site-packages/linglong_control_tools-0.3.0-py3.12.egg-info" TYPE DIRECTORY FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_python/linglong_control_tools/linglong_control_tools.egg-info/")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/python3.12/site-packages/linglong_control_tools" TYPE DIRECTORY FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/linglong_control_tools/" REGEX "/[^/]*\\.pyc$" EXCLUDE REGEX "/\\_\\_pycache\\_\\_$" EXCLUDE)
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  execute_process(
        COMMAND
        "/usr/bin/python3" "-m" "compileall"
        "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/install-release/linglong_control/lib/python3.12/site-packages/linglong_control_tools"
      )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib/linglong_control" TYPE PROGRAM FILES
    "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/scripts/control_diagnostics"
    "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/scripts/trajectory_demo"
    "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/scripts/architecture_probe"
    "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/scripts/fault_snapshot"
    "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/scripts/system_manager"
    "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/scripts/system_transition"
    )
endif()

if(NOT CMAKE_INSTALL_LOCAL_ONLY)
  # Include the install script for the subdirectory.
  include("/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/gtest/cmake_install.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/environment" TYPE FILE FILES "/opt/ros/jazzy/lib/python3.12/site-packages/ament_package/template/environment_hook/library_path.sh")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/environment" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_environment_hooks/library_path.dsv")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/ament_index/resource_index/package_run_dependencies" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_index/share/ament_index/resource_index/package_run_dependencies/linglong_control")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/ament_index/resource_index/parent_prefix_path" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_index/share/ament_index/resource_index/parent_prefix_path/linglong_control")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/environment" TYPE FILE FILES "/opt/ros/jazzy/share/ament_cmake_core/cmake/environment_hooks/environment/ament_prefix_path.sh")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/environment" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_environment_hooks/ament_prefix_path.dsv")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/environment" TYPE FILE FILES "/opt/ros/jazzy/share/ament_cmake_core/cmake/environment_hooks/environment/path.sh")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/environment" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_environment_hooks/path.dsv")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_environment_hooks/local_setup.bash")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_environment_hooks/local_setup.sh")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_environment_hooks/local_setup.zsh")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_environment_hooks/local_setup.dsv")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_environment_hooks/package.dsv")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/ament_index/resource_index/packages" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_index/share/ament_index/resource_index/packages/linglong_control")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/ament_index/resource_index/hardware_interface__pluginlib__plugin" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_index/share/ament_index/resource_index/hardware_interface__pluginlib__plugin/linglong_control")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/linglong_control/cmake/export_linglong_controlExport.cmake")
    file(DIFFERENT _cmake_export_file_changed FILES
         "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/linglong_control/cmake/export_linglong_controlExport.cmake"
         "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/CMakeFiles/Export/e194fde726a73f43d8191ca2beaa33a8/export_linglong_controlExport.cmake")
    if(_cmake_export_file_changed)
      file(GLOB _cmake_old_config_files "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/linglong_control/cmake/export_linglong_controlExport-*.cmake")
      if(_cmake_old_config_files)
        string(REPLACE ";" ", " _cmake_old_config_files_text "${_cmake_old_config_files}")
        message(STATUS "Old export file \"$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/linglong_control/cmake/export_linglong_controlExport.cmake\" will be replaced.  Removing files [${_cmake_old_config_files_text}].")
        unset(_cmake_old_config_files_text)
        file(REMOVE ${_cmake_old_config_files})
      endif()
      unset(_cmake_old_config_files)
    endif()
    unset(_cmake_export_file_changed)
  endif()
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/cmake" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/CMakeFiles/Export/e194fde726a73f43d8191ca2beaa33a8/export_linglong_controlExport.cmake")
  if(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Dd][Ee][Bb][Uu][Gg])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/cmake" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/CMakeFiles/Export/e194fde726a73f43d8191ca2beaa33a8/export_linglong_controlExport-debug.cmake")
  endif()
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/cmake" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_export_targets/ament_cmake_export_targets-extras.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/cmake" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_export_dependencies/ament_cmake_export_dependencies-extras.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control/cmake" TYPE FILE FILES
    "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_core/linglong_controlConfig.cmake"
    "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/ament_cmake_core/linglong_controlConfig-version.cmake"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/linglong_control" TYPE FILE FILES "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/src/linglong_control/package.xml")
endif()

if(CMAKE_INSTALL_COMPONENT)
  set(CMAKE_INSTALL_MANIFEST "install_manifest_${CMAKE_INSTALL_COMPONENT}.txt")
else()
  set(CMAKE_INSTALL_MANIFEST "install_manifest.txt")
endif()

string(REPLACE ";" "\n" CMAKE_INSTALL_MANIFEST_CONTENT
       "${CMAKE_INSTALL_MANIFEST_FILES}")
file(WRITE "/workspace/delivery/linglong-jazzy-20261001-fault-stop-v1/ros2_ws/build-release/linglong_control/${CMAKE_INSTALL_MANIFEST}"
     "${CMAKE_INSTALL_MANIFEST_CONTENT}")
