#!/usr/bin/python
import os
import json
import secrets
import signal
import sys
from flask import Flask
from flask import request
from logging.config import dictConfig
import utils
from web_event_worker import WebEventWorker

GITLAB_WEBHOOK_SECRET_TOKEN = os.environ.get('GITLAB_WEBHOOK_SECRET_TOKEN', '')

dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    }},
    'handlers': {'wsgi': {
        'class': 'logging.StreamHandler',
        'stream': 'ext://flask.logging.wsgi_errors_stream',
        'formatter': 'default'
    }},
    'root': {
        'level': 'INFO',
        'handlers': ['wsgi']
    }
})

DEFAULT_WEBHOOKS_CONFIG = {
    'merge-request': {
        'review-checklist': {
            'enabled-projects': ['test/test'],
            'remote-file': '.gitlab-robot/review-checklist.md',
            'file': '../resources/review-checklist.md',
            'target-branches': ['main', 'master']
        },
        'reviewer-suggestion': {
            'enabled-projects': ['test/test'], 
            'remote-file': '.gitlab-robot/reviewer-suggestion.jinja',
            'file': '../resources/reviewer-suggestion.jinja',
            'target-branches': ['main', 'master']
        },
        "jira-issue-transition": {
            "enabled-project-keys": ["JTP", "EI", "SWC"]
        }
    }
}

app = Flask(__name__)

config = None
try: 
    config = json.loads(utils.load_from_local_file('../resources/config.json'))
except Exception:
    config = DEFAULT_WEBHOOKS_CONFIG
    app.logger.error("Failed to load custom config, using default")
 
worker = WebEventWorker(app.logger, config)

@app.route('/', methods = ['POST'])
def index_handler():
    secret_token = request.headers.get('X-Gitlab-Token', '')
    if not secrets.compare_digest(GITLAB_WEBHOOK_SECRET_TOKEN, secret_token):
        app.logger.error("Invalid X-Gitlab-Token header")
        return 'ERROR', 403
    if request.is_json:
        content = request.get_json()
        event_type = request.headers.get('X-Gitlab-Event', None)
        if event_type:
            worker.put((event_type, content))
        else:
            app.logger.error("Missing X-Gitlab-Event header")
    else:
        app.logger.error("Invalid content type")
    return 'OK'
 

def graceful_shutdown():
    app.logger.info("Waiting for worker thread to finish...")
    worker.stop()

def signal_handler(signum, frame):
    graceful_shutdown()
    sys.exit()

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGQUIT, signal_handler)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8887)
else:
    import uwsgi
    uwsgi.atexit = graceful_shutdown