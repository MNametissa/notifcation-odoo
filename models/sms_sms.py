from odoo import models, api
import logging

_logger = logging.getLogger(__name__)

class SmsSms(models.Model):
    _inherit = 'sms.sms'

    def _send(self, unlink_failed=False, unlink_sent=True, raise_exception=False):
        """Override the core SMS sending method to use our providers."""
        _logger.info("=== Starting SMS _send method with %s records ===", len(self))
        _logger.info("Parameters: unlink_failed=%s, unlink_sent=%s, raise_exception=%s", 
                    unlink_failed, unlink_sent, raise_exception)
        
        # Get the mailing record if this SMS is part of a mass mailing
        mailing_ids = self.mapped('mailing_id.id')
        _logger.info("Found mailing IDs: %s", mailing_ids)
        
        mailing = self.env['mailing.mailing'].search([('id', 'in', mailing_ids)])
        _logger.info("Found mailing records Karbura Notification: %s", mailing)
        _logger.info("Mailing type", mailing.mailing_type)
        
        # If this is a mass mailing SMS, use our provider
        if mailing and mailing.mailing_type == 'sms':
            _logger.info("Using Karbura SMS provider for mass mailing")
            
            for record in self:
                _logger.info("Processing SMS record ID %s", record.id)
                _logger.debug("SMS details: number=%s, body=%s", record.number, record.body[:50] if record.body else None)
                
                if not record.number:
                    _logger.warning("Missing number for SMS record %s", record.id)
                    continue

                try:
                    # Get provider from mailing or default
                    provider = mailing.sms_provider_id or mailing._get_default_sms_provider()
                    _logger.info("Using provider: %s", provider.name if provider else None)
                    
                    if not provider:
                        _logger.error("No SMS provider configured")
                        if raise_exception:
                            raise Exception("No SMS provider configured")
                        continue

                    # Send SMS using our API
                    _logger.info("Sending SMS via Karbura API to %s", record.number)
                    result = self.env['karbura.notification.sms.api'].send_sms(
                        provider=provider,
                        recipient=record.number,
                        message=record.body
                    )
                    _logger.info("SMS API result: %s", result)

                    if result.get('success'):
                        _logger.info("SMS sent successfully to %s", record.number)
                        record.write({'state': 'sent'})
                        if unlink_sent:
                            _logger.debug("Unlinking sent record %s", record.id)
                            record.unlink()
                    else:
                        _logger.error("Failed to send SMS: %s", result.get('failure_reason'))
                        record.write({
                            'state': 'error',
                            'failure_type': result.get('failure_type', 'unknown'),
                            'error_code': result.get('failure_reason', 'Unknown error')
                        })
                        if unlink_failed:
                            _logger.debug("Unlinking failed record %s", record.id)
                            record.unlink()
                        if raise_exception:
                            raise Exception(result.get('failure_reason'))

                except Exception as e:
                    _logger.exception("Error sending SMS: %s", str(e))
                    record.write({
                        'state': 'error',
                        'failure_type': 'unknown',
                        'error_code': str(e)
                    })
                    if unlink_failed:
                        record.unlink()
                    if raise_exception:
                        raise

            _logger.info("=== Finished processing SMS records ===")
            return True

        # For non-mass mailing SMS, use the standard sending method
        _logger.info("Using standard Odoo SMS sending for non-mass mailing")
        return super()._send(
            unlink_failed=unlink_failed,
            unlink_sent=unlink_sent,
            raise_exception=raise_exception
        )
