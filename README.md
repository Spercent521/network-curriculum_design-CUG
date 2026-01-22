# 计算机网络课程设计 - 综合网络系统

本项目为计算机网络课程设计的完整代码实现。项目采用分层架构设计，从物理层的串口通信出发，循序渐进地构建了包含数据链路层转发、网络层动态路由（DV算法）、运输层可靠传输（停等协议）以及应用层网络管理（Ping/Traceroute）的完整协议栈。

本项目代码经过重构（位于 `Code_Refactored` 目录），提供了更加友好的交互界面（如自动扫描串口、数字菜单选择、统一日志输出等），极大降低了上手难度。

---

## 1. 项目基本介绍

本项目旨在通过 Python 代码模拟真实的网络协议栈行为。我们不使用操作系统的 TCP/IP 栈，而是通过**串口（Serial Port）**作为物理层介质，手动实现上层协议。

### 协议栈架构
*   **物理层 (Physical Layer)**: 使用 `pyserial` 库直接读写串口，模拟物理链路。
*   **数据链路层 (Data Link Layer)**: 简单的帧封装与解封装，实现点对点传输。
*   **网络层 (Network Layer)**: 实现 **距离向量 (Distance Vector)** 路由算法，支持多跳网络、路由收敛、毒性逆转。
*   **运输层 (Transport Layer)**: 实现 **停等协议 (Stop-and-Wait)**，提供重传、ACK 确认、CRC32 校验等可靠传输机制。
*   应用层 (Data Layer): 提供了 Ping 和 Traceroute 等网络诊断工具。

---

## 2. 快速启动指令 (Visualization / 可视化模式)

从 **Experiment 6** 开始，我们支持 Web 可视化管理。您可以实时观察网络拓扑，并直接在网页终端控制所有节点。

**启动步骤 (需要打开3个终端):**

1.  **终端 1 (后端)**: 
    ```bash
    cd Web-Interface/Backend
    uvicorn main:app --host 0.0.0.0 --port 8000
    ```
2.  **终端 2 (前端)**: 
    ```bash
    cd Web-Interface/Frontend
    # 首次运行需: npm install
    npm run dev
    ```
    *浏览器会自动打开 http://localhost:5173*

3.  **终端 3 (实验节点)**: 
    ```bash
    python Code_Refactored/Experiment6/network_app.py
    # 按提示输入ID并选择串口即可，节点会自动连接后端。
    ```

更多细节请参考 [VISUALIZATION.md](VISUALIZATION.md)。

---

## 3. 快速启动指令 (CLI / 命令行模式)

使用传统命令行方式运行各个实验（推荐使用 `Code_Refactored` 版本）。

### 3.0 环境准备
请确保已安装 Python 3.11+ 及相关依赖库。为方便管理，我们在根目录下提供了 `requirements.txt`。

```bash
# 推荐使用 conda 创建独立环境
conda create -n cnetwork python=3.11
conda activate cnetwork

# 安装项目所需的所有依赖 (包含 CLI 和 Web 界面所需库)
pip install -r requirements.txt
# 或者手动安装: pip install pyserial fastapi "uvicorn[standard]" python-multipart aiofiles requests pydantic
```

> **依赖说明**: 
> *   `pyserial`: 核心依赖，用于串口通信。
> *   `requests`: 实验节点用于向可视化后端上报状态。
> *   `fastapi`, `uvicorn`: Web 后端框架及服务器。
>
> **硬件连接提示**: 
> 运行以下实验前，请确保您的电脑插上了 USB-TTL 串口模块，或者使用虚拟串口工具（如 VSPD）创建了成对的虚拟串口。

### 实验一：单机串口回环测试
**目标**: 验证串口硬件好坏及驱动安装是否正确。请将串口模块的 TX 与 RX 引脚短接。

```bash
python Code_Refactored/Experiment1/main.py
```
*   **操作**: 启动后通过数字菜单选择串口，输入任意字符，若能收到相同回显即成功。

### 实验二：双机点对点通信 (C/S模式)
**目标**: 模拟客户端与服务器通信。需准备两个串口（或两台电脑连接）。

**启动服务器**:
```bash
python Code_Refactored/Experiment2/server.py
```
**启动客户端**:
```bash
python Code_Refactored/Experiment2/client.py
```
*   **操作**: 客户端启动后，按提示选择串口和波特率，输入 `HELLO` 或 `TIME` 等命令与服务器交互。

### 实验三：简单拓扑转发 (Root/Leaf)
**目标**: 构建星型拓扑，Leaf 节点通过 Root 节点转发消息。

**启动根节点 (Root/Switch)**:
```bash
python Code_Refactored/Experiment3/root.py
```
*   **配置**: Root 启动后，需按提示多次添加连接的 Leaf 端口，并绑定逻辑 ID（如 A, B）。

**启动叶子节点 (Leaf)**:
```bash
python Code_Refactored/Experiment3/leaf.py
```
*   **配置**: Leaf 启动后连接到 Root，并设置自己的 ID。之后可发送消息给其他 ID。

### 实验四：多跳动态路由 (DV算法)
**目标**: 实现分布式路由网络。每个节点运行相同的路由脚本，自动发现邻居并计算路由表。

```bash
python Code_Refactored/Experiment4/router.py
```
*   **操作**: 
    1. 输入本机 ID (如 `RouterA`)。
    2. 在列表中**多选**通过该路由器连接的所有串口（输入逗号分隔的序号，如 `1,2`）。
    3. 程序将自动进行邻居发现和 DV 广播。
    4. 输入 `table` 查看实时路由表，输入 `send <DestID> <Msg>` 发送跨网段消息。

### 实验五：可靠传输协议 (Transport Layer)
**目标**: 在动态路由之上，增加可靠性（ACK、重传、校验）。

```bash
python Code_Refactored/Experiment5/reliable_router.py
```
*   **操作**: 
    *   基础配置同实验四。
    *   **发送命令**: `send <DestID> <Msg>` (会触发三次握手和停等传输)。
    *   **模拟干扰**: 输入 `corrupt on` 开启校验错误模拟，验证超时重传机制。

### 实验六：网络管理工具 (Ping/Traceroute)
**目标**: 综合应用层实验，支持 TTL 处理。

```bash
python Code_Refactored/Experiment6/network_app.py
```
*   **操作**:
    *   **Ping**: `ping <DestID>` (测试连通性和 RTT)。
    *   **Traceroute**: `tracert <DestID>` (追踪路径上的每一跳路由)。

---

## 3. 可视化界面 (开发中)

本项目包含一个基于 Web 的可视化监控界面，位于 `Web-Interface` 目录。

> **状态说明**: 
> 可视化模块目前正在进行适配性更新，以对接重构后的底层协议栈。当前版本可能无法完美展示 `Code_Refactored` 中的日志流。
> 
> 敬请期待后续更新版本，该版本将支持：
> *   实时网络拓扑图绘制
> *   数据包动画演示
> *   Web端全功能控制台

目前建议优先使用上述 **第2部分** 的命令行工具进行实验和调试。

