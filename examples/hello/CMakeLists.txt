cmake_minimum_required(VERSION 3.21)
project(Hello VERSION 1.0 LANGUAGES C)

option(HELLO_ENABLE_GREETING "Print a friendly greeting" ON)
option(HELLO_ENABLE_EXTRAS "Build the extras library" OFF)

set(HELLO_FLAVOR "vanilla" CACHE STRING "Flavour of greeting")
set_property(CACHE HELLO_FLAVOR PROPERTY STRINGS vanilla chocolate strawberry)

set(HELLO_DATA_DIR "${CMAKE_CURRENT_SOURCE_DIR}" CACHE PATH "Where data files live")
mark_as_advanced(HELLO_DATA_DIR)

add_executable(hello main.c)
target_compile_definitions(hello PRIVATE HELLO_FLAVOR="${HELLO_FLAVOR}")
if(HELLO_ENABLE_GREETING)
  target_compile_definitions(hello PRIVATE HELLO_GREETING=1)
endif()

if(HELLO_ENABLE_EXTRAS)
  add_library(hello_extras STATIC extras.c)
  target_link_libraries(hello PRIVATE hello_extras)
endif()
