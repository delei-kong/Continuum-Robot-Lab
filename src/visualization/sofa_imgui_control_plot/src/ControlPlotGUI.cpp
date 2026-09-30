#include "ControlPlotGUI.h"

#include <imgui.h>
#include <implot.h>

#include <sofa/core/objectmodel/BaseData.h>
#include <sofa/core/objectmodel/BaseObject.h>
#include <sofa/simulation/Node.h>

#include <algorithm>
#include <cmath>
#include <iostream>
#include <sstream>

namespace continuum_robot_lab::visualization
{
namespace
{

bool parseFirstScalar(std::string valueText, double& value)
{
    for (char& character : valueText)
    {
        if (character == '[' || character == ']' || character == ',')
        {
            character = ' ';
        }
    }
    std::istringstream stream(valueText);
    return static_cast<bool>(stream >> value);
}

} // namespace

std::string ControlPlotGUI::getWindowName() const
{
    return "Trunk Control Plot";
}

void ControlPlotGUI::resetForScene(sofa::simulation::Node* root)
{
    m_sceneRoot = root;
    m_commandData = nullptr;
    m_timeSeconds.clear();
    m_commandMillimeters.clear();
    m_lastSampleTime = -std::numeric_limits<double>::infinity();
    m_commandMaximum = 0.0;
    m_status = "Waiting for cableL0/cable.value";
    m_liveDataAnnounced = false;
}

bool ControlPlotGUI::connectToScene(sofa::simulation::Node* root)
{
    if (root == nullptr)
    {
        m_status = "Scene root is unavailable";
        return false;
    }
    auto* cableNode = root->getTreeNode("cableL0");
    if (cableNode == nullptr)
    {
        m_status = "Waiting for node cableL0";
        return false;
    }
    auto* cableObject = cableNode->getObject("cable");
    if (cableObject == nullptr)
    {
        m_status = "Waiting for object cableL0/cable";
        return false;
    }
    m_commandData = cableObject->findData("value");
    if (m_commandData == nullptr)
    {
        m_status = "Waiting for Data cableL0/cable.value";
        return false;
    }
    m_status = "Live SOFA Data: cableL0/cable.value";
    return true;
}

void ControlPlotGUI::sampleScene(sofa::simulation::Node* root)
{
    if (root != m_sceneRoot)
    {
        resetForScene(root);
    }
    if (m_commandData == nullptr && !connectToScene(root))
    {
        return;
    }

    const double timeSeconds = static_cast<double>(root->getTime());
    if (timeSeconds < m_lastSampleTime)
    {
        resetForScene(root);
        if (!connectToScene(root))
        {
            return;
        }
    }
    if (timeSeconds <= m_lastSampleTime)
    {
        return;
    }

    double commandMillimeters = 0.0;
    if (!parseFirstScalar(m_commandData->getValueString(), commandMillimeters)
        || !std::isfinite(commandMillimeters))
    {
        m_status = "Cannot read scalar cableL0/cable.value";
        return;
    }

    m_timeSeconds.push_back(timeSeconds);
    m_commandMillimeters.push_back(commandMillimeters);
    m_lastSampleTime = timeSeconds;
    m_commandMaximum = std::max(m_commandMaximum, commandMillimeters);
    if (!m_liveDataAnnounced)
    {
        std::cout << "[ContinuumRobotLabViz] live SOFA Data connected "
                  << "source=cableL0/cable.value" << std::endl;
        m_liveDataAnnounced = true;
    }
}

void ControlPlotGUI::doDraw(sofa::core::sptr<sofa::simulation::Node> root)
{
    sampleScene(root.get());
    ImGui::TextUnformatted(m_status.c_str());
    ImGui::Text("Samples: %zu", m_timeSeconds.size());

    if (!m_commandMillimeters.empty())
    {
        ImGui::SameLine();
        ImGui::Text("Current command: %.3f mm", m_commandMillimeters.back());
    }

    if (ImPlot::BeginPlot("Cable displacement command", ImVec2(-1.0F, 320.0F)))
    {
        ImPlot::SetupAxes(
            "Simulation time (s)",
            "cableL0 command (mm)",
            ImPlotAxisFlags_NoMenus,
            ImPlotAxisFlags_NoMenus);
        if (!m_timeSeconds.empty())
        {
            const double xMaximum = std::max(1.0, m_timeSeconds.back());
            const double yMaximum = std::max(1.0, m_commandMaximum * 1.1);
            ImPlot::SetupAxisLimits(ImAxis_X1, 0.0, xMaximum, ImGuiCond_Always);
            ImPlot::SetupAxisLimits(ImAxis_Y1, 0.0, yMaximum, ImGuiCond_Always);
            ImPlot::PlotLine(
                "cableL0 command",
                m_timeSeconds.data(),
                m_commandMillimeters.data(),
                static_cast<int>(m_timeSeconds.size()));
        }
        ImPlot::EndPlot();
    }
}

} // namespace continuum_robot_lab::visualization
