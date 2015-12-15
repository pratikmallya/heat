#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import copy

from oslo_log import log as logging

from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LW
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources.openstack.nova import server
from heat.engine import support


try:
    import pyrax  # noqa
    PYRAX_INSTALLED = True
except ImportError:
    PYRAX_INSTALLED = False

LOG = logging.getLogger(__name__)


class CloudServer(server.Server):
    """Resource for Rackspace Cloud Servers.

    This resource overloads existent integrated OS::Nova::Server resource and
    is used for Rackspace Cloud Servers.
    """

    support_status = support.SupportStatus(
        status=support.UNSUPPORTED,
        message=_('This resource is not supported, use at your own risk.'))

    # RAX Server automation statuses
    RSA_STATUS_IN_PROGRESS = 'In Progress'
    RSA_STATUS_COMPLETE = 'Complete'
    RSA_STATUS_BUILD_ERROR = 'Build Error'

    # RackConnect automation statuses
    RC_STATUS_DEPLOYING = 'DEPLOYING'
    RC_STATUS_DEPLOYED = 'DEPLOYED'
    RC_STATUS_FAILED = 'FAILED'
    RC_STATUS_UNPROCESSABLE = 'UNPROCESSABLE'

    properties_schema = copy.deepcopy(server.Server.properties_schema)
    properties_schema.update(
        {
            server.Server.USER_DATA_FORMAT: properties.Schema(
                properties.Schema.STRING,
                _('How the user_data should be formatted for the server. For '
                  'HEAT_CFNTOOLS, the user_data is bundled as part of the '
                  'heat-cfntools cloud-init boot configuration data. For RAW '
                  'the user_data is passed to Nova unmodified. '
                  'For SOFTWARE_CONFIG user_data is bundled as part of the '
                  'software config data, and metadata is derived from any '
                  'associated SoftwareDeployment resources.'),
                default=server.Server.RAW,
                constraints=[
                    constraints.AllowedValues(
                        server.Server._SOFTWARE_CONFIG_FORMATS),
                ]
            ),
        }
    )

    def __init__(self, name, json_snippet, stack):
        super(CloudServer, self).__init__(name, json_snippet, stack)
        self._rax_server_automation_started_event_sent = False
        self._rack_connect_started_event_sent = False

    def _config_drive(self):
        user_data = self.properties.get(self.USER_DATA)
        config_drive = self.properties.get(self.CONFIG_DRIVE)
        if user_data or config_drive:
            return True
        else:
            return False

    def _check_rax_server_automation_complete(self, server):
        if not self._rax_server_automation_started_event_sent:
            msg = _("Waiting for RAX Server automation to complete")
            self._add_event(self.action, self.status, msg)
            self._rax_server_automation_started_event_sent = True

        if 'rax_service_level_automation' not in server.metadata:
            LOG.debug("Server does not have the "
                      "rax_service_level_automation metadata tag yet")
            return False

        rsa_status = server.metadata['rax_service_level_automation']
        LOG.debug("RAX Server automation status: %s" % rsa_status)

        if rsa_status == self.RSA_STATUS_IN_PROGRESS:
            return False

        elif rsa_status == self.RSA_STATUS_COMPLETE:
            msg = _("RAX Server automation has completed")
            self._add_event(self.action, self.status, msg)
            return True

        elif rsa_status == self.RSA_STATUS_BUILD_ERROR:
            raise exception.Error(_("RAX Server automation failed"))

        else:
            raise exception.Error(_("Unknown RAX Server automation "
                                    "status: %s") % rsa_status)

    def _check_rack_connect_complete(self, server):
        if not self._rack_connect_started_event_sent:
            msg = _("Waiting for RackConnect automation to complete")
            self._add_event(self.action, self.status, msg)
            self._rack_connect_started_event_sent = True

        if 'rackconnect_automation_status' not in server.metadata:
            LOG.debug("RackConnect server does not have the "
                      "rackconnect_automation_status metadata tag yet")
            return False

        rc_status = server.metadata['rackconnect_automation_status']
        LOG.debug("RackConnect automation status: %s" % rc_status)

        if rc_status == self.RC_STATUS_DEPLOYING:
            return False

        elif rc_status == self.RC_STATUS_DEPLOYED:
            self._server = None  # The public IP changed, forget old one
            return True

        elif rc_status == self.RC_STATUS_UNPROCESSABLE:
            # UNPROCESSABLE means the RackConnect automation was not
            # attempted (eg. Cloud Server in a different DC than
            # dedicated gear, so RackConnect does not apply).  It is
            # okay if we do not raise an exception.
            reason = server.metadata.get('rackconnect_unprocessable_reason',
                                         None)
            if reason is not None:
                LOG.warn(_LW("RackConnect unprocessable reason: %s"), reason)

            msg = _("RackConnect automation has completed")
            self._add_event(self.action, self.status, msg)
            return True

        elif rc_status == self.RC_STATUS_FAILED:
            raise exception.Error(_("RackConnect automation FAILED"))

        else:
            msg = _("Unknown RackConnect automation status: %s") % rc_status
            raise exception.Error(msg)

    def check_create_complete(self, server_id):
        """Check if server creation is complete and handle server configs."""
        if not super(CloudServer, self).check_create_complete(server_id):
            return False

        server = self.client_plugin().fetch_server(server_id)
        if not server:
            return False

        if ('rack_connect' in self.context.roles and not
                self._check_rack_connect_complete(server)):
            return False

        if not self._check_rax_server_automation_complete(server):
            return False

        return True

    # Since rackspace compute service does not support 'os-interface' endpoint,
    # accessing addresses attribute of OS::Nova::Server results in NotFound
    # error. Here overrdiing '_add_port_for_address' method and using different
    # endpoint named 'os-virtual-interfacesv2' to get the same information.
    def _add_port_for_address(self, server):
        def get_port(net_name, address):
            for iface in ifaces:
                for ip_addr in iface.ip_addresses:
                    if ip_addr['network_label'] == net_name and ip_addr[
                            'address'] == address:
                        return iface.id

        nets = copy.deepcopy(server.addresses)
        nova_ext = self.client().os_virtual_interfacesv2_python_novaclient_ext
        ifaces = nova_ext.list(server.id)
        for net_name, addresses in nets.items():
            for address in addresses:
                address['port'] = get_port(net_name, address['addr'])

        return self._extend_networks(nets)


def resource_mapping():
    return {'OS::Nova::Server': CloudServer}


def available_resource_mapping():
    if PYRAX_INSTALLED:
        return resource_mapping()
    return {}
