from flask import Flask, request, jsonify
from anthropic import Anthropic
import json
import os
import requests

app = Flask(__name__)

# Initialize Anthropic client
client = Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

# Load DOT prompt from file
with open('dot_prompt.txt', 'r') as f:
    DOT_PROMPT = f.read()

def get_next_job_number(client_code):
    """Call Google Apps Script to get next job number"""
    try:
        url = os.environ.get('GOOGLE_SCRIPT_URL')
        response = requests.get(url, params={
            'code': client_code,
            'mode': 'next'
        })
        data = response.json()
        return data.get('jobNumber', f'{client_code} TBC')
    except Exception as e:
        print(f"Error getting job number: {e}")
        return f'{client_code} TBC'

@app.route('/triage', methods=['POST'])
def triage():
    """Main triage endpoint"""
    try:
        # Get email content from request
        data = request.get_json()
        email_content = data.get('emailContent', '')
        
        if not email_content:
            return jsonify({'error': 'No email content provided'}), 400
        
        # Call Claude with DOT prompt
        response = client.messages.create(
            model='claude-3-5-sonnet-20241022',
            max_tokens=2000,
            temperature=0.2,
            system=DOT_PROMPT,
            messages=[
                {'role': 'user', 'content': f'Email content:\n\n{email_content}'}
            ]
        )
        
        # Parse Claude's JSON response
        content = response.content[0].text
        analysis = json.loads(content)
        
        # Get job number if not HUN
        client_code = analysis.get('clientCode', 'HUN')
        if client_code != 'HUN':
            job_number = get_next_job_number(client_code)
        else:
            job_number = 'HUN TBC'
        
        # Return complete analysis
        return jsonify({
            'jobNumber': job_number,
            'jobName': analysis.get('jobName', 'Untitled'),
            'clientCode': client_code,
            'clientName': analysis.get('clientName', ''),
            'projectOwner': analysis.get('projectOwner', ''),
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

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'service': 'Dot Triage'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
