from odoo import fields, models


class ExtraHeader(models.Model):
    _name = 'karbura.notification.extra.header'
    _description = 'Extra Headers for SMS Provider'

    provider_id = fields.Many2one('karbura.notification.provider', string='Provider', required=True, ondelete='cascade')
    name = fields.Char(string='Field Name', required=True)
    value = fields.Char(string='Field Value', required=True)
