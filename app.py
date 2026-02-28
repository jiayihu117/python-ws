#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import socket
import struct
import base64
import asyncio
import aiohttp
import logging
import ipaddress
from aiohttp import web

# === 环境变量 ===
UUID = os.environ.get('UUID', '7bd180e8-1142-4387-93f5-03e8d750a896')
DOMAIN = os.environ.get('DOMAIN', 'dataopen.wasmer.app')
SUB_PATH = os.environ.get('SUB_PATH', 'sub')
NAME = os.environ.get('NAME', 'MyNode')
WSPATH = os.environ.get('WSPATH', UUID[:8])
PORT = int(os.environ.get('PORT') or 8080) # 强制监听 8080

CurrentDomain = DOMAIN
CurrentPort = 443
Tls = 'tls'
ISP = 'Cloud_Node'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

async def resolve_host(host: str) -> str:
    try:
        ipaddress.ip_address(host)
        return host
    except:
        pass
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://dns.google/resolve?name={host}&type=A', timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('Answer'):
                        for ans in data['Answer']:
                            if ans.get('type') == 1: return ans.get('data')
    except: pass
    return host

class ProxyHandler:
    def __init__(self, uuid: str):
        self.uuid = uuid
        self.uuid_bytes = bytes.fromhex(uuid.replace('-', ''))
        
    async def handle_vless(self, websocket, first_msg: bytes) -> bool:
        try:
            if len(first_msg) < 18 or first_msg[0] != 0: return False
            if first_msg[1:17] != self.uuid_bytes: return False
            i = first_msg[17] + 19
            if i + 3 > len(first_msg): return False
            port = struct.unpack('!H', first_msg[i:i+2])[0]
            i += 2
            atyp = first_msg[i]
            i += 1
            host = ''
            if atyp == 1:
                host = '.'.join(str(b) for b in first_msg[i:i+4])
                i += 4
            elif atyp == 2:
                host_len = first_msg[i]
                i += 1
                host = first_msg[i:i+host_len].decode()
                i += host_len
            elif atyp == 3:
                host = ':'.join(f'{(first_msg[j] << 8) + first_msg[j+1]:04x}' for j in range(i, i+16, 2))
                i += 16
            else: return False

            await websocket.send_bytes(bytes([0, 0]))
            resolved_host = await resolve_host(host)

            try:
                reader, writer = await asyncio.open_connection(resolved_host, port)
                if i < len(first_msg):
                    writer.write(first_msg[i:])
                    await writer.drain()

                async def forward_ws_to_tcp():
                    try:
                        async for msg in websocket:
                            if msg.type == aiohttp.WSMsgType.BINARY:
                                writer.write(msg.data)
                                await writer.drain()
                    except: pass
                    finally: writer.close()

                async def forward_tcp_to_ws():
                    try:
                        while True:
                            data = await reader.read(4096)
                            if not data: break
                            await websocket.send_bytes(data)
                    except: pass

                await asyncio.gather(forward_ws_to_tcp(), forward_tcp_to_ws())
            except: pass
            return True
        except: return False

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    if f'/{WSPATH}' not in request.path:
        await ws.close()
        return ws
    proxy = ProxyHandler(UUID)
    try:
        first_msg = await asyncio.wait_for(ws.receive(), timeout=5)
        if first_msg.type == aiohttp.WSMsgType.BINARY:
            await proxy.handle_vless(ws, first_msg.data)
    except: pass
    return ws

async def http_handler(request):
    if request.path == '/':
        # 直接把网页写死在这里，不需要 HTML 文件了！
        html = "<html><body style='text-align:center;padding:50px;font-family:sans-serif;'><h1>Protect Our Earth</h1><p>Node backend is running successfully!</p></body></html>"
        return web.Response(text=html, content_type='text/html')
    
    elif request.path == f'/{SUB_PATH}':
        # 仅保留核心 VLESS 节点生成
        vless_url = f"vless://{UUID}@{DOMAIN}:443?encryption=none&security=tls&sni={DOMAIN}&fp=chrome&type=ws&host={DOMAIN}&path=%2F{WSPATH}#{NAME}"
        base64_content = base64.b64encode(vless_url.encode()).decode()
        return web.Response(text=base64_content + '\n', content_type='text/plain')
    
    return web.Response(status=404, text='Not Found\n')

async def main():
    app = web.Application()
    app.router.add_get('/', http_handler)
    app.router.add_get(f'/{SUB_PATH}', http_handler)
    app.router.add_get(f'/{WSPATH}', websocket_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"✅ Pure Server is running on port {PORT}")
    
    try:
        await asyncio.Future()
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
