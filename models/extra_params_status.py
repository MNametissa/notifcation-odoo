from odoo import fields, models


class ExtraParamsStatus(models.Model):
    _name = 'karbura.notification.extra.params.status'
    _description = 'Extra Status Parameters for SMS Provider'

    provider_id = fields.Many2one('karbura.notification.provider', string='Provider', required=True, ondelete='cascade')
    name = fields.Char(string='Field Name', required=True)
    value = fields.Char(string='Field Value', required=True)
