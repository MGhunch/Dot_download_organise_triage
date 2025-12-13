from flask import Flask, request, jsonify
from openai import OpenAI
import json
import os
import requests

app = Flask(__name__)

# Initialize OpenAI client
client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY'))

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
        
        # Call ChatGPT with DOT prompt
        response = client.chat.completions.create(
            model='gpt-3.5-turbo',
            temperature=0.2,
            messages=[
                {'role': 'system', 'content': DOT_PROMPT},
                {'role': 'user', 'content': f'Email content:\n\n{email_content}'}
            ]
        )
        
        # Parse ChatGPT's JSON response
        content = response.choices[0].message.content
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
            'error': 'ChatGPT returned invalid JSON',
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
