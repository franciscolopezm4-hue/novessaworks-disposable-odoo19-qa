"""Executed inside the new Odoo database only; never on an existing server."""
import datetime
import json
import os

prefix = os.environ['NWQA_PREFIX']
admin = env.ref('base.user_admin')
admin.write({'name': prefix + ' Admin', 'login': 'nwqa-admin@example.invalid',
             'password': os.environ['NWQA_WEB_PASSWORD']})
env.ref('base.main_company').write({'name': prefix + ' Company'})
for partner in env['res.partner'].sudo().search([]):
    partner.write({'name': prefix + ' Baseline ' + str(partner.id),
                   'email': False, 'phone': False})
admin.partner_id.write({'name': prefix + ' Admin'})
contact = env['res.partner'].create({'name': prefix + ' Contact Alpha',
    'email': 'qa.contact.alpha@example.invalid', 'phone': '+1 202 555 0101'})
conflict = env['res.partner'].create({'name': prefix + ' Conflict Contact',
    'email': 'qa.conflict@example.invalid'})
opportunity = env['crm.lead'].create({'name': prefix + ' Opportunity Alpha',
    'type': 'opportunity', 'partner_id': contact.id, 'expected_revenue': 12500})
project = env['project.project'].create({'name': prefix + ' Project Alpha'})
task = env['project.task'].create({'name': prefix + ' Task Alpha', 'project_id': project.id})
expiration = datetime.datetime.now() + datetime.timedelta(hours=2)
api_key = env['res.users.apikeys'].with_user(admin)._generate(
    'rpc', prefix + ' ephemeral JSON-2', expiration)
env.cr.commit()
with open('/nwqa/credential.json', 'w') as stream:
    json.dump({'apiKey': api_key, 'login': admin.login,
        'password': os.environ['NWQA_WEB_PASSWORD'], 'database': 'NWQA',
        'prefix': prefix, 'expiresAt': expiration.isoformat() + 'Z',
        'fixtures': {'contact': contact.id, 'conflict': conflict.id,
        'opportunity': opportunity.id, 'project': project.id, 'task': task.id}}, stream)
