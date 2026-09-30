#include "ControlPlotGUI.h"

#include <SofaImGui/guis/AdditionalGUIRegistry.h>

#include <string>

namespace
{

bool g_initialized = false;

} // namespace

extern "C"
{

void initExternalModule()
{
    if (!g_initialized)
    {
        sofaimgui::guis::MainAdditionGUIRegistry::registerAdditionalGUI(
            new continuum_robot_lab::visualization::ControlPlotGUI());
        g_initialized = true;
    }
}

const char* getModuleName()
{
    return "ContinuumRobotLabViz";
}

const char* getModuleVersion()
{
    return "0.1.0";
}

const char* getModuleLicense()
{
    return "Unspecified";
}

const char* getModuleDescription()
{
    return "Project-specific real-time plots for Continuum Robot Lab.";
}

const char* getModuleComponentList()
{
    static const std::string noComponents;
    return noComponents.c_str();
}

} // extern "C"
