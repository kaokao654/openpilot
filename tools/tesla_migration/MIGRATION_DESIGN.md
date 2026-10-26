# AP1 未开通 AP：RDF V4 / TSFDO 模块迁移设计

日期：2026-10-26。状态：固定源码审计与设计，尚未实现控车迁移、编译完整底座或进行真机验证。

## 1. 决策与已知条件

已知可用基线为 `kaokao654/openpilot` 的 `tesla_unity_releaseC3`，提交 `c0901fc97b02553315f6e9e88e6c8eb797ca850f`；设备为 Mr One C3，车辆为未开通 AP 软件的 Model S AP1，无 Pedal。用户已确认转向和原车巡航调速能用，约 30 km/h 以下人工控制纵向。无需用户再次报告分支、拍软件页面或先运行 SSH 工具。

**主路线：在已有统一 v15 模型运行器的固定 StarPilot 快照中，新增仅限 HW1 的未开通 AP + 原车巡航调速模式。** Tinkla 提供行为与报文参考，不整体覆盖新平台车型目录或 Panda 安全实现。

候选底座固定为 `firestar5683/StarPilot@823a5d5674ec6635b51dd989884dfbd661f90dc4`。底座要求的 AGNOS 为 19.8.1；旧分支要求 9.1。这是源码要求的差异，不能当作已经读取的设备系统版本，也不能直接推断可跨版本刷机。Mr One 对新系统的驱动适配仍是进入实机阶段的验证项，不妨碍现在编写协议、状态机和离线测试。

第一款目标是 RDF V4（`rdf43` / v15，模型源提交 `a5a6412d08474cffb49a69afb910756afdee123e`），随后在同一车辆适配中比较 TSFDO（`tsfdo` / v15，源提交 `0394d7284cfc229f772ee4fa73ff724ba8245110`）。底座 tinygrad 固定为 `e837e367aac9e1a66e689f4f32ce20ca9367df13`。机内编译包的校验值应在取得或重编译后记录；外接 GPU 编译包的哈希不能冒充机内包哈希。

## 2. 可以复用什么，实际缺少什么

| 模块 | 当前 Tinkla 依据 | 新底座现状 | 迁移动作 |
|---|---|---|---|
| 模型运行、解析、规划 | 旧模型链及旧消息结构 | 已有 v15 统一模型、RDF 默认值及新规划链 | 复用固定快照，不单独把权重塞进旧 modeld |
| 规划速度到车型控制器 | `LONG_module.py:162–184` 读取 `longitudinalPlan.speeds[-1]` | `controlsd.py:815–816` 已赋给 `CC.actuators.speed`，单位 m/s | 直接使用现有字段，增加有效性和能力边界检查 |
| HW1 转向 | `carcontroller.py:137–153`、`teslacan.py:126` | 已有 HW1 角度控制、0x488 打包、角度与人工接管检查 | 优先复用新实现，对照方向、单位、限幅、退出条件 |
| 软件启停 | `carstate.py:487–520` 独立 `cruiseEnabled` | HW1 仍以 `DI_cruiseState` 为启用依据 | 新增显式模式与独立意图状态，向新框架输出按钮事件和状态 |
| 自适应巡航拨杆算法 | `ACC_module.py` | Pre-AP `StockCCSpoofer` 只有启用/取消辅助，没有这套自适应调速算法 | 抽出独立 ACC 策略模块，保留已确认的执行方式 |
| 拨杆消息 | `teslacan.py:301–309` 复制原报文、递增计数、重算 CRC | Pre-AP 有相关打包器，但不完整保留所有开关字段 | 新建 HW1 专用打包入口，按位保留无关字段，验证新旧字节结果 |
| Panda 启用和发送规则 | 0x659 模式位、0x45 接收拨杆的特殊规则 | HW1 已注册 legacy hooks；TX 列表只有 0x488/0x2b9 | 新增限定车型、限定模式的状态和消息规则，不扩大为任意发送 |
| 雷达 | Bosch 32 目标，bus 1，8 Hz 目标数据 | HW1 已配置 Bosch DBC、bus 1 和目标解析器 | 复用，核对目标、误差字段、偏置/安装方向与失效处理 |
| 仪表与提示 | HUD 既有显示，也承担向旧 Panda 传模式的通信 | 无等价的旧 HUD 模式通信 | 拆分模式配置与仪表显示；先完成必要状态和人工接管提示 |

新平台已经具备两项重要基础：HW1 雷达的 DBC 和解析不是空缺；规划目标速度也已有公开字段。由此主要新增内容可以集中到 HW1 未开通 AP 模式、ACC 适配和相关安全规则。

## 3. 控制链与接口约定

```text
RDF V4 或 TSFDO
  → 新 modeld / 输出解析
  → 新平台横向与纵向规划、控制
     ├─ steeringAngleDeg → 现有 HW1 角度控制 → 0x488
     └─ actuators.speed [m/s]
          → HW1 ACC 意图、能力与节流状态机
          → 保留原拨杆其他字段的请求 → 0x45
  → 与该模式匹配的 Panda 许可、限幅和发送检查
```

不得把 v15 原始 `action` 的第一项直接当转向角，或把第二项直接映射成拨杆。现有运行器中包含速度缩放、时间延迟和输出适配，应经过完整规划/控制链获得车型所需的目标。

ACC 模块设计为可独立测试的纯策略：输入包含单调时间、真实车速/制动/油门、人工拨杆边沿、原车巡航状态与设定速度、驾驶员上限、新平台目标速度及其有效性；输出为无操作、取消或有限的巡航拨杆动作，以及意图/可用性和提示状态。它不创建消息订阅、不读设备参数、不访问 Panda、不使用墙上时钟或隐式全局状态。

**三个状态不能混用：** 驾驶员希望横向启用、驾驶员希望 ACC 调速、实际获准输出。Panda 获得横向许可，不代表 ACC 已开启；软件界面显示启用，也不能代替实际的控制许可。

保留旧代码中横向与双拉 ACC 的分层意图。旧 ACC 的双拉窗口为 750 ms；模式内单拉可能关闭 ACC 而保留横向意图。取消、制动、人工转向接管、系统故障分别建事件，最终输出服从新平台和 Panda 的实际许可。制动后横向是否退出由明确策略表达，不能伪造输入实现。

## 4. CAN/DBC 核对得到的直接证据

已对比两个固定提交中的 `tesla_can.dbc`：

| 项目 | 静态核对结果 | 含义 |
|---|---|---|
| STW_ACTN_RQ / 0x45 | 31 个信号的起始位、长度、字节序、符号、缩放和偏移一致 | 协议主体可以适配复用；不等于已经做过实包验证 |
| DAS_steeringControl / 0x488 | 5 个信号的上述定义一致 | 转向报文布局有明确的兼容基础 |
| 原车巡航设定速度 | 旧 `DI_cruiseSet` = `48\|8 (1,0)`；新 HW1 的 `DI_hw1CruiseSet` 同样为 `48\|8 (1,0)` | HW1 必须使用专用字段 |
| 新 DBC 的通用 `DI_cruiseSet` | `32\|9 (0.5,0)` | 与旧同名字段不同；仅照抄名称会读错 |

0x45 的输出只应有明确允许的拨杆位、计数器和 CRC 差异。转向灯、雨刷、远光、喇叭、方向盘开关等位应保留。旧打包器复制整份解析值；新 Pre-AP 打包器仅复制部分字段并强制一个标志位，不能直接当作等价替代品。

旧代码使用的 `CANPacker.make_can_msg` 数据位于返回值索引 2；新代码位于索引 1，消息元组格式也不同。不能直接复制旧函数后原样调用新 API。

原拨杆接收检查为 10 Hz；旧 LONG 每 20 个 100 Hz 控制周期评估一次 ACC，即 5 Hz。算法另有人工操作后 3000 ms、自动操作后 400 ms 的静默窗口。决策频率不等于允许无间隔发同频率的加速命令。新模块需要可注入的时钟、原拨杆新鲜度、重复请求抑制和明确的取消优先级。

## 5. 不能照抄的旧实现细节

### 5.1 制动输入被改写

旧 `carstate.py:219–220` 先保存真实制动状态，随后在特殊路径 `:517` 把对外 `brakePressed` 设为 False；ACC 另读 `realBrakePressed`。这种双重表达不应原样搬进新框架。保留真实物理输入，让状态机表达纵向退出以及单独的横向策略，并验证 Panda 的制动与接管检查。

### 5.2 低速取消请求存在被后续分支覆盖的可能

旧 `ACC_module.py:390` 先因目标低于最低巡航速度而设置 CANCEL，后续独立的速度差判断可能重新赋为减速拨杆。新实现应明确处理低速/无效目标并结束该轮决策，写边界用例，不以逐行复制作为行为正确的证明。

最低巡航常量 17.1 mph 约为 27.5 km/h，与用户观察的约 30 km/h 执行范围相符。本次不调低这个限制、不增加低速起停。纵向不可用时必须在状态和提示上表达，不能继续宣称正在自动控制速度。

### 5.3 已读取前车不等于自动恢复逻辑已使用它

旧 `update_acc` 读取了 `lead_1`，但 `_calc_button` 调用 `_should_autoengage_cc(CS)` 时未传入这个前车对象；后者注释中的防碰撞条件不能当作已经接通。首轮迁移默认不自动恢复，采用明确人工重新启用；后续若实现自动恢复，应单独提供完整输入、测试和验证依据。

### 5.4 模式开关、规划权限与执行类型分离

新接口需要允许高层规划速度，但本模式执行类型为“原车巡航拨杆”，而非 0x2b9 原生纵向控制。不能只开启现有 LONG_CONTROL 位后沿用所有原生纵向报文；必须明确分流，避免同时发出两套纵向命令。

## 6. Panda 与模式配置设计

建议使用启动时固定的 HW1 专用模式标志，名称与位值在统一检查冲突后分配。默认关闭，必须同时匹配 Model S HW1 和明确的未开通 AP 设置；普通 HW1、现代 Tesla、Pre-AP 都不受影响。

旧系统通过 0x659 的 byte 5 bit 7 告知 Panda AP 已关闭，这一行为应由明确的启动安全配置替代，而非把 HUD 报文变成随时改变许可的隐藏入口。替代后，要验证主机与 Panda 模式一致、不匹配时不能启用。仪表显示可以另行迁移。

本模式的安全审计范围包括：

- 0x45 接收状态与有限的启停规则，区分人工拨杆和软件请求。
- 仅在准确模式、准确总线、正确长度下允许相应消息；取消与增加速度的许可条件分开。
- 有效性、源报文新鲜度、按钮值、计数、CRC、无关位保持与请求频率的约束。
- 保留转向限幅、制动/油门/方向盘覆盖、通信超时与故障退出；完整检查转发行为和原车 AEB 路径。
- 禁止通过本模式顺带开放 Pedal、iBooster 或 0x2b9 加减速；也不直接移植旧版 1378 行 Tesla safety 文件覆盖新模式。

现有 `test_tesla_legacy.py` 检查 HW1 hooks 注册、无许可转向拒绝、纵向权限及转发；尚未运行这些测试，也不覆盖本次新增的巡航模式。测试文件存在不能代替通过。

## 7. 文件与提交拆分

以下新文件名为设计提案，不是已存在或已实现的接口。

| 提交阶段 | 主要目标文件/范围 | 可审查结果 |
|---|---|---|
| A：协议与纯策略 | 新增 `tesla/hw1_stock_cc.py`、`tesla/hw1_stock_cc_can.py` 及测试 | 意图状态、时钟、低速/人工优先、字节保留和报文向量；尚不接入运行路径 |
| B：车型适配 | `tesla/values.py`、`interface.py`、`carstate.py`、`carcontroller.py` | 明确模式、HW1 专用字段、`actuators.speed` 桥接、纵向能力与提示、默认关闭 |
| C：安全匹配 | `safety/modes/tesla_legacy.h` 和专项测试、模式参数映射 | 独立许可和受限 TX/RX/FWD；普通 HW1/现代 Tesla/Pre-AP 回归 |
| D：模型与系统试运行 | 固定模型包、运行清单、离线/停车入口、Mr One 必要适配 | 不发控制 CAN 的模型验证；保持模型源、编译版本和校验值可追踪 |
| E：集成候选 | 经审查的主机+固件+模型组合、恢复与验证说明 | 再按转向、原有范围纵向、模型对照的顺序验证 |

A、B、C 的初步开发与静态/离线测试可以现在开始，不依赖 SSH。任何分支能编译或测试通过，都不直接等于可供道路使用。

实现分支应从已选新底座建立；当前 `tesla_unity_releaseC3` 保留作行为与恢复基线。当前 PR #2 仍仅放预检工具和设计文档，不能把它刷入后视为完成了新模型迁移。

## 8. 离线验证清单

1. 用旧/新 DBC 或实际 CANPacker 生成相同输入的参考帧，对照 0x45/0x488 字节，覆盖非零方向盘、雨刷、转向灯等所有无关位。
2. 覆盖 KPH/MPH、HW1 巡航字段、四位计数器回绕、CRC、不完整或过期原帧。
3. 时钟推进覆盖单拉、750 ms 双拉边界、按住不重复触发、人工 3 s 优先窗口、自动 400 ms 窗口及取消优先。
4. 覆盖低速边界、目标低于限制、空目标、NaN/Inf、模型/规划超时；不得产生错误的恢复或加速请求。
5. 制动、油门覆盖、手动转向接管、取消、档位/车门/安全带异常和故障退出，分别验证软件意图与最终许可。
6. 验证本模式输出只有设计允许的执行路线，并做其他 Tesla 模式的负面回归。
7. 模型试运行检查输入分辨率、时间戳、动作量纲、持续推理耗时、帧率、内存和温度；实际阈值在运行清单中固定，再判断是否进入控制测试。

当前已完成的验证仅为源码阅读、固定 DBC 信号布局比较，以及既有只读工具的 3 项单元测试。未执行 CANPacker 字节向量测试、完整 safety 测试、模型推理或实车验证。

## 9. 关键源码依据

- [旧 ACC 策略与双拉/节流](https://github.com/kaokao654/openpilot/blob/c0901fc97b02553315f6e9e88e6c8eb797ca850f/selfdrive/car/tesla/ACC_module.py)
- [旧 LONG 的规划速度到拨杆路径](https://github.com/kaokao654/openpilot/blob/c0901fc97b02553315f6e9e88e6c8eb797ca850f/selfdrive/car/tesla/LONG_module.py#L162)
- [旧启用状态与制动表达](https://github.com/kaokao654/openpilot/blob/c0901fc97b02553315f6e9e88e6c8eb797ca850f/selfdrive/car/tesla/carstate.py#L487)
- [旧模式通信与安全逻辑](https://github.com/kaokao654/openpilot/blob/c0901fc97b02553315f6e9e88e6c8eb797ca850f/panda/board/safety/safety_tesla.h#L913)
- [旧 DBC](https://github.com/kaokao654/openpilot/blob/c0901fc97b02553315f6e9e88e6c8eb797ca850f/opendbc/tesla_can.dbc) / [新 DBC](https://github.com/firestar5683/StarPilot/blob/823a5d5674ec6635b51dd989884dfbd661f90dc4/opendbc_repo/opendbc/dbc/tesla_can.dbc)
- [新规划速度输出](https://github.com/firestar5683/StarPilot/blob/823a5d5674ec6635b51dd989884dfbd661f90dc4/selfdrive/controls/controlsd.py#L815)
- [新 HW1 状态](https://github.com/firestar5683/StarPilot/blob/823a5d5674ec6635b51dd989884dfbd661f90dc4/opendbc_repo/opendbc/car/tesla/carstate.py#L226) / [接口](https://github.com/firestar5683/StarPilot/blob/823a5d5674ec6635b51dd989884dfbd661f90dc4/opendbc_repo/opendbc/car/tesla/interface.py#L41)
- [新 HW1 车辆控制](https://github.com/firestar5683/StarPilot/blob/823a5d5674ec6635b51dd989884dfbd661f90dc4/opendbc_repo/opendbc/car/tesla/carcontroller.py)
- [已有 Pre-AP 巡航辅助的实际范围](https://github.com/firestar5683/StarPilot/blob/823a5d5674ec6635b51dd989884dfbd661f90dc4/opendbc_repo/opendbc/car/tesla/preap/stock_cc_spoofer.py)
- [新 HW1 雷达](https://github.com/firestar5683/StarPilot/blob/823a5d5674ec6635b51dd989884dfbd661f90dc4/opendbc_repo/opendbc/car/tesla/radar_interface.py) / [雷达配置](https://github.com/firestar5683/StarPilot/blob/823a5d5674ec6635b51dd989884dfbd661f90dc4/opendbc_repo/opendbc/car/tesla/values.py#L73)
- [HW1 安全实现](https://github.com/firestar5683/StarPilot/blob/823a5d5674ec6635b51dd989884dfbd661f90dc4/opendbc_repo/opendbc/safety/modes/tesla_legacy.h) / [已有安全测试](https://github.com/firestar5683/StarPilot/blob/823a5d5674ec6635b51dd989884dfbd661f90dc4/opendbc_repo/opendbc/safety/tests/test_tesla_legacy.py)
