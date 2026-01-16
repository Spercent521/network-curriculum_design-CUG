"""
实验五：多机可靠传输实验（运输层）
功能：
1. 基于实验四的动态路由 (DV算法)
2. 增加可靠传输机制 (停等协议 Stop-and-Wait)
3. 数据校验 (CRC32), 超时重传, ACK确认机制

使用方法：
python Code/Experiment5/reliable_router.py
命令：
- table: 查看路由表
- send <目标ID> <消息>: 发送可靠消息
- corrupt <on/off>: 开启/关闭 模拟校验码错误（下一次发送时篡改校验码）
"""

import serial
import serial.tools.list_ports
import threading
import time
import json
import sys
import zlib
import random

# === 协议常量 ===
TYPE_HELLO = 'HELLO'
TYPE_DV    = 'DV'
TYPE_DATA  = 'DATA'  # 网络层数据包类型
SEPARATOR  = '|'

# 运输层常量
TRANS_TYPE_DATA = 'DAT'
TRANS_TYPE_ACK  = 'ACK'
TRANS_TYPE_SYN  = 'SYN' # 类似TCP SYN，用于建立新会话并同步序列号
TRANS_TYPE_SYNACK = 'SAK' # SYN-ACK
# 配置
BAUDRATE = 9600
HELLO_INTERVAL = 3
DV_INTERVAL    = 5
NEIGHBOR_TIMEOUT = 10
TIMEOUT_RETRANSMIT = 3.0 # 超时重传时间(秒)
MAX_RETRIES = 3          # 最大重传次数

class ReliableRouterNode:
    def __init__(self):
        self.my_id = ""
        self.running = False
        
        self.active_ports = {}
        self.port_locks = {}
        self.neighbors = {} 
        self.neighbors_lock = threading.Lock()

        # 路由表
        self.routing_table = {}
        self.rt_lock = threading.Lock()

        # === 实验五新增状态 ===
        self.seq_num = 0              # 发送序号 (简单的递增整数)
        self.expected_seqs = {}       # 接收端状态: {SrcID: NextExpectedSeq}
        self.ack_event = threading.Event() # 用于等待ACK
        self.received_ack_seq = -1    # 收到的ACK序号
        
        self.simulate_error = False   # 模拟错误开关

    def start(self):
        print("="*60)
        print("实验五：多机可靠传输 (Transport Layer)")
        print("="*60)
        
        available_ports = [p.device for p in serial.tools.list_ports.comports()]
        if not available_ports:
            print("错误: 未检测到任何串口设备。")
            # For testing without hardware, you might want to remove this return or mock it.
            # return

        print(f"检测到可用串口: {available_ports}")
        
        while not self.my_id:
            self.my_id = input("请输入本机ID (例如 A, B, PC1): ").strip()
        
        print("\n请选择要激活的串口 (用于构建网络)")
        print("输入串口名 (如 COM1)，多个用逗号分隔，或者输入 'all' 选择全部")
        selection = input("选择串口: ").strip()
        
        target_ports = []
        if selection.lower() == 'all':
            target_ports = available_ports
        else:
            parts = [p.strip() for p in selection.replace(',', ' ').split()]
            for p in parts:
                p_fixed = f"COM{p}" if p.isdigit() else p
                if p_fixed in available_ports:
                    target_ports.append(p_fixed)
                else:
                    print(f"警告: 串口 {p_fixed} 不存在或不可用")

        if not target_ports and available_ports:
             print("未选择有效串口，程序退出。")
             return

        # Init Routing Table
        self.routing_table[self.my_id] = {'cost': 0, 'next_hop_port': 'LOCAL', 'next_hop_id': self.my_id}

        self.running = True
        
        # Start Listeners
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

        # Start Background Tasks
        threading.Thread(target=self._task_hello, daemon=True).start()
        threading.Thread(target=self._task_broadcast_dv, daemon=True).start()
        threading.Thread(target=self._task_check_timeout, daemon=True).start()
        
        print("\n系统启动完成。")
        print("命令: send <Dest> <Msg> | table | corrupt on/off")
        print("="*60)
        
        self._input_loop()

    def _listen_port(self, port_name):
        ser = self.active_ports[port_name]
        while self.running and ser.is_open:
            try:
                if ser.in_waiting:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        self._handle_packet(line, port_name)
                else:
                    time.sleep(0.01)
            except Exception as e:
                print(f"[{port_name}] 读取错误: {e}")
                break

    def _send_to_port(self, port_name, packet_str):
        if port_name not in self.active_ports:
            return False
        with self.port_locks[port_name]:
            try:
                data = (packet_str + '\n').encode('utf-8')
                self.active_ports[port_name].write(data)
                return True
            except Exception as e:
                print(f"[{port_name}] 发送错误: {e}")
                return False

    def _handle_packet(self, raw_data, port_source):
        try:
            parts = raw_data.split(SEPARATOR, 3) 
            if len(parts) < 2: return
            
            p_type = parts[0]
            
            if p_type == TYPE_HELLO:
                sender_id = parts[1]
                self._on_recv_hello(sender_id, port_source)
                
            elif p_type == TYPE_DV:
                if len(parts) < 3: return
                sender_id = parts[1]
                dv_json = parts[2]
                self._on_recv_dv(sender_id, dv_json, port_source)
                
            elif p_type == TYPE_DATA:
                # DATA|SrcID|DstID|Payload(TransportFrame)
                if len(parts) != 4: return
                _, src_id, dst_id, payload = parts
                self._on_recv_data(src_id, dst_id, payload)
                
        except Exception as e:
            print(f"[Packet Error] {e} | Raw: {raw_data}")

    # === 路由协议处理 (Exp 3/4) ===
    def _on_recv_hello(self, sender_id, port):
        with self.neighbors_lock:
            self.neighbors[port] = {'id': sender_id, 'last_seen': time.time()}
            with self.rt_lock:
                current_entry = self.routing_table.get(sender_id)
                if not current_entry or current_entry['cost'] > 1:
                    self.routing_table[sender_id] = {
                        'cost': 1, 
                        'next_hop_port': port,
                        'next_hop_id': sender_id
                    }

    def _on_recv_dv(self, sender_id, dv_json, port):
        try:
            neighbor_dv = json.loads(dv_json)
        except:
            return

        with self.rt_lock:
            updated = False
            for dest, info in neighbor_dv.items():
                if dest == self.my_id: continue
                cost_neighbor_to_dest = info.get('cost', 999)
                new_cost = 1 + cost_neighbor_to_dest
                current_route = self.routing_table.get(dest)
                
                if not current_route:
                    self.routing_table[dest] = {
                        'cost': new_cost,
                        'next_hop_port': port,
                        'next_hop_id': sender_id
                    }
                    updated = True
                elif current_route['next_hop_id'] == sender_id:
                    if current_route['cost'] != new_cost:
                        current_route['cost'] = new_cost
                        updated = True
                elif new_cost < current_route['cost']:
                    self.routing_table[dest] = {
                        'cost': new_cost,
                        'next_hop_port': port,
                        'next_hop_id': sender_id
                    }
                    updated = True

    # === 可靠传输处理 (Exp 5) ===
    
    def _calculate_checksum(self, src, dst, seq, t_type, body):
        """计算校验码 (CRC32)"""
        # 伪首部 + 数据
        # Src|Dst|Seq|Type|Body
        content = f"{src}{SEPARATOR}{dst}{SEPARATOR}{seq}{SEPARATOR}{t_type}{SEPARATOR}{body}"
        return zlib.crc32(content.encode('utf-8')) & 0xffffffff

    def _transport_send_ack(self, target_id, seq_ack, is_syn_ack=False):
        """发送ACK (或 SYN-ACK) 帧"""
        # 决定类型
        t_type = TRANS_TYPE_SYNACK if is_syn_ack else TRANS_TYPE_ACK
        
        # Frame: SrcPort(0)|DstPort(0)|Seq(AckNum)|Checksum|Type|Payload("")
        chk = self._calculate_checksum(self.my_id, target_id, seq_ack, t_type, "")
        
        # Transport Frame Str
        tf_str = f"0{SEPARATOR}0{SEPARATOR}{seq_ack}{SEPARATOR}{chk}{SEPARATOR}{t_type}{SEPARATOR}"
        
        # Encap in Network Packet
        packet = f"{TYPE_DATA}{SEPARATOR}{self.my_id}{SEPARATOR}{target_id}{SEPARATOR}{tf_str}"
        
        # 路由发送
        print(f"[Transport] Sending {t_type} Seq={seq_ack} to {target_id}...")
        if not self._network_send(target_id, packet):
             print(f"[Transport] Error: Failed to send {t_type} to {target_id} (No Route?)")
        else:
             print(f"[Transport] Sent {t_type} {seq_ack} to {target_id} Success")

    def _on_recv_data(self, src_id, dst_id, payload):
        """
        处理网络层数据包
        如果是发给我的 -> 交给运输层处理
        如果不是 -> 转发
        """
        if dst_id == self.my_id:
            # 传输层解封装
            try:
                t_parts = payload.split(SEPARATOR, 5)
                if len(t_parts) < 6:
                    print(f"错误: 收到格式错误的运输层帧: {payload}")
                    return
                
                src_port, dst_port, seq_str, chk_str, t_type, body = t_parts
                seq = int(seq_str)
                recv_chk = int(chk_str)
                
                # 1. 校验
                cal_chk = self._calculate_checksum(src_id, dst_id, seq, t_type, body)
                if recv_chk != cal_chk:
                    print(f"[RX Error] 校验失败! 来自{src_id} Seq={seq} (Recv:{recv_chk} vs Calc:{cal_chk}) - 丢弃")
                    return 
                
                # 2. 处理 Type
                if t_type == TRANS_TYPE_SYN or t_type == TRANS_TYPE_DATA:
                    is_syn = (t_type == TRANS_TYPE_SYN)
                    if is_syn:
                        print(f"[RX SYN] 新会话请求 来自{src_id} InitSeq={seq}")
                        self.expected_seqs[src_id] = seq # 同步序列号
                    
                    print(f"[RX] 收到数据 来自{src_id} Seq={seq}: {body}")
                    
                    # 发送确认 (如果是SYN，回SYN-ACK；否则回ACK)
                    self._transport_send_ack(src_id, seq, is_syn_ack=is_syn)
                    
                    # 检查是否重复并交付
                    expected = self.expected_seqs.get(src_id, 0)
                    if seq == expected:
                        if body: print(f"    >>> [交付应用层] {body}")
                        self.expected_seqs[src_id] = seq + 1
                    elif seq < expected:
                        print(f"    [重复帧] Seq={seq}, 期望={expected}. 丢弃.")
                    else:
                        print(f"    [失序帧] Seq={seq}, 期望={expected}. 暂时丢弃.")

                elif t_type == TRANS_TYPE_ACK or t_type == TRANS_TYPE_SYNACK:
                    # 收到ACK或SYN-ACK
                    print(f"[RX] 收到 {t_type} 来自{src_id} AckSeq={seq}")
                    if seq == self.seq_num: # 确认当前发送的
                        self.received_ack_seq = seq
                        self.ack_event.set()
                        
            except ValueError:
                print("解析错误")
            return
        
        # --- 转发 ---
        with self.rt_lock:
            route = self.routing_table.get(dst_id)
            if route and route['cost'] < 999:
                next_port = route['next_hop_port']
                # 重新封装 (源我不变，Payload不变)
                packet = f"{TYPE_DATA}{SEPARATOR}{src_id}{SEPARATOR}{dst_id}{SEPARATOR}{payload}"
                print(f"[Forward] {src_id}->{dst_id} via {next_port}")
                self._send_to_port(next_port, packet)
            else:
                print(f"[Drop] 目标不可达: {dst_id}")

    def _network_send(self, target_id, packet_content):
        """查找路由并发送（不封装DATA头，参数已经是完整包或需要封装?）"""
        # 注意: _on_recv_data里的转发重构了包。
        # 这里 _send_reliable 构建的 packet_content 已经是 TransportFrame
        # 也就是 DATA 的 payload。
        # 所以这里需要封装网络层头
        # Wait, usually _network_send takes payload.
        # But `_transport_send_ack` constructed the full packet.
        # Let's standardize: `_network_send` takes the full packet string ready to go to serial?
        # Or takes payload?
        # Let's make `_network_send` strictly the "Lookup and Serial Write" function.
        # But `packet_content` passed here is expected to be `DATA|...`.
        
        # Check if packet already has header? 
        # In `_transport_send_ack` I constructed: `DATA|Me|Target|TF_Str`.
        pass 
        # Using helper logic below:
        
        with self.rt_lock:
            route = self.routing_table.get(target_id)
            if not route:
                print(f"错误: 找不到去往 {target_id} 的路由")
                return False
            if route['cost'] >= 999:
                print(f"错误: 目标 {target_id} 当前不可达")
                return False
            
            port = route['next_hop_port']
            self._send_to_port(port, packet_content)
            return True

    def _initiate_reliable_send(self, target_id, msg):
        """停等协议发送逻辑 (Blocking)"""
        # [NEW] 随机生成 Seq (类似 TCP ISN)
        seq = random.randint(0, 65535)
        self.seq_num = seq # [FIX] Sync state for RX thread
        
        # 准备 Transport Frame
        # Fmt: SrcP|DstP|Seq|Chk|Type|Body
        
        # [NEW] 使用 SYN 类型来标志这是一个新会话 (Send命令是一次性会话)
        t_type = TRANS_TYPE_SYN
        
        # 1. 计算校验码
        chk = self._calculate_checksum(self.my_id, target_id, seq, t_type, msg)
        
        if self.simulate_error:
            print("[Simulate] 模拟校验码错误 (发送损坏包)")
            chk += 123 # 破坏校验码
            self.simulate_error = False # Reset
            
        tf_str = f"0{SEPARATOR}0{SEPARATOR}{seq}{SEPARATOR}{chk}{SEPARATOR}{t_type}{SEPARATOR}{msg}"
        
        # 2. 封装网络层
        packet = f"{TYPE_DATA}{SEPARATOR}{self.my_id}{SEPARATOR}{target_id}{SEPARATOR}{tf_str}"
        
        print(f"--- 开始可靠发送 (SYN Mode) Seq={seq} to {target_id} ---")
        
        success = False
        for attempt in range(MAX_RETRIES):
            # 发送
            if not self._network_send(target_id, packet):
                print("发送失败: 网络层无法发送")
                break # 路由问题，重传也没用
            
            print(f"[TX] 发送 Seq={seq} (尝试 {attempt+1}/{MAX_RETRIES})... 等待ACK")
            
            # 等待
            self.ack_event.clear()
            self.received_ack_seq = -1
            
            if self.ack_event.wait(TIMEOUT_RETRANSMIT):
                if self.received_ack_seq == seq:
                    print(f"[TX Success] 收到确认 ACK={seq}")
                    success = True
                    break
                else:
                    print(f"[TX Info] 收到非当前ACK: {self.received_ack_seq}")
            else:
                print(f"[TX Timeout] 超时未收到ACK")
                
        if success:
            # self.seq_num += 1 # 不需要了，每次随机
            pass
        else:
            print("--- 发送最终失败 (达到最大重传次数) ---")

    # === 定时任务 (Hello/DV) ===
    def _task_hello(self):
        while self.running:
            packet = f"{TYPE_HELLO}{SEPARATOR}{self.my_id}"
            for port in list(self.active_ports.keys()): 
                self._send_to_port(port, packet)
            time.sleep(HELLO_INTERVAL)

    def _task_broadcast_dv(self):
        while self.running:
            dv_snapshot = {}
            with self.rt_lock:
                for dest, info in self.routing_table.items():
                    dv_snapshot[dest] = {'cost': info['cost']}
            dv_str = json.dumps(dv_snapshot)
            packet = f"{TYPE_DV}{SEPARATOR}{self.my_id}{SEPARATOR}{dv_str}"
            for port in list(self.active_ports.keys()):
                self._send_to_port(port, packet)
            time.sleep(DV_INTERVAL)

    def _task_check_timeout(self):
        while self.running:
            now = time.time()
            timeout_ports = []
            with self.neighbors_lock:
                for port, info in self.neighbors.items():
                    if now - info['last_seen'] > NEIGHBOR_TIMEOUT:
                        print(f"[连接断开] 邻居 {info['id']} ({port}) 超时")
                        timeout_ports.append(port)
                for p in timeout_ports:
                    del self.neighbors[p]
            if timeout_ports:
                with self.rt_lock:
                    for dest, info in self.routing_table.items():
                        if info['next_hop_port'] in timeout_ports and dest != self.my_id:
                            info['cost'] = 999
            time.sleep(1)

    # === UI ===
    def _input_loop(self):
        while self.running:
            try:
                cmd = input("> ").strip()
                if not cmd: continue
                parts = cmd.split()
                op = parts[0].lower()
                
                if op == 'table':
                    self._print_table()
                elif op == 'corrupt':
                    if len(parts) > 1 and parts[1] == 'on':
                        self.simulate_error = True
                        print("模拟错误已开启 (下一次发送的包校验码将错误)")
                    else:
                        self.simulate_error = False
                        print("模拟错误已关闭")
                elif op == 'send':
                    if len(parts) < 3:
                        print("用法: send <目标ID> <消息>")
                        continue
                    target = parts[1]
                    msg = " ".join(parts[2:])
                    # 在主线程发，会阻塞UI。这是预期的Stop-Wait
                    self._initiate_reliable_send(target, msg)
                elif op == 'exit':
                    self.running = False
                    for s in self.active_ports.values(): s.close()
                    sys.exit(0)
                else:
                    print("未知命令")
            except KeyboardInterrupt:
                self.running = False
                sys.exit(0)
            except Exception as e:
                print(f"Error: {e}")

    def _print_table(self):
        print("\n------- 路由表 -------")
        with self.rt_lock:
            for dest, info in self.routing_table.items():
                print(f"{dest:<5} Cost:{info['cost']:<5} Next:{info['next_hop_id']:<5} IF:{info['next_hop_port']}")
        print("-" * 30)

if __name__ == '__main__':
    node = ReliableRouterNode()
    try:
        node.start()
    except KeyboardInterrupt:
        pass
