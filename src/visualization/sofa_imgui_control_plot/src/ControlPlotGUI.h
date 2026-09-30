#pragma once

#include <SofaImGui/guis/BaseAdditionalGUI.h>

#include <limits>
#include <string>
#include <vector>

namespace sofa::core::objectmodel
{
class BaseData;
}

namespace continuum_robot_lab::visualization
{

class ControlPlotGUI final : public sofaimgui::guis::BaseAdditionalGUI
{
public:
    std::string getWindowName() const override;

private:
    void doDraw(sofa::core::sptr<sofa::simulation::Node> root) override;
    bool connectToScene(sofa::simulation::Node* root);
    void sampleScene(sofa::simulation::Node* root);
    void resetForScene(sofa::simulation::Node* root);

    sofa::simulation::Node* m_sceneRoot {nullptr};
    sofa::core::objectmodel::BaseData* m_commandData {nullptr};
    std::vector<double> m_timeSeconds;
    std::vector<double> m_commandMillimeters;
    double m_lastSampleTime {-std::numeric_limits<double>::infinity()};
    double m_commandMaximum {0.0};
    std::string m_status {"Waiting for cableL0/cable.value"};
    bool m_liveDataAnnounced {false};
};

} // namespace continuum_robot_lab::visualization
