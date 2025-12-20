from flask import Flask, request, jsonify
from anthropic import Anthropic
import httpx
import json
import os

app = Flask(__name__)

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
AIRTABLE_TABLE_NAME = 'Job Numbers'

with open('dot_prompt.txt', 'r') as f:
    DOT_PROMPT = f.read()

def get_client_info(client_code):
    """Look up client in Airtable, return team ID and SharePoint URL"""
    if not AIRTABLE_API_KEY:
        print("No Airtable API key configured")
        return None, None
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        search_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
        params = {'filterByFormula': f"{{Client code}}='{client_code}'"}
        
        response = httpx.get(search_url, headers=headers, params=params, timeout=10.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        if not records:
            print(f"Client code '{client_code}' not found in Airtable")
            return None, None
        
        record = records[0]
        fields = record['fields']
        
        team_id = fields.get('Teams ID', None)
        sharepoint_url = fields.get('Sharepoint ID', None)
        
        return team_id, sharepoint_url
        
    except Exception as e:
        print(f"Airtable error: {e}")
        return None, None

def get_next_job_number(client_code):
    """Look up client in Airtable, increment job number, return formatted string, team ID, and SharePoint URL"""
    if not AIRTABLE_API_KEY:
        print("No Airtable API key configured")
        return f"{client_code} TBC", None, None
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        search_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
        params = {'filterByFormula': f"{{Client code}}='{client_code}'"}
        
        response = httpx.get(search_url, headers=headers, params=params, timeout=10.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        if not records:
            print(f"Client code '{client_code}' not found in Airtable")
            return f"{client_code} TBC", None, None
        
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
        update_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}/{record_id}"
        update_data = {'fields': {'Next #': next_number}}
        
        update_response = httpx.patch(update_url, headers=headers, json=update_data, timeout=10.0)
        update_response.raise_for_status()
        
        print(f"Job number assigned: {job_number}, next will be {next_number}")
        return job_number, team_id, sharepoint_url
        
    except Exception as e:
        print(f"Airtable error: {e}")
        return f"{client_code} TBC", None, None

@app.route('/triage', methods=['POST'])
def triage():
    try:
        # DEBUG LOGGING
        print(f"=== INCOMING REQUEST ===")
        print(f"Content-Type: {request.content_type}")
        print(f"Is JSON: {request.is_json}")
        raw_data = request.get_data(as_text=True)
        print(f"Raw data length: {len(raw_data)}")
        print(f"First 200 chars: {raw_data[:200]}")
        
        # Get email content - try multiple methods
        email_content = ''
        
        # Method 1: JSON
        if request.is_json:
            try:
                data = request.get_json()
                email_content = data.get('emailContent', '') or data.get('body', '')
                print(f"Got content from JSON: {len(email_content)} chars")
            except:
                pass
        
        # Method 2: Plain text
        if not email_content:
            email_content = raw_data.strip()
            print(f"Got content from raw data: {len(email_content)} chars")
        
        # Final check
        if not email_content:
            print("ERROR: No email content found")
            return jsonify({'error': 'No email content provided'}), 400
        
        print(f"Sending to Claude: {len(email_content)} chars")
        
        # Call Claude
        response = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=2000,
            temperature=0.2,
            system=DOT_PROMPT,
            messages=[
                {'role': 'user', 'content': f'Email content:\n\n{email_content}'}
            ]
        )
        
        # Parse response
        content = response.content[0].text
        print(f"Claude response: {len(content)} chars")
        
        analysis = json.loads(content)
        
        # Get intent and client code from Claude's analysis
        intent = analysis.get('intent', 'unclear')
        client_code = analysis.get('clientCode', 'TBC')
        
        # Initialize response with all of Claude's analysis
        result = {**analysis}
        
        # Handle based on intent
        if intent == 'triage':
            # New job - get job number from Airtable (increments counter)
            if client_code and client_code != 'TBC':
                job_number, team_id, sharepoint_url = get_next_job_number(client_code)
                result['jobNumber'] = job_number
                result['teamId'] = team_id
                result['sharepointUrl'] = sharepoint_url
            else:
                result['jobNumber'] = 'TBC'
                result['teamId'] = None
                result['sharepointUrl'] = None
                
        elif intent in ['update', 'job_number_reply']:
            # Existing job - just get team ID and SharePoint URL (no increment)
            if client_code and client_code != 'TBC':
                team_id, sharepoint_url = get_client_info(client_code)
                result['teamId'] = team_id
                result['sharepointUrl'] = sharepoint_url
            else:
                result['teamId'] = None
                result['sharepointUrl'] = None
                
        elif intent == 'update_needs_job':
            # Update but no job number - still need client info for potential later use
            if client_code and client_code != 'TBC':
                team_id, sharepoint_url = get_client_info(client_code)
                result['teamId'] = team_id
                result['sharepointUrl'] = sharepoint_url
            else:
                result['teamId'] = None
                result['sharepointUrl'] = None
                
        else:
            # Unclear intent
            result['teamId'] = None
            result['sharepointUrl'] = None
        
        print(f"Returning intent: {intent}")
        return jsonify(result)
        
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        return jsonify({
            'error': 'Claude returned invalid JSON',
            'details': str(e)
        }), 500
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({
            'error': 'Internal server error',
            'details': str(e)
        }), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'service': 'Dot Triage'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
