import os
import json
import gitlab
from jira import JIRA
import queue
import threading

from reviewer_suggestion import ReviewerSuggestion
from review_checklist import ReviewChecklist
from jira_update import JiraUpdate

class WebEventWorker:
    GET_EVENT_TIMEOUT = 0.2

    def __init__(self, logger, config):
        self._config = config
        self._logger = logger
        self._events = queue.Queue()
        self._thread = threading.Thread(target=self._thread_proc, args=())
        
        self._gitlab = gitlab.Gitlab(os.environ['GITLAB_URL'], private_token=os.environ['GITLAB_ROBOT_TOKEN'])

        self._jira = JIRA(os.environ['JIRA_URL'], basic_auth=(os.environ['JIRA_ROBOT_USER'], os.environ['JIRA_ROBOT_TOKEN']))
        
        self._reviewer_suggestion = ReviewerSuggestion(self._logger, self._config['merge-request']['reviewer-suggestion'], self._gitlab)
        self._review_checklist = ReviewChecklist(self._logger, self._config['merge-request']['review-checklist'], self._gitlab)
        self._jira_update = JiraUpdate(self._logger, self._config['merge-request']['jira-issue-transition'], self._gitlab, self._jira)

        self._termination_event = threading.Event()

        self._thread.start()
    
    def stop(self):
         self._termination_event.set()
         self._thread.join()

    def put(self, event):
        self._logger.info("New event queued")
        self._events.put(event)

    def _thread_proc(self):
        self._logger.info("Started processing thread")
        while not self._termination_event.is_set():
            try:
                self._process_events()
                self._jira_update.poll()
            except Exception:
                self._logger.exception("Failure in processing thread loop")
        
    def _process_events(self):
        try: 
            (event_type, event) = self._events.get(True, self.GET_EVENT_TIMEOUT)
            self._logger.info("Processing event type: {0}, content:\n{1}".format(event_type, json.dumps(event, indent=4)))
            
            self._reviewer_suggestion.process(event)
            self._review_checklist.process(event)
            self._jira_update.process(event)
        except queue.Empty:
            pass