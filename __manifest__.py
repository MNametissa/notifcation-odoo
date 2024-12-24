{
    'name': 'Karbura Notification',
    'version': '18.0.1.0.0',
    'summary': 'SMS Provider Integration for Marketing',
    'description': """
        SMS Provider Integration for Marketing
        - Configure SMS providers directly in SMS marketing
        - Monitor SMS providers
        - Send SMS through configured providers
        - Track provider usage in SMS campaigns
    """,
    'category': 'Marketing/Email Marketing',
    'depends': ['base', 'sms', 'mass_mailing_sms', 'mass_mailing'],
    'data': [
        'security/ir.model.access.csv',
        'views/sms_provider_views.xml',
        'views/mailing_mailing_views.xml',
    ],
    'images': ['static/description/icon.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
