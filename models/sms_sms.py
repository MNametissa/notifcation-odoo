from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)

class SmsSms(models.Model):
    _inherit = 'sms.sms'

    provider_message_id = fields.Char(string='Provider Message ID', readonly=True, 
                                    help='Message ID returned by the SMS provider')
    last_status_check = fields.Datetime(string='Last Status Check')

    def _send(self, unlink_failed=False, unlink_sent=True, raise_exception=False):
        """Override the core SMS sending method to use our providers."""
        _logger.info("=== Starting SMS _send method with %s records ===", len(self))
        
        # Find the first active provider
        provider = self.env['karbura.notification.provider'].search([('active', '=', True)], limit=1)
        if not provider:
            _logger.error("No active SMS provider found")
            return False
            
        _logger.info("Using provider: %s, message_id_field: %s", provider.name, provider.message_id_field)
        
        # Group recipients
        recipients = ','.join(record.number for record in self)
        
        try:
            # Mark messages as processing
            self.write({'state': 'process'})
            
            # Send SMS to all recipients
            result = self.env['karbura.notification.sms.api'].send_sms(
                provider=provider, 
                recipients=recipients, 
                message=self[0].body  # Assumes all records have the same body
            )
            
            # Process results
            if result.get('success'):
                response_json = result.get('response_data', {})
                _logger.info("=== Processing provider response ===")
                _logger.info("Provider: %s", provider.name)
                _logger.info("Message ID field: %s", provider.message_id_field)
                _logger.info("Response data: %s", response_json)
                
                # Get the message IDs using the configured field/path
                message_ids = self._get_value_by_path(response_json, provider.message_id_field)
                _logger.info("=== Message ID extraction result ===")
                _logger.info("Found message IDs: %s", message_ids)
                
                if message_ids:
                    _logger.info("=== Storing message IDs ===")
                    _logger.info("Message IDs to store: %s", message_ids)
                    
                    # Map message IDs to records if we have multiple
                    if len(message_ids) == len(self):
                        _logger.info("Number of message IDs matches number of records, mapping one-to-one")
                        for record, msg_id in zip(self, message_ids):
                            record.write({
                                'state': 'pending',
                                'provider_message_id': msg_id,
                                'failure_type': False
                            })
                            _logger.info("Stored message ID %s for record %s", msg_id, record.id)
                    else:
                        _logger.info("Using first message ID for all records")
                        self.write({
                            'state': 'pending',
                            'provider_message_id': message_ids[0],
                            'failure_type': False
                        })
                        _logger.info("Stored message ID %s for records: %s", message_ids[0], self.ids)
                else:
                    _logger.warning("No message IDs found in provider response using field %s", provider.message_id_field)
                
                # Mark failed recipients
                failed_recipients = result.get('failed_recipients', [])
                failed_records = self.filtered(lambda r: r.number in failed_recipients)
                if failed_records:
                    failed_records.write({
                        'state': 'error',
                        'failure_type': 'sms_server'
                    })
                    if unlink_failed:
                        failed_records.unlink()
                
                # Only unlink records that are confirmed delivered
                if unlink_sent:
                    delivered_records = self.filtered(lambda r: r.state == 'sent')
                    _logger.debug("Unlinking %s delivered records", len(delivered_records))
                    delivered_records.unlink()
                
                # Trigger status check cron immediately
                try:
                    self.env.ref('karbura_notification.ir_cron_sms_delivery_status_check').sudo().method_direct_trigger()
                    _logger.info("Triggered SMS delivery status check")
                except ValueError as e:
                    _logger.warning("Could not trigger SMS delivery status check: %s", str(e))
                
            else:
                # Entire batch failed
                _logger.error("Failed to send SMS batch: %s", result.get('failure_reason'))
                self.write({
                    'state': 'error',
                    'failure_type': result.get('failure_type', 'sms_server')
                })
                
                if unlink_failed:
                    self.unlink()
                
                if raise_exception:
                    raise Exception(result.get('failure_reason'))
            
            return True
        
        except Exception as e:
            _logger.exception("Error sending SMS batch: %s", str(e))
            self.write({
                'state': 'error',
                'failure_type': 'sms_server'
            })
            
            if raise_exception:
                raise
            
            return False

    def _get_value_by_path(self, data, path):
        """Get a value from nested dictionaries/lists using a dot-separated path.
        Returns a list of values found at the path."""
        _logger.info("=== Extracting message IDs ===")
        _logger.info("Looking for path: %s in data: %s", path, data)
        
        def search_recursively(d, target_key):
            """Search for key recursively in nested dictionaries and lists.
            Returns a list of all matching values."""
            _logger.info("Searching recursively in: %s for key: %s", d, target_key)
            results = []
            
            if isinstance(d, dict):
                for key, value in d.items():
                    _logger.info("Checking dict key: %s", key)
                    if key == target_key:
                        _logger.info("Found direct match! Key: %s, Value: %s", key, value)
                        results.append(value)
                    
                    # Recurse into nested structures
                    if isinstance(value, (dict, list)):
                        _logger.info("Recursing into nested structure: %s", value)
                        nested_results = search_recursively(value, target_key)
                        if nested_results:
                            results.extend(nested_results)
                            
            elif isinstance(d, list):
                _logger.info("Searching in list of length: %s", len(d))
                for item in d:
                    if isinstance(item, (dict, list)):
                        _logger.info("Recursing into list item: %s", item)
                        nested_results = search_recursively(item, target_key)
                        if nested_results:
                            results.extend(nested_results)
            
            return results
        
        try:
            # If no dots in path, search recursively through all nested structures
            if '.' not in path:
                _logger.info("No dots in path, searching recursively for key: %s", path)
                results = search_recursively(data, path)
                if results:
                    _logger.info("Found values recursively: %s", results)
                    return [str(r) if r is not None else None for r in results]
                _logger.info("Key %s not found in any level", path)
                return []
            
            # Handle dot notation path
            _logger.info("Path contains dots, traversing: %s", path)
            current = data
            parts = path.split('.')
            results = []
            
            # Special handling for the last part to collect all values
            *path_parts, last_part = parts
            
            # Navigate to the parent level
            for part in path_parts:
                _logger.info("Processing part: %s, current data: %s", part, current)
                # Handle array indexing
                if '[' in part and ']' in part:
                    array_part = part.split('[')[0]
                    index = int(part.split('[')[1].split(']')[0])
                    _logger.info("Array access - key: %s, index: %s", array_part, index)
                    current = current[array_part][index]
                else:
                    _logger.info("Dict access - key: %s", part)
                    current = current[part]
                _logger.info("After access - value: %s", current)
            
            # At the final level, collect all matching values
            if isinstance(current, list):
                for item in current:
                    if isinstance(item, dict) and last_part in item:
                        value = item[last_part]
                        _logger.info("Found value in list item: %s", value)
                        results.append(value)
            elif isinstance(current, dict) and last_part in current:
                value = current[last_part]
                _logger.info("Found value in dict: %s", value)
                if isinstance(value, list):
                    results.extend(value)
                else:
                    results.append(value)
            
            _logger.info("Found values at path: %s", results)
            return [str(r) if r is not None else None for r in results]
                
        except (KeyError, IndexError, TypeError, ValueError) as e:
            _logger.warning("Failed to get value using path %s: %s", path, str(e))
            return []

    @api.model
    def _check_sms_status(self):
        """Check delivery status for pending SMS messages."""
        _logger.info("=== Starting SMS Status Check Cron ===")
        
        # Find SMS records that are pending and have a provider message ID
        pending_sms = self.search([
            ('state', '=', 'pending'),  # Only check messages that are sent but not confirmed delivered
            ('provider_message_id', '!=', False)
        ])
        
        _logger.info("Found %s pending SMS messages to check", len(pending_sms))
        
        # Find active provider
        provider = self.env['karbura.notification.provider'].search([('active', '=', True)], limit=1)
        if not provider:
            _logger.error("No active SMS provider configured")
            return
            
        for record in pending_sms:
            try:
                _logger.info("Checking status for SMS ID: %s, Provider Message ID: %s", 
                           record.id, record.provider_message_id)
                
                result = self.env['karbura.notification.sms.api'].check_sms_status(
                    provider=provider,
                    message_id=record.provider_message_id
                )
                
                record.last_status_check = fields.Datetime.now()
                
                if result.get('success'):
                    if result.get('delivered'):
                        _logger.info("SMS ID %s marked as delivered", record.id)
                        record._update_sms_state_and_trackers('sent', failure_type=False)
                    elif result.get('failure_reason'):
                        _logger.warning("SMS ID %s failed: %s", record.id, result.get('failure_reason'))
                        record._update_sms_state_and_trackers('error', failure_type='sms_server')
                else:
                    _logger.error("Status check failed for SMS ID %s: %s", 
                                record.id, result.get('failure_reason'))
                        
            except Exception as e:
                _logger.exception("Error checking SMS status for ID %s: %s", record.id, str(e))
                
        _logger.info("=== Completed SMS Status Check Cron ===")
