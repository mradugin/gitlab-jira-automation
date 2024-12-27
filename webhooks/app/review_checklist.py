import gitlab
import utils

class ReviewChecklist:
    _logger = None
    _config = None
    _gitlab = None

    _checklist = None
    _checklist_remote_file = None
    
    def __init__(self, logger, config, gitlab:gitlab.Gitlab):
        self._config = config
        self._logger = logger
        self._gitlab = gitlab

        self._checklist = utils.load_from_local_file(self._config['file'])
        self._checklist_remote_file = self._config['remote-file']
 
    def _add_checklist(self, event):
        project_name = event['project']['path_with_namespace']
        if project_name not in self._config['enabled-projects']:
            return

        if event['object_attributes']['target_branch'] not in self._config['target-branches']: 
            return

        action = event['object_attributes']['action']
        if action != 'open':
            return 

        self._logger.info('Processing merge request checklist')

        project = self._gitlab.projects.get(event['project']['id'])

        checklist = utils.load_from_remote_file(project, self._checklist_remote_file, 
            fallback=self._checklist)

        if checklist is None:
            self._logger.error('No checklist defined local or remote')
            return

        if len(checklist) == 0:
            self._logger.warning('Checklist is empty, not posting')
            return

        mr_iid = event['object_attributes']['iid']
        mr = project.mergerequests.get(mr_iid, lazy=True)
        self._logger.info('Adding checklist to newly opened merge_request {0} in {1} event...'.format(mr_iid, project_name))
        mr.notes.create({'body': checklist})

    def process(self, event):
        if event.get('event_type') != 'merge_request':
            return
        
        try:
            self._add_checklist(event)
        except Exception:
            self._logger.exception('Error adding checklist')

