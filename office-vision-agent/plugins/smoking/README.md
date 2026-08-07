# Smoking Detector（抽烟检测插件）

阶段3（PluginManager）实现时，从原型的 `plugins/smoking/` 迁入：

- `detector.py`：手-嘴启发式 + Idle→Suspect→Smoking→Finish 状态机（已通过 36 项单元测试）
- `plugin.py`：插件入口，实现 BaseBehaviorDetector
- `config.yaml`：阈值与超时参数

产出事件：`SmokingStarted` / `SmokingEnded`（一根烟一条记录）。
