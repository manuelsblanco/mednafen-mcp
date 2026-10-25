#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""MCP stdio server for the local WonderSwan debugger. Standard library only."""
import json
import sys
from client import Debugger

TOOLS = [
    ('debug_status', 'Query paused/running state, physical PC and stop reason. Pauses expire after 30 seconds without a request.', {}),
    ('debug_pause', 'Pause at the next instruction boundary.', {}),
    ('debug_continue', 'Resume for at most budget instructions or until a breakpoint. Returns immediately; query status for the stop.', {'budget': (100000000, 10000000)}),
    ('debug_step', 'Execute count instructions. Returns immediately; query status until paused.', {'count': (1000000, 1)}),
    ('debug_registers', 'Read V30 registers and ROM bank selectors. Requires paused state.', {}),
    ('debug_read_memory', 'Read mapped 20-bit physical memory as hexadecimal. Requires paused state.', {'address': (1048575, None), 'length': (65536, 256)}),
    ('debug_disassemble', 'Disassemble at a 16-bit IP in the current CS segment. Requires paused state.', {'ip': (65535, None), 'count': (64, 16)}),
    ('debug_clear_breakpoints', 'Clear only MCP-owned breakpoints.', {}),
]


def definitions():
    result = []
    for name, description, args in TOOLS:
        props, required = {}, []
        for key, (maximum, default) in args.items():
            props[key] = {'type': 'integer', 'minimum': 0 if key in ('ip', 'address') else 1, 'maximum': maximum}
            if default is None:
                required.append(key)
            else:
                props[key]['default'] = default
        result.append({'name': name, 'description': description,
                       'inputSchema': {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False}})
    result.append({'name': 'debug_add_breakpoint', 'description': 'Stop BEFORE an instruction that executes at PC or accesses a physical memory range. Read hooks include instruction fetches. Returns the first matching access, not a committed write.',
                   'inputSchema': {'type': 'object', 'properties': {'kind': {'type': 'string', 'enum': ['pc', 'read', 'write']}, 'start': {'type': 'integer', 'minimum': 0, 'maximum': 1048575}, 'end': {'type': 'integer', 'minimum': 0, 'maximum': 1048575}}, 'required': ['kind', 'start', 'end'], 'additionalProperties': False}})
    return result


def invoke(name, args):
    schema = next((t['inputSchema'] for t in definitions() if t['name'] == name), None)
    if schema is None:
        raise ValueError('Unknown tool')
    if not isinstance(args, dict) or set(args) - set(schema['properties']) or any(k not in args for k in schema['required']):
        raise ValueError('Invalid tool arguments')
    values = {}
    for key, spec in schema['properties'].items():
        value = args.get(key, spec.get('default'))
        if spec['type'] == 'integer':
            if type(value) is not int or not spec['minimum'] <= value <= spec['maximum']:
                raise ValueError('Invalid numeric argument: ' + key)
        elif value not in spec['enum']:
            raise ValueError('Invalid enum: ' + key)
        values[key] = value
    commands = {'debug_status': 'status', 'debug_pause': 'pause', 'debug_registers': 'registers', 'debug_clear_breakpoints': 'clear_breakpoints'}
    if name in commands:
        command = commands[name]
    elif name == 'debug_continue':
        command = 'resume %d' % values['budget']
    elif name == 'debug_step':
        command = 'step %d' % values['count']
    elif name == 'debug_read_memory':
        command = 'read_memory {address} {length}'.format(**values)
    elif name == 'debug_disassemble':
        command = 'disassemble {ip} {count}'.format(**values)
    else:
        if values['end'] < values['start']:
            raise ValueError('Reversed breakpoint range')
        command = 'breakpoint {kind} {start} {end}'.format(**values)
    return Debugger().call(command)


def dispatch(message):
    method, params = message.get('method'), message.get('params', {})
    if method == 'initialize':
        requested = params.get('protocolVersion')
        version = requested if requested in ('2024-11-05', '2025-03-26', '2025-06-18') else '2025-03-26'
        return {'protocolVersion': version, 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'mednafen-mcp', 'version': '0.1.0'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': definitions()}
    if method == 'tools/call':
        try:
            value = invoke(params['name'], params.get('arguments', {}))
            return {'content': [{'type': 'text', 'text': json.dumps(value)}]}
        except (KeyError, ValueError, RuntimeError, OSError) as exc:
            return {'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}
    raise LookupError('Method not found')


def handle(message):
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid JSON-RPC request'}}
    if 'id' not in message:
        return None
    if not isinstance(message.get('params', {}), dict):
        return {'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': -32602, 'message': 'Object params required'}}
    try:
        return {'jsonrpc': '2.0', 'id': message['id'], 'result': dispatch(message)}
    except (ValueError, LookupError, KeyError, TypeError) as exc:
        code = -32601 if isinstance(exc, LookupError) else -32602
        return {'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': code, 'message': str(exc)}}


def main():
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if isinstance(message, list):
                if not message:
                    reply = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Empty batch'}}
                else:
                    reply = [result for item in message if (result := handle(item)) is not None]
                    if not reply:
                        continue
            else:
                reply = handle(message)
                if reply is None:
                    continue
        except json.JSONDecodeError as exc:
            reply = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': str(exc)}}
        print(json.dumps(reply), flush=True)


if __name__ == '__main__':
    main()
