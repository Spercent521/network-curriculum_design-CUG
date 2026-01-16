# 计算机网络课程设计 - 综合网络系统

## 0. 项目概述

本项目为计算机网络课程设计的完整代码实现。项目采用分层架构设计，从物理层的串口通信出发，循序渐进地构建了包含数据链路层转发、网络层动态路由（DV算法）、运输层可靠传输（停等协议）以及应用层网络管理（Ping/Traceroute）的完整协议栈。

此外，项目还包含一个基于 **React**  的现代化 Web 可视化界面，能够实时监控网络拓扑结构、动态展示数据包流向，并提供图形化的交互操作控制台。

---

## 1. 传统的快速调试方法 (CLI)

本节汇总了六个基础实验的命令行启动方法。这是调试底层协议逻辑、验证算法正确性的推荐方式。

> **前置条件**: 请确保已安装 Python 3.8+ 及必要依赖 `pip install pyserial`
>
> **建议**:
>
> ```shell
> conda create -n cnetwork python=3.11
> conda activate cnetwork
> pip install pyserial
> ```

### Experiment 1 : 单机串口测试
**功能说明**：
验证 USB-TTL 串口模块的基础收发功能。通过“自环”测试（Tx接Rx），确保本地硬件与驱动环境正常。

**快速启动**：
```bash
python Code/Experiment1/main.py
```

### Experiment 2 : 双机点对点通信
**功能说明**：
模拟基础的 C/S (客户端/服务器) 架构。客户端可向服务器发送时间查询、计算表达式等指令。
*   支持命令: `TIME`, `ECHO <msg>`, `CALC <expr>`

**快速启动**：
*   **服务器端**:
    ```bash
    python Code/Experiment2/server.py
    ```
*   **客户端**:
    ```bash
    python Code/Experiment2/client.py
    ```

### Experiment 3 : 简单拓扑转发
**功能说明**：
构建树状/星型拓扑。**Root节点**作为交换中心，维护静态转发表；**Leaf节点**之间通过 Root 进行数据帧的中转通信。

**快速启动**：
*   **根节点 (Root)**:
    ```bash
    python Code/Experiment3/root.py
    # 启动后需按提示绑定端口与ID
    ```
*   **叶子节点 (Leaf)**:
    ```bash
    python Code/Experiment3/leaf.py
    ```

### Experiment 4 : 多跳动态路由
**功能说明**：
实现网络层核心功能。所有节点运行 **DV (距离向量)** 路由算法，自动发现邻居、交换路由表并计算全网路径。支持**断线重连**与**毒性逆转**。
*   支持命令: `table` (查看路由表), `send <ID> <Msg>` (发送消息)

**快速启动**：
```bash
python Code/Experiment4/router.py
```

### Experiment 5 : 可靠传输协议
**功能说明**：
在动态路由的基础上，增加运输层可靠性保障。实现 **Stop-and-Wait (停等协议)**，具备 **CRC32校验**、**超时重传**、**三次握手建立连接** 等机制。
*   支持命令: `corrupt <次数>` (模拟校验错误), `loss` (模拟丢包)

**快速启动**：
```bash
python Code/Experiment5/reliable_router.py
```

### Experiment 6 : 网络管理工具
**功能说明**：
应用层综合实验。引入 **TTL (生存时间)** 处理，实现 ICMP 协议逻辑，提供网络诊断工具。

*   支持命令: `ping <ID>` (测试连通性), `tracert <ID>` (路由追踪)

**快速启动**：
```bash
python Code/Experiment6/network_app.py
```

---

## 2. Web端可视化的启动方法

Web 界面提供了更直观的拓扑图和全网流量监控。系统已集成静态资源，无需安装 Node.js 即可运行。

### 依赖环境
*   **基础**: `Python 3.11+`
*   **开发**: `Node.js` (仅修改前端代码时需要)

### 启动步骤

#### 方法一：快速启动 (推荐)
直接运行后端即可自动托管前端页面。

```bash
# cd Web-Interface/Backend
pip install -r requirements.txt
python main.py
```
> **启动成功后**: 在浏览器打开 [http://localhost:8000](http://localhost:8000)
>
> **自定义端口**: 如果 8000 端口被占用，可在命令行指定端口启动：
> ```bash
> python main.py 10000  # 将在 10000 端口启动
> ```

#### 方法二：开发模式 (前后端分离)
如果你需要修改 React 前端代码并实时预览：

1.  **启动后端** (同上):
    ```bash
    python Web-Interface/Backend/main.py
    ```
2.  **启动前端** (开启热更新):
    ```bash
    cd Web-Interface/Frontend
    npm install
    npm run dev
    ```
> **开发地址**: 打开终端显示的 Frontend 地址 (通常为 `http://localhost:5173`)

#### 使用说明 (操作演示)

以 **Experiment 4 (动态路由)** 为例：

1.  **进入系统**: 浏览器打开网页，点击或聚焦下方的 **Terminal** 区域。
2.  **选择实验**: 在菜单中输入 `4` 并回车，启动路由器脚本。
3.  **初始化节点**:
    *   根据终端提示输入本机 ID (例如 `A`)。
    *   根据列表选择串口编号 (例如输入 `1` 选择第一个串口)。
4.  **可视化交互**:
    *   在终端输入 `table` 命令查看路由表。
    *   **关键**: 此时上方拓扑图会自动根据路由表数据更新节点和连线。
    *   尝试输入 `send B Hello` 发送数据，观察控制台输出。
5.  **退出与切换**:
    *   输入 `exit` 停止当前脚本，返回主菜单选择其他实验。
