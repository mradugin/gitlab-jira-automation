import re
import time
import gitlab
import jira

import utils

class JiraDeferredTransition:
    def __init__(self, interval, issue_key):
        self.issue_key = issue_key
        self.reset(interval)
        
    def reset(self, interval):
        self.tries = 1
        self.scheduled_time = time.time() + interval
        
    def update(self, interval):
        self.tries += 1 
        self.scheduled_time = time.time() + interval
        
    def triggered(self):
        return time.time() >= self.scheduled_time
    
    def exhausted(self, max_tries):
        return self.tries >= max_tries

class JiraUpdate:
    OPEN_STATUSES = ['Open', 'Reopened']
    IN_PROGRESS_STATUSES = ['In Progress']
    IN_REVIEW_STATUSES = ['In Review', 'Ready To Merge']
    
    RESOLUTION_NOTES_FIELD = 'Resolution Notes'
    DEV_RESOLUTION_FIELD = 'Dev Resolution'

    FINAL_TRANSITION = 'Request QA'
    START_REVIEW_TRANSITION = 'Start Review'
    START_PROGRESS_TRANSITION = 'Start Progress On Push'
    
    DEFER_INTERNAL = 5
    CHECK_MR_STATUS_TRIES = 10

    def __init__(self, logger, config, gitlab:gitlab.Gitlab, jira:jira.JIRA):
        self._config = config
        self._logger = logger
        self._gitlab = gitlab
        self._jira = jira

        self._done_merge_request_issues = []

        self._jira_fields = { field['name'] : field['id'] for field in self._jira.fields() }
        
        self._eligible_issue_key_pattern = r'({keys})-\d+'.format(keys='|'.join(self._config.get("enabled-project-keys", [])))

        self._final_transition = self._config.get("final-transition", self.FINAL_TRANSITION)
        self._start_review_transition = self._config.get("start-review-transition", self.START_REVIEW_TRANSITION)
        self._start_progress_transition = self._config.get("start-progress-transition", self.START_PROGRESS_TRANSITION)

        self._open_statuses = self._config.get("open-statuses", self.OPEN_STATUSES)
        self._in_progress_statuses = self._config.get("in-progress-statuses", self.IN_PROGRESS_STATUSES)
        self._in_review_statuses = self._config.get("in-review-statuses", self.IN_REVIEW_STATUSES)
        self._resolution_notes_field = self._config.get("resolution-notes-field", self.RESOLUTION_NOTES_FIELD)
        self._dev_resolution_field = self._config.get("dev-resolution-field", self.DEV_RESOLUTION_FIELD)

    def _transition_issue_when_done(self, event):
        action = event['object_attributes']['action']
        done = action in ['close', 'merge']
        
        if not done:
            return

        branch = event['object_attributes']['source_branch']
        title = event['object_attributes']['title']

        issue_keys = utils.extract_issue_keys(branch).union(utils.extract_issue_keys(title))

        if not issue_keys:
            self._logger.warning(f'No issue keys found in branch name: {branch}, and title: {title}')
            return
        
        eligible_issue_keys = [x for x in issue_keys if re.match(self._eligible_issue_key_pattern, x) is not None]
        self._logger.info(f'Eligible issues for transition: {eligible_issue_keys}')
        if not eligible_issue_keys:
            self._logger.warning(f'None of {issue_keys} belong to eligible projects')
            return
            
        for issue_key in eligible_issue_keys:
            matching_issues = [entry for entry in self._done_merge_request_issues if entry.issue_key == issue_key]
            if not matching_issues:
                self._logger.info(f'Added {issue_key} for checking if all merge requests are done')
                self._done_merge_request_issues.append(JiraDeferredTransition(self.DEFER_INTERNAL, issue_key))
            else:
                matching_issues[0].reset(self.DEFER_INTERNAL)
                self._logger.info(f'{issue_key} is already on the list for checking if all merge requests are done, rescheduling')
        
    def _process_done_merge_request_issues(self, entry:JiraDeferredTransition):
        if not entry.triggered():
            return False

        self._logger.info(f'Checking if merge requests are done for {entry.issue_key}...')
        issue_key = entry.issue_key
        try: 
            issue = self._jira.issue(issue_key)
        except Exception:
            self._logger.exception(f'Failed to get issue {issue_key}, skipping')
            return True
        # Trick to make sure current issue has at least one pull request and none of them are open
        results = self._jira.search_issues(f"issuekey = {issue_key} AND development[pullrequests].all > 0 AND development[pullrequests].open = 0")
        if len(results) == 1 and results[0].key == issue_key:
            transition = None
            try:
                if issue.fields.status.name in self._in_review_statuses:
                    transition = self._final_transition
                    self._logger.info(f"Executing {issue_key} transition '{transition}' from '{issue.fields.status.name}' state")
                    self._transition_issue(issue, transition, {})
                else:
                    self._logger.info(f"{issue_key} is in '{issue.fields.status.name}' state that is not eligible for transition")
            except Exception:
                self._logger.exception(f'Failed to execute issue {issue_key} transition {transition}')
            else:
                self._logger.info(f'All merge requests are done for {issue_key}')
            return True

        if entry.exhausted(self.CHECK_MR_STATUS_TRIES):
            self._logger.info(f'Failed to process {issue_key} after {entry.tries} tries, removing')
            return True

        entry.update(self.DEFER_INTERNAL)
        self._logger.info(f'There are still open merge requests for {issue_key} issues, scheduling to retry in {self.DEFER_INTERNAL} seconds')
        return False

    def _transition_issues_in_review_or_update(self, event):
        action = event['object_attributes']['action']
        
        created = False
        draft = False
        closed = False
        merged = False

        draft_updated = event.get('changes', {}).get('draft', None) != None
        description_updated = event.get('changes', {}).get('description') != None or \
            event.get('changes', {}).get('title') != None
        
        if action == 'open':
            created = True
            draft_updated = True
            description_updated = True
            draft = event['object_attributes'].get('draft', False)
        elif action == 'update':
            draft = event.get('changes', {}).get('draft', {}).get('current', False)
        elif action == 'merge':
            merged = True
        elif action == 'close':
            closed = True

        if not created and not draft_updated and not description_updated and not closed and not merged:
            self._logger.info('No relevant changes in merge request to update issue in jira')
            return            
        
        branch = event['object_attributes']['source_branch']
        description = utils.sanitize_description(event['object_attributes']['description'])
        title = utils.sanitize_title(event['object_attributes']['title'])
        id = str(event['object_attributes']['id'])
        url = event['object_attributes']['url']

        issue_keys = utils.extract_issue_keys(branch).union(utils.extract_issue_keys(title))
        
        if not issue_keys:
            self._logger.warning(f"No issue keys found in merge request branch '{branch}' and title '{title}'")
            return
        
        resolution_notes = utils.create_merge_request_resolution_notes(merged, closed, id, title, url, description)

        transition_to_review = (created or draft_updated) and not draft
        update_only = created or closed or merged or description_updated

        for issue_key in issue_keys:
            try: 
                issue = self._jira.issue(issue_key)
            except Exception:
                self._logger.warning(f'Non-existent {issue_key} issue key, skipping')
                continue
            new_resolution_notes = utils.update_resolution_notes_text(getattr(issue.fields, \
                self._jira_fields[self._resolution_notes_field]), id, resolution_notes)
            if transition_to_review:
                self._transition_issue_in_review(issue, new_resolution_notes)
            elif update_only:
                self._update_issue_resolution_notes(issue, new_resolution_notes)

    def _update_issue_resolution_notes(self, issue, resolution_notes):            
        fields = {}
        if issue.fields.status.name in self._in_review_statuses:
            fields[self._jira_fields[self._resolution_notes_field]] = resolution_notes
            self._logger.info(f'Updating {issue.key} fields: {fields}')
            issue.update(fields=fields)
            
    def _transition_issue_in_review(self, issue, resolution_notes):
        fields = {}
        if issue.fields.status.name in self._in_progress_statuses:
            fields[self._jira_fields[self._resolution_notes_field]] = resolution_notes
            if self._dev_resolution_field:
                fields[self._jira_fields[self._dev_resolution_field]] = { 'value': 'Done' }
            self._transition_issue(issue, self._start_review_transition, fields)
            
    def _transition_issue(self, issue, transition_name, fields):
        self._logger.info(f"Executing {issue.key} transition '{transition_name}' from '{issue.fields.status.name}' state, fields: {fields}")
        try:
            transitions = self._jira.transitions(issue)
            transition_id = [t['id'] for t in transitions if t['name'] == transition_name][0]
            self._jira.transition_issue(issue.key, transition_id, fields=fields)
        except Exception:
            self._logger.exception(f"Failed to execute issue {issue.key} transition '{transition_name}'")
            raise
        
    def _transition_issues_in_progress_on_push(self, event):
        if event.get('object_kind') != 'push':
            return

        self._logger.info('Transitioning jira issues to in progress on push')
        
        issue_keys = utils.extract_issue_keys(event.get('ref', ''))
        
        # try to extract issue keys from commits only if no issue keys found in ref name
        if not issue_keys:
            for commit in event.get('commits', []):
                issue_keys.update(utils.extract_issue_keys(commit.get('message', '')))
                issue_keys.update(utils.extract_issue_keys(commit.get('title', '')))

        if not issue_keys:
            self._logger.warning('No issue keys found in push event ref and commit data')
            return
        
        self._logger.info(f'Issue keys extracted {issue_keys}')

        user = self._jira.search_users(query=event.get('user_name'), maxResults=1)[0]

        for issue_key in issue_keys:
            try: 
                issue = self._jira.issue(issue_key)
            except Exception:
                self._logger.warning(f'Non-existent {issue_key} issue key, skipping')
                continue
            if issue.fields.status.name in self._open_statuses:
                start_transition = self._start_progress_transition
                self._transition_issue(issue, start_transition, None)
                self._logger.info(f"Assigning {issue_key} to '{user.displayName}'")
                self._jira.assign_issue(issue, user.displayName)
            else:
                self._logger.warning(f'Not transitioning {issue_key}, issue not in {self._open_statuses}')

    def _process_merge_request_event(self, event):
        if event.get('event_type') != 'merge_request':
            return

        try:
            self._transition_issues_in_review_or_update(event)
        except Exception:
            self._logger.exception('Error setting jira issue to in review state on merge request')
            
        try:
            self._transition_issue_when_done(event)
        except Exception:
            self._logger.exception('Error setting jira issue to in qa state on if all merge requests are done')

    def _process_push(self, event):
        if event.get('object_kind') != 'push':
            return
        try:
            self._transition_issues_in_progress_on_push(event)
        except Exception:
            self._logger.exception('Error transitioning jira issues to in progress on push')
             
    def process(self,event):
        try:
            self._process_merge_request_event(event)
            self._process_push(event)
        except Exception:
            self._logger.exception('Error processing jira update')
    
    def poll(self):
        self._done_merge_request_issues = [x for x in self._done_merge_request_issues if not self._process_done_merge_request_issues(x) ]
