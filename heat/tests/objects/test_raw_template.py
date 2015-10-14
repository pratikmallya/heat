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

from oslo_config import cfg

from heat.common import crypt
from heat.common import template_format
from heat.engine import environment
from heat.engine import template
from heat.objects import raw_template
from heat.tests import common
from heat.tests import utils


parameter_template = template_format.parse('''{
  "HeatTemplateFormatVersion" : "2012-12-12",
  "Parameters" : {
    "foo" : { "Type" : "String" },
    "blarg" : { "Type" : "String", "Default": "quux", "NoEcho": 'true'}
  }
}''')


class RawTemplateTest(common.HeatTestCase):

    def setUp(self):
        super(RawTemplateTest, self).setUp()
        self.ctx = utils.dummy_context()

    def test_encrypt_hidden_parameters_default_template(self):
        cfg.CONF.set_override('encrypt_parameters_and_properties', True)
        tmpl = template.Template(parameter_template)
        raw_template.RawTemplate.encrypt_hidden_parameters(tmpl)
        self.assertEqual(['blarg'], tmpl.env.encrypted_param_names)
        self.assertEqual('cryptography_decrypt_v1',
                         tmpl.env.params['blarg'][0])

    def test_encrypt_hidden_parameters_template_env(self):
        env = environment.Environment({'blarg': 'bar'})
        cfg.CONF.set_override('encrypt_parameters_and_properties', True)
        tmpl = template.Template(parameter_template, env=env)
        raw_template.RawTemplate.encrypt_hidden_parameters(tmpl)
        self.assertEqual(['blarg'], tmpl.env.encrypted_param_names)
        self.assertEqual('cryptography_decrypt_v1',
                         tmpl.env.params['blarg'][0])
        name, value = tmpl.env.params['blarg']
        decrypted_val = crypt.decrypt(name, value)
        self.assertEqual('bar', decrypted_val)
