cmake_minimum_required(VERSION 3.18)
project(build_torch_cpp_test CXX)

# find_package(Torch) reads TorchConfig.cmake from CMAKE_PREFIX_PATH/lib/cmake/Torch/
find_package(Torch REQUIRED)

add_executable(program program.cpp)
target_link_libraries(program "${TORCH_LIBRARIES}")
set_property(TARGET program PROPERTY CXX_STANDARD 17)

# On Windows copy all libtorch DLLs next to the binary so it can run without PATH changes.
if(WIN32)
  file(GLOB TORCH_DLLS "${TORCH_INSTALL_PREFIX}/lib/*.dll")
  add_custom_command(TARGET program POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
      ${TORCH_DLLS}
      $<TARGET_FILE_DIR:program>)
endif()
