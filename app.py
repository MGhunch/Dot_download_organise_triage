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

with open('dot_prompt.txt', 'r') as f:
    DOT_PROMPT = f.read()

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
        
        # Return analysis
        return jsonify({
            'clientCode': analysis.get('clientCode', 'TBC'),
            'clientName': analysis.get('clientName', ''),
            'projectOwner': analysis.get('projectOwner', ''),
            'jobName': analysis.get('jobName', 'Untitled'),
            'emailBody': analysis.get('emailBody', ''),
            'fullAnalysis': analysis
        })
        
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
