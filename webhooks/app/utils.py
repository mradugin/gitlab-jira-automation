import re

def split_resolution_notes_text(resolution_notes):
    pattern = r"\[(\d+)\]:\s*(.*?)(?=\n\[|\Z)"
    return re.findall(pattern, resolution_notes, re.DOTALL)

def update_resolution_notes_text(resolution_notes, mr_id, mr_resolution_notes):
    if not resolution_notes:
        return mr_resolution_notes
    all_merge_request_info = split_resolution_notes_text(resolution_notes)
    if all_merge_request_info:
        resolution_notes = ''
        matched_current = False
        for (match_id, match_text) in all_merge_request_info:
            if match_id == mr_id:
                matched_current = True
                resolution_notes += mr_resolution_notes
            else:
                resolution_notes += f'[{match_id}]: {match_text}\n'
        if not matched_current:
            resolution_notes += mr_resolution_notes
    else:
        resolution_notes = None
    return resolution_notes

def create_merge_request_resolution_notes(merged, closed, id, title, url, description):
    state_symbol = get_merge_request_state_symbol(merged, closed)
    resolution_notes = f'[{id}]: [{title}|{url}] {state_symbol}\n'

    if not closed and description:
        resolution_notes += description + '\n\n'

    return resolution_notes

def get_merge_request_state_symbol(merged, closed):
    if merged: 
        return '(/)'
    elif closed:
        return '(x)'
    return '(?)'

def extract_issue_keys(commit_message):
    return set(re.findall( r'(?:\/|\'|\"|\[|\s|^)([a-zA-Z]+-\d+)(?=\-|\'|\"|\]|\?|!|.|,|;|\s|$)', commit_message))

def remove_square_brackets_around_issue_keys(text):
    # Remove square brackets around issue number, as Jira intreprets them as links
    return re.sub(r'\[([a-zA-Z]+-\d+)\]', r'\1', text, 0)

def sanitize_description(description):
    # Remove useless "Closes AAA-111" text
    result = re.sub(r'Closes ([a-zA-Z]+-\d+)', '', description, 0)
    # Remove excess newlines
    result = re.sub(r'\n+', '\n', result, 0)
    
    return remove_square_brackets_around_issue_keys(result)

def sanitize_title(title):
    # Remove useless work Resolve from "Resolve AAA-111" text
    result = re.sub(r'Resolve ([a-zA-Z]+-\d+)', r'\1', title, 0)
    return remove_square_brackets_around_issue_keys(result)

def load_from_local_file(filename, fallback=None):
    try:
        with open(filename) as f:
            return f.read()
    except Exception:
        pass
    return fallback

def load_from_remote_file(project, file_path, refs=['main', 'master'], fallback=None):
    for ref in refs:
        try:
            return project.files.raw(file_path=file_path, ref=ref).decode('utf-8')
        except Exception:
            pass
    return fallback
