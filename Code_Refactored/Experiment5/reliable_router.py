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

import threading
import time
import json
import sys
import zlib
import random
import os

# 导入 utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils import Logger, select_multiple_ports, create_serial_connection

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
# BAUDRATE = 9600
HELLO_INTERVAL = 3
DV_INTERVAL    = 5
NEIGHBOR_TIMEOUT = 10
TIMEOUT_RETRANSMIT = 3.0 # 超时重传时间(秒)
MAX_RETRIES = 30         # 最大重传次数

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
        
        self.simulate_error = False   # 模拟校验错误开关
        self.corruption_count = 0     # 剩余干扰次数
        self.simulate_loss = False    # 模拟丢包开关

    def start(self):
        print("="*60)
        print("实验五：多机可靠传输 (Transport Layer)")
        print("="*60)
        
        # 1. 选择串口
        target_ports = select_multiple_ports("请选择要激活的串口 (用于构建网络)")
        if not target_ports:
             Logger.warning("未选择有效串口，程序退出。")
             return
        
        # 2. 本机ID
        while not self.my_id:
            self.my_id = input("请输入本机ID (例如 A, B, PC1): ").strip()

        # Init Routing Table
        self.routing_table[self.my_id] = {'cost': 0, 'next_hop_port': 'LOCAL', 'next_hop_id': self.my_id}

        self.running = True
        
        # Start Listeners
        for port in target_ports:
            ser = create_serial_connection(port, timeout=0.1)
            if ser:
                self.active_ports[port] = ser
                self.port_locks[port] = threading.Lock()
                
                t = threading.Thread(target=self._listen_port, args=(port,), daemon=True)
                t.start()
                Logger.info(f"[{port}] 监听已启动...")
            else:
                Logger.error(f"[{port}] 打开失败")

        if not self.active_ports:
            Logger.error("无可用端口，退出")
            return

        # Start Background Tasks
        threading.Thread(target=self._task_hello, daemon=True).start()
        threading.Thread(target=self._task_broadcast_dv, daemon=True).start()
        threading.Thread(target=self._task_check_timeout, daemon=True).start()
        
        Logger.success("系统启动完成。")
        print("命令: send <Dest> <Msg> | table | corrupt on/off | loss on/off | help | exit")
        print("输入 'help' 获取详细帮助")
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
                Logger.error(f"[{port_name}] 读取错误: {e}")
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
                Logger.error(f"[{port_name}] 发送错误: {e}")
                return False
    
    def _send_to_port_with_simulation(self, port_name, packet_str):
        """支持模拟的发送（仅用于可靠消息）"""
        if port_name not in self.active_ports:
            return False
        
        # 模拟丢包（仅在可靠传输时）
        if self.simulate_loss:
            Logger.warning(f"[Simulate] 模拟丢包 (本应发往 {port_name})")
            self.simulate_loss = False  # 只模拟一次
            return True  # 返回True表示"发送"了，但实际没有
        
        return self._send_to_port(port_name, packet_str)

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
            Logger.debug(f"[Packet Error] {e} | Raw: {raw_data}")

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
        # Logger.debug(f"[Checksum Calc] Str='{content}'") # 调试用
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
        Logger.info(f"[Transport DEBUG] 正在回复 {t_type} 给 {target_id} Seq={seq_ack} ...") 
        if not self._network_send(target_id, packet):
             Logger.error(f"[Transport] 关键错误! 收到消息但无法回复 {t_type} 给 {target_id} (没有回程路由!)")
             print(f"!!! 请检查本机的路由表 (table命令)，确认是否有去往 {target_id} 的路径 !!!")
        else:
             pass 

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
                    Logger.error(f"收到格式错误的运输层帧: {payload}")
                    return
                
                src_port, dst_port, seq_str, chk_str, t_type, body = t_parts
                seq = int(seq_str)
                recv_chk = int(chk_str)
                
                # 1. 校验
                cal_chk = self._calculate_checksum(src_id, dst_id, seq, t_type, body)
                if recv_chk != cal_chk:
                    Logger.warning(f"[RX Error] 校验失败! 来自{src_id} Type={t_type} Seq={seq}")
                    Logger.warning(f"    Recv Checksum: {recv_chk}")
                    Logger.warning(f"    Calc Checksum: {cal_chk}")
                    Logger.warning(f"    Calc String: '{src_id}{SEPARATOR}{dst_id}{SEPARATOR}{seq}{SEPARATOR}{t_type}{SEPARATOR}{body}'")
                    # 校验失败，不发送ACK（等待发送方超时重传）
                    return 
                
                # 2. 处理 Type
                if t_type == TRANS_TYPE_SYN or t_type == TRANS_TYPE_DATA:
                    is_syn = (t_type == TRANS_TYPE_SYN)
                    if is_syn:
                        Logger.info(f"[RX SYN] 新会话请求 来自{src_id} InitSeq={seq}: {body}")
                        # 对于 SYN, 直接接受并重置期望序列号
                        self.expected_seqs[src_id] = seq + 1 
                        
                        if body:
                            Logger.info(f"    >>> [交付应用层] {body}")
                            
                        # 发送 SYN-ACK
                        self._transport_send_ack(src_id, seq, is_syn_ack=True)

                    else:
                        # 普通数据包
                        Logger.info(f"[RX] 收到数据 来自{src_id} Seq={seq}: {body}")
                        expected = self.expected_seqs.get(src_id, seq) # default to seq if not found?
                        
                        if seq == expected:
                            self._transport_send_ack(src_id, seq, is_syn_ack=False)
                            if body: 
                                Logger.info(f"    >>> [交付应用层] {body}")
                            self.expected_seqs[src_id] = seq + 1
                        elif seq < expected:
                            Logger.warning(f"    [重复帧] Seq={seq}, 期望={expected}. 发送ACK.")
                            self._transport_send_ack(src_id, seq, is_syn_ack=False)
                        else:
                            Logger.warning(f"    [失序帧] Seq={seq}, 期望={expected}. 暂不应答.")

                elif t_type == TRANS_TYPE_ACK or t_type == TRANS_TYPE_SYNACK:
                    # 收到ACK或SYN-ACK
                    Logger.info(f"[RX] 收到 {t_type} 来自{src_id} AckSeq={seq}")
                    if seq == self.seq_num: 
                        self.received_ack_seq = seq
                        self.ack_event.set()
                        Logger.success(f"[RX ACK] 确认成功")
                    else:
                        Logger.warning(f"[RX ACK] 序号不匹配 (期望{self.seq_num}，收到{seq})")
                        
            except ValueError as e:
                Logger.error(f"解析错误: {e}")
            return
        
        # --- 转发 ---
        with self.rt_lock:
            route = self.routing_table.get(dst_id)
            if route and route['cost'] < 999:
                next_port = route['next_hop_port']
                packet = f"{TYPE_DATA}{SEPARATOR}{src_id}{SEPARATOR}{dst_id}{SEPARATOR}{payload}"
                Logger.info(f"[Forward] {src_id}->{dst_id} via {next_port}")
                self._send_to_port(next_port, packet)
            else:
                Logger.warning(f"[Drop] 目标不可达: {dst_id}")

    def _network_send(self, target_id, packet_content):
        """查找路由并发送完整网络层包（支持模拟丢包）"""
        with self.rt_lock:
            route = self.routing_table.get(target_id)
            if not route:
                Logger.error(f"错误: 找不到去往 {target_id} 的路由")
                return False
            if route['cost'] >= 999:
                Logger.error(f"错误: 目标 {target_id} 当前不可达")
                return False
            
            port = route['next_hop_port']
            self._send_to_port_with_simulation(port, packet_content)
            return True

    def _initiate_reliable_send(self, target_id, msg):
        """停等协议发送逻辑 (Blocking)"""
        # [Step 1] 发送 SYN 建立会话
        seq = random.randint(0, 65535)
        self.seq_num = seq
        
        t_type = TRANS_TYPE_SYN
        
        Logger.info(f"\n=== 开始可靠发送到 {target_id} ===")
        print(f"[TX] 发送 SYN (Seq={seq}, 数据='{msg}')")
        
        syn_ack_received = False
        for attempt in range(MAX_RETRIES):
            # [RE-CALC]
            chk = self._calculate_checksum(self.my_id, target_id, seq, t_type, msg)
            
            # [干扰逻辑]
            if self.corruption_count > 0:
                Logger.warning(f"[Simulate] 模拟校验码错误 (剩余干扰次数: {self.corruption_count})")
                chk += 123
                self.corruption_count -= 1
            elif self.simulate_error: 
                Logger.warning(f"[Simulate] 模拟校验码错误 (本次)")
                chk += 123
                self.simulate_error = False

            tf_str = f"0{SEPARATOR}0{SEPARATOR}{seq}{SEPARATOR}{chk}{SEPARATOR}{t_type}{SEPARATOR}{msg}"
            packet = f"{TYPE_DATA}{SEPARATOR}{self.my_id}{SEPARATOR}{target_id}{SEPARATOR}{tf_str}"

            if not self._network_send(target_id, packet):
                Logger.error("发送失败: 网络层无法发送")
                break
            
            print(f"[TX] SYN发送 (尝试 {attempt+1}/{MAX_RETRIES})... 等待SYN-ACK")
            
            self.ack_event.clear()
            self.received_ack_seq = -1
            
            if self.ack_event.wait(TIMEOUT_RETRANSMIT):
                if self.received_ack_seq == seq:
                    Logger.success(f"[TX] 收到 SYN-ACK，会话已建立")
                    syn_ack_received = True
                    break
                else:
                    Logger.warning(f"[TX] 收到非期望的ACK: {self.received_ack_seq}，继续等待...")
            else:
                Logger.warning(f"[TX] 超时，准备重传...")
        
        if not syn_ack_received:
            Logger.error("=== 发送失败: 无法建立会话 ===\n")
            return
        
        Logger.success("=== 发送成功 ===\n")

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
                        Logger.warning(f"[连接断开] 邻居 {info['id']} ({port}) 超时")
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
                parts = cmd.split(maxsplit=2)
                op = parts[0].lower()
                
                if op == 'table' or op == 't':
                    self._print_table()
                elif op == 'corrupt':
                    if len(parts) > 1:
                        val = parts[1]
                        if val.isdigit():
                            self.corruption_count = int(val)
                            Logger.info(f"模拟校验错误已开启 (下 {self.corruption_count} 次)")
                        elif val == 'on':
                            self.corruption_count = 5 
                            Logger.info(f"模拟校验错误已开启 (默认5次)")
                        else:
                             self.simulate_error = False
                             self.corruption_count = 0
                             Logger.info("模拟校验错误已关闭")
                    else:
                        print("用法: corrupt <on/off/次数>")
                elif op == 'loss':
                    if len(parts) > 1 and parts[1] == 'on':
                        self.simulate_loss = True
                        Logger.info("模拟丢包已开启 (下一次)")
                    else:
                        self.simulate_loss = False
                        Logger.info("模拟丢包已关闭")
                elif op == 'send':
                    if len(parts) < 3:
                        print("用法: send <目标ID> <消息>")
                        continue
                    target = parts[1]
                    msg = parts[2]
                    self._initiate_reliable_send(target, msg)
                elif op == 'help' or op == 'h' or op == '?':
                    self._print_help()
                elif op == 'exit' or op == 'quit':
                    self.running = False
                    for s in self.active_ports.values(): s.close()
                    sys.exit(0)
                else:
                    print(f"未知命令: {op}。输入 'help' 查看帮助。")
            except KeyboardInterrupt:
                self.running = False
                sys.exit(0)
            except Exception as e:
                Logger.error(f"Error: {e}")
    
    def _print_help(self):
        print("""
=== 可靠传输路由节点 - 命令帮助 ===
命令列表:
  table (t)           - 显示当前路由表
  send <ID> <MSG>     - 向目标ID发送可靠消息 (停等协议)
  corrupt on/off      - 开启/关闭模拟校验错误
  loss on/off         - 开启/关闭模拟丢包
  help (h, ?)         - 显示此帮助
  exit (quit)         - 退出程序
        """)

    def _print_table(self):
        print("\n" + "="*60)
        print("当前路由表 (Distance Vector)")
        print("="*60)
        print(f"{'目标':<10} {'开销':<10} {'下一跳':<10} {'接口':<15}")
        print("-"*60)
        with self.rt_lock:
            for dest, info in self.routing_table.items():
                cost_str = str(info['cost']) if info['cost'] < 999 else "∞"
                print(f"{dest:<10} {cost_str:<10} {info['next_hop_id']:<10} {info['next_hop_port']:<15}")
        print("="*60 + "\n")

if __name__ == '__main__':
    node = ReliableRouterNode()
    try:
        node.start()
    except KeyboardInterrupt:
        pass
