from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class Mailing(models.Model):
    _inherit = 'mailing.mailing'

    sms_provider_id = fields.Many2one('karbura.notification.provider', string='SMS Provider',
        domain=[('active', '=', True)],
        help='Provider to use for sending SMS messages')

    def _get_default_sms_provider(self):
        """Get the default SMS provider."""
        provider = self.env['karbura.notification.provider'].search([
            ('is_default', '=', True),
            ('active', '=', True)
        ], limit=1)
        _logger.info("Default SMS provider: %s", provider.name if provider else None)
        return provider

    def _send_sms_get_composer_values(self, res_ids):
        """Override to validate SMS provider without passing to composer."""
        _logger.info("Getting composer values for SMS mailing to %s recipients", len(res_ids))
        composer_values = super()._send_sms_get_composer_values(res_ids)
        if self.mailing_type == 'sms':
            provider = self.sms_provider_id or self._get_default_sms_provider()
            if not provider:
                _logger.error("No SMS provider configured")
                raise UserError('No SMS provider configured')
            _logger.debug("Using SMS provider: %s", provider.name)
        return composer_values

    def _send_sms(self, records, body):
        """Override to use custom SMS provider."""
        _logger.info("=== Starting _send_sms in mailing.mailing ===")
        _logger.info("Records count: %s, Body preview: %s", len(records), body[:100] if body else None)
        
        if self.mailing_type != 'sms':
            _logger.info("Not an SMS mailing, using standard method")
            return super()._send_sms(records, body)

        _logger.info("Starting SMS mailing to %s recipients", len(records))
        provider = self.sms_provider_id or self._get_default_sms_provider()
        if not provider:
            _logger.error("No SMS provider configured")
            raise UserError('No SMS provider configured')
        
        _logger.info("Using provider: %s", provider.name)
        
        # Create SMS records first
        sms_values = []
        for record in records:
            phone = self._get_recipient_phone(record)
            if phone:
                rendered_body = self._render_field('body_plaintext', [record.id])[record.id]
                sms_values.append({
                    'number': phone,
                    'body': rendered_body,
                    'mailing_id': self.id,
                })
                _logger.debug("Prepared SMS for %s: %s", phone, rendered_body[:50])
            else:
                _logger.warning("No phone number found for record %s", record)

        _logger.info("Creating %s SMS records", len(sms_values))
        sms_records = self.env['sms.sms'].sudo().create(sms_values)
        _logger.info("Created SMS records: %s", sms_records.ids)
        
        # Let the SMS model handle the sending
        if sms_records:
            _logger.info("Calling _send on SMS records")
            sms_records._send(raise_exception=False)
        else:
            _logger.warning("No SMS records created")
        
        _logger.info("=== Finished _send_sms in mailing.mailing ===")
        return True

    def _get_recipient_phone(self, record):
        """Get recipient's phone number from record."""
        if hasattr(record, 'mobile'):
            return record.mobile
        elif hasattr(record, 'phone'):
            return record.phone
        elif hasattr(record, 'partner_id'):
            partner = record.partner_id
            return partner.mobile or partner.phone
        return False
