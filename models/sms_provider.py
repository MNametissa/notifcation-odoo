from odoo import fields, models, api
from odoo.exceptions import UserError


class SMSProvider(models.Model):
    _name = 'karbura.notification.provider'
    _description = 'SMS Provider Configuration'
    _order = 'sequence, id'

    name = fields.Char(string="Name", required=True)
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(default=True)

    # Provider Type
    is_international = fields.Boolean(
        string='International Provider',
        help="If checked, this provider can send SMS worldwide. Otherwise, it only sends within Cameroon.",
        default=False
    )

    # URL Configuration
    base_url = fields.Char(string="Send URL", required=True)
    status_url = fields.Char(string="Status URL")
    status_waited = fields.Char(string="Awaited Status", default='{"status":"success"}', required=True)

    url_type = fields.Selection([
        ('simple_url', 'Simple'),
        ('multi_endpoint_url', 'Multi Endpoint'),
        ('custom_url', 'Custom')
    ], string="URL Type", required=True, default='simple_url')

    # Authentication
    auth_type = fields.Selection([
        ('none', 'None'),
        ('basic', 'Basic Auth'),
        ('api_key', 'API Key'),
        ('oauth2', 'OAuth2')
    ], string="Auth Type", required=True, default='api_key')
    username = fields.Char(string="Username")
    password = fields.Char(string="Password")
    api_key = fields.Char(string="API Key")
    oauth2_token = fields.Text(string="OAuth2 Token")

    # Templates
    payload_template = fields.Text(
        string="Payload Template (JSON)", 
        help="Payload template in JSON format",
        default='{"to": "{recipient}", "body": "{message}"}'
    )
    status_body_template = fields.Text(
        string="Status Body Template (JSON)", 
        help="Payload template in JSON format",
        default='{"to": "{recipient}", "body": "{message}"}'
    )

    # Provider Selection
    is_default = fields.Boolean(string="Default Provider", default=False)

    # Extra Configurations
    extra_fields = fields.One2many('karbura.notification.extra.field', 'provider_id', string='Extra Fields')
    extra_params_status = fields.One2many('karbura.notification.extra.params.status', 'provider_id', string='Status Params')
    extra_headers = fields.One2many('karbura.notification.extra.header', 'provider_id', string='Extra Headers')

    @api.model
    def create(self, vals):
        if vals.get('is_default'):
            self.search([]).write({'is_default': False})
        else:
            if not self.search([('is_default', '=', True)]):
                vals['is_default'] = True
        return super().create(vals)

    def write(self, vals):
        if 'is_default' in vals and vals['is_default']:
            self.search([('id', '!=', self.id)]).write({'is_default': False})
        elif 'is_default' not in vals:
            if not self.search([('is_default', '=', True)]):
                vals['is_default'] = True
        return super().write(vals)

    @api.model
    def get_default_provider(self):
        """Returns the default SMS provider."""
        return self.search([('is_default', '=', True)], limit=1)

    @api.model
    def set_default_provider(self):
        if not self.search([('is_default', '=', True)]):
            default_provider = self.search([], limit=1)
            if default_provider:
                default_provider.is_default = True
