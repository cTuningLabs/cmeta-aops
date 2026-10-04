cmake_minimum_required(VERSION 3.18)
project(test_nmm_torch_cpp CXX)

# find_package(Torch) reads TorchConfig.cmake from CMAKE_PREFIX_PATH/lib/cmake/Torch/
find_package(Torch REQUIRED)

add_executable(program program.cpp)
target_link_libraries(program "${TORCH_LIBRARIES}")
# The C++ standard LibTorch's headers need: the one its TorchConfig.cmake sets on the torch target
# (17 up to 2.8, 20 from 2.9 on), else 17; -DCMETA_CXX_STANDARD=<n> overrides it
set(CMETA_CXX_STANDARD "" CACHE STRING "C++ standard of the program (default: the one LibTorch needs)")
if(CMETA_CXX_STANDARD)
  set(_cmeta_cxx_standard ${CMETA_CXX_STANDARD})
else()
  get_target_property(_cmeta_cxx_standard torch CXX_STANDARD)
  if(NOT _cmeta_cxx_standard)
    set(_cmeta_cxx_standard 17)
  endif()
endif()
message(STATUS "C++ standard for the program: ${_cmeta_cxx_standard} (LibTorch ${Torch_VERSION})")
set_property(TARGET program PROPERTY CXX_STANDARD ${_cmeta_cxx_standard})
set_property(TARGET program PROPERTY CXX_STANDARD_REQUIRED ON)

# Honor compute-backend flags passed by cMeta (-DUSE_MPS=ON, -DUSE_CUDA=ON, etc.)
# and convert them into compile definitions so #ifdef guards in program.cpp work.
foreach(_flag USE_CUDA USE_ROCM USE_MPS USE_XPU)
  if(${_flag})
    target_compile_definitions(program PRIVATE ${_flag}=1)
  endif()
endforeach()

# On Windows copy all libtorch DLLs next to the binary so it can run without PATH changes.
if(WIN32)
  file(GLOB TORCH_DLLS "${TORCH_INSTALL_PREFIX}/lib/*.dll")
  add_custom_command(TARGET program POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
      ${TORCH_DLLS}
      $<TARGET_FILE_DIR:program>)
endif()
