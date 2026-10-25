"""Exercise the actual C++ file bridge and Python MCP server in subprocesses."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from client import Debugger

ROOT = Path(__file__).resolve().parents[2]

class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name) / 'fake-core'
        subprocess.run(['g++', '-std=c++11', str(ROOT/'mcp/tests/fake_core.cpp'), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = subprocess.Popen([str(self.binary), self.tmp.name])
        self.client = Debugger(self.tmp.name)
        for _ in range(200):
            if (Path(self.tmp.name)/'emulator.lock').exists(): break
            time.sleep(.01)
        self.assertTrue(self.client.call('status')['paused'])

    def tearDown(self):
        self.core.terminate()
        self.core.wait(timeout=5)
        self.tmp.cleanup()

    def wait_paused(self):
        for _ in range(100):
            status = self.client.call('status')
            if status['paused']: return status
            time.sleep(.01)
        self.fail('Core did not pause')

    def test_step_memory_and_breakpoint(self):
        start = self.client.call('status')['ticks']
        self.client.call('step 3')
        status = self.wait_paused()
        self.assertEqual(status['ticks']-start, 3)
        self.assertEqual(status['reason'], 'budget')
        self.assertEqual(self.client.call('read_memory 255 3')['hex'], 'ff0001')
        self.assertEqual(self.client.call('registers')['AX'], 123)
        self.client.call('breakpoint write 34336 34336')
        self.client.call('resume 10000')
        status = self.wait_paused()
        self.assertEqual(status['hit'], {'kind':'write','address':34336,'value':42})
        self.assertEqual(status['reason'], 'breakpoint')
        previous = status['ticks']
        self.client.call('resume 100')
        self.assertEqual(self.wait_paused()['ticks'], previous+1)
        self.client.call('clear_breakpoints')
        self.client.call('step 2')
        self.assertEqual(self.wait_paused()['ticks'], previous+3)
        with self.assertRaises(RuntimeError): self.client.call('read_memory 1048575 2')
        with self.assertRaises(RuntimeError): self.client.call('step 0')

    def test_mcp_stdio(self):
        env = dict(os.environ, MEDNAFEN_MCP_DIR=self.tmp.name)
        requests = [
            {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26'}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'},
            {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'debug_read_memory','arguments':{'address':255,'length':3}}},
            {'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'debug_step','arguments':{'count':True}}},
        ]
        completed = subprocess.run([sys.executable,str(ROOT/'mcp/server.py')], input=''.join(json.dumps(r)+'\n' for r in requests), text=True, capture_output=True, env=env, check=True)
        replies = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual(len(replies),4)
        self.assertEqual(replies[0]['result']['protocolVersion'],'2025-03-26')
        self.assertEqual(len(replies[1]['result']['tools']),9)
        self.assertEqual(json.loads(replies[2]['result']['content'][0]['text'])['hex'],'ff0001')
        self.assertTrue(replies[3]['result']['isError'])

    def test_pause_lease_expires(self):
        time.sleep(31)
        status = self.client.call("status")
        self.assertFalse(status["paused"])
        self.assertEqual(status["reason"], "lease_expired")

    def test_disconnected_emulator(self):
        self.core.terminate(); self.core.wait(timeout=5)
        with self.assertRaisesRegex(RuntimeError, 'No emulator'):
            self.client.call('status')

if __name__ == '__main__': unittest.main()
