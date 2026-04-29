# GDC 2025 - 恐鬼症(Phasmophobia)引擎技术揭秘

> **演讲主题**: Building Fear - The Tech Behind Phasmophobia  
> **演讲者**: Kinetic Games (Unity官方)  
> **来源**: GDC 2025  
> **视频时长**: ~56分钟

---

## 1. 演讲概述

本次演讲由 Kinetic Games 的技术负责人主讲，揭秘了现象级恐怖游戏《恐鬼症》(Phasmophobia) 背后的 Unity 引擎技术实现。

**演讲核心主题：**

| 主题 | 时间 | 说明 |
|------|------|------|
| **Alive AI** | ~2-4min | 鬼魂AI的设计哲学与实现 |
| **思维导图** | ~4min | Alive AI完整架构 |
| **Sensor Toolkit** | ~5-6min | 传感器系统架构 |
| **Voice Recognition** | ~9min | 语音识别与交互 |
| **AutoProp** | ~11min | 自动道具系统 |
| **Interact Effects 2** | ~13-16min | 交互效果系统 |
| **Developer Console** | ~16-19min | 开发者调试控制台 |
| **Live Demo** | ~20-26min | 现场演示 |
| **Q&A** | ~33min+ | 观众问答 |

---

## 2. Alive AI - 鬼魂AI系统

### 2.1 核心概念

![Alive AI Concept](screenshots/frame_0155_00.jpg)

**"Alive AI"的五大特征：**

1. **One instance** - 单场游戏中只有一个鬼魂实例
2. **No scripted events** - 完全没有脚本化事件，所有行为由AI驱动
3. **Interactions are happening even when not visible** - 即使玩家看不见，鬼魂仍在持续行动
4. **Constantly receiving input to make decisions** - 持续接收输入并做出决策
5. **Voice recognition** - 支持语音识别交互

> **关键洞察**: 传统恐怖游戏依赖脚本化jump scare，而恐鬼症的恐怖来自于"你不知道鬼魂在做什么"的不确定性。即使你在安全屋，鬼魂仍在地图中游荡、决策。

### 2.2 Alive AI 架构思维导图

![Alive AI Mind Map](screenshots/frame_0235_00.jpg)

**思维导图结构解析：**

```
Alive AI
├── Ghost Type (鬼魂类型)
│   ├── Interactions (交互)
│   ├── Roaming (游荡)
│   └── Movement (移动)
├── Equipment (装备)
│   ├── Evidence (证据)
│   ├── Electronics (电子设备)
│   └── Disruption (干扰)
├── Sensors (传感器)
│   ├── Vision (视觉)
│   └── Interaction (交互感知)
├── Interactions (交互行为)
│   ├── Light switches (开关灯)
│   ├── Throwing (投掷物品)
│   └── Effects (特效)
└── Player (玩家)
    ├── Microphone Input (麦克风输入)
    ├── Position (位置)
    └── Interactions (玩家交互)
```

**技术要点：**
- 鬼魂类型决定基础行为模式（如Mare、Spirit等）
- **传感器系统**是AI的"感官"，决定鬼魂能感知到什么
- 玩家位置、麦克风输入、交互行为都会作为输入影响AI决策
- 交互行为包括物理交互（扔东西）和环境交互（开关灯）

---

## 3. Sensor Toolkit - 传感器工具包

### 3.1 系统概述

![Sensor toolkit](screenshots/frame_0320_00.jpg)

**传感器工具包的核心特性：**

| 特性 | 说明 |
|------|------|
| **AI and equipment** | 同时为AI和设备提供感知能力 |
| **Photo camera sensor** | 支持相机类设备的特殊传感器 |
| **Wrapper for physics queries as "Pulses"** | 将物理查询包装为"脉冲"形式，如 `Physics.OverlapSphereNonAlloc()` |
| **Signal processors** | 信号处理器，可处理传感器数据 |
| **Can combine multiple sensors** | 支持多传感器组合 |
| **No triggers required** | 无需Unity触发器 |
| **No collision messages** | 不产生碰撞消息（避免 `OnTriggerEnter` 等开销） |

### 3.2 LOS Sensor (视线传感器)

从截图中可见Unity Inspector中的LOS Sensor配置：

**关键参数：**
- **Input Sensor**: 输入传感器（如Range Sensor）
- **Blocks Line Of Sight**: 视线阻挡设置
- **Ignore Trigger Colliders**: 忽略触发器碰撞体
- **Number Of Rays**: 射线数量
- **Point Sampling Method**: 采样方法（Fast）
- **Limit Distance / Max Distance**: 距离限制（5单位）
- **Limit View Angle**: 视角限制
  - Max Horiz Angle: 45°
  - Max Vert Angle: 30°
- **Visibility By Distance/Angle**: 基于距离和角度的可见性曲线
- **FOV Constraint Method**: Bounding Box
- **Pulse Mode**: Manual

**设计优势：**
- 使用**脉冲式检测**而非持续的碰撞检测，大幅降低性能开销
- 支持**距离和角度的可见性衰减曲线**，让感知更自然
- **无触发器依赖**，完全基于物理查询，更可控

---

## 4. Voice Recognition - 语音识别

### 4.1 系统架构

![Voice recognition](screenshots/frame_0530_00.jpg)

**技术栈：**
- **Windows** 平台API
- **Vosk** (前身是Recognissimo)
- **Text UI** 文本界面

**交互流程：**
```
Player Voice (玩家语音)
    ↓
Voice Recognition Engine (语音识别引擎)
    ↓
Text Processing (文本处理)
    ↓
Ghost Response (鬼魂响应)
```

### 4.2 应用场景

| 场景 | 说明 |
|------|------|
| **Spirit box** | 通灵盒 - 玩家提问，鬼魂通过语音回应 |
| **Ouija board** | 通灵板 - 可以问很多问题 |
| **Monkey paw** | 猴爪 - 许愿道具 |
| **Hunting** | 猎杀阶段 - 语音可能触发或影响鬼魂行为 |
| **Interactivity** | 整体交互性提升 |

> **实现细节**: 系统同时识别中英文（或其他语言），将玩家语音转为文本后匹配预定义的意图，然后触发相应的鬼魂行为。

---

## 5. AutoProp - 自动道具系统

### 5.1 系统目标

![AutoProp](screenshots/frame_0685_00.jpg)

**设计目标：**
- **Easy for Artists** - 对美术人员友好
- **No additional code/setup required** - 无需额外代码或配置
- **Expansion in future** - 易于扩展
  - AutoDoor? (自动门)
  - AutoInteractable? (自动可交互物)

### 5.2 Unity集成

从截图可见Unity Inspector中的 **Auto Prop (Script)** 组件：
- 挂载到3D模型上
- 点击 **"Make Prop"** 按钮即可自动设置
- 自动配置材质、碰撞体等

**工作流程：**
```
1. 美术制作3D模型
2. 拖拽模型到场景
3. 添加 Auto Prop 脚本
4. 点击 "Make Prop"
5. 自动完成所有配置
```

> **技术价值**: 大幅减少美术与程序之间的沟通成本，让美术可以独立创建可交互道具，无需程序员介入。

---

## 6. Interact Effects 2 - 交互效果系统

### 6.1 系统概述

![Interact Effects 2](screenshots/frame_0750_00.jpg)

**设计原则：**
- **Artists' freedom** - 给予美术充分的自由度
- **No additional code required** - 无需额外代码
- **Easy to scale** - 易于扩展
- **Only necessary references are visible** - 只显示必要的引用，减少认知负担

### 6.2 支持的Action类型

从截图中的下拉菜单可见支持的动作：

| Action | 功能 |
|--------|------|
| `AnimatorSetBool` | 设置Animator布尔值 |
| `AnimatorSetTrigger` | 触发Animator触发器 |
| `ToggleParticleSystem` | 开关粒子系统 |
| `Delay` | 延迟执行 |
| `SetObjectActive` | 激活/禁用单个对象 |
| `SetObjectsActive` | 批量激活/禁用 |
| `SetTransform` | 设置Transform属性 |
| `DOTweenSequence` | DoTween动画序列 |
| `ToggleSound` | 开关音效 |
| `LoopSound` | 循环播放音效 |
| `CallFunction` | 调用自定义函数 |

### 6.3 代码架构

#### InteractableAction 基类

![Interactable Action Code](screenshots/frame_0940_00.jpg)

```csharp
[System.Serializable]
public abstract class InteractableAction
{
    public bool ghostAction = true;   // 是否可由鬼魂触发
    public bool playerAction = true;  // 是否可由玩家触发

    public virtual IEnumerator<CoroutineAction> Execute()
    {
        throw new System.NotImplementedException("This action has not been implemented");
    }

    public bool ExecuteCheck(bool isGhost)
    {
        return (ghostAction && isGhost) || (playerAction && !isGhost);
    }
}
```

**关键点：**
- 使用**协程(IEnumerator)**表示动作执行，支持长时间运行的效果
- **ghostAction / playerAction** 布尔值区分触发者身份
- `ExecuteCheck()` 方法确保只有正确的角色能触发动作

---

## 7. Developer Console - 开发者控制台

### 7.1 功能概述

![Developer console](screenshots/frame_1370_00.jpg)

**控制台功能：**

| 功能 | 说明 |
|------|------|
| **AI behaviour** | 实时查看和修改AI行为参数 |
| **Cheat codes** | 作弊码（如设置金钱、等级） |
| **Testing & tuning** | 测试和调优 |
| **Stripped in non-development builds** | 非开发版本自动剥离 |
| **Trailers** | 辅助预告片拍摄 |

### 7.2 实时调试信息

截图右侧显示了实时AI状态面板：

```
Sanity: 99.84481          (理智值)
Temperature: 13            (温度)
Long Rooms: 0              (长房间数)
Ghost Abilities: 0         (鬼魂能力)
Ghost Activity: 15         (鬼魂活跃度)
Ghost State: idle          (鬼魂状态)
Ghost Type: Mare           (鬼魂类型)
Current Ghost Room:        (当前房间)
  Garden Porch
Favourite Room: Garden     (偏好房间)
  Porch
Player Room: Outside       (玩家所在房间)
```

**技术价值：**
- 实时显示AI内部状态，方便调试
- 预告片团队可以精确控制场景（设置特定鬼魂状态、玩家位置）
- 支持快速迭代调优，无需重新编译

---

## 8. Live Demo - 现场演示

### 8.1 演示内容

![Live demo](screenshots/frame_1195_00.jpg)

演讲者在Unity编辑器中进行了实时演示，展示了：
- 相机传感器的工作原理
- 可见性评分系统
- 射线检测可视化

### 8.2 相机传感器可视化

![Camera Sensor Visualization](screenshots/frame_1295_00.jpg)

**演示要点：**
- 在Scene视图中可视化**相机传感器到骨骼的射线**
- 显示了**可见性分数(visibility score)**
- 当玩家靠近鬼魂时，照片质量会变化

---

## 9. Q&A - 问答环节

### 9.1 主要问题

Q&A环节从约 **33分钟** 开始，持续到视频结束。主要问题包括：

| 问题 | 回答要点 |
|------|----------|
| **程序化的变化 vs 纯随机？** | 是的，几乎所有事件都有随机机会和波动，不仅仅是基于鬼魂类型的纯随机 |
| **语音识别的多语言支持难度？** | 目前支持5种语言，使用Vosk引擎 |
| **VR体验？** | VR是最沉浸式的游戏方式，身体动作比按键更有恐怖感 |

---

## 10. 技术总结与启发

### 10.1 架构亮点

| 技术点 | 启发 |
|--------|------|
| **Alive AI (持续运行AI)** | 恐怖感来自于"不确定性"，而非脚本化事件。AI始终运行，玩家永远不知道鬼魂在做什么 |
| **传感器工具包** | 将物理查询包装为"脉冲"，大幅降低性能开销，同时保持灵活性 |
| **InteractableAction协程架构** | 使用协程表示可中断、可延迟的动作序列，非常适合游戏交互 |
| **AutoProp** | 通过工具减少美术-程序沟通成本，让美术自主工作 |
| **开发者控制台** | 实时状态监控 + 作弊功能，大幅提升开发效率和预告片制作效率 |

### 10.2 可复用的设计模式

1. **脉冲式传感器**: 将持续检测改为定时脉冲，降低CPU开销
2. **协程动作序列**: 用协程组合复杂行为，支持延迟、取消、条件判断
3. **自动配置工具**: 一键化重复性配置工作，提升美术效率
4. **双角色触发系统**: 通过布尔值区分鬼魂/玩家触发权限，统一交互接口
5. **实时调试面板**: 在Game视图中显示AI内部状态，加速迭代

### 10.3 与Unity的深度集成

- 大量使用 **Unity Inspector自定义界面** 让工具对美术友好
- **协程(IEnumerator)** 作为核心并发机制
- **Physics.OverlapSphereNonAlloc** 等无GC物理查询
- **DoTween** 用于动画序列

---

> **备注**: 本笔记基于视频截图自动生成，关键截图已嵌入。如需查看完整截图序列，请查阅 `screenshots/` 目录（共200张截图）。
