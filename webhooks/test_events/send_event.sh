#!/bin/bash

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <event type> <payload file> [secret token]"
    echo "  - event type: 'push' or 'merge_request'"
    exit 1
fi

curl -X POST -H "Content-Type: application/json" -H "X-Gitlab-Token: $3" -H "X-Gitlab-Event: $1 Hook" --data "@$2" http://127.0.0.1:8887
