FROM python:3.8-slim-buster

LABEL maintainer="maxim@radugin.com" \
      version="1.0.0" \
      description="Dockerfile for the Flask GitLab Webhooks API in Production"

RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && apt-get autoremove -y

RUN pip install pipenv uwsgi

# VOLUME /webhooks/resources

COPY webhooks/app /webhooks/app

RUN groupadd -r flaskuser && useradd -r -g flaskuser flaskuser
RUN chown -R flaskuser:flaskuser /webhooks

WORKDIR /webhooks/app

RUN PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy --system

USER flaskuser

ENV FLASK_ENV=production
ENV ENV=prod
ENV GITLAB_URL=https://gitlab.yourcompany.com
ENV GITLAB_ROBOT_TOKEN=secret
# ENV GITLAB_WEBHOOK_SECRET_TOKEN=

ENV JIRA_URL=https://yourcompany.atlassian.net
ENV JIRA_ROBOT_USER=user
ENV JIRA_ROBOT_TOKEN=secret

STOPSIGNAL SIGTERM
EXPOSE 5000

CMD ["uwsgi", "--ini", "uwsgi.ini", "--lazy"]
