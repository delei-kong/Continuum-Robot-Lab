# Visualization

项目自有的运行时可视化源码放在本目录。

`sofa_imgui_control_plot/` 构建 `ContinuumRobotLabViz` SOFA 插件。插件通过
SofaImGui 的 `AdditionalGUIRegistry` 注册 ImPlot 窗口，直接从当前场景树的
`cableL0/cable.value` SOFA Data 读取控制量并保存在绘图内存中。它不通过 CSV 传递
实时数据，也不回写或参与仿真求解。

远端安装入口：

```bash
scripts/remote/install_continuum_viz.sh
```

插件只由远端 GUI 启动脚本加载；batch 仿真不依赖 SofaImGui 或本插件。
