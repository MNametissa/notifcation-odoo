import json
import logging
import requests
from odoo import models, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class SMSApi(models.AbstractModel):
    _name = 'karbura.notification.sms.api'
    _description = 'SMS API Integration'

    @api.model
    def _prepare_request(self, provider, recipient, message):
        """Prepare the request headers and payload."""
        _logger.info("Preparing SMS request for recipient: %s", recipient)
        headers = {}
        
        # Add extra headers
        for header in provider.extra_headers:
            headers[header.name] = header.value
        _logger.debug("Request headers: %s", headers)

        # Prepare payload from template
        extra_fields = {field.name: field.value for field in provider.extra_fields}
        _logger.debug("Extra fields: %s", extra_fields)
        
        try:
            payload_template = json.loads(provider.payload_template or '{}')
            payload = self._format_payload(payload_template, recipient, message, extra_fields)
            _logger.debug("Formatted payload: %s", payload)
        except json.JSONDecodeError as e:
            _logger.error("Failed to parse payload template: %s", str(e))
            raise UserError(f'Invalid payload template: {str(e)}')

        if headers.get('Content-Type') == 'application/json':
            payload = json.dumps(payload)

        return headers, payload

    @api.model
    def _format_payload(self, template, recipient, message, extra_fields):
        """Format the payload template with values."""
        if isinstance(template, dict):
            return {k: self._format_payload(v, recipient, message, extra_fields) 
                   for k, v in template.items()}
        elif isinstance(template, list):
            return [self._format_payload(v, recipient, message, extra_fields) 
                   for v in template]
        elif isinstance(template, str):
            return template.format(
                recipient=recipient,
                message=message,
                **extra_fields
            )
        return template

    @api.model
    def send_sms(self, provider, recipient, message):
        """Send SMS using the configured provider.
        
        Args:
            provider: karbura.notification.provider record
            recipient: Phone number to send to
            message: Message content
            
        Returns:
            dict: Result containing success status and any error info
        """
        _logger.info("=== Starting send_sms in sms_api ===")
        _logger.info("Provider: %s, Recipient: %s", provider.name, recipient)
        _logger.debug("Message: %s", message[:100] if message else None)
        
        try:
            # Prepare request
            _logger.info("Preparing request")
            headers, payload = self._prepare_request(provider, recipient, message)
            _logger.debug("Request URL: %s", provider.base_url)
            
            # Add authentication
            if provider.auth_type == 'basic':
                _logger.debug("Using Basic authentication")
                headers['Authorization'] = f"Basic {provider.username}:{provider.password}"
            elif provider.auth_type == 'api_key':
                _logger.debug("Using API Key authentication")
                headers['Authorization'] = f"Bearer {provider.api_key}"
            elif provider.auth_type == 'oauth2':
                _logger.debug("Using OAuth2 authentication")
                headers['Authorization'] = f"Bearer {provider.oauth2_token}"

            # Send request
            _logger.info("Making HTTP request")
            response = requests.post(
                provider.base_url,
                headers=headers,
                data=payload,
                timeout=30
            )
            
            # Check response
            _logger.debug("Response status: %s", response.status_code)
            _logger.debug("Response body: %s", response.text[:500])
            response.raise_for_status()
            
            # Validate response against expected status
            try:
                expected_status = json.loads(provider.status_waited)
                response_json = response.json()
                _logger.debug("Expected status: %s", expected_status)
                _logger.debug("Response JSON: %s", response_json)
                
                success = all(
                    response_json.get(key) == value 
                    for key, value in expected_status.items()
                )
                
                if not success:
                    error_msg = f'Unexpected response: {response.text[:64]}'
                    _logger.error("SMS sending failed: %s", error_msg)
                    return {
                        'success': False,
                        'failure_type': 'sms_server',
                        'failure_reason': error_msg
                    }
                    
            except (json.JSONDecodeError, AttributeError) as e:
                error_msg = f'Invalid response format: {str(e)}'
                _logger.error("Failed to parse response: %s", str(e))
                return {
                    'success': False,
                    'failure_type': 'sms_server',
                    'failure_reason': error_msg
                }

            _logger.info("SMS sent successfully to %s", recipient)
            return {'success': True}

        except requests.RequestException as e:
            error_msg = f'Request failed: {str(e)}'
            _logger.error("SMS sending failed: %s", str(e))
            return {
                'success': False,
                'failure_type': 'sms_server',
                'failure_reason': error_msg
            }
        except Exception as e:
            error_msg = str(e)
            _logger.error("SMS sending failed: %s", str(e))
            return {
                'success': False,
                'failure_type': 'unknown',
                'failure_reason': error_msg
            }
        finally:
            _logger.info("=== Finished send_sms in sms_api ===")
