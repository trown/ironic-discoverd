# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import functools
import time

import eventlet
from ironicclient import exceptions
import mock
from oslo_config import cfg

from ironic_discoverd import firewall
from ironic_discoverd import node_cache
from ironic_discoverd.plugins import base as plugins_base
from ironic_discoverd.plugins import example as example_plugin
from ironic_discoverd.plugins import standard as std_plugins
from ironic_discoverd import process
from ironic_discoverd.test import base as test_base
from ironic_discoverd import utils

CONF = cfg.CONF


class BaseTest(test_base.NodeTest):
    def setUp(self):
        super(BaseTest, self).setUp()
        self.started_at = time.time()
        self.all_macs = self.macs + ['DE:AD:BE:EF:DE:AD']
        self.pxe_mac = self.macs[1]
        self.data = {
            'ipmi_address': self.bmc_address,
            'cpus': 2,
            'cpu_arch': 'x86_64',
            'memory_mb': 1024,
            'local_gb': 20,
            'interfaces': {
                'em1': {'mac': self.macs[0], 'ip': '1.2.0.1'},
                'em2': {'mac': self.macs[1], 'ip': '1.2.0.2'},
                'em3': {'mac': self.all_macs[2]},
            },
            'boot_interface': '01-' + self.pxe_mac.replace(':', '-'),
        }
        self.all_ports = [
            mock.Mock(uuid='port_uuid%d' % i, address=mac)
            for i, mac in enumerate(self.macs)
        ]
        self.ports = [self.all_ports[1]]


@mock.patch.object(process, '_process_node', autospec=True)
@mock.patch.object(node_cache, 'find_node', autospec=True)
@mock.patch.object(utils, 'get_client', autospec=True)
class TestProcess(BaseTest):
    def setUp(self):
        super(TestProcess, self).setUp()
        self.fake_result_json = 'node json'

    def prepare_mocks(func):
        @functools.wraps(func)
        def wrapper(self, client_mock, pop_mock, process_mock, *args, **kw):
            cli = client_mock.return_value
            pop_mock.return_value = node_cache.NodeInfo(
                uuid=self.node.uuid,
                started_at=self.started_at)
            pop_mock.return_value.finished = mock.Mock()
            cli.node.get.return_value = self.node
            process_mock.return_value = self.fake_result_json

            return func(self, cli, pop_mock, process_mock, *args, **kw)

        return wrapper

    @prepare_mocks
    def test_ok(self, cli, pop_mock, process_mock):
        res = process.process(self.data)

        self.assertEqual(self.fake_result_json, res)

        # Only boot interface is added by default
        self.assertEqual(['em2'], sorted(self.data['interfaces']))
        self.assertEqual(['em1', 'em2', 'em3'],
                         sorted(self.data['all_interfaces']))
        self.assertEqual([self.pxe_mac], self.data['macs'])

        pop_mock.assert_called_once_with(bmc_address=self.bmc_address,
                                         mac=self.data['macs'])
        cli.node.get.assert_called_once_with(self.uuid)
        process_mock.assert_called_once_with(cli, cli.node.get.return_value,
                                             self.data, pop_mock.return_value)

    @prepare_mocks
    def test_boot_interface_as_mac(self, cli, pop_mock, process_mock):
        self.data['boot_interface'] = self.pxe_mac

        res = process.process(self.data)

        self.assertEqual(self.fake_result_json, res)

        # Only boot interface is added by default
        self.assertEqual(['em2'], sorted(self.data['interfaces']))
        self.assertEqual(['em1', 'em2', 'em3'],
                         sorted(self.data['all_interfaces']))
        self.assertEqual([self.pxe_mac], self.data['macs'])

        pop_mock.assert_called_once_with(bmc_address=self.bmc_address,
                                         mac=self.data['macs'])
        cli.node.get.assert_called_once_with(self.uuid)
        process_mock.assert_called_once_with(cli, cli.node.get.return_value,
                                             self.data, pop_mock.return_value)

    @prepare_mocks
    def test_no_boot_interface(self, cli, pop_mock, process_mock):
        del self.data['boot_interface']

        res = process.process(self.data)

        self.assertEqual(self.fake_result_json, res)

        # By default interfaces w/o IP are dropped
        self.assertEqual(['em1', 'em2'], sorted(self.data['interfaces']))
        self.assertEqual(['em1', 'em2', 'em3'],
                         sorted(self.data['all_interfaces']))
        self.assertEqual(self.macs, sorted(self.data['macs']))

        pop_mock.assert_called_once_with(bmc_address=self.bmc_address,
                                         mac=self.data['macs'])
        cli.node.get.assert_called_once_with(self.uuid)
        process_mock.assert_called_once_with(cli, cli.node.get.return_value,
                                             self.data, pop_mock.return_value)

    @prepare_mocks
    def test_add_ports_active(self, cli, pop_mock, process_mock):
        CONF.set_override('add_ports', 'active', 'discoverd')

        res = process.process(self.data)

        self.assertEqual(self.fake_result_json, res)

        self.assertEqual(['em1', 'em2'],
                         sorted(self.data['interfaces']))
        self.assertEqual(['em1', 'em2', 'em3'],
                         sorted(self.data['all_interfaces']))
        self.assertEqual(self.macs, sorted(self.data['macs']))

        pop_mock.assert_called_once_with(bmc_address=self.bmc_address,
                                         mac=self.data['macs'])
        cli.node.get.assert_called_once_with(self.uuid)
        process_mock.assert_called_once_with(cli, cli.node.get.return_value,
                                             self.data, pop_mock.return_value)

    @prepare_mocks
    def test_add_ports_all(self, cli, pop_mock, process_mock):
        CONF.set_override('add_ports', 'all', 'discoverd')

        res = process.process(self.data)

        self.assertEqual(self.fake_result_json, res)

        # By default interfaces w/o IP are dropped
        self.assertEqual(['em1', 'em2', 'em3'],
                         sorted(self.data['interfaces']))
        self.assertEqual(['em1', 'em2', 'em3'],
                         sorted(self.data['all_interfaces']))
        self.assertEqual(self.all_macs, sorted(self.data['macs']))

        pop_mock.assert_called_once_with(bmc_address=self.bmc_address,
                                         mac=self.data['macs'])
        cli.node.get.assert_called_once_with(self.uuid)
        process_mock.assert_called_once_with(cli, cli.node.get.return_value,
                                             self.data, pop_mock.return_value)

    @prepare_mocks
    def test_no_ipmi(self, cli, pop_mock, process_mock):
        del self.data['ipmi_address']
        process.process(self.data)

        pop_mock.assert_called_once_with(bmc_address=None,
                                         mac=self.data['macs'])
        cli.node.get.assert_called_once_with(self.uuid)
        process_mock.assert_called_once_with(cli, cli.node.get.return_value,
                                             self.data, pop_mock.return_value)

    @prepare_mocks
    def test_no_interfaces(self, cli, pop_mock, process_mock):
        del self.data['interfaces']
        self.assertRaises(utils.Error, process.process, self.data)

    @prepare_mocks
    def test_ports_for_inactive(self, cli, pop_mock, process_mock):
        CONF.set_override('ports_for_inactive_interfaces', True, 'discoverd')
        del self.data['boot_interface']

        process.process(self.data)

        self.assertEqual(['em1', 'em2', 'em3'],
                         sorted(self.data['interfaces']))
        self.assertEqual(self.all_macs, sorted(self.data['macs']))

        pop_mock.assert_called_once_with(bmc_address=self.bmc_address,
                                         mac=self.data['macs'])
        cli.node.get.assert_called_once_with(self.uuid)
        process_mock.assert_called_once_with(cli, cli.node.get.return_value,
                                             self.data, pop_mock.return_value)

    @prepare_mocks
    def test_invalid_interfaces_all(self, cli, pop_mock, process_mock):
        self.data['interfaces'] = {
            'br1': {'mac': 'broken', 'ip': '1.2.0.1'},
            'br2': {'mac': '', 'ip': '1.2.0.2'},
            'br3': {},
        }

        self.assertRaises(utils.Error, process.process, self.data)

    @prepare_mocks
    def test_invalid_interfaces(self, cli, pop_mock, process_mock):
        self.data['interfaces'] = {
            'br1': {'mac': 'broken', 'ip': '1.2.0.1'},
            'br2': {'mac': '', 'ip': '1.2.0.2'},
            'br3': {},
            'em1': {'mac': self.macs[1], 'ip': '1.2.3.4'},
        }

        process.process(self.data)

        self.assertEqual(['em1'], list(self.data['interfaces']))
        self.assertEqual([self.macs[1]], self.data['macs'])

        pop_mock.assert_called_once_with(bmc_address=self.bmc_address,
                                         mac=[self.macs[1]])
        cli.node.get.assert_called_once_with(self.uuid)
        process_mock.assert_called_once_with(cli, cli.node.get.return_value,
                                             self.data, pop_mock.return_value)

    @prepare_mocks
    def test_missing_required(self, cli, pop_mock, process_mock):
        del self.data['cpus']

        self.assertRaisesRegexp(utils.Error,
                                'missing',
                                process.process, self.data)
        self.assertFalse(process_mock.called)

    @prepare_mocks
    def test_not_found_in_cache(self, cli, pop_mock, process_mock):
        pop_mock.side_effect = utils.Error('not found')

        self.assertRaisesRegexp(utils.Error,
                                'not found',
                                process.process, self.data)
        self.assertFalse(cli.node.get.called)
        self.assertFalse(process_mock.called)

    @prepare_mocks
    def test_not_found_in_ironic(self, cli, pop_mock, process_mock):
        cli.node.get.side_effect = exceptions.NotFound()

        self.assertRaisesRegexp(utils.Error,
                                'not found',
                                process.process, self.data)
        cli.node.get.assert_called_once_with(self.uuid)
        self.assertFalse(process_mock.called)
        pop_mock.return_value.finished.assert_called_once_with(error=mock.ANY)

    @prepare_mocks
    def test_expected_exception(self, cli, pop_mock, process_mock):
        process_mock.side_effect = utils.Error('boom')

        self.assertRaisesRegexp(utils.Error, 'boom',
                                process.process, self.data)

        pop_mock.return_value.finished.assert_called_once_with(error='boom')

    @prepare_mocks
    def test_unexpected_exception(self, cli, pop_mock, process_mock):
        process_mock.side_effect = RuntimeError('boom')

        self.assertRaisesRegexp(utils.Error, 'Unexpected exception',
                                process.process, self.data)

        pop_mock.return_value.finished.assert_called_once_with(
            error='Unexpected exception during processing')

    @prepare_mocks
    def test_hook_unexpected_exceptions(self, cli, pop_mock, process_mock):
        for ext in plugins_base.processing_hooks_manager():
            patcher = mock.patch.object(ext.obj, 'before_processing',
                                        side_effect=RuntimeError('boom'))
            patcher.start()
            self.addCleanup(lambda p=patcher: p.stop())

        self.assertRaisesRegexp(utils.Error, 'Unexpected exception',
                                process.process, self.data)

        pop_mock.return_value.finished.assert_called_once_with(
            error='Data pre-processing failed')

    @prepare_mocks
    def test_hook_unexpected_exceptions_no_node(self, cli, pop_mock,
                                                process_mock):
        # Check that error from hooks is raised, not "not found"
        pop_mock.side_effect = utils.Error('not found')
        for ext in plugins_base.processing_hooks_manager():
            patcher = mock.patch.object(ext.obj, 'before_processing',
                                        side_effect=RuntimeError('boom'))
            patcher.start()
            self.addCleanup(lambda p=patcher: p.stop())

        self.assertRaisesRegexp(utils.Error, 'Unexpected exception',
                                process.process, self.data)

        self.assertFalse(pop_mock.return_value.finished.called)


@mock.patch.object(eventlet.greenthread, 'spawn_n',
                   lambda f, *a: f(*a) and None)
@mock.patch.object(eventlet.greenthread, 'sleep', lambda _: None)
@mock.patch.object(example_plugin.ExampleProcessingHook, 'before_update')
@mock.patch.object(firewall, 'update_filters', autospec=True)
class TestProcessNode(BaseTest):
    def setUp(self):
        super(TestProcessNode, self).setUp()
        CONF.set_override('processing_hooks',
                          'ramdisk_error,scheduler,validate_interfaces,'
                          'example',
                          'discoverd')
        self.validate_attempts = 5
        self.data['macs'] = self.macs  # validate_interfaces hook
        self.data['all_interfaces'] = self.data['interfaces']
        self.ports = self.all_ports
        self.cached_node = node_cache.NodeInfo(uuid=self.uuid,
                                               started_at=self.started_at)
        self.patch_before = [
            {'path': '/properties/cpus', 'value': '2', 'op': 'add'},
            {'path': '/properties/cpu_arch', 'value': 'x86_64', 'op': 'add'},
            {'path': '/properties/memory_mb', 'value': '1024', 'op': 'add'},
            {'path': '/properties/local_gb', 'value': '20', 'op': 'add'}
        ]  # scheduler hook
        self.patch_after = [
            {'op': 'add', 'path': '/extra/newly_discovered', 'value': 'true'},
            {'op': 'remove', 'path': '/extra/on_discovery'},
        ]
        self.new_creds = ('user', 'password')
        self.patch_credentials = [
            {'op': 'add', 'path': '/driver_info/ipmi_username',
             'value': self.new_creds[0]},
            {'op': 'add', 'path': '/driver_info/ipmi_password',
             'value': self.new_creds[1]},
        ]

        self.cli = mock.Mock()
        self.cli.node.get_boot_device.side_effect = (
            [RuntimeError()] * self.validate_attempts + [None])
        self.cli.port.create.side_effect = self.ports
        self.cli.node.update.return_value = self.node

    def call(self):
        return process._process_node(self.cli, self.node, self.data,
                                     self.cached_node)

    def test_wrong_provision_state(self, filters_mock, post_hook_mock):
        self.node.provision_state = 'active'
        self.assertRaises(utils.Error, self.call)
        self.assertFalse(post_hook_mock.called)

    @mock.patch.object(node_cache.NodeInfo, 'finished', autospec=True)
    def test_ok(self, finished_mock, filters_mock, post_hook_mock):
        self.call()

        self.cli.port.create.assert_any_call(node_uuid=self.uuid,
                                             address=self.macs[0])
        self.cli.port.create.assert_any_call(node_uuid=self.uuid,
                                             address=self.macs[1])
        self.cli.node.update.assert_any_call(self.uuid, self.patch_before)
        self.cli.node.update.assert_any_call(self.uuid, self.patch_after)
        self.cli.node.set_power_state.assert_called_once_with(self.uuid, 'off')
        self.assertFalse(self.cli.node.validate.called)

        post_hook_mock.assert_called_once_with(self.node, mock.ANY,
                                               self.data)
        # List is built from a dict - order is undefined
        self.assertEqual(self.ports, sorted(post_hook_mock.call_args[0][1],
                                            key=lambda p: p.address))
        finished_mock.assert_called_once_with(mock.ANY)

    def test_overwrite_disabled(self, filters_mock, post_hook_mock):
        CONF.set_override('overwrite_existing', False, 'discoverd')
        patch = [
            {'op': 'add', 'path': '/properties/cpus', 'value': '2'},
            {'op': 'add', 'path': '/properties/memory_mb', 'value': '1024'},
        ]

        self.call()

        self.cli.node.update.assert_any_call(self.uuid, patch)
        self.cli.node.update.assert_any_call(self.uuid, self.patch_after)

    def test_update_retry_on_conflict(self, filters_mock, post_hook_mock):
        self.cli.node.update.side_effect = [exceptions.Conflict, self.node,
                                            exceptions.Conflict, self.node]

        self.call()

        self.cli.port.create.assert_any_call(node_uuid=self.uuid,
                                             address=self.macs[0])
        self.cli.port.create.assert_any_call(node_uuid=self.uuid,
                                             address=self.macs[1])
        self.cli.node.update.assert_any_call(self.uuid, self.patch_before)
        self.cli.node.update.assert_any_call(self.uuid, self.patch_after)
        self.assertEqual(4, self.cli.node.update.call_count)
        self.cli.node.set_power_state.assert_called_once_with(self.uuid, 'off')

    def test_power_off_retry_on_conflict(self, filters_mock, post_hook_mock):
        self.cli.node.set_power_state.side_effect = [exceptions.Conflict, None]

        self.call()

        self.cli.port.create.assert_any_call(node_uuid=self.uuid,
                                             address=self.macs[0])
        self.cli.port.create.assert_any_call(node_uuid=self.uuid,
                                             address=self.macs[1])
        self.cli.node.update.assert_any_call(self.uuid, self.patch_before)
        self.cli.node.update.assert_any_call(self.uuid, self.patch_after)
        self.cli.node.set_power_state.assert_called_with(self.uuid, 'off')
        self.assertEqual(2, self.cli.node.set_power_state.call_count)

    def test_port_failed(self, filters_mock, post_hook_mock):
        self.ports[0] = exceptions.Conflict()

        self.call()

        self.cli.port.create.assert_any_call(node_uuid=self.uuid,
                                             address=self.macs[0])
        self.cli.port.create.assert_any_call(node_uuid=self.uuid,
                                             address=self.macs[1])
        self.cli.node.update.assert_any_call(self.uuid, self.patch_before)
        self.cli.node.update.assert_any_call(self.uuid, self.patch_after)

        post_hook_mock.assert_called_once_with(self.node, self.ports[1:],
                                               self.data)

    def test_hook_patches(self, filters_mock, post_hook_mock):
        node_patches = ['node patch1', 'node patch2']
        port_patch = ['port patch']
        post_hook_mock.return_value = (node_patches,
                                       {self.macs[1]: port_patch})

        self.call()

        self.cli.node.update.assert_any_call(self.uuid,
                                             self.patch_before + node_patches)
        self.cli.node.update.assert_any_call(self.uuid, self.patch_after)
        self.cli.port.update.assert_called_once_with(self.ports[1].uuid,
                                                     port_patch)

    def test_set_ipmi_credentials(self, filters_mock, post_hook_mock):
        self.cached_node.set_option('new_ipmi_credentials', self.new_creds)

        self.call()

        self.cli.node.update.assert_any_call(self.uuid, self.patch_credentials)
        self.cli.node.set_power_state.assert_called_once_with(self.uuid, 'off')
        self.cli.node.get_boot_device.assert_called_with(self.uuid)
        self.assertEqual(self.validate_attempts + 1,
                         self.cli.node.get_boot_device.call_count)

    def test_set_ipmi_credentials_no_address(self, filters_mock,
                                             post_hook_mock):
        self.cached_node.set_option('new_ipmi_credentials', self.new_creds)
        del self.node.driver_info['ipmi_address']
        self.patch_credentials.append({'op': 'add',
                                       'path': '/driver_info/ipmi_address',
                                       'value': self.bmc_address})

        self.call()

        self.cli.node.update.assert_any_call(self.uuid, self.patch_credentials)
        self.cli.node.set_power_state.assert_called_once_with(self.uuid, 'off')
        self.cli.node.get_boot_device.assert_called_with(self.uuid)
        self.assertEqual(self.validate_attempts + 1,
                         self.cli.node.get_boot_device.call_count)

    @mock.patch.object(node_cache.NodeInfo, 'finished', autospec=True)
    def test_set_ipmi_credentials_timeout(self, finished_mock,
                                          filters_mock, post_hook_mock):
        self.cached_node.set_option('new_ipmi_credentials', self.new_creds)
        self.cli.node.get_boot_device.side_effect = RuntimeError('boom')

        self.assertRaisesRegexp(utils.Error, 'Failed to validate',
                                self.call)

        self.cli.node.update.assert_any_call(self.uuid, self.patch_before)
        self.cli.node.update.assert_any_call(self.uuid, self.patch_credentials)
        self.assertEqual(2, self.cli.node.update.call_count)
        self.assertEqual(process._CREDENTIALS_WAIT_RETRIES,
                         self.cli.node.get_boot_device.call_count)
        self.assertFalse(self.cli.node.set_power_state.called)
        finished_mock.assert_called_once_with(
            mock.ANY,
            error='Failed to validate updated IPMI credentials for node %s, '
            'node might require maintenance' % self.uuid)

    @mock.patch.object(node_cache.NodeInfo, 'finished', autospec=True)
    def test_power_off_failed(self, finished_mock, filters_mock,
                              post_hook_mock):
        self.cli.node.set_power_state.side_effect = RuntimeError('boom')

        self.assertRaisesRegexp(utils.Error, 'Failed to power off',
                                self.call)

        self.cli.node.set_power_state.assert_called_once_with(self.uuid, 'off')
        self.cli.node.update.assert_called_once_with(self.uuid,
                                                     self.patch_before)
        finished_mock.assert_called_once_with(
            mock.ANY,
            error='Failed to power off node %s, check it\'s power management'
            ' configuration: boom' % self.uuid)

    @mock.patch.object(utils, 'get_client')
    def test_keep_ports_present(self, client_mock, filters_mock,
                                post_hook_mock):
        CONF.set_override('keep_ports', 'present', 'discoverd')

        # 2 MACs valid, one invalid, one not present in data
        all_macs = self.all_macs + ['01:09:02:08:03:07']
        all_ports = [
            mock.Mock(uuid='port_uuid%d' % i, address=mac)
            for i, mac in enumerate(all_macs)
        ]

        client_mock.return_value = self.cli
        self.cli.node.list_ports.return_value = all_ports

        self.call()

        self.cli.node.list_ports.assert_called_once_with(self.uuid, limit=0)
        self.cli.port.delete.assert_called_once_with(all_ports[-1].uuid)

    @mock.patch.object(utils, 'get_client')
    def test_keep_ports_added(self, client_mock, filters_mock, post_hook_mock):
        CONF.set_override('keep_ports', 'added', 'discoverd')

        # 2 MACs valid, one invalid, one not present in data
        all_macs = self.all_macs + ['01:09:02:08:03:07']
        all_ports = [
            mock.Mock(uuid='port_uuid%d' % i, address=mac)
            for i, mac in enumerate(all_macs)
        ]

        client_mock.return_value = self.cli
        self.cli.node.list_ports.return_value = all_ports

        self.call()

        self.cli.node.list_ports.assert_called_once_with(self.uuid, limit=0)
        for port in all_ports[2:]:
            self.cli.port.delete.assert_any_call(port.uuid)
        self.assertEqual(2, self.cli.port.delete.call_count)


class TestValidateInterfacesHook(test_base.BaseTest):
    def test_wrong_add_ports(self):
        CONF.set_override('add_ports', 'foobar', 'discoverd')
        self.assertRaises(SystemExit, std_plugins.ValidateInterfacesHook)

    def test_wrong_keep_ports(self):
        CONF.set_override('keep_ports', 'foobar', 'discoverd')
        self.assertRaises(SystemExit, std_plugins.ValidateInterfacesHook)
