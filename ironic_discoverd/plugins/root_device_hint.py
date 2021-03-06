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

"""Gather root device hint from recognized block devices."""

import logging

from ironic_discoverd.common.i18n import _LI, _LW
from ironic_discoverd.plugins import base


LOG = logging.getLogger('ironic_discoverd.plugins.root_device_hint')


class RootDeviceHintHook(base.ProcessingHook):
    """Interact with Instack ramdisk for discovery data processing hooks.

    The plugin can figure out the root device in 2 runs. First, it saves the
    discovered block device serials in node.extra. The second run will check
    the difference between the recently discovered block devices and the
    previously saved ones. After saving the root device in node.properties, it
    will delete the temporarily saved block device serials in node.extra.

    This way, it helps to figure out the root device hint in cases when
    otherwise Ironic doesn't have enough information to do so. Such a usecase
    is DRAC RAID configuration where the BMC doesn't provide any useful
    information about the created RAID disks. Using this plugin immediately
    before and after creating the root RAID device will solve the issue of root
    device hints.
    """

    def before_update(self, node, ports, node_info):
        if 'block_devices' not in node_info:
            LOG.warning(_LW('No block device was received from ramdisk'))
            return [], {}

        if 'root_device' in node.properties:
            LOG.info(_LI('Root device is already known for the node'))
            return [], {}

        if 'block_devices' in node.extra:
            # Compare previously discovered devices with the current ones
            previous_devices = node.extra['block_devices']['serials']
            current_devices = node_info['block_devices']['serials']
            new_devices = [device for device in current_devices
                           if device not in previous_devices]

            if len(new_devices) > 1:
                LOG.warning(_LW('Root device cannot be identified because '
                            'multiple new devices were found'))
                return [], {}
            elif len(new_devices) == 0:
                LOG.warning(_LW('No new devices were found'))
                return [], {}

            return [
                {'op': 'remove',
                 'path': '/extra/block_devices'},
                {'op': 'add',
                 'path': '/properties/root_device',
                 'value': {'serial': new_devices[0]}}
            ], {}

        else:
            # No previously discovered devices - save the discoverd block
            # devices in node.extra
            return [
                {'op': 'add',
                 'path': '/extra/block_devices',
                 'value': node_info['block_devices']}
            ], {}
