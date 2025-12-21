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
AIRTABLE_JOBS_TABLE = 'Jobs'

# Load prompts from files
with open('dot_traffic_prompt.txt', 'r') as f:
    TRAFFIC_PROMPT = f.read()

with open('dot_triage_prompt.txt', 'r') as f:
    TRIAGE_PROMPT = f.read()


def get_job_info_from_airtable(client_code):
    """Look up client in Airtable, increment job number, return job number, team ID, SharePoint URL, and client record ID"""
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


def create_job_in_airtable(job_number, job_name, client_code, description, project_owner, client_record_id):
    """Create a new job record in the Jobs table"""
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
                'Project name': job_name,
                'Description': description,
                'Status': 'In Progress',
                'Stage': 'Triage',
                'Project owner': project_owner,
                'Start Date': date.today().isoformat()
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
    """Route incoming emails to the correct handler"""
    try:
        data = request.get_json()
        email_content = data.get('emailContent', '')
        subject_line = data.get('subjectLine', '')
        
        if not email_content:
            return jsonify({'error': 'No email content provided'}), 400
        
        # Combine subject and body for analysis
        full_content = f"Subject: {subject_line}\n\n{email_content}"
        
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
        routing = json.loads(content)
        
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
    """Process new job triage"""
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
# UPDATE ENDPOINT (placeholder)
# ===================
@app.route('/update', methods=['POST'])
def update():
    """Process job updates - placeholder for now"""
    try:
        data = request.get_json()
        
        return jsonify({
            'status': 'placeholder',
            'message': 'Dot Update endpoint - coming soon',
            'received': {
                'jobNumber': data.get('jobNumber'),
                'emailContent': data.get('emailContent', '')[:100] + '...'
            }
        })
        
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
        'service': 'Dot Traffic Hub',
        'endpoints': ['/traffic', '/triage', '/update', '/health']
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
