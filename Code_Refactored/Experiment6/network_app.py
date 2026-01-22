"""
实验六：简单网络管理实验（应用层 Ping/Traceroute）
功能：
1. 继承实验四/五的动态路由与转发功能
2. 网络层增加 TTL (Time To Live) 处理
3. 实现 ICMP 协议逻辑 (Echo Request/Reply, Time Exceeded)
4. 实现 Ping 和 Traceroute 工具
"""

import threading
import time
import json
import sys
import zlib
import os

try:
    import requests
except ImportError:
    pass

# 导入 utils
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils import Logger, select_multiple_ports, create_serial_connection

# === 协议常量 ===
TYPE_HELLO = 'HELLO'
TYPE_DV    = 'DV'
TYPE_DATA  = 'DATA'  
SEPARATOR  = '|'

# 内部子协议类型
PROTO_TRANSPORT = 'TRA' # 实验五的可靠传输
PROTO_ICMP      = 'ICMP' # 实验六的网络管理

# ICMP 类型
ICMP_ECHO_REQUEST = 'ECHO_REQ'
ICMP_ECHO_REPLY   = 'ECHO_REP'
ICMP_TIME_EXCEEDED = 'TIME_EXC'

# 配置
# BAUDRATE = 9600
HELLO_INTERVAL = 3
DV_INTERVAL    = 5
NEIGHBOR_TIMEOUT = 10
DEFAULT_TTL = 64
VIZ_SERVER_URL = "http://localhost:8000/api/report"

class NetworkNode:
    def __init__(self):
        self.my_id = ""
        self.running = False
        
        self.active_ports = {}
        self.port_locks = {}
        self.neighbors = {} 
        self.neighbors_lock = threading.Lock()

        self.routing_table = {}
        self.rt_lock = threading.Lock()
        
        # Ping/Tracert State Management
        self.icmp_events = {}
        self.icmp_results = {}
        self.icmp_lock = threading.Lock()
        self.seq_counter = 0

        # Visualization
        self.log_buffer = []
        self.log_lock = threading.Lock()

    def _log_viz(self, msg):
        """记录日志用于可视化上报"""
        with self.log_lock:
            self.log_buffer.append(msg)
        # 同时打印到本地，但在非阻塞输入时可能会乱序
        # print(f"[LOG] {msg}") 

    def start(self):
        print("="*60)
        print("实验六：网络管理工具 (Ping / Traceroute)")
        
        # 1. 选择串口
        ports = select_multiple_ports("选择要激活的串口")
        # 2. 本机ID
        while not self.my_id:
            self.my_id = input("本机ID: ").strip()

        self.routing_table[self.my_id] = {'cost': 0, 'next_hop_port': 'LOCAL', 'next_hop_id': self.my_id}
        self.running = True

        for p in ports:
            try:
                ser = create_serial_connection(p, timeout=0.1)
                if ser:
                    self.active_ports[p] = ser
                    self.port_locks[p] = threading.Lock()
                    threading.Thread(target=self._listen_port, args=(p,), daemon=True).start()
                    Logger.info(f"[{p}] 监听中...")
                else:
                    Logger.error(f"[{p}] 打开失败")
            except Exception as e:
                Logger.error(f"[{p}] 异常: {e}")

        # 启动后台任务
        threading.Thread(target=self._task_hello, daemon=True).start()
        threading.Thread(target=self._task_broadcast_dv, daemon=True).start()
        threading.Thread(target=self._task_check_timeout, daemon=True).start()
        
        # 启动可视化上报任务
        threading.Thread(target=self._task_report_viz, daemon=True).start()

        Logger.success("系统就绪。可用命令: ping, tracert, table, send, exit")
        self._input_loop()
    
    def _task_report_viz(self):
        """定期上报状态给可视化后端"""
        import requests 
        while self.running:
            try:
                # 收集日志
                logs = []
                with self.log_lock:
                    logs = self.log_buffer[:]
                    self.log_buffer.clear()
                
                # 收集邻居 (简化)
                nb_list = []
                with self.neighbors_lock:
                    for p, info in self.neighbors.items():
                        nb_list.append(info['id'])

                # 收集路由表 (Snap)
                rt_snap = {}
                with self.rt_lock:
                    for k,v in self.routing_table.items():
                        rt_snap[k] = v.copy()

                payload = {
                    "node_id": self.my_id,
                    "routing_table": rt_snap,
                    "neighbors": nb_list,
                    "logs": logs
                }
                
                resp = requests.post(VIZ_SERVER_URL, json=payload, timeout=0.5)
                
                # 处理指令
                if resp.status_code == 200:
                    data = resp.json()
                    commands = data.get("commands", [])
                    for cmd in commands:
                        self._log_viz(f"Execute Remote Cmd: {cmd}")
                        self._execute_command_string(cmd)

            except Exception as e:
                # Logger.warning(f"Viz Report Failed: {e}") 
                pass
            
            time.sleep(1.0)
    
    def _execute_command_string(self, cmd_str):
        """执行命令字符串 (复用逻辑)"""
        try:
            parts = cmd_str.strip().split()
            if not parts: return
            op = parts[0].lower()
            if op == 'ping' and len(parts) >= 2:
                self.do_ping(parts[1])
            elif op == 'tracert' and len(parts) >= 2:
                self.do_traceroute(parts[1])
            elif op == 'send' and len(parts) >= 3:
                payload = f"{PROTO_TRANSPORT}{SEPARATOR}{' '.join(parts[2:])}"
                self._network_send(parts[1], payload, DEFAULT_TTL)
        except Exception as e:
            self._log_viz(f"Cmd Error: {e}")

    # === 基础通信 ===
    def _close_port(self, port):
        """安全关闭并移除故障串口"""
        if port in self.active_ports:
            try:
                Logger.warning(f"[{port}] 检测到通信故障，正在关闭端口...")
                self.active_ports[port].close()
            except:
                pass
            self.active_ports.pop(port, None)
            self.port_locks.pop(port, None)
            
            # 同时移除该端口的邻居记录
            with self.neighbors_lock:
                self.neighbors.pop(port, None)
                
            self._log_viz(f"Port {port} removed due to error.")

    def _listen_port(self, port):
        # 只要端口在 active_ports 中，就认为是活跃的
        while self.running and port in self.active_ports:
            ser = self.active_ports.get(port)
            if not ser or not ser.is_open:
                break
            try:
                if ser.in_waiting:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line: self._handle_packet(line, port)
                else:
                    time.sleep(0.01)
            except Exception as e:
                # 读错误通常也意味着掉线
                Logger.error(f"Read Error on {port}: {e}")
                self._close_port(port)
                break

    def _send_bytes(self, port, data_str):
        if port not in self.active_ports: return
        
        # 获取锁
        lock = self.port_locks.get(port)
        if not lock: return

        # 尝试发送
        with lock:
            try:
                ser = self.active_ports.get(port)
                if ser and ser.is_open:
                    ser.write((data_str + '\n').encode('utf-8'))
            except Exception as e:
                # 捕获权限错误 (设备拔出) 或 IO 错误
                if "PermissionError" in str(e) or "拒绝访问" in str(e) or "Access is denied" in str(e):
                     Logger.error(f"Send Error on {port} (Device disconnected?): {e}")
                     self._close_port(port)
                else:
                     Logger.error(f"Send Error on {port}: {e}")
                     # 对于其他类型的写错误，可能也需要关闭以防死循环
                     # 这里暂时选择只在明确断开时关闭，或者重试逻辑（暂不实现重试）
                     # 为稳健起见，写失败通常意味着物理层问题，关闭是更安全的选择
                     self._close_port(port)

    # === 核心处理 ===
    def _handle_packet(self, raw, port_src):
        try:
            parts = raw.split(SEPARATOR, 4)
            # 简单起见，先按最少分割，再根据类型细分
            base_parts = raw.split(SEPARATOR)
            p_type = base_parts[0]
            
            if p_type == TYPE_HELLO:
                if len(base_parts) > 1: self._on_recv_hello(base_parts[1], port_src)
            elif p_type == TYPE_DV:
                if len(base_parts) > 2: self._on_recv_dv(base_parts[1], base_parts[2], port_src)
            elif p_type == TYPE_DATA:
                # DATA|Src|Dst|TTL|Payload(Type|Body)
                # Payload 内部再解析
                if len(base_parts) < 5: return
                src, dst, ttl_str, payload = base_parts[1], base_parts[2], base_parts[3], SEPARATOR.join(base_parts[4:])
                self._process_network_packet(src, dst, int(ttl_str), payload)
                
        except Exception as e:
            # Logger.debug(f"Parse Error: {e}")
            pass

    def _process_network_packet(self, src_id, dst_id, ttl, payload):
        """网络层处理：转发、或者是给我的"""
        self._log_viz(f"NET: Pkt {src_id}->{dst_id} TTL={ttl}")
        
        # 1. 如果是发给我的
        if dst_id == self.my_id:
            self._handle_application_payload(src_id, payload)
            return

        # 2. 也是关键点：TTL处理与转发
        # TTL减1
        ttl -= 1
        if ttl <= 0:
            # TTL耗尽，发送 ICMP Time Exceeded 给 Source
            self._log_viz(f"TTL Expired: {src_id}->{dst_id}")
            self._send_icmp_time_exceeded(src_id, payload)
            return

        # 查找路由转发
        with self.rt_lock:
            route = self.routing_table.get(dst_id)
            if route and route['cost'] < 999:
                next_port = route['next_hop_port']
                # 重新打包
                packet = f"{TYPE_DATA}{SEPARATOR}{src_id}{SEPARATOR}{dst_id}{SEPARATOR}{ttl}{SEPARATOR}{payload}"
                self._send_bytes(next_port, packet)
                self._log_viz(f"FWD: To {dst_id} via {next_port}")
            else:
                self._log_viz(f"DROP: No route to {dst_id}")

    def _handle_application_payload(self, src_id, payload):
        """应用层/传输层分发"""
        # Payload 格式: Proto|Content
        try:
            sub_parts = payload.split(SEPARATOR, 1)
            proto = sub_parts[0]
            content = sub_parts[1]
            
            if proto == PROTO_ICMP:
                self._handle_icmp(src_id, content)
            elif proto == PROTO_TRANSPORT:
                Logger.info(f"[ReliableMsg] From {src_id}: {content}")
                self._log_viz(f"APP: Msg from {src_id}: {content}")
        except:
            pass

    # === ICMP 实现 ===
    # Format: Type|Seq|Timestamp
    
    def _send_icmp_echo_request(self, target, seq, ttl=DEFAULT_TTL):
        ts = time.time()
        # Payload: ICMP|ECHO_REQ|Seq|Ts
        payload = f"{PROTO_ICMP}{SEPARATOR}{ICMP_ECHO_REQUEST}{SEPARATOR}{seq}{SEPARATOR}{ts}"
        self._network_send(target, payload, ttl)

    def _send_icmp_echo_reply(self, target, seq, orig_ts):
        # Payload: ICMP|ECHO_REP|Seq|OrigTs|RecvTs
        recv_ts = time.time()
        payload = f"{PROTO_ICMP}{SEPARATOR}{ICMP_ECHO_REPLY}{SEPARATOR}{seq}{SEPARATOR}{orig_ts}{SEPARATOR}{recv_ts}"
        self._network_send(target, payload, DEFAULT_TTL)

    def _send_icmp_time_exceeded(self, target, orig_payload):
        # Payload: ICMP|TIME_EXC|OrigPayload(Partial)
        try:
            parts = orig_payload.split(SEPARATOR)
            if parts[0] == PROTO_ICMP and parts[1] == ICMP_ECHO_REQUEST:
                seq = parts[2]
                payload = f"{PROTO_ICMP}{SEPARATOR}{ICMP_TIME_EXCEEDED}{SEPARATOR}{seq}{SEPARATOR}{self.my_id}"
                self._network_send(target, payload, DEFAULT_TTL)
        except:
            pass

    def _handle_icmp(self, src_id, content):
        parts = content.split(SEPARATOR)
        icmp_type = parts[0]

        if icmp_type == ICMP_ECHO_REQUEST:
            # PONG
            seq = parts[1]
            ts = parts[2]
            self._send_icmp_echo_reply(src_id, seq, ts)

        elif icmp_type == ICMP_ECHO_REPLY:
            # 收到回显
            seq = int(parts[1])
            orig_ts = float(parts[2])
            
            rtt = (time.time() - orig_ts) * 1000 # ms
            # 通知等待线程
            with self.icmp_lock:
                if seq in self.icmp_events:
                    self.icmp_results[seq] = {'type': 'REPLY', 'src': src_id, 'rtt': rtt}
                    self.icmp_events[seq].set()

        elif icmp_type == ICMP_TIME_EXCEEDED:
            # TTL 过期
            seq = int(parts[1])
            router_id = parts[2]
            
            with self.icmp_lock:
                if seq in self.icmp_events:
                    self.icmp_results[seq] = {'type': 'EXPIRED', 'src': router_id}
                    self.icmp_events[seq].set()

    def _network_send(self, dst_id, payload, ttl):
        packet = f"{TYPE_DATA}{SEPARATOR}{self.my_id}{SEPARATOR}{dst_id}{SEPARATOR}{ttl}{SEPARATOR}{payload}"
        
        # 路由查找
        with self.rt_lock:
            route = self.routing_table.get(dst_id)
            if not route or route['cost'] >= 999:
                return False
            port = route['next_hop_port']
            self._send_bytes(port, packet)
            return True

    # === API Ping/Traceroute ===
    
    def do_ping(self, target_id, count=4):
        msg = f"Ping {target_id} with 32 bytes of data:"
        print(f"\n{msg}")
        self._log_viz(msg)
        lost = 0
        rtts = []
        
        for i in range(count):
            seq = self.seq_counter
            self.seq_counter += 1
            
            evt = threading.Event()
            with self.icmp_lock:
                self.icmp_events[seq] = evt
            
            self._send_icmp_echo_request(target_id, seq)
            
            # Wait
            if evt.wait(2.0): # 2s timeout
                res = self.icmp_results.get(seq)
                if res and res['type'] == 'REPLY':
                    rtt = res['rtt']
                    rtts.append(rtt)
                    print(f"来自 {res['src']} 的回复: time={rtt:.1f}ms")
                    self._log_viz(f"Reply from {res['src']}: time={rtt:.1f}ms")
                else:
                    print("请求超时 (异常回复).")
                    lost += 1
            else:
                print("请求超时.")
                self._log_viz("Request timed out.")
                lost += 1
                
            # Cleanup
            with self.icmp_lock:
                self.icmp_events.pop(seq, None)
                self.icmp_results.pop(seq, None)
                
            time.sleep(1)

        stat_msg = f"Ping statistics for {target_id}: Packets: Sent={count}, Lost={lost}"
        print(f"\n{stat_msg}")
        self._log_viz(stat_msg)

        if rtts:
            avg = sum(rtts)/len(rtts)
            print(f"Approximate round trip times in milli-seconds:")
            print(f"    Minimum = {min(rtts):.1f}ms, Maximum = {max(rtts):.1f}ms, Average = {avg:.1f}ms")

    def do_traceroute(self, target_id, max_hops=15):
        print(f"\nTracing route to {target_id} over a maximum of {max_hops} hops:\n")
        
        for ttl in range(1, max_hops + 1):
            seq = self.seq_counter
            self.seq_counter += 1
            
            evt = threading.Event()
            with self.icmp_lock:
                self.icmp_events[seq] = evt
            
            start_t = time.time()
            # 发送 TTL=ttl 的 Echo Request
            self._send_icmp_echo_request(target_id, seq, ttl=ttl)
            
            print(f"{ttl:2d}  ", end='', flush=True)
            
            if evt.wait(3.0):
                rtt = (time.time() - start_t) * 1000
                res = self.icmp_results.get(seq)
                
                if not res:
                    print(f"    *     Error")
                elif res['type'] == 'EXPIRED':
                    print(f"  {rtt:6.1f} ms    {res['src']}")
                elif res['type'] == 'REPLY':
                    # 到达目的地
                    print(f"  {rtt:6.1f} ms    {res['src']}")
                    print("\nTrace complete.")
                    with self.icmp_lock:
                        self.icmp_events.pop(seq, None)
                        self.icmp_results.pop(seq, None)
                    return
            else:
                print(f"    *        Request timed out.")
                
            with self.icmp_lock:
                self.icmp_events.pop(seq, None)
                self.icmp_results.pop(seq, None)

    # === Helper (Hello/DV/Routing) ===
    def _on_recv_hello(self, sender_id, port):
        with self.neighbors_lock:
            self.neighbors[port] = {'id': sender_id, 'last_seen': time.time()}
        with self.rt_lock:
            cur = self.routing_table.get(sender_id)
            if not cur or cur['cost'] > 1:
                self.routing_table[sender_id] = {'cost': 1, 'next_hop_port': port, 'next_hop_id': sender_id}

    def _send_dv_updates(self):
        """发送路由更新（支持毒性逆转）"""
        with self.rt_lock:
            snapshot = {k:v.copy() for k,v in self.routing_table.items()}
        
        current_ports = list(self.active_ports.keys())
        for port_out in current_ports:
            # Poison Reverse Logic
            custom_dv = {}
            for dest, info in snapshot.items():
                cost = info['cost']
                if info.get('next_hop_port') == port_out:
                    cost = 999 
                custom_dv[dest] = {'cost': cost}
            
            pkt = f"{TYPE_DV}{SEPARATOR}{self.my_id}{SEPARATOR}{json.dumps(custom_dv)}"
            self._send_bytes(port_out, pkt)

    def _on_recv_dv(self, sender_id, dv_json, port):
        """优化的 DV 处理 (Triggered Updates + Poison Reverse Support)"""
        try: neighbors_dv = json.loads(dv_json)
        except: return
        updated = False
        with self.rt_lock:
            # 1. Update from neighbor
            for dst, info in neighbors_dv.items():
                if dst == self.my_id: continue
                cost_neighbor = info.get('cost', 999)
                new_cost = 1 + cost_neighbor
                if new_cost > 999: new_cost = 999
                
                cur = self.routing_table.get(dst)
                
                if not cur:
                    if new_cost < 999:
                        self.routing_table[dst] = {'cost': new_cost, 'next_hop_port': port, 'next_hop_id': sender_id}
                        updated = True
                
                elif cur['next_hop_id'] == sender_id:
                    if cur['cost'] != new_cost:
                        cur['cost'] = new_cost
                        updated = True
                
                elif new_cost < cur['cost']:
                    self.routing_table[dst] = {'cost': new_cost, 'next_hop_port': port, 'next_hop_id': sender_id}
                    updated = True

            # 2. Poison Logic for missing routes from next hop
            for dst in list(self.routing_table.keys()):
                if dst == self.my_id: continue
                route = self.routing_table[dst]
                if route['next_hop_id'] == sender_id and dst not in neighbors_dv:
                    if route['cost'] != 999:
                        route['cost'] = 999
                        updated = True
        
        if updated:
            self._send_dv_updates()

    def _task_hello(self):
        while self.running:
            for p in list(self.active_ports.keys()): self._send_bytes(p, f"{TYPE_HELLO}{SEPARATOR}{self.my_id}")
            time.sleep(HELLO_INTERVAL)

    def _task_broadcast_dv(self):
        while self.running:
            self._send_dv_updates()
            time.sleep(DV_INTERVAL)

    def _task_check_timeout(self):
        while self.running:
            now = time.time()
            drops = []
            with self.neighbors_lock:
                for k,v in self.neighbors.items():
                    if now - v['last_seen'] > NEIGHBOR_TIMEOUT: drops.append(k)
                for k in drops: del self.neighbors[k]
            if drops:
                with self.rt_lock:
                    for d,i in self.routing_table.items():
                        if i['next_hop_port'] in drops and d!=self.my_id: i['cost']=999
            time.sleep(1)

    def _print_table(self):
        print("\n" + "="*60)
        print(f"路由表 - MyID: {self.my_id}")
        print("="*60)
        print(f"{'Target':<10} {'Cost':<10} {'NextHop':<10} {'Interface':<15}")
        print("-"*60)
        with self.rt_lock:
             # 按Target排序
            for dest in sorted(self.routing_table.keys()):
                info = self.routing_table[dest]
                cost_str = str(info['cost']) if info['cost'] < 999 else "∞"
                next_hop = info['next_hop_id'] if info.get('next_hop_id') else "-"
                port = info['next_hop_port']
                print(f"{dest:<10} {cost_str:<10} {next_hop:<10} {port:<15}")
        print("="*60 + "\n")

    def _input_loop(self):
        while self.running:
            try:
                cmd = input("> ").strip().split()
                if not cmd: continue
                op = cmd[0].lower()
                if op == 'ping':
                    if len(cmd)<2: print("Usage: ping <ID>")
                    else: self.do_ping(cmd[1])
                elif op == 'tracert':
                    if len(cmd)<2: print("Usage: tracert <ID>")
                    else: self.do_traceroute(cmd[1])
                elif op == 'table':
                    self._print_table()
                elif op == 'send': # 简单的不可靠发送示例
                    if len(cmd)<3: print("Usage: send <ID> <Msg>")
                    else:
                        payload = f"{PROTO_TRANSPORT}{SEPARATOR}{' '.join(cmd[2:])}"
                        self._network_send(cmd[1], payload, DEFAULT_TTL)
                elif op == 'exit':
                    self.running=False
                    sys.exit()
            except KeyboardInterrupt:
                self.running=False
            except Exception as e:
                Logger.error(f"Err: {e}")

if __name__ == "__main__":
    NetworkNode().start()
