from flask import Flask, request, jsonify
from anthropic import Anthropic
import httpx
import json
import os

app = Flask(__name__)

# Custom HTTP client for Anthropic
custom_http_client = httpx.Client(
    timeout=60.0,
    follow_redirects=True
)

client = Anthropic(
    api_key=os.environ.get('ANTHROPIC_API_KEY'),
    http_client=custom_http_client
)

# Airtable config
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = 'app8CI7NAZqhQ4G1Y'
AIRTABLE_CLIENTS_TABLE = 'Clients'
AIRTABLE_JOBS_TABLE = 'Projects'

# Load prompts from files
with open('dot_traffic_prompt.txt', 'r') as f:
    TRAFFIC_PROMPT = f.read()

with open('dot_triage_prompt.txt', 'r') as f:
    TRIAGE_PROMPT = f.read()

with open('dot_update_prompt.txt', 'r') as f:
    UPDATE_PROMPT = f.read()


def strip_markdown_json(content):
    """Strip markdown code blocks from Claude's JSON response"""
    content = content.strip()
    if content.startswith('```'):
        # Remove first line (```json or ```)
        content = content.split('\n', 1)[1] if '\n' in content else content[3:]
    if content.endswith('```'):
        # Remove trailing ```
        content = content.rsplit('```', 1)[0]
    return content.strip()


# ===================
# AIRTABLE HELPERS
# ===================

def get_job_info_from_airtable(client_code):
    """Look up client in Airtable, increment job number, return job number, team ID, SharePoint URL, and client record ID
    Used by TRIAGE for new jobs"""
    if not AIRTABLE_API_KEY:
        print("No Airtable API key configured")
        return f"{client_code} TBC", None, None, None
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        # Search for the client code
        search_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_CLIENTS_TABLE}"
        params = {'filterByFormula': f"{{Client code}}='{client_code}'"}
        
        response = httpx.get(search_url, headers=headers, params=params, timeout=10.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        if not records:
            print(f"Client code '{client_code}' not found in Airtable")
            return f"{client_code} TBC", None, None, None
        
        record = records[0]
        record_id = record['id']
        fields = record['fields']
        
        current_number = fields.get('Next #', 1)
        team_id = fields.get('Teams ID', None)
        sharepoint_url = fields.get('Sharepoint ID', None)
        next_number = current_number + 1
        
        # Format job number (e.g., "TOW 023")
        job_number = f"{client_code} {str(current_number).zfill(3)}"
        
        # Update Airtable with incremented number
        update_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_CLIENTS_TABLE}/{record_id}"
        update_data = {'fields': {'Next #': next_number}}
        
        httpx.patch(update_url, headers=headers, json=update_data, timeout=10.0)
        
        return job_number, team_id, sharepoint_url, record_id
        
    except Exception as e:
        print(f"Error getting job info from Airtable: {e}")
        return f"{client_code} TBC", None, None, None


def get_project_from_airtable(job_number):
    """Look up existing project by job number. Returns project details or None.
    Used by TRAFFIC to validate job numbers and enrich routing data."""
    if not AIRTABLE_API_KEY:
        print("No Airtable API key configured")
        return None
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        # Search for the job number
        search_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_JOBS_TABLE}"
        params = {'filterByFormula': f"{{Job Number}}='{job_number}'"}
        
        response = httpx.get(search_url, headers=headers, params=params, timeout=10.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        if not records:
            print(f"Job '{job_number}' not found in Airtable")
            return None
        
        record = records[0]
        fields = record['fields']
        
        # Get client name from linked record if available
        client_name = fields.get('Client', '')
        if isinstance(client_name, list):
            client_name = client_name[0] if client_name else ''
        
        return {
            'recordId': record['id'],
            'jobNumber': fields.get('Job Number', job_number),
            'jobName': fields.get('Project Name', ''),
            'clientName': client_name,
            'stage': fields.get('Stage', ''),
            'status': fields.get('Status', ''),
            'round': fields.get('Round', 0),
            'withClient': fields.get('With Client?', False),
            'teamsChannelId': fields.get('Teams Channel ID', None)
        }
        
    except Exception as e:
        print(f"Error looking up project in Airtable: {e}")
        return None


def update_project_in_airtable(job_number, updates):
    """Update project fields in Airtable. 
    Used by UPDATE endpoint to write changes."""
    if not AIRTABLE_API_KEY:
        print("No Airtable API key configured")
        return False
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        # First find the record
        search_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_JOBS_TABLE}"
        params = {'filterByFormula': f"{{Job Number}}='{job_number}'"}
        
        response = httpx.get(search_url, headers=headers, params=params, timeout=10.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        if not records:
            print(f"Job '{job_number}' not found for update")
            return False
        
        record_id = records[0]['id']
        
        # Build update payload - only include non-null values
        update_fields = {}
        
        field_mapping = {
            'Update': 'Update',
            'Stage': 'Stage',
            'Status': 'Status',
            'Live Date': 'Live Date',
            'Update due': 'Update due',
            'With Client?': 'With Client?'
        }
        
        for key, airtable_field in field_mapping.items():
            if key in updates and updates[key] is not None:
                update_fields[airtable_field] = updates[key]
        
        if not update_fields:
            print("No fields to update")
            return True
        
        # Update the record
        update_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_JOBS_TABLE}/{record_id}"
        update_data = {'fields': update_fields}
        
        response = httpx.patch(update_url, headers=headers, json=update_data, timeout=10.0)
        response.raise_for_status()
        
        print(f"Updated project {job_number}: {update_fields}")
        return True
        
    except Exception as e:
        print(f"Error updating project in Airtable: {e}")
        return False


def create_job_in_airtable(job_number, job_name, client_code, description, project_owner, client_record_id):
    """Create a new job record in the Jobs table.
    Used by TRIAGE for new jobs."""
    if not AIRTABLE_API_KEY:
        print("No Airtable API key configured")
        return None
    
    try:
        from datetime import date
        
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        # Build the job record
        job_data = {
            'fields': {
                'Job Number': job_number,
                'Project Name': job_name,
                'Description': description,
                'Status': 'In Progress',
                'Stage': 'Triage',
                'Project Owner': project_owner,
                'Start Date': date.today().isoformat(),
                'Round': 0  # NEW: Initialize round at 0
            }
        }
        
        # Add client link if we have the record ID
        if client_record_id:
            job_data['fields']['Client Link'] = [client_record_id]
        
        # Create the record
        create_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_JOBS_TABLE}"
        response = httpx.post(create_url, headers=headers, json=job_data, timeout=10.0)
        response.raise_for_status()
        
        new_record = response.json()
        print(f"Created job record: {new_record.get('id')}")
        return new_record.get('id')
        
    except Exception as e:
        print(f"Error creating job in Airtable: {e}")
        return None


# ===================
# TRAFFIC ENDPOINT
# ===================
@app.route('/traffic', methods=['POST'])
def traffic():
    """Route incoming emails to the correct handler.
    
    UPDATED: Now accepts additional fields and validates job numbers against Airtable.
    """
    try:
        data = request.get_json()
        
        # Required field
        email_content = data.get('emailContent', '')
        if not email_content:
            return jsonify({'error': 'No email content provided'}), 400
        
        # Original fields
        subject_line = data.get('subjectLine', '')
        
        # NEW: Additional fields for smarter routing
        sender_email = data.get('senderEmail', '')
        sender_name = data.get('senderName', '')
        all_recipients = data.get('allRecipients', [])  # List of TO and CC emails
        has_attachments = data.get('hasAttachments', False)
        attachment_names = data.get('attachmentNames', [])
        
        # Build content for Claude
        full_content = f"""Subject: {subject_line}

From: {sender_name} <{sender_email}>
Recipients: {', '.join(all_recipients) if all_recipients else 'Not specified'}
Has Attachments: {has_attachments}
Attachment Names: {', '.join(attachment_names) if attachment_names else 'None'}

Email Body:
{email_content}"""
        
        # Call Claude to determine routing
        response = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=1000,
            temperature=0.1,
            system=TRAFFIC_PROMPT,
            messages=[
                {'role': 'user', 'content': f'Email to route:\n\n{full_content}'}
            ]
        )
        
        # Parse Claude's JSON response
        content = response.content[0].text
        content = strip_markdown_json(content)
        routing = json.loads(content)
        
        # NEW: If job number found, validate against Airtable and enrich
        if routing.get('jobNumber'):
            project = get_project_from_airtable(routing['jobNumber'])
            
            if project:
                # Enrich routing with project data
                routing['jobName'] = project['jobName']
                routing['clientName'] = project['clientName']
                routing['currentRound'] = project['round']
                routing['currentStage'] = project['stage']
                routing['withClient'] = project['withClient']
                routing['teamsChannelId'] = project['teamsChannelId']
                routing['projectRecordId'] = project['recordId']
            else:
                # Job number not found - reroute to clarify
                routing['route'] = 'clarify'
                routing['reason'] = f"Job {routing['jobNumber']} not found in system"
                routing['clarifyEmail'] = f"""<p>Hi {routing.get('senderName', 'there')},</p>
<p>I couldn't find job {routing['jobNumber']} in our system.</p>
<p>Could you double-check the job number? Or if this is a new job, just reply "Triage" and I'll set it up.</p>
<p>Thanks,<br>Dot</p>"""
        
        return jsonify(routing)
        
    except json.JSONDecodeError as e:
        return jsonify({
            'error': 'Claude returned invalid JSON',
            'details': str(e),
            'raw_response': content
        }), 500
    except Exception as e:
        return jsonify({
            'error': 'Internal server error',
            'details': str(e)
        }), 500


# ===================
# TRIAGE ENDPOINT
# ===================
@app.route('/triage', methods=['POST'])
def triage():
    """Process new job triage.
    
    UNCHANGED - keeping exactly as it was since it works.
    """
    try:
        data = request.get_json()
        email_content = data.get('emailContent', '')
        
        if not email_content:
            return jsonify({'error': 'No email content provided'}), 400
        
        # Call Claude with Triage prompt
        response = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=2000,
            temperature=0.2,
            system=TRIAGE_PROMPT,
            messages=[
                {'role': 'user', 'content': f'Email content:\n\n{email_content}'}
            ]
        )
        
        # Parse Claude's JSON response
        content = response.content[0].text
        content = strip_markdown_json(content)
        analysis = json.loads(content)
        
        # Get job number and client info from Airtable
        client_code = analysis.get('clientCode', 'TBC')
        if client_code not in ['HUN', 'TBC']:
            job_number, team_id, sharepoint_url, client_record_id = get_job_info_from_airtable(client_code)
        else:
            job_number = f'{client_code} TBC'
            team_id = None
            sharepoint_url = None
            client_record_id = None
        
        # Create job record in Airtable
        job_record_id = None
        if job_number and 'TBC' not in job_number:
            job_record_id = create_job_in_airtable(
                job_number=job_number,
                job_name=analysis.get('jobName', 'Untitled'),
                client_code=client_code,
                description=analysis.get('jobSummary', ''),
                project_owner=analysis.get('projectOwner', 'TBC'),
                client_record_id=client_record_id
            )
        
        # Return complete analysis with job info
        return jsonify({
            'jobNumber': job_number,
            'jobName': analysis.get('jobName', 'Untitled'),
            'clientCode': client_code,
            'clientName': analysis.get('clientName', ''),
            'projectOwner': analysis.get('projectOwner', ''),
            'teamId': team_id,
            'sharepointUrl': sharepoint_url,
            'jobRecordId': job_record_id,
            'emailBody': analysis.get('emailBody', ''),
            'fullAnalysis': analysis
        })
        
    except json.JSONDecodeError as e:
        return jsonify({
            'error': 'Claude returned invalid JSON',
            'details': str(e),
            'raw_response': content
        }), 500
    except Exception as e:
        return jsonify({
            'error': 'Internal server error',
            'details': str(e)
        }), 500


# ===================
# UPDATE ENDPOINT
# ===================
@app.route('/update', methods=['POST'])
def update():
    """Process job updates.
    
    NEW: Full implementation replacing placeholder.
    """
    try:
        data = request.get_json()
        
        # Required fields
        job_number = data.get('jobNumber')
        email_content = data.get('emailContent', '')
        
        if not job_number:
            return jsonify({'error': 'No job number provided'}), 400
        
        if not email_content:
            return jsonify({'error': 'No email content provided'}), 400
        
        # Get project details from Airtable
        project = get_project_from_airtable(job_number)
        
        if not project:
            return jsonify({
                'error': 'job_not_found',
                'jobNumber': job_number,
                'message': f"Could not find job {job_number} in the system"
            }), 404
        
        # Build content for Claude
        update_content = f"""Job Number: {job_number}
Client Name: {project['clientName']}
Current Stage: {project['stage']}
Email/Message Content:
{email_content}"""
        
        # Call Claude with Update prompt
        response = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=1500,
            temperature=0.2,
            system=UPDATE_PROMPT,
            messages=[
                {'role': 'user', 'content': update_content}
            ]
        )
        
        # Parse Claude's JSON response
        content = response.content[0].text
        content = strip_markdown_json(content)
        analysis = json.loads(content)
        
        # Check for errors from Claude
        if analysis.get('error'):
            return jsonify(analysis), 400
        
        # Update Airtable with the changes
        if analysis.get('projectUpdates'):
            update_success = update_project_in_airtable(
                job_number, 
                analysis['projectUpdates']
            )
            analysis['airtableUpdated'] = update_success
        
        # Add project context to response
        analysis['teamsChannelId'] = project['teamsChannelId']
        analysis['projectRecordId'] = project['recordId']
        
        return jsonify(analysis)
        
    except json.JSONDecodeError as e:
        return jsonify({
            'error': 'Claude returned invalid JSON',
            'details': str(e),
            'raw_response': content
        }), 500
    except Exception as e:
        return jsonify({
            'error': 'Internal server error',
            'details': str(e)
        }), 500


# ===================
# HEALTH CHECK
# ===================
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Dot Main',
        'endpoints': ['/traffic', '/triage', '/update', '/health']
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
