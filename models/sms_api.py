import json
import logging
import requests
import socket
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
    def _find_success_in_response(self, response_data):
        """Recursively search for 'success' value in response data."""
        if isinstance(response_data, dict):
            for key, value in response_data.items():
                if key == 'success' and isinstance(value, bool):
                    return value
                result = self._find_success_in_response(value)
                if result is not None:
                    return result
        elif isinstance(response_data, list):
            for item in response_data:
                result = self._find_success_in_response(item)
                if result is not None:
                    return result
        return None

    @api.model
    def _replace_template_params(self, provider, template, base_params=None):
        """
        Replace template parameters with provided values.
        
        Args:
            provider: SMS provider record
            template (str): JSON template string with placeholders
            base_params (dict): Base parameters (recipient, message, messageid, etc.)
        
        Returns:
            dict: Parsed template with placeholders replaced
        """
        _logger.info("=== Template Parameter Replacement ===")
        
        # Convert template to string for replacement
        template_str = json.dumps(template)
        _logger.info("Original template: %s", template_str)
        
        # Start with base parameters
        base_params = base_params or {}
        replacements = {
            # SMS send parameters
            '{recipient}': base_params.get('to', ''),
            '{message}': base_params.get('body', ''),
            # Status check parameters
            '{messageid}': base_params.get('messageid', ''),
            # Authentication parameters
            '{username}': provider.username or '',
            '{password}': provider.password or ''
        }
        
        # Add provider's extra fields
        for extra_field in provider.extra_fields:
            placeholder = '{' + extra_field.name + '}'
            replacements[placeholder] = extra_field.value
            
        # Log replacement mapping (excluding sensitive data)
        safe_replacements = {
            k: '***' if any(s in k.lower() for s in ['password', 'token', 'key']) else v 
            for k, v in replacements.items()
        }
        _logger.info("Replacement mapping: %s", safe_replacements)
        
        # Perform replacements
        for placeholder, value in replacements.items():
            template_str = template_str.replace(placeholder, str(value))
        
        # Parse back to JSON
        try:
            result = json.loads(template_str)
            _logger.info("Final template: %s", 
                        {k: '***' if any(s in k.lower() for s in ['password', 'token', 'key']) else v 
                         for k, v in result.items()})
            return result
        except json.JSONDecodeError as e:
            _logger.error("Error parsing replaced template: %s", str(e))
            _logger.error("Problematic template string: %s", template_str)
            return template

    @api.model
    def _extract_message_ids(self, response_data, message_id_path):
        """Extract message IDs from the response using the configured path."""
        message_ids = []
        
        def get_value_by_path(data, path):
            """Get a value from nested dictionaries/lists using a dot-separated path."""
            try:
                current = data
                parts = path.split('.')
                
                for part in parts:
                    # Handle array indexing
                    if '[' in part and ']' in part:
                        array_part = part.split('[')[0]
                        index = int(part.split('[')[1].split(']')[0])
                        current = current[array_part][index]
                    else:
                        current = current[part]
                
                # Handle both single values and lists
                if isinstance(current, list):
                    return [str(item) for item in current]
                else:
                    return [str(current)]
                    
            except (KeyError, IndexError, TypeError, ValueError) as e:
                _logger.warning("Failed to extract message ID using path %s: %s", path, str(e))
                return []
        
        # Extract message IDs using the configured path
        message_ids = get_value_by_path(response_data, message_id_path)
        _logger.info("Extracted message IDs using path %s: %s", message_id_path, message_ids)
        
        return message_ids

    @api.model
    def _check_internet_connection(self):
        """Check if there is an internet connection by trying to reach a reliable host."""
        test_hosts = [
            "8.8.8.8",  # Google DNS
            "1.1.1.1"   # Cloudflare DNS
        ]
        
        for host in test_hosts:
            try:
                # Try to connect to the host's port 53 (DNS)
                socket.create_connection((host, 53), timeout=3)
                _logger.debug("Internet connection check successful using %s", host)
                return True
            except OSError:
                continue
        
        _logger.warning("No internet connection available")
        return False

    @api.model
    def send_sms(self, provider, recipients, message):
        """Send SMS to multiple recipients in a batch.
        
        Args:
            provider: SMS provider configuration
            recipients: Comma-separated list of phone numbers
            message: SMS message text
            
        Returns:
            dict: Sending results with:
                - success: Overall sending status
                - response_data: Full response JSON from provider
                - failed_recipients: List of recipients that failed
        """
        _logger.info("=== Starting SMS Send ===")
        _logger.info("Provider: %s", provider.name)
        _logger.info("Recipients: %s", recipients)
        
        # Check internet connection first
        if not self._check_internet_connection():
            _logger.error("Cannot send SMS: No internet connection")
            return {'success': False}
        
        try:
            # Load payload template
            try:
                payload_template = json.loads(provider.payload_template or '{}')
            except json.JSONDecodeError as e:
                _logger.error("Failed to parse payload template: %s", str(e))
                return {'success': False}
            
            # Prepare headers
            headers = self._prepare_headers(provider)
            
            # Base parameters for template
            base_params = {
                'to': recipients,
                'body': message
            }
            
            # Replace template parameters using provider's extra fields
            payload = self._replace_template_params(provider, payload_template, base_params)
            
            # Log detailed request information
            _logger.info("=== API Request Details ===")
            _logger.info("Request URL: %s", provider.base_url)
            _logger.info("Request Headers: %s", json.dumps(headers, indent=2))
            _logger.info("Request Payload: %s", json.dumps(payload, indent=2))
            
            # Make API request
            response = requests.post(
                provider.base_url, 
                json=payload, 
                headers=headers
            )
            
            # Log full response details
            _logger.info("=== API Response Details ===")
            _logger.info("Response Status Code: %s", response.status_code)
            _logger.info("Response Headers: %s", json.dumps(dict(response.headers), indent=2))
            _logger.info("Response Body (full): %s", response.text)
            
            response.raise_for_status()
            
            try:
                response_json = response.json()
                
                # Check for success
                success = self._find_success_in_response(response_json)
                
                # Log parsing details
                _logger.info("=== Response Parsing ===")
                _logger.info("Success Value: %s", success)
                _logger.info("Parsed Response JSON: %s", json.dumps(response_json, indent=2))
                
                if success is not None:
                    if success:
                        _logger.info("SMS sent successfully to %s", recipients)
                        return {
                            'success': True,
                            'response_data': response_json,
                            'failed_recipients': []
                        }
                    else:
                        error_msg = f'API indicated failure in response: {response.text[:64]}'
                        _logger.error("SMS sending failed: %s", error_msg)
                        return {
                            'success': False,
                            'response_data': response_json,
                            'failed_recipients': recipients.split(','),
                            'failure_type': 'sms_server',
                            'failure_reason': error_msg
                        }
                
                # If no success field found, assume success if HTTP status was 200
                _logger.info("No explicit success field found, assuming success")
                return {
                    'success': True,
                    'response_data': response_json,
                    'failed_recipients': []
                }
                    
            except json.JSONDecodeError as e:
                _logger.error("Failed to parse response: %s", str(e))
                return {'success': False, 'failed_recipients': recipients.split(',')}
                     
        except requests.RequestException as e:
            _logger.error("SMS sending failed: %s", str(e))
            return {'success': False, 'failed_recipients': recipients.split(',')}
        finally:
            _logger.info("=== Finished SMS Send ===")

    @api.model
    def check_sms_status(self, provider, message_id):
        """Check the delivery status of an SMS message.
        
        Args:
            provider: SMS provider configuration
            message_id: Provider's message ID to check
            
        Returns:
            dict: Status check results with:
                - success: Whether the status check succeeded
                - delivered: Whether the message was delivered
        """
        _logger.info("=== Checking SMS Status ===")
        _logger.info("Provider: %s", provider.name)
        _logger.info("Message ID: %s", message_id)
        
        # Check internet connection first
        if not self._check_internet_connection():
            _logger.error("Cannot check SMS status: No internet connection")
            return {'success': False}
        
        try:
            # Load status template
            try:
                status_template = json.loads(provider.status_body_template or '{}')
                _logger.info("Status template: %s", status_template)
            except json.JSONDecodeError as e:
                _logger.error("Failed to parse status template: %s", str(e))
                return {'success': False}
            
            # Prepare headers
            headers = self._prepare_headers(provider)
            
            # Base parameters for template
            base_params = {
                'messageid': message_id,
                'username': provider.username,
                'password': provider.password
            }
            
            # Replace template parameters using provider's extra fields
            payload = self._replace_template_params(provider, status_template, base_params)
            _logger.info("Status check payload: %s", payload)
            
            # Make API request
            response = requests.post(
                provider.status_url,
                json=payload,
                headers=headers
            )
            
            response.raise_for_status()
            response_json = response.json()
            _logger.info("Status check response: %s", response_json)
            
            # Extract status using the same path mechanism
            status_values = self._get_value_by_path(response_json, provider.status_field)
            _logger.info("Extracted status values: %s", status_values)
            
            if not status_values:
                return {'success': True, 'delivered': False}
            
            # Check if status indicates delivery
            status = status_values[0]  # Use first status if multiple
            waited_statuses = json.loads(provider.status_waited or '[]')
            
            _logger.info("Status: %s, Waited statuses: %s", status, waited_statuses)
            
            if status in waited_statuses:
                _logger.info("Message is in waited status")
                return {'success': True, 'delivered': False}
            
            # Consider message delivered if not in waited status
            return {'success': True, 'delivered': True}
                
        except requests.RequestException as e:
            _logger.error("Status check request failed: %s", str(e))
            return {'success': False}
        except Exception as e:
            _logger.error("Status check failed: %s", str(e))
            return {'success': False}
        finally:
            _logger.info("=== Completed SMS Status Check ===")

    def _get_value_by_path(self, data, path):
        """Get a value from nested dictionaries/lists using a dot-separated path.
        Returns a list of values found at the path."""
        _logger.info("=== Extracting value ===")
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
    def _prepare_headers(self, provider):
        headers = {}
        for header in provider.extra_headers:
            headers[header.name] = header.value
        return headers
