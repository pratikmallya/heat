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

from oslo_log import log as logging

from heat.engine import api as engine_api
from heat.engine import notification

LOG = logging.getLogger(__name__)


def send(resource, reason, notfcn_type=None, data=None):
    """Send usage notifications to the configured notification driver."""

    # The current notifications have a start/end:
    # see: https://wiki.openstack.org/wiki/SystemUsageData
    # so to be consistent we translate our status into a known start/end/error
    # suffix.
    level = notification.get_default_level()

    if notfcn_type == 'hook':
        suffix = data['suffix']
        hook = data['hook']
        event_type = '%s.%s.%s' % ('resource', 'hook', suffix)
        body = engine_api.format_resource_hook_notification_body(
            resource, reason, hook)
    elif notfcn_type == 'signal':
        event_type = '%s.%s' % ('resource', 'signal')
        body = engine_api.format_resource_signal_notification_body(
            resource, reason, data)
        level = notification.INFO
    elif notfcn_type == 'resource':
        if resource.status == resource.IN_PROGRESS:
            suffix = 'start'
        elif resource.status == resource.COMPLETE:
            suffix = 'end'
        else:
            suffix = 'error'
            level = notification.ERROR
        event_type = '%s.%s.%s' % ('resource', resource.action.lower(), suffix)
        body = engine_api.format_resource_notification_body(resource, reason)
    else:
        LOG.error(_("Unexpected notification type %s!") % notfcn_type)
        return

    notification.notify(resource.context, event_type, level, body)
