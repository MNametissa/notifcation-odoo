from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class Mailing(models.Model):
    _inherit = 'mailing.mailing'

    sms_provider_id = fields.Many2one('karbura.notification.provider', string='SMS Provider',
        domain=[('active', '=', True)],
        help='Provider to use for sending SMS messages')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_queue', 'In Queue'),
        ('sending', 'Sending'),
        ('partially_sent', 'Partially Sent'),  
        ('failed', 'Failed'),  
        ('done', 'Sent')
    ], string='Status', default='draft', required=True, copy=False, tracking=True)

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
                raise UserError(_('No SMS provider configured'))
            _logger.debug("Using SMS provider: %s", provider.name)
        return composer_values

    def action_put_in_queue(self):
        for mailing in self:
            if mailing.mailing_type == 'sms':
                # Check for recipients
                recipients = mailing._get_remaining_recipients()
                if not recipients:
                    raise UserError(_('Please select recipients for your SMS campaign. You can add recipients by:\n'
                                    '- Adding them to a mailing list\n'
                                    '- Using filters to select specific records\n'
                                    '- Importing contacts with phone numbers'))
                
                # Check for SMS provider
                if not mailing.sms_provider_id:
                    raise UserError(_('Please select an SMS provider before sending the campaign.'))
                
        return super().action_put_in_queue()

    def _send_sms(self, records, body):
        """Override to use custom SMS provider."""
        if not records:
            raise UserError(_('No valid recipients found for this SMS campaign.'))
            
        _logger.info("=== Starting _send_sms in mailing.mailing ===")
        _logger.info("Records count: %s, Body preview: %s", len(records), body[:100] if body else None)
        
        if self.mailing_type != 'sms':
            _logger.info("Not an SMS mailing, using standard method")
            return super()._send_sms(records, body)

        _logger.info("Starting SMS mailing to %s recipients", len(records))
        provider = self.sms_provider_id or self._get_default_sms_provider()
        if not provider:
            _logger.error("No SMS provider configured")
            raise UserError(_('No SMS provider configured'))
        
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

    @api.depends('mailing_trace_ids.trace_status')
    def _compute_statistics(self):
        super()._compute_statistics()
        for mailing in self:
            if mailing.mailing_type != 'sms' or mailing.state not in ['done', 'failed', 'partially_sent', 'sending']:
                continue
                
            total_sent = mailing.sent + mailing.delivered
            total_failed = mailing.failed + mailing.bounced
            total_canceled = mailing.canceled
            total_pending = mailing.pending
            total_expected = total_sent + total_failed + total_pending + total_canceled

            # Update state based on statistics
            if total_expected > 0:
                if total_canceled == total_expected:
                    mailing.state = 'failed'  # All messages were canceled
                elif total_failed == total_expected:
                    mailing.state = 'failed'  # All messages failed
                elif total_sent > 0 and total_sent < total_expected:
                    mailing.state = 'partially_sent'
                elif total_sent == total_expected:
                    mailing.state = 'done'
                elif total_pending > 0:
                    mailing.state = 'sending'  # There are messages still pending to be sent
            elif mailing.state == 'sending':
                # Keep 'sending' state when no messages processed yet
                pass
