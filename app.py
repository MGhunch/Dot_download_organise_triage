from flask import Flask, request, jsonify
from anthropic import Anthropic
import httpx
import json
import os
import requests

app = Flask(__name__)

custom_http_client = httpx.Client(
    timeout=30.0,
    follow_redirects=True
)

client = Anthropic(
    api_key=os.environ.get('ANTHROPIC_API_KEY'),
    http_client=custom_http_client
)

with open('dot_prompt.txt', 'r') as f:
    DOT_PROMPT = f.read()

def get_next_job_number(client_code):
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
    try:
        data = request.get_json()
        email_content = data.get('emailContent', '')
        
        if not email_content:
            return jsonify({'error': 'No email content provided'}), 400
        
        response = client.messages.create(
model='claude-sonnet-4-20250514',
            max_tokens=2000,
            temperature=0.2,
            system=DOT_PROMPT,
            messages=[
                {'role': 'user', 'content': f'Email content:\n\n{email_content}'}
            ]
        )
        
        content = response.content[0].text
        analysis = json.loads(content)
        
        client_code = analysis.get('clientCode', 'TBC')
        if client_code not in ['HUN', 'TBC']:
            job_number = get_next_job_number(client_code)
        else:
            job_number = f'{client_code} TBC'
        
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
    return jsonify({'status': 'healthy', 'service': 'Dot Triage'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
