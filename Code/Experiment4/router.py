"""
实验四：跨链路的多机通信实验（网络层 DV算法版本）
原理：基于距离向量 (Distance Vector) 算法 和 Bellman-Ford 方程
功能：
1. 自动邻居发现 (Hello Protocol)
2. 动态路由更新 (DV Exchange)
3. 数据包转发 (Routing)

使用方法：
在每一台计算机上运行此脚本，输入本机ID和要使用的串口列表。
程序会自动建立网络拓扑并交换路由表。
"""

import serial
import serial.tools.list_ports
import threading
import time
import json
import sys

# === 协议常量 ===
TYPE_HELLO = 'HELLO' # 邻居发现
TYPE_DV    = 'DV'    # 路由通告
TYPE_DATA  = 'DATA'  # 数据传输
SEPARATOR  = '|'     # 字段分隔符

# 配置
BAUDRATE = 9600
HELLO_INTERVAL = 3   # 发送Hello包的间隔(秒)
DV_INTERVAL    = 5   # 发送路由表的间隔(秒)
NEIGHBOR_TIMEOUT = 10 # 邻居超时判定(秒)

class RouterNode:
    def __init__(self):
        self.my_id = ""
        self.running = False
        
        # 串口管理
        # active_ports: port_name -> serial.Serial 对象
        self.active_ports = {}
        # port_locks: port_name -> threading.Lock (用于互斥写入)
        self.port_locks = {}
        
        # 邻居表
        # neighbors: port_name -> {'id': neighbor_id, 'last_seen': timestamp}
        self.neighbors = {} 
        self.neighbors_lock = threading.Lock()

        # 路由表 (Distance Vector)
        # 结构: dest_id -> {'cost': int, 'next_hop_port': port_name, 'next_hop_id': id}
        # 初始时包含自己: {my_id: {'cost': 0, 'next_hop_port': 'LOCAL', 'next_hop_id': my_id}}
        self.routing_table = {}
        self.rt_lock = threading.Lock()

    def start(self):
        print("="*60)
        print("实验四：动态路由 (DV算法)")
        print("="*60)
        
        # 1. 扫描并展示可用串口
        available_ports = [p.device for p in serial.tools.list_ports.comports()]
        if not available_ports:
            print("错误: 未检测到任何串口设备。")
            return

        print(f"检测到可用串口: {available_ports}")
        
        # 2. 获取本机配置
        while not self.my_id:
            self.my_id = input("请输入本机ID (例如 A, B, PC1): ").strip()
        
        print("\n请选择要激活的串口 (用于构建网络)")
        print("输入串口名 (如 COM1)，多个用逗号分隔，或者输入 'all' 选择全部")
        selection = input("选择串口: ").strip()
        
        target_ports = []
        if selection.lower() == 'all':
            target_ports = available_ports
        else:
            # 解析用户输入 "COM1, COM2"
            parts = [p.strip() for p in selection.replace(',', ' ').split()]
            for p in parts:
                # 简单修正 COM1 这种输入，如果是 1 则转 COM1
                p_fixed = f"COM{p}" if p.isdigit() else p
                if p_fixed in available_ports:
                    target_ports.append(p_fixed)
                else:
                    print(f"警告: 串口 {p_fixed} 不存在或不可用，已忽略")

        if not target_ports:
            print("未选择有效串口，程序退出。")
            return

        # 初始化路由表（加入自己）
        self.routing_table[self.my_id] = {'cost': 0, 'next_hop_port': 'LOCAL', 'next_hop_id': self.my_id}

        self.running = True
        
        # 3. 启动端口监听线程
        for port in target_ports:
            try:
                ser = serial.Serial(port, BAUDRATE, timeout=0.1)
                self.active_ports[port] = ser
                self.port_locks[port] = threading.Lock()
                
                t = threading.Thread(target=self._listen_port, args=(port,), daemon=True)
                t.start()
                print(f"[{port}] 监听已启动...")
            except Exception as e:
                print(f"[{port}] 打开失败: {e}")

        # 4. 启动周期性任务 (Hello广播, DV广播, 超时检测)
        threading.Thread(target=self._task_hello, daemon=True).start()
        threading.Thread(target=self._task_broadcast_dv, daemon=True).start()
        threading.Thread(target=self._task_check_timeout, daemon=True).start()
        
        print("\n系统启动完成。正在自动发现邻居并构建路由表...")
        print("输入 'table' 查看路由表，输入 'send <Dest> <Msg>' 发送消息。")
        print("="*60)
        
        # 5. 主循环：处理用户输入
        self._input_loop()

    def _listen_port(self, port_name):
        """串口接收线程"""
        ser = self.active_ports[port_name]
        buffer = ""
        while self.running and ser.is_open:
            try:
                if ser.in_waiting:
                    # 读取数据，拼接到buffer中处理粘包/分包 (这里简化按行读取)
                    # 实际工程可能需要更复杂的帧头帧尾校验
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        self._handle_packet(line, port_name)
                else:
                    time.sleep(0.01)
            except Exception as e:
                print(f"[{port_name}] 读取错误: {e}")
                break

    def _send_to_port(self, port_name, packet_str):
        """线程安全地发送数据"""
        if port_name not in self.active_ports:
            return False
        
        lock = self.port_locks[port_name]
        ser = self.active_ports[port_name]
        
        with lock:
            try:
                data = (packet_str + '\n').encode('utf-8')
                ser.write(data)
                return True
            except Exception as e:
                print(f"[{port_name}] 发送错误: {e}")
                return False

    # === 协议处理核心 ===

    def _handle_packet(self, raw_data, port_source):
        """
        处理接收到的数据包
        三种类型:
        1. HELLO|SenderID
        2. DV|SenderID|JSON_Routing_Table
        3. DATA|SrcID|DstID|Payload
        """
        try:
            parts = raw_data.split(SEPARATOR, 3) # 最多切分出前几个字段
            if len(parts) < 2: return
            
            p_type = parts[0]
            
            if p_type == TYPE_HELLO:
                sender_id = parts[1]
                self._on_recv_hello(sender_id, port_source)
                
            elif p_type == TYPE_DV:
                # DV|SenderID|JSON
                if len(parts) < 3: return
                sender_id = parts[1]
                dv_json = parts[2]
                self._on_recv_dv(sender_id, dv_json, port_source)
                
            elif p_type == TYPE_DATA:
                # DATA|SrcID|DstID|Payload
                if len(parts) != 4: return
                _, src_id, dst_id, payload = parts
                self._on_recv_data(src_id, dst_id, payload)
                
        except Exception as e:
            print(f"[Packet Error] {e} | Raw: {raw_data}")

    def _on_recv_hello(self, sender_id, port):
        """收到Hello包，更新邻居状态"""
        with self.neighbors_lock:
            # 记录或更新邻居
            self.neighbors[port] = {'id': sender_id, 'last_seen': time.time()}
            
            # 如果邻居不在路由表中（或者路由表中该邻居是不可达状态），立即标记为直连
            with self.rt_lock:
                # 直连邻居 Distance = 1
                current_entry = self.routing_table.get(sender_id)
                # 如果没有路由，或者现有路由开销大于1（说明之前绕路了），则更新为直连
                if not current_entry or current_entry['cost'] > 1:
                    # print(f"[拓扑变动] 发现直连邻居: {sender_id} via {port}")
                    self.routing_table[sender_id] = {
                        'cost': 1, 
                        'next_hop_port': port,
                        'next_hop_id': sender_id
                    }

    def _on_recv_dv(self, sender_id, dv_json, port):
        """收到距离向量，运行 Bellman-Ford"""
        try:
            neighbor_dv = json.loads(dv_json)
        except:
            return

        with self.rt_lock:
            updated = False
            
            # 1. 遍历邻居通告的所有目的地
            for dest, info in neighbor_dv.items():
                if dest == self.my_id: continue # 忽略去往自己的路由通告
                
                # 邻居到目标的开销
                cost_neighbor_to_dest = info.get('cost', 999)
                # 经由该邻居到达目标的总开销 = 1 (我到邻居) + cost (邻居到目标)
                new_cost = 1 + cost_neighbor_to_dest
                
                current_route = self.routing_table.get(dest)
                
                # 情况A: 发现新目标
                if not current_route:
                    self.routing_table[dest] = {
                        'cost': new_cost,
                        'next_hop_port': port,
                        'next_hop_id': sender_id
                    }
                    updated = True
                    # print(f"[路由新增] -> {dest} cost={new_cost} via {sender_id}")
                
                # 情况B: 现有路由的下一跳就是该邻居
                # 必须更新（哪怕cost变大了，因为邻居那边的路况变了）
                elif current_route['next_hop_id'] == sender_id:
                    if current_route['cost'] != new_cost:
                        current_route['cost'] = new_cost
                        updated = True
                        # print(f"[路由更新] -> {dest} cost变更为 {new_cost}")

                # 情况C: 现有路由下一跳不是这个邻居，但这个邻居提供了更短路径
                elif new_cost < current_route['cost']:
                    self.routing_table[dest] = {
                        'cost': new_cost,
                        'next_hop_port': port,
                        'next_hop_id': sender_id
                    }
                    updated = True
                    # print(f"[路由优化] -> {dest} via {sender_id} (cost {current_route['cost']}->{new_cost})")

            # 2. (进阶) 如果邻居告知某些目的地它是不可达的(cost=inf)，这里简化处理，不做 Poison Reverse
            
            # 如果路由表有变动，可以在下一次周期广播，或立即触发广播(Triggered Update)
            # 这里简单起见，等待周期广播

    def _on_recv_data(self, src_id, dst_id, payload):
        """收到数据包"""
        if dst_id == self.my_id:
            print(f"\n>>> 收到消息 [{src_id}]: {payload}")
            print("> ", end="", flush=True)
            return
        
        # 转发逻辑
        with self.rt_lock:
            route = self.routing_table.get(dst_id)
            if route and route['cost'] < 999:
                next_port = route['next_hop_port']
                # 封装并转发
                # DATA|Src|Dst|Payload
                # 注意：我们转发的是原始包内容，或者重新封装。因为源ID不变。
                packet = f"{TYPE_DATA}{SEPARATOR}{src_id}{SEPARATOR}{dst_id}{SEPARATOR}{payload}"
                print(f"[转发] {src_id}->{dst_id} via {next_port}")
                self._send_to_port(next_port, packet)
            else:
                print(f"[丢弃] 目标不可达: {dst_id} (From {src_id})")

    # === 定时任务 ===

    def _task_hello(self):
        """定期发送 Hello 包"""
        while self.running:
            packet = f"{TYPE_HELLO}{SEPARATOR}{self.my_id}"
            # 向所有激活端口广播
            for port in list(self.active_ports.keys()): # Copy keys
                self._send_to_port(port, packet)
            time.sleep(HELLO_INTERVAL)

    def _task_broadcast_dv(self):
        """定期广播路由表 (DV)"""
        while self.running:
            # 构建路由表快照
            dv_snapshot = {}
            with self.rt_lock:
                for dest, info in self.routing_table.items():
                    # 水平分割 (Split Horizon) 可以在发送时针对不同接口过滤
                    # 这里为了简化，发送完整表，开销仅为数字
                    dv_snapshot[dest] = {'cost': info['cost']}
            
            dv_str = json.dumps(dv_snapshot)
            packet = f"{TYPE_DV}{SEPARATOR}{self.my_id}{SEPARATOR}{dv_str}"
            
            for port in list(self.active_ports.keys()):
                # 进阶: 这里可以实现 Split Horizon，即不向 next_hop 所在的端口通告去往该目的地的路由
                # 但基础 DV 算法不强制要求
                self._send_to_port(port, packet)
                
            time.sleep(DV_INTERVAL)

    def _task_check_timeout(self):
        """检测邻居超时"""
        while self.running:
            now = time.time()
            timeout_ports = []
            
            with self.neighbors_lock:
                for port, info in self.neighbors.items():
                    if now - info['last_seen'] > NEIGHBOR_TIMEOUT:
                        print(f"[连接断开] 邻居 {info['id']} ({port}) 超时")
                        timeout_ports.append(port)
                
                # 清除超时邻居
                for p in timeout_ports:
                    del self.neighbors[p]
            
            if timeout_ports:
                # 触发路由表更新：将经过这些端口的路由标记为不可达
                with self.rt_lock:
                    for dest, info in self.routing_table.items():
                        if info['next_hop_port'] in timeout_ports and dest != self.my_id:
                            info['cost'] = 999 # 无穷大
                            # 这里不立即删除，而是保留为不可达，以便毒性逆转传播
            
            time.sleep(1)

    # === 用户交互 ===
    def _input_loop(self):
        while self.running:
            try:
                cmd = input("> ").strip()
                if not cmd: continue
                
                parts = cmd.split()
                op = parts[0].lower()
                
                if op == 'table' or op == 't':
                    self._print_table()
                elif op == 'send' or op == 's':
                    # send ID Hello World
                    if len(parts) < 3:
                        print("用法: send <目标ID> <消息内容>")
                        continue
                    target = parts[1]
                    msg = " ".join(parts[2:])
                    self._initiate_send(target, msg)
                elif op == 'exit' or op == 'quit':
                    self.running = False
                    print("正在退出...")
                    for s in self.active_ports.values():
                        s.close()
                    sys.exit(0)
                else:
                    print("未知命令。可用: table, send, exit")
                    
            except KeyboardInterrupt:
                self.running = False
                sys.exit(0)
            except Exception as e:
                print(f"输入错误: {e}")

    def _print_table(self):
        print("\n------- 当前路由表 (Distance Vector) -------")
        print(f"{'Destination':<15} {'Cost':<10} {'Next Hop':<15} {'Interface':<10}")
        print("-" * 55)
        with self.rt_lock:
            for dest, info in self.routing_table.items():
                print(f"{dest:<15} {info['cost']:<10} {info['next_hop_id']:<15} {info['next_hop_port']:<10}")
        print("-" * 55)

    def _initiate_send(self, target_id, msg):
        """本机发起发送数据"""
        # 包格式: DATA|Src|Dst|Payload
        packet = f"{TYPE_DATA}{SEPARATOR}{self.my_id}{SEPARATOR}{target_id}{SEPARATOR}{msg}"
        
        # 查表发送
        with self.rt_lock:
            route = self.routing_table.get(target_id)
            if not route:
                print(f"错误: 找不到去往 {target_id} 的路由")
                return
            if route['cost'] >= 999:
                print(f"错误: 目标 {target_id} 当前不可达")
                return
            
            port = route['next_hop_port']
            print(f"[发送] 目标:{target_id} 下一跳:{route['next_hop_id']} ({port})")
            self._send_to_port(port, packet)

if __name__ == '__main__':
    node = RouterNode()
    try:
        node.start()
    except KeyboardInterrupt:
        print("\n强制退出")

