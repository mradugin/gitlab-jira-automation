import gitlab
from codeowners import CodeOwners
from jinja2 import Environment, FileSystemLoader
import utils

class ReviewerSuggestion:
    _logger = None
    _config = None
    _gitlab = None

    _env = None

    _template = None
    _template_remote_file = None
    
    def __init__(self, logger, config, gitlab:gitlab.Gitlab):
        self._config = config
        self._logger = logger
        self._gitlab = gitlab

        self._template = utils.load_from_local_file(self._config['file'])

        self._template_remote_file = self._config['remote-file']

        self._env = Environment(loader=FileSystemLoader("."), autoescape=True)

    def _add_reviewer_suggestion(self, event):
        project_name = event['project']['path_with_namespace']
        if project_name not in self._config['enabled-projects']:
            return

        if event['object_attributes']['target_branch'] not in self._config['target-branches']: 
            return

        action = event['object_attributes']['action']
        if action != 'open':
            return

        self._logger.info('Processing reviewer suggestion')

        project = self._gitlab.projects.get(event['project']['id'])
        mr_iid = event['object_attributes']['iid']
        mr = project.mergerequests.get(mr_iid, lazy=True)
        mr_changes = mr.changes()
        changed_files = set()
        if 'changes' in mr_changes.keys():
            for change in mr_changes['changes']:
                changed_files.add(change['old_path'])
                changed_files.add(change['new_path'])
        if len(changed_files) == 0:
            self._logger.error('No changed files in merge request')
            return

        self._logger.info('Changed files: {0}'.format(changed_files))
        owners_file = None
        refs = ['master', 'main']
        try:
            owners_file = utils.load_from_remote_file(project, 'CODEOWNERS', refs)
        except:
            self._logger.error("CODEOWNERS file is not present in: {0}".format(', '.join(refs)))
            raise
        owners = CodeOwners(owners_file)
        change_owners = set()
        for changed_file in changed_files:
            self._logger.info('Owners of file {0} are {1}'.format(changed_file, owners.of(changed_file)))
            change_owners = set.union(change_owners, {v[1] for v in owners.of(changed_file)})

        author = '@{0}'.format(event['user']['username'])
        author_is_the_only_codeowner = (author in change_owners) and (len(change_owners) == 1)

        if author in change_owners:
            change_owners.remove(author)

        self._logger.info('Change owners: {0}'.format(change_owners))

        template_text = utils.load_from_remote_file(project, self._template_remote_file,
            fallback=self._template)
            
        if template_text is None:
            self._logger.error('Reviewer suggestion template is not defined')
            return

        if len(template_text) == 0:
            self._logger.warning('Reviewer suggestion template is empty, not posting')
            return

        reviewer_suggestion_template = self._env.from_string(template_text)
        data={
            'codeowners': change_owners,
            'author': author,
            'author_is_the_only_codeowner': author_is_the_only_codeowner
        }
        reviewer_suggestion_text = reviewer_suggestion_template.render(data=data)
        self._logger.info('Adding reviewer suggestion to newly opened merge_request {0} in {1} event...'.format(mr_iid, project_name))
        mr.notes.create({'body': reviewer_suggestion_text})

    def process(self, event):
        if event.get('event_type') != 'merge_request':
            return
        try:
            self._add_reviewer_suggestion(event)
        except Exception:
            self._logger.exception('Error adding reviewer suggestion')
