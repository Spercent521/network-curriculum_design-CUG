# 网络可视化指南

本实验（Experiment 6）已集成可视化系统。您可以实时观察网络拓扑、路由表以及数据包流动，并通过 Web 界面下发指令。

## 1. 架构说明

*   **Backend (FastAPI)**: 作为中心控制器，接收各节点的路由表和日志上报，并维护全局网络状态。
*   **Frontend (React)**: 从 Backend 获取数据并渲染拓扑图，提供 Web 终端控制。
*   **Nodes (Experiment 6)**: 启动时自动连接 Backend，上报自身状态并拉取远程指令。

## 2. 启动步骤

请开启三个终端窗口，分别运行以下组件：

### 终端 1: 启动可视化后端

```bash
cd Web-Interface/Backend
# 确保已安装依赖: pip install -r ../../requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 终端 2: 启动可视化前端

```bash
cd Web-Interface/Frontend
# 确保已安装 Node.js 依赖
npm install 
npm run dev
```

*   启动后，浏览器打开显示的地址 (通常是 http://localhost:5173)。

### 终端 3+ : 启动实验节点

您可以启动多个节点 (如 A, B, C)，它们会自动连接到后端。

```bash
python Code_Refactored/Experiment6/network_app.py
```

*   **输入 ID**: 例如 `A`
*   **选择串口**: 选择与其他节点相连的虚拟串口。

## 3. 使用方法

### 查看状态
*   前端页面会自动显示连接的节点（绿色节点）。
*   连线表示节点间的物理/逻辑邻居关系。
*   点击节点或查看右侧日志面板，可以看到实时的路由更新和 Ping/Traceroute 结果。

### 下发指令
在 Web 界面的黑色终端窗口中，您可以直接控制任意节点。终端支持类似 Bash 的命令输入。

**语法格式**: `<节点ID> <命令>`

**支持的命令列表**:

1.  **Ping 测试**
    *   `A ping B`: 让节点 A 向节点 B 发送 Ping 请求。
    *   *说明*: 检测连通性。

2.  **路由追踪 (Traceroute)**
    *   `A tracert B`: 让节点 A 探测到节点 B 的路径。
    *   *说明*: 显示沿途经过的路由器和跳数。

3.  **查看路由表**
    *   `A table`: 让节点 A 在其**本地控制台**打印路由表信息。
    *   *说明*: 目前路由表详情主要在本地显示，Web 端拓扑图也会自动反映路由关系。

4.  **发送文本消息**
    *   `A send B HelloCurrent`: 让节点 A 向节点 B 发送 "HelloCurrent"。

**示例**:
*   让节点 A Ping 节点 B:
    `A ping B`
*   让节点 A 追踪节点 C:
    `A tracert C`

### 常见问题与排错

**1. 节点显示 "WriteFile failed / PermissionError"**
*   **原因**: 虚拟串口可能不稳定，或者 USB 串口被拔出/占用。
*   **解决**: 程序包含自动恢复机制，会移除故障的串口防止崩溃。您可以尝试重启节点程序或重新插拔串口。

**2. Web 终端无反应**
*   **原因**: WebSocket 可能断开。
*   **解决**: 刷新网页。如果后端显示 "Client disconnected"，请检查后端终端是否有报错。

### 注意事项
*   如果后端未启动，节点程序仍可正常运行，但会忽略上报错（为了增强鲁棒性）。
*   确保 `Experiment6` 代码中的 `VIZ_SERVER_URL` 指向正确的后端地址 (默认为 `http://localhost:8000/api/report`)。
