from odoo import fields, models


class ExtraField(models.Model):
    _name = 'karbura.notification.extra.field'
    _description = 'Extra Fields for SMS Provider'

    provider_id = fields.Many2one('karbura.notification.provider', string='Provider', required=True, ondelete='cascade')
    name = fields.Char(string='Field Name', required=True)
    value = fields.Char(string='Field Value', required=True)
