cmake_minimum_required(VERSION 3.22)
project(ContinuumRobotLabViz VERSION 0.1.0 LANGUAGES CXX)

if(NOT DEFINED SOFA_IMGUI_ROOT OR NOT DEFINED SOFA_IMGUI_LIBRARY)
    message(FATAL_ERROR "SOFA_IMGUI_ROOT and SOFA_IMGUI_LIBRARY are required")
endif()
if(NOT DEFINED IMGUI_SOURCE_ROOT OR NOT DEFINED IMPLOT_SOURCE_ROOT)
    message(FATAL_ERROR "IMGUI_SOURCE_ROOT and IMPLOT_SOURCE_ROOT are required")
endif()

find_package(Sofa.Simulation.Core REQUIRED)

add_library(SofaImGuiExternal SHARED IMPORTED GLOBAL)
set_target_properties(SofaImGuiExternal PROPERTIES
    IMPORTED_LOCATION "${SOFA_IMGUI_LIBRARY}"
    INTERFACE_INCLUDE_DIRECTORIES "${SOFA_IMGUI_ROOT}/include"
)

add_library(${PROJECT_NAME} SHARED
    src/ControlPlotGUI.cpp
    src/init.cpp
)
target_compile_features(${PROJECT_NAME} PRIVATE cxx_std_17)
target_compile_definitions(${PROJECT_NAME} PRIVATE
    IMGUI_API=SOFAIMGUI_API
    IMGUI_USER_CONFIG=<SofaImGui/config.h>
)
target_include_directories(${PROJECT_NAME} PRIVATE
    "${IMGUI_SOURCE_ROOT}"
    "${IMPLOT_SOURCE_ROOT}"
)
target_link_libraries(${PROJECT_NAME} PRIVATE
    Sofa.Simulation.Core
    SofaImGuiExternal
)

install(TARGETS ${PROJECT_NAME} LIBRARY DESTINATION lib)
